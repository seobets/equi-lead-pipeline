"""Equi assessment | 02: OpenAI enrichment across four commercial hypotheses.

Uses the supplied SYNTHETIC lead CSV only. No web search, announcements,
confirmed buying intent or publicly verified firm facts are claimed.

Stage 1: python 01_clean_leads.py
Stage 2: python 02_enrich_leads.py --max-new 5   # trial, then rerun without limit
Stage 3: python 03_score_leads.py

Preserves all original AI columns required by the existing 03_score_leads.py.
Adds independently reviewable evidence/status/angle for four hypotheses.
"""
import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')

# Changing the version invalidates prior OpenAI cache rows automatically.
ANALYSIS_VERSION = 'equi_four_hypotheses_v2'
HYPOTHESES = (
    ('ria_to_mfo', 'RIA transitioning or expanding into multi-family-office services'),
    ('alternatives_expansion', 'Expanding alternatives offerings or coverage'),
    ('investment_differentiation', 'Pursuing proprietary or white-label investment differentiation'),
    ('infrastructure_gap', 'Growth or client complexity outpacing internal investment infrastructure'),
)
LEGACY_AI_COLUMNS = [
    'ai_potential_need', 'ai_opportunity_hypothesis', 'ai_buying_signal_type',
    'ai_buying_signal_basis', 'ai_signal_source_field', 'ai_signal_quote',
    'ai_decision_maker_strategy', 'ai_outreach_angle', 'ai_confidence',
    'ai_evidence_basis', 'ai_research_limits', 'ai_enrichment_status',
    'ai_model', 'ai_input_hash',
]
HYPOTHESIS_COLUMNS = [
    f'ai_{key}_{field}'
    for key, _ in HYPOTHESES
    for field in ('status', 'source_field', 'quote', 'reasoning', 'equi_opportunity')
]
AI_COLUMNS = LEGACY_AI_COLUMNS + HYPOTHESIS_COLUMNS
INPUT_FIELDS = [
    'firm_name', 'firm_type_normalized', 'city', 'state', 'country',
    'aum_usd', 'avg_client_usd', 'alts_normalized', 'notes', 'last_touch',
    'title', 'custodian',
]


class HypothesisAssessment(BaseModel):
    status: Literal['INPUT_EXPLICIT', 'PLAUSIBLE_UNVERIFIED', 'NO_EVIDENCE'] = Field(
        description='INPUT_EXPLICIT only for a specific event actually stated in notes/last_touch; '
                    'PLAUSIBLE_UNVERIFIED for a reasoned commercial opportunity without such an event; '
                    'NO_EVIDENCE when there is no useful reason even to infer opportunity.'
    )
    source_field: Literal[
        'notes', 'last_touch', 'firm_type_normalized', 'aum_usd',
        'avg_client_usd', 'alts_normalized', 'title', 'none',
    ] = Field(description='One existing CSV field supporting the assessment. Use none if no support.')
    evidence_quote: str = Field(description='Exact, brief substring from source_field; blank if none.')
    reasoning: str = Field(description='Specific evidence-based logic; do not imply a hypothetical event occurred.')
    equi_opportunity: str = Field(description='Conditional Equi relevance, or empty if no defensible angle.')


class FourHypothesisAnalysis(BaseModel):
    ria_to_mfo: HypothesisAssessment
    alternatives_expansion: HypothesisAssessment
    investment_differentiation: HypothesisAssessment
    infrastructure_gap: HypothesisAssessment
    ai_potential_need: str = Field(description='Best plausible specific buyer challenge, never a proven pain point.')
    ai_opportunity_hypothesis: str = Field(description='Concise if-then hypothesis supported by the input.')
    ai_decision_maker_strategy: str = Field(description='Buyer-aware strategy for the supplied title and decision process.')
    ai_outreach_angle: str = Field(description='Non-presumptuous question/topic tied to an observed fact or clear hypothesis.')
    ai_confidence: Literal['LOW', 'MEDIUM', 'HIGH']
    ai_evidence_basis: str = Field(description='Exact supplied fields behind the hypothesis; never public sources.')
    ai_research_limits: str = Field(description='Unverified needs/events requiring confirmation in a real sales process.')


