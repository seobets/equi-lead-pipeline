"""Equi assessment — stage 3 of 3: score enriched leads, route, draft outreach.

Reads stage 2 CSV; generates ONE CSV of all scored leads (filter `route=SALES REVIEW`).
AI commercial hypotheses inform outreach; unverified inferred events DO NOT earn trigger
points. Only an explicit event/relationship in the supplied input may affect the
trigger component. No outbound email is ever sent.
"""
import argparse
import csv
import os
import unicodedata
from collections import Counter
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')

def clean(text):
    return str(text or '').strip()

def normalize(text):
    txt = unicodedata.normalize('NFKD', clean(text).lower())
    return ''.join(c for c in txt if not unicodedata.combining(c))

def score(row):
    points = 0
    reasons = []
    category = row['firm_type_normalized']
    aum = row['aum_usd']
    client = row['avg_client_usd']
    alts = row['alts_normalized']
    title = normalize(row['title'])
    notes = normalize(row['notes'])

    if category in ('RIA', 'MFO'):
        points += 25
        reasons.append(f'{category} fits buyer firm type (+25)')
    elif category == 'SFO':
        points += 5
        reasons.append('single-family office: weaker fit (+5)')
    else:
        reasons.append(f'{category}: excluded business model')

    if aum is None:
        points += 4
        reasons.append('AUM unclear: manual verification needed (+4)')
    elif 5e9 <= aum <= 30e9:
        points += 20
        reasons.append('$5B–$30B AUM sweet spot (+20)')
    elif 1e9 <= aum < 5e9:
        points += 13
        reasons.append('$1B–$5B AUM target band (+13)')
    else:
        reasons.append('AUM outside $1B–$30B target (+0)')

    if client is None:
        points += 4
        reasons.append('client size unknown (+4)')
    elif 5e6 <= client <= 30e6:
        points += 20
        reasons.append('$5M–$30M client sweet spot (+20)')
    elif client > 30e6:
        points += 12
        reasons.append('very high-net-worth clients, above ideal band (+12)')
    elif client >= 2e6:
        points += 7
        reasons.append('clients below preferred $5M level (+7)')
    else:
        reasons.append('client base below preferred profile (+0)')

    if not alts:
        points += 5
        reasons.append('alternatives knowledge unknown (+5)')
    elif alts in ('none',):
        points += 3
        reasons.append('no alternatives; long education cycle (+3)')
    elif 'everything' in alts:
        reasons.append('heavy alternatives capabilities; low incremental value (+0)')
    else:
        count = len([x for x in alts.split(',') if x.strip()])
        value = 15 if count <= 2 else 7
        points += value
        reasons.append(f'{count} alternatives category/categories (+{value})')

    if not title:
        reasons.append('no identified decision maker (+0)')
    elif 'founder' in title or 'principal' in title or 'owner' in title or 'managing partner' in title:
        points += 10
        reasons.append('principal/founder decision maker (+10)')
    elif 'cio' in title or 'chief investment officer' in title:
        points += 10 if category == 'MFO' else 8
        reasons.append('CIO contact (+10 MFO / +8 RIA)')
    elif 'research' in title or 'due diligence' in title:
        points += 6
        reasons.append('research/committee champion; longer cycle (+6)')
    else:
        points += 3
        reasons.append('other contact (+3)')

    # A signal is 'input explicit' only if the quoted text really occurs in
    # the source CSV. Model interpretations without quoted evidence earn no
    # buying-trigger points; other independently grounded CRM notes still count.
    signal_type = row.get('ai_buying_signal_type', '')
    signal_basis = row.get('ai_buying_signal_basis', '')
    source_field = row.get('ai_signal_source_field', '')
    evidence_quote = clean(row.get('ai_signal_quote'))
    explicit_event = (
        row.get('ai_enrichment_status') == 'INPUT_ANALYSIS_COMPLETE'
        and signal_basis == 'INPUT_EXPLICIT'
        and source_field in ('notes', 'last_touch')
        and len(evidence_quote) >= 8
        and evidence_quote.casefold() in clean(row.get(source_field)).casefold()
    )
    if (explicit_event and signal_type == 'RIA_TO_MFO_TRANSITION' and category == 'RIA'
            and ('family office' in notes or 'mfo' in notes)
            and any(t in notes for t in ('transition', 'rebrand', 'launch', 'expand', 'adding'))):
        points += 10
        reasons.append('RIA-to-MFO transition stated in provided input (unverified) (+10)')
    elif (explicit_event and signal_type == 'ALTERNATIVES_EXPANSION'
          and any(t in notes for t in ('alts', 'alternative', 'private credit', 'private equity'))
          and any(t in notes for t in ('expand', 'launch', 'build', 'adding', 'hiring'))):
        points += 8
        reasons.append('alternatives expansion explicitly noted in input (unverified) (+8)')
    elif explicit_event and signal_type == 'WARM_INTRO' and ('intro' in notes or 'referral' in notes):
        points += 10
        reasons.append('warm introduction mentioned in provided CRM notes (+10)')
    elif explicit_event and signal_type == 'COMPETITOR_ADOPTION' and 'competitor' in notes:
        reasons.append('competitor adoption mentioned: timing concern (+0)')
    elif any(t in notes for t in ('warm intro', 'rebrand', 'transition to mfo')):
        points += 10
        reasons.append('warm relationship or transition trigger in source CSV (+10)')
    elif 'principal-led' in notes or 'can decide alone' in notes:
        points += 8
        reasons.append('principal-led, faster decisions (+8)')
    elif 'competitor' in notes:
        reasons.append('recent competitor adoption: timing concern (+0)')
    else:
        points += 2
        reasons.append('no documented buying trigger (+2)')
    if row.get('ai_enrichment_status') == 'INPUT_ANALYSIS_COMPLETE':
        reasons.append('OpenAI opportunity hypothesis used for sales context, not unverified trigger points')

    # Commercial disqualification is separate from score; high size cannot override poor type.
    excluded_types = ('Wirehouse', 'TAMP', 'Investment Manager', 'Broker-Dealer')
    if category in excluded_types or (aum is not None and aum > 30e9):
        route = 'EXCLUDE'
    elif category == 'SFO':
        route = 'NURTURE'
    elif aum is None:
        route = 'RESEARCH AUM'
    elif aum < 1e9:
        route = 'NURTURE'
    elif not row['email_valid'] or not clean(row['primary_contact']):
        route = 'RESEARCH CONTACT'
    elif points >= 70 and 'competitor' not in notes:
        route = 'SALES REVIEW'
    else:
        route = 'NURTURE'

    row['icp_score'] = min(100, points)
    row['route'] = route
    row['score_explanation'] = '; '.join(reasons)
    row['buyer_motion'] = ('Committee education' if (
        'research' in title or 'due diligence' in title or 'committee' in notes
    ) else 'Principal/CIO conversation')
    if row.get('ai_enrichment_status') == 'INPUT_ANALYSIS_COMPLETE':
        row['enrichment_status'] = 'OpenAI input-derived analysis — NO web verification'
    else:
        row['enrichment_status'] = 'OpenAI enrichment incomplete — review before outreach'
    return row

