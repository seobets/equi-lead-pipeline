"""Equi take-home assessment — reproducible synthetic lead qualification pipeline.

Run: python pipeline.py
Optional AI personalization: set OPENAI_API_KEY in .env, then run again.
This sample input is SYNTHETIC; company facts are never asserted as verified online.
"""
import csv
import os
import re
import unicodedata
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / 'sample-leads-SYNTHETIC.csv'
OUTPUT = ROOT / 'outputs'
load_dotenv(ROOT / '.env')


def clean(text):
    return str(text or '').strip()


def normalize(text):
    txt = unicodedata.normalize('NFKD', clean(text).lower())
    return ''.join(c for c in txt if not unicodedata.combining(c))


def firm_key(name):
    s = re.sub(r'[^a-z0-9 ]+', ' ', normalize(name))
    s = re.sub(r'\b(llc|inc|incorporated|company|co|group|grp|advisors|advisers|advisory|partners|wealth|the)\b', ' ', s)
    return ' '.join(s.split())


def email_domain(email):
    email = clean(email).lower().replace(' ', '')
    if re.fullmatch(r'[^@\s]+@[^@\s]+\.[a-z]{2,}', email):
        return email.split('@', 1)[1]
    return ''


def amount_usd(value, kind='aum'):
    """Return integer dollars, or None if value is blank/ambiguous.
    Bare >=1_000_000 interpreted as dollars; bare 11500 is deliberately ambiguous.
    """
    s = clean(value).lower().replace('$', '').replace(',', '').replace(' ', '')
    if not s:
        return None
    m = re.fullmatch(r'(\d+(?:\.\d+)?)(b|bn|billion|m|mm|million|k|thousand)?', s)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2)
    multiplier = {'b':1e9, 'bn':1e9, 'billion':1e9,
                  'm':1e6, 'mm':1e6, 'million':1e6,
                  'k':1e3, 'thousand':1e3}.get(unit)
    if multiplier:
        return round(n*multiplier)
    if n >= 1_000_000:
        return round(n)
    # A bare number like 11500 may be AUM in millions or literal dollars.
    return None


def firm_type(raw):
    s = normalize(raw)
    if s == 'ria':
        return 'RIA'
    if s in ('mfo', 'multi-family office', 'multi family office'):
        return 'MFO'
    if s in ('single family office', 'sfo'):
        return 'SFO'
    if 'wirehouse' in s:
        return 'Wirehouse'
    if 'tamp' in s:
        return 'TAMP'
    if 'hedge fund manager' in s or 'private credit manager' in s:
        return 'Investment Manager'
    if 'broker-dealer' in s:
        return 'Broker-Dealer'
    return 'Unknown'


def normalize_exposure(value):
    s = normalize(value)
    if not s or s in ('n/a', 'na'):
        return ''
    s = re.sub(r'\bpe\b', 'private equity', s)
    s = re.sub(r'\bre\b', 'real estate', s)
    s = s.replace(' / ', ', ').replace('/', ',')
    return s


def same_firm(a, b):
    # Require same city and reasonable identity evidence; avoid merging unrelated firms.
    if normalize(a['city']) != normalize(b['city']):
        return False
    if a['firm_type_normalized'] != b['firm_type_normalized']:
        return False
    ka, kb = firm_key(a['firm_name']), firm_key(b['firm_name'])
    similar = bool(ka and kb) and SequenceMatcher(None, ka, kb).ratio() >= .79
    domain_a, domain_b = email_domain(a['email']), email_domain(b['email'])
    domain_match = bool(domain_a and domain_b and domain_a == domain_b)
    # Exact domain without any company-name similarity could be a shared provider.
    names_related = SequenceMatcher(None, normalize(a['firm_name']), normalize(b['firm_name'])).ratio() >= .55
    return similar or (domain_match and names_related)


def combine_records(rows):
    groups = []
    for row in rows:
        match = next((g for g in groups if any(same_firm(row, item) for item in g)), None)
        if match is None:
            groups.append([row])
        else:
            match.append(row)
    merged = []
    for group in groups:
        # Prefer most complete entry; fill gaps from duplicates but never fabricate fields.
        primary = max(group, key=lambda r: sum(bool(clean(v)) for v in r.values()) + 2*bool(email_domain(r['email'])))
        combined = primary.copy()
        for r in group:
            for key in primary:
                if not clean(combined[key]) and clean(r[key]):
                    combined[key] = r[key]
        # Value in primary may be ambiguous (11500); use unambiguous duplicate value.
        for key in ('aum', 'avg_client_size'):
            if amount_usd(combined[key]) is None:
                known = next((r[key] for r in group if amount_usd(r[key]) is not None), None)
                if known:
                    combined[key] = known
        combined['duplicate_rows'] = len(group)
        combined['merged_names'] = ' | '.join(dict.fromkeys(r['firm_name'] for r in group))
        combined['firm_type_normalized'] = firm_type(combined['firm_type'])
        combined['aum_usd'] = amount_usd(combined['aum'])
        combined['avg_client_usd'] = amount_usd(combined['avg_client_size'], 'client')
        combined['email'] = clean(combined['email']).replace(' ', '').lower()
        combined['email_valid'] = bool(email_domain(combined['email']))
        combined['email_domain'] = email_domain(combined['email'])
        combined['alts_normalized'] = normalize_exposure(combined['alts_exposure'])
        combined['data_source'] = 'provided synthetic CSV; not web-verified'
        merged.append(combined)
    return merged


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

    if any(t in notes for t in ('warm intro', 'rebrand', 'transition to mfo')):
        points += 10
        reasons.append('warm relationship or transition trigger (+10)')
    elif 'principal-led' in notes or 'can decide alone' in notes:
        points += 8
        reasons.append('principal-led, faster decisions (+8)')
    elif 'competitor' in notes:
        reasons.append('recent competitor adoption: timing concern (+0)')
    else:
        points += 2
        reasons.append('no documented buying trigger (+2)')

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
    row['buyer_motion'] = 'Committee education' if ('research' in title or 'committee' in notes) else 'Principal/CIO conversation'
    row['enrichment_status'] = 'Cleaned/derived from synthetic input; external enrichment not performed'
    return row