SYSTEM = """You are a skeptical B2B research analyst for Equi, selling ONLY to the right
wealth-advisor buyers. Equi partners with independent RIAs and multi-family offices
($1B–$30B AUM, best $5B+, clients typically $5M–$30M), offering evergreen managed-risk
liquid alternatives, white-label fund-of-funds, and advisor-facing educational materials.
RIAs: approach founders/principals; MFOs: approach CIOs; committee-run firms: research
and due diligence champions. Investment managers, wirehouses, TAMPs, broker-dealers
and large aggregators are NOT buyers. Single-family offices are weaker fits.

INPUT IS SYNTHETIC. You have NO web access. ONLY the supplied JSON can support claims.
No invented announcements, family-office launches, hiring, expansion, returns, websites,
internal shortages, buyer needs, client conversations, or introduction status.

Systematically and INDEPENDENTLY evaluate ALL FOUR hypotheses:
1. ria_to_mfo: Is an independent RIA actually transitioning/rebranding/launching MFO
   services? An RIA with wealthy clients is NOT evidence of an ongoing transition.
   An existing MFO is NOT transitioning merely by being an MFO.
2. alternatives_expansion: Evidence of NEW alternatives products, hiring or expanded
   allocations? EXISTING alternatives exposure is not evidence of expansion.
3. investment_differentiation: Is the firm actively developing a proprietary, branded,
   or white-label investment offering? Principal-led alone is NOT evidence of that plan.
4. infrastructure_gap: Is there ACTUAL evidence of rapid growth, client complexity, or
   strain on internal investment research? Large AUM or a small contact team alone
   DOES NOT prove strain or growth.

For each hypothesis use one of these statuses:
- INPUT_EXPLICIT: An actual event/change/plan EXPLICITLY noted in 'notes' or 'last_touch'.
  Give an exact short substring from that SAME field, not a paraphrase. This is still
  unverified CRM input, NOT independent research.
- PLAUSIBLE_UNVERIFIED: There is a specific, defensible commercial inference from
  supplied fields, but no evidence the buyer is actively doing or seeking it. Quote
  an exact relevant field value when possible. Explain uncertainty.
- NO_EVIDENCE: Nothing sufficiently specific supports that hypothesis; do not force
  a story. Set source_field='none', evidence_quote='', equi_opportunity='' if none.

Do not use generic 'they probably need Equi' statements for all firms. Keep each
hypothesis distinctive, cautious, concise, and grounded. A possible customer need is
NOT a recent buying signal. For the main outreach_angle, prefer an observable fact
and an exploratory question, not a claimed event or a hard product pitch.
A 'warm intro via Tory' does NOT mean Tory already introduced anyone or recommended
contacting the recipient. Describe relationships precisely.
"""