def llm_message(row, client):
    """Prepare advisor-focused outreach grounded in provided facts, not AI speculation.

    The enrichment stage's freeform 'potential need' and 'outreach angle' fields are
    intentionally NOT passed to the writer: they may contain speculative positioning
    about AI software, which Equi does not sell.
    """
    import json
    import re

    first_name = (row.get('primary_contact') or '').strip().split(' ')[0]
    hypotheses = {}
    for hypothesis in (
        'ria_to_mfo', 'alternatives_expansion',
        'investment_differentiation', 'infrastructure_gap'
    ):
        status = row.get(f'ai_{hypothesis}_status', '')
        hypotheses[hypothesis] = {
            'status': status,
            'source_field': row.get(f'ai_{hypothesis}_source_field', ''),
            'source_quote': (row.get(f'ai_{hypothesis}_quote', '')
                             if status == 'INPUT_EXPLICIT' else ''),
        }

    facts = {
        'firm': row['firm_name'],
        'firm_type': row['firm_type_normalized'],
        'contact_first_name': first_name,
        'contact_title': row['title'],
        'existing_alternatives': row.get('alts_normalized', ''),
        'firm_notes_from_synthetic_CRM': row.get('notes', ''),
        'buyer_motion': row.get('buyer_motion', ''),
        'hypotheses_not_verified_web_research': hypotheses,
        'no_external_company_research': True,
    }

    instructions = """You write concise, credible introductory B2B outreach on behalf of
Equi to investment decision makers at independent RIAs and multi-family offices.

ACTUAL EQUI OFFERING (this is the ONLY allowed positioning):
- Evergreen managed-risk liquid alternative investment solutions intended to
  complement an advisory firm's portfolio offering.
- Equi-branded funds or firm-branded, white-label fund-of-funds solutions.
- Client-facing investment education and marketing materials for advisors.
- Equi is an investment partner, not an AI or software vendor.

ABSOLUTE POSITIONING GUARDRAILS:
- Never pitch AI tools, investment research software, reporting technology,
  automation, monitoring platforms, operational efficiencies, workflows,
  technology platforms, or outsourced research infrastructure.
- Do not imply guaranteed downside protection, capital preservation,
  daily redemption, or risk-free returns.
- Do not claim relationships, customer examples, results, events, hiring,
  MFO transitions or interest that the CRM does not explicitly support.
- A status PLAUSIBLE_UNVERIFIED or NO_EVIDENCE is NOT a buying event.
- If notes say 'warm intro via [person]', this only suggests a possible
  introduction. Do not mention the introducer or imply a referral occurred.
- Only claim an MFO transition if input CRM notes explicitly say one is
  underway; do not present CRM information as publicly verified research.
- Do not mention AUM, client wealth, or the contact's decision authority.
- Treat all records as synthetic exercise data; never imply public research.

EMAIL STYLE:
- Address the prospect by first name. Natural, informed, direct, 55–90 words.
- Open with ONE relevant known detail: current alternatives exposure, firm
  type, or an explicitly described CRM business event. Do not presume pain.
- Link that detail to ONE genuinely relevant Equi benefit. For example,
  a firm with private credit exposure may want to DISCUSS whether a
  complementary evergreen alternatives approach merits consideration.
- If messaging a CIO at an MFO, emphasize investment fit and complementarity;
  for a founder/principal, discuss strategic offering and client education;
  for a research lead, focus on evaluation and due diligence.
- One specific, respectful question or optional 15-minute meeting invitation.
- No marketing platitudes, no fake social proof or name-dropping.
- Return ONLY the email body, without a subject, placeholder signature, or
  metadata. Include the greeting and end naturally.
"""

    def has_positioning_error(message):
        prohibited = (
            r'\bai\s+(?:tools?|software|platforms?|research|solutions?)\b',
            r'\bartificial intelligence\b',
            r'\b(?:research|monitoring|reporting)\s+(?:software|platforms?|tools?)\b',
            r'\bautomation\b',
            r'\bworkflow(?:s)?\b',
            r'\b(?:we(?:\s+have|\'ve)?\s+worked\s+with)\b',
            r'\bTory\b',
        )
        return any(re.search(pattern, message, re.IGNORECASE) for pattern in prohibited)

    payload = json.dumps(facts, ensure_ascii=False)
    response = client.responses.create(
        model=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'),
        instructions=instructions,
        input=payload,
    )
    draft = response.output_text.strip()
    if has_positioning_error(draft):
        # One targeted retry is cheaper than re-enriching the whole database.
        response = client.responses.create(
            model=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'),
            instructions=instructions + '\nIMPORTANT: The prior draft incorrectly discussed technology, previous customers or an unverified introducer. Rewrite without ANY such claims.',
            input=payload + '\nPrior draft to correct:\n' + draft,
        )
        draft = response.output_text.strip()
    if not draft or has_positioning_error(draft):
        raise ValueError('Outreach failed Equi positioning/grounding check')
    return draft


