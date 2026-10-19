"""Equi assessment — stage 1 of 3: clean, standardize and deduplicate leads."""
import argparse
import csv
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent

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


def main():
    parser = argparse.ArgumentParser(description="01 | Clean, normalize and deduplicate Equi leads")
    parser.add_argument("--input", type=Path, default=ROOT / "sample-leads-SYNTHETIC.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "01_cleaned_leads.csv")
    args = parser.parse_args()
    if not args.input.is_file():
        raise SystemExit(f"Missing input: {args.input}")
    with args.input.open(newline="", encoding="utf-8-sig") as handle:
        source = list(csv.DictReader(handle))
    required = {'firm_name', 'firm_type', 'city', 'aum', 'avg_client_size', 'email', 'alts_exposure', 'primary_contact', 'title', 'notes'}
    if not source or not required.issubset(source[0]):
        raise SystemExit("Input CSV is empty or missing required lead fields")
    for row in source:
        row['firm_type_normalized'] = firm_type(row['firm_type'])
    leads = combine_records(source)
    for lead in leads:
        lead['data_source'] = ("SYNTHETIC PROVIDED DATA" if "synthetic" in args.input.name.lower()
                               else "USER-PROVIDED DATA — NOT INDEPENDENTLY VERIFIED")
    fields = list(dict.fromkeys(list(source[0]) + [
        'firm_type_normalized', 'aum_usd', 'avg_client_usd', 'email_valid',
        'email_domain', 'alts_normalized', 'duplicate_rows', 'merged_names', 'data_source']))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader(); writer.writerows(leads)
    print(f"01 CLEAN: {len(source)} input rows -> {len(leads)} unique firms; {len(source)-len(leads)} duplicate rows consolidated")
    print(f"Saved: {args.output}")


if __name__ == '__main__':
    main()