def llm_message(row, client):
    """Draft only; never send. All facts come from supplied synthetic row."""
    facts = {
        'firm':row['firm_name'], 'firm_type':row['firm_type_normalized'],
        'aum_usd':row['aum_usd'], 'contact':row['primary_contact'],
        'title':row['title'], 'alternatives':row['alts_normalized'],
        'client_size_usd':row['avg_client_usd'], 'notes':row['notes'],
        'motion':row['buyer_motion'],
    }
    instructions = (
        'You draft accurate first-contact B2B emails for Equi, a provider of managed-risk evergreen '
        'liquid alternative investment solutions and advisor-branded white-label fund-of-funds. '
        'Equi works with independent RIAs and multi-family offices, not retail investors. '
        'Draft a concise, human, low-pressure email under 95 words to the given contact. '
        'Use ONLY the provided SYNTHETIC lead facts; do not claim you visited websites, spoke to the '
        'person, verified facts, or saw private information. Do not invent a relationship, returns, '
        'guarantees, track record, or product terms. If notes say warm intro, do not name a mutual '
        'contact unless one is explicitly given. Explain the business relevance of Equi, include '
        'one thoughtful question and a gentle call to discuss. Output only the email body.'
    )
    response = client.responses.create(
        model=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'),
        instructions=instructions,
        input=str(facts),
    )
    return response.output_text.strip()


def write_csv(path, rows, columns):
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def main():
    if not INPUT.exists():
        raise FileNotFoundError(f'Put sample-leads-SYNTHETIC.csv next to pipeline.py: {INPUT}')
    OUTPUT.mkdir(exist_ok=True)
    with INPUT.open(newline='', encoding='utf-8-sig') as f:
        source = list(csv.DictReader(f))
    for row in source:
        row['firm_type_normalized'] = firm_type(row['firm_type'])

    prospects = [score(x) for x in combine_records(source)]
    prospects.sort(key=lambda r: (r['route'] == 'SALES REVIEW', r['icp_score']), reverse=True)

    api_key = os.getenv('OPENAI_API_KEY', '').strip()
    model_client = None
    if api_key:
        from openai import OpenAI
        model_client = OpenAI(api_key=api_key)
    drafted = 0
    for row in prospects:
        row['email_draft'] = ''
        row['email_draft_status'] = 'not eligible for auto draft'
        if row['route'] not in ('SALES REVIEW',) or drafted >= 10:
            continue
        if not model_client:
            row['email_draft_status'] = 'API KEY MISSING — LLM not run'
            continue
        try:
            row['email_draft'] = llm_message(row, model_client)
            row['email_draft_status'] = 'LLM draft — needs human/compliance review'
            drafted += 1
        except Exception as exc:
            row['email_draft_status'] = f'LLM error ({type(exc).__name__}) — retry'

    cols = ['firm_name', 'firm_type_normalized', 'aum', 'aum_usd', 'avg_client_size',
            'avg_client_usd', 'alts_exposure', 'primary_contact', 'title', 'email',
            'email_domain', 'email_valid', 'city', 'state', 'country', 'notes',
            'duplicate_rows', 'merged_names', 'icp_score', 'score_explanation',
            'buyer_motion', 'route', 'enrichment_status', 'data_source',
            'email_draft_status', 'email_draft']
    write_csv(OUTPUT / 'results.csv', prospects, cols)
    shortlist = [r for r in prospects if r['route'] == 'SALES REVIEW']
    write_csv(OUTPUT / 'sales_shortlist.csv', shortlist, cols)
    print(f'Input records: {len(source)} | Unique firms: {len(prospects)}')
    print('Routing:', dict(Counter(r['route'] for r in prospects)))
    print(f'Sales-review shortlist: {len(shortlist)} firms')
    print('AI status:', 'OpenAI drafts attempted' if model_client else 'OPENAI_API_KEY missing — no AI calls')
    print('Saved: outputs/results.csv and outputs/sales_shortlist.csv')
    print('\nTop prospects:')
    for r in prospects[:5]:
        print(f"  {r['icp_score']:3d}  {r['firm_name']}  [{r['route']}]")


if __name__ == '__main__':
    main()