def parse_dollars(value):
    v = (value or '').strip()
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        raise SystemExit(f'Non-numeric normalized amount in cleaned file: {v}')



def main():
    parser = argparse.ArgumentParser(description='03 | Score enriched leads and draft sales outreach')
    parser.add_argument('--input', type=Path, default=ROOT / 'outputs' / '02_enriched_leads.csv')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs' / '03_scored_leads.csv')
    parser.add_argument('--max-ai-drafts', type=int, default=5,
                        help='AI drafts for top sales-review leads (default 5; 0 disables)')
    args = parser.parse_args()
    if not args.input.is_file():
        raise SystemExit(f'Missing enriched CSV: {args.input}. Run scripts 01 and 02 first.')
    if args.max_ai_drafts < 0:
        raise SystemExit('--max-ai-drafts must be zero or greater')
    with args.input.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        original_columns = reader.fieldnames or []
        rows = list(reader)
    if not rows or not {'firm_name', 'aum_usd', 'firm_type_normalized', 'ai_enrichment_status', 'data_source'}.issubset(original_columns):
        raise SystemExit('Expected enriched leads CSV from 02_enrich_leads.py')
    synthetic_only = all(r.get('data_source') == 'SYNTHETIC PROVIDED DATA' for r in rows)
    for row in rows:
        row['aum_usd'] = parse_dollars(row.get('aum_usd'))
        row['avg_client_usd'] = parse_dollars(row.get('avg_client_usd'))
        row['email_valid'] = row.get('email_valid', '').strip().lower() == 'true'
        score(row)
        row['email_draft'] = ''
        row['email_draft_status'] = 'not selected for drafting'
    rows.sort(key=lambda r: (r['route'] == 'SALES REVIEW', r['icp_score']), reverse=True)

    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    client = None
    if api_key and args.max_ai_drafts:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    # Prioritize highest-scoring eligible sales prospects; favor enriched ties.
    draft_candidates = sorted(
        [r for r in rows if r['route'] == 'SALES REVIEW'],
        key=lambda r: (r['icp_score'], r.get('ai_enrichment_status') == 'INPUT_ANALYSIS_COMPLETE'),
        reverse=True)
    attempted = 0
    for row in draft_candidates:
        if attempted >= args.max_ai_drafts:
            continue
        if not client:
            row['email_draft_status'] = 'No API key — no AI email generated'
            continue
        if row.get('ai_enrichment_status') != 'INPUT_ANALYSIS_COMPLETE':
            row['email_draft_status'] = 'Skipped — enrichment incomplete'
            continue
        attempted += 1
        try:
            generated = llm_message(row, client)
            if synthetic_only:
                row['email_draft'] = '[SYNTHETIC-LEAD DEMO — DO NOT SEND]\n' + generated
                row['email_draft_status'] = 'AI DRAFT — SYNTHETIC INPUT — DO NOT SEND'
            else:
                row['email_draft'] = generated
                row['email_draft_status'] = 'AI DRAFT — human/compliance review required'
        except Exception as exc:
            row['email_draft_status'] = f'AI DRAFT FAILED ({type(exc).__name__})'

    fields = list(dict.fromkeys(original_columns + [
        'icp_score', 'score_explanation', 'buyer_motion', 'route', 'email_draft_status', 'email_draft']))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    print(f'03 SCORE: {len(rows)} unique firms | routes {dict(Counter(r["route"] for r in rows))}')
    print(f'AI input analyses: {sum(r.get("ai_enrichment_status") == "INPUT_ANALYSIS_COMPLETE" for r in rows)}')
    print(f'AI draft attempts: {attempted}; all synthetic drafts are labeled DO NOT SEND')
    print(f'Saved: {args.output}')
    print('Filter the route column to SALES REVIEW for the sales shortlist (no extra CSV).')
    print('Top 5:')
    for row in rows[:5]:
        print(f'  {row["icp_score"]:3d} | {row["firm_name"]} | {row["route"]}')


if __name__ == '__main__':
    main()