def fingerprint(row, model):
    payload = {
        'analysis_version': ANALYSIS_VERSION,
        'model': model,
        'fields': {k: row.get(k, '') for k in INPUT_FIELDS},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def is_out_of_scope(row):
    kind = str(row.get('firm_type_normalized', '')).strip()
    if kind in ('Wirehouse', 'TAMP', 'Investment Manager', 'Broker-Dealer'):
        return True
    try:
        aum = float(row.get('aum_usd') or 0)
        if aum > 30_000_000_000:
            return True
    except (ValueError, TypeError):
        pass
    return False


def _has_any(text, patterns):
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def explicit_event_supported(key, row, source, quote):
    """Never promote an OpenAI claim to explicit without a matching CRM quote + trigger.

    No word-based gate alone establishes external verification; labels stay INPUT_EXPLICIT.
    """
    if source not in ('notes', 'last_touch') or len(quote.strip()) < 8:
        return False
    original = str(row.get(source) or '')
    if quote.casefold() not in original.casefold():
        return False
    # Require BOTH the action and subject in the literal quote to avoid citing
    # an unrelated phrase as proof of a different buying signal.
    q = quote.casefold()
    if key == 'ria_to_mfo':
        return (row.get('firm_type_normalized') == 'RIA'
                and _has_any(q, (r'family[\s-]*office', r'\bmfo\b'))
                and _has_any(q, (r'transition', r'rebrand', r'launch', r'expan', r'conver', r'mov(?:e|ing)', r'add(?:ed|ing)?')))
    if key == 'alternatives_expansion':
        return (_has_any(q, (r'\balts\b', r'alternativ', r'private.credit', r'private.equity', r'hedge.fund'))
                and _has_any(q, (r'expan', r'launch', r'build', r'add(?:ed|ing)?', r'hir(?:e|ing)')))
    if key == 'investment_differentiation':
        return (_has_any(q, (r'white.label', r'proprietary', r'own.brand', r'branded.fund', r'differenti'))
                and _has_any(q, (r'launch', r'build', r'develop', r'explor', r'plan', r'creat', r'add')))
    if key == 'infrastructure_gap':
        return (_has_any(q, (r'investment.team', r'research.team', r'infrastructure', r'capacity', r'staff', r'analyst', r'due.diligence'))
                and _has_any(q, (r'outgrow', r'stretch', r'strain', r'understaff', r'hir', r'expand', r'scal', r'gap', r'need')))
    return False


def clean_assessment(key, entry, row):
    a = entry.model_dump()
    a['evidence_quote'] = (a['evidence_quote'] or '').strip()
    if a['status'] == 'INPUT_EXPLICIT':
        if not explicit_event_supported(key, row, a['source_field'], a['evidence_quote']):
            # If the model hallucinates the event, erase the putative proof.
            a.update(status='NO_EVIDENCE', source_field='none', evidence_quote='',
                     equi_opportunity='',
                     reasoning='No explicit event supported by the supplied CRM text.')
    elif a['status'] == 'PLAUSIBLE_UNVERIFIED':
        f = a['source_field']
        source_value = str(row.get(f, '')) if f != 'none' else ''
        if f == 'none' or not a['evidence_quote'] or a['evidence_quote'].casefold() not in source_value.casefold():
            # No quoted input support: do not keep a speculative inference.
            a.update(status='NO_EVIDENCE', source_field='none', evidence_quote='',
                     equi_opportunity='',
                     reasoning='No verifiable input field was provided for this inference.')
    else:
        a.update(source_field='none', evidence_quote='', equi_opportunity='')
    return a


def derive_legacy_signal(assessments, row):
    """Preserve existing 03_score_leads.py contract without inventing triggers."""
    for key, type_name in (
        ('ria_to_mfo', 'RIA_TO_MFO_TRANSITION'),
        ('alternatives_expansion', 'ALTERNATIVES_EXPANSION'),
        ('investment_differentiation', 'OTHER_INPUT_EVENT'),
        ('infrastructure_gap', 'OTHER_INPUT_EVENT'),
    ):
        a = assessments[key]
        if a['status'] == 'INPUT_EXPLICIT':
            return {
                'ai_buying_signal_type': type_name,
                'ai_buying_signal_basis': 'INPUT_EXPLICIT',
                'ai_signal_source_field': a['source_field'],
                'ai_signal_quote': a['evidence_quote'],
            }
    # Preserve already-used CRM relationship/timing categories. Actual introduction
    # has NOT necessarily occurred; CRM note is a potential lead-in only.
    for field in ('notes', 'last_touch'):
        v = str(row.get(field, ''))
        if re.search(r'\b(warm\s+intro|intro\s+via|referral\s+via)\b', v, re.I):
            return {
                'ai_buying_signal_type': 'WARM_INTRO',
                'ai_buying_signal_basis': 'INPUT_EXPLICIT',
                'ai_signal_source_field': field,
                'ai_signal_quote': v.strip()[:250],
            }
        if re.search(r'\bcompetitor\b', v, re.I):
            return {
                'ai_buying_signal_type': 'COMPETITOR_ADOPTION',
                'ai_buying_signal_basis': 'INPUT_EXPLICIT',
                'ai_signal_source_field': field,
                'ai_signal_quote': v.strip()[:250],
            }
    return {
        'ai_buying_signal_type': 'NONE',
        'ai_buying_signal_basis': 'NO_SIGNAL',
        'ai_signal_source_field': 'none',
        'ai_signal_quote': '',
    }


def analyze(client, row, model):
    payload = {k: row.get(k, '') for k in INPUT_FIELDS}
    response = client.responses.parse(
        model=model,
        input=[
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
        ],
        text_format=FourHypothesisAnalysis,
    )
    result = response.output_parsed
    if result is None:
        raise ValueError('OpenAI returned no parsed enrichment result')

    outcome = {
        'ai_potential_need': result.ai_potential_need,
        'ai_opportunity_hypothesis': result.ai_opportunity_hypothesis,
        'ai_decision_maker_strategy': result.ai_decision_maker_strategy,
        'ai_outreach_angle': result.ai_outreach_angle,
        'ai_confidence': result.ai_confidence,
        'ai_evidence_basis': result.ai_evidence_basis,
        'ai_research_limits': result.ai_research_limits,
    }
    assessments = {}
    for key, _label in HYPOTHESES:
        assessment = clean_assessment(key, getattr(result, key), row)
        assessments[key] = assessment
        for field, value in assessment.items():
            out_field = 'quote' if field == 'evidence_quote' else field
            outcome[f'ai_{key}_{out_field}'] = value
    outcome.update(derive_legacy_signal(assessments, row))
    return outcome


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description='02 | OpenAI analysis of four Equi buying hypotheses')
    parser.add_argument('--input', type=Path, default=ROOT / 'outputs' / '01_cleaned_leads.csv')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs' / '02_enriched_leads.csv')
    parser.add_argument('--model', default=os.getenv('OPENAI_ENRICH_MODEL') or os.getenv('OPENAI_MODEL') or 'gpt-4.1-mini')
    parser.add_argument('--max-new', type=int, default=None, help='Make at most N new API calls (resume later)')
    parser.add_argument('--force', action='store_true', help='Ignore cached analyses (additional API charges)')
    args = parser.parse_args()
    if args.max_new is not None and args.max_new < 1:
        parser.error('--max-new must be >= 1')
    if not args.input.is_file():
        raise SystemExit(f'Missing input: {args.input}. Run python 01_clean_leads.py first.')
    with args.input.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        rows = list(reader)
    if not rows or not set(INPUT_FIELDS).issubset(fields):
        raise SystemExit('Expected cleaned CSV output from 01_clean_leads.py')
    if not os.getenv('OPENAI_API_KEY', '').strip():
        raise SystemExit('OPENAI_API_KEY missing. Keep it in your private .env file.')

    # Fingerprint includes schema version: older analyses won't be silently reused.
    cache = {}
    if args.output.is_file() and not args.force:
        with args.output.open(newline='', encoding='utf-8-sig') as handle:
            for old in csv.DictReader(handle):
                cache[(old.get('firm_name'), old.get('city'), old.get('ai_input_hash'))] = old

    from openai import OpenAI
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=60.0, max_retries=2)
    output_fields = list(dict.fromkeys(fields + AI_COLUMNS))
    completed_rows = []
    calls = 0
    reused = 0
    skipped = 0
    errors = 0
    for row in rows:
        key = (row['firm_name'], row['city'], fingerprint(row, args.model))
        old = cache.get(key)
        item = dict(row)
        if is_out_of_scope(row):
            item.update({k: '' for k in AI_COLUMNS})
            item['ai_enrichment_status'] = 'SKIPPED_OUT_OF_SCOPE'
            item['ai_research_limits'] = 'Outside Equi ICP; do not prospect.'
            item['ai_input_hash'] = key[2]
            for hypothesis, _ in HYPOTHESES:
                item[f'ai_{hypothesis}_status'] = 'NOT_ASSESSED'
            skipped += 1
        elif old and old.get('ai_enrichment_status') == 'INPUT_ANALYSIS_COMPLETE' and all(
            col in old for col in HYPOTHESIS_COLUMNS
        ):
            item.update({k: old.get(k, '') for k in AI_COLUMNS})
            reused += 1
        elif args.max_new is not None and calls >= args.max_new:
            item.update({k: '' for k in AI_COLUMNS})
            item['ai_enrichment_status'] = 'NOT_PROCESSED'
            item['ai_input_hash'] = key[2]
        else:
            calls += 1
            try:
                result = analyze(client, row, args.model)
                item.update(result)
                item['ai_enrichment_status'] = 'INPUT_ANALYSIS_COMPLETE'
                item['ai_model'] = args.model
                item['ai_input_hash'] = key[2]
                statuses = ', '.join(f'{k}:{result[f"ai_{k}_status"]}' for k, _ in HYPOTHESES)
                print(f'  [{calls}] {row["firm_name"]}: {statuses}', flush=True)
            except Exception as exc:
                errors += 1
                item.update({k: '' for k in AI_COLUMNS})
                item['ai_enrichment_status'] = 'ERROR — ' + type(exc).__name__
                item['ai_input_hash'] = key[2]
                print(f'  [{calls}] {row["firm_name"]}: API error ({type(exc).__name__})', flush=True)
        completed_rows.append(item)
        # Checkpoint every processed row. Interrupted runs can safely resume.
        write_csv(args.output, output_fields, completed_rows + [
            dict(remaining, ai_enrichment_status='NOT_PROCESSED')
            for remaining in rows[len(completed_rows):]
        ])
    write_csv(args.output, output_fields, completed_rows)
    complete = sum(r.get('ai_enrichment_status') == 'INPUT_ANALYSIS_COMPLETE' for r in completed_rows)
    print(f'02 ENRICH: {len(rows)} firms | {complete} AI profiles | {skipped} excluded | '
          f'{reused} reused | {calls} API calls | {errors} errors')
    print('All evidence is FROM THE SUPPLIED SYNTHETIC LEAD RECORDS ONLY; no live research.')
    print(f'Saved: {args.output}')


if __name__ == '__main__':
    main()
