"""Equi assessment — stage 2: AI analysis of the CLEANED lead CSV.

The companies in the supplied dataset are synthetic. This module uses ONLY fields in
that CSV (no web search) and carefully separates observed input from hypotheses.
No fictional announcements, source URLs, or unverifiable 'buying events' are created.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')

ANALYSIS_VERSION = 'equi_input_analysis_v1'
AI_COLUMNS = [
    'ai_potential_need', 'ai_opportunity_hypothesis', 'ai_buying_signal_type',
    'ai_buying_signal_basis', 'ai_signal_source_field', 'ai_signal_quote',
    'ai_decision_maker_strategy', 'ai_outreach_angle', 'ai_confidence',
    'ai_evidence_basis', 'ai_research_limits', 'ai_enrichment_status',
    'ai_model', 'ai_input_hash',
]
INPUT_FIELDS = [
    'firm_name', 'firm_type_normalized', 'city', 'state', 'country',
    'aum_usd', 'avg_client_usd', 'alts_normalized', 'notes', 'last_touch',
    'title', 'custodian',
]


class LeadAnalysis(BaseModel):
    ai_potential_need: str = Field(description='Specific plausible need; hypothesis, not fact.')
    ai_opportunity_hypothesis: str = Field(description='If-then commercial hypothesis grounded in the record.')
    ai_buying_signal_type: Literal[
        'RIA_TO_MFO_TRANSITION', 'ALTERNATIVES_EXPANSION', 'WARM_INTRO',
        'COMPETITOR_ADOPTION', 'OTHER_INPUT_EVENT', 'NONE',
    ]
    ai_buying_signal_basis: Literal['INPUT_EXPLICIT', 'INFERRED_ONLY', 'NO_SIGNAL']
    ai_signal_source_field: Literal['notes', 'last_touch', 'alts_normalized', 'none']
    ai_signal_quote: str = Field(description='Exact substring copied from the source field, or empty.')
    ai_decision_maker_strategy: str = Field(description='Approach for founder/CIO/research champion given title.')
    ai_outreach_angle: str = Field(description='Specific, non-presumptuous opening topic. No invented news.')
    ai_confidence: Literal['LOW', 'MEDIUM', 'HIGH']
    ai_evidence_basis: str = Field(description='Which input fields support the hypothesis, no imagined sources.')
    ai_research_limits: str = Field(description='What is not known or needs independent validation.')


SYSTEM = """You are a careful GTM research analyst for Equi, a B2B partner to independent RIAs
and multi-family offices (MFOs). Equi provides managed-risk evergreen liquid alternatives,
white-label fund-of-funds, and advisor-facing client education materials. Its target firms:
RIA/MFO with roughly $1–30B AUM (especially $5B+), HNW clients $5–30M, some alternatives
experience. RIA principals/founders, MFO CIOs, and research champions are key buyers.

You are analyzing a SYNTHETIC dataset. You have NO access to the web. Treat ONLY the user-
provided JSON fields as evidence. Never invent a firm event, website, source URL, meeting,
personal connection, growth trend, fund return, or advisor need as an established fact.
Every 'need' is a commercial hypothesis. Be specific and helpful, not generic.

Signal logic:
- INPUT_EXPLICIT is allowed ONLY for a current event / relationship / action clearly
  stated in notes or last_touch, with an EXACT quote from that field.
- Existing alternatives exposure alone is NOT an alternatives-expansion buying EVENT.
- A company already being an MFO is NOT an RIA-to-MFO transition event.
- RIA-to-MFO requires explicit transition/rebrand/launch in supplied notes.
- INFERRED_ONLY is an opportunity suggested by characteristics, not verified activity.
- NO_SIGNAL: no observed event or meaningful trigger; use signal_type NONE.
- When not INPUT_EXPLICIT, set source_field='none' and quote=''.
- Never claim to have checked public records or news.
- 'warm intro via X' means a possible introduction, NOT that X has spoken to the prospect.
- Suggested outreach must not assert inferred needs as known problems.
Write useful concise explanations; avoid fluff and product pitching.
"""


def fingerprint(row, model):
    payload = {'analysis_version': ANALYSIS_VERSION, 'model': model,
               'fields': {k: row.get(k, '') for k in INPUT_FIELDS}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def analyze(client, row, model):
    payload = {k: row.get(k, '') for k in INPUT_FIELDS}
    response = client.responses.parse(
        model=model,
        input=[{'role': 'system', 'content': SYSTEM},
               {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
        text_format=LeadAnalysis,
    )
    result = response.output_parsed
    if result is None:
        raise ValueError('Model returned no parsed enrichment output')
    outcome = result.model_dump()
    # Defensive evidence gate: an AI statement cannot create a new confirmed event.
    basis = outcome['ai_buying_signal_basis']
    source = outcome['ai_signal_source_field']
    quote = outcome['ai_signal_quote'].strip()
    if basis == 'INPUT_EXPLICIT':
        original = str(row.get(source, ''))
        signal_type = outcome['ai_buying_signal_type']
        note = original.casefold()
        # In addition to an exact quote, check that the claimed EVENT is actually
        # supported by the note wording, not just the model's classification.
        category_gate = {
            'RIA_TO_MFO_TRANSITION': (
                row.get('firm_type_normalized') == 'RIA'
                and ('family office' in note or 'mfo' in note)
                and any(w in note for w in ('transition', 'rebrand', 'launch', 'expand', 'adding'))
            ),
            'ALTERNATIVES_EXPANSION': (
                any(w in note for w in ('alts', 'alternative', 'private credit', 'private equity'))
                and any(w in note for w in ('expand', 'launch', 'build', 'adding', 'hiring'))
            ),
            'WARM_INTRO': ('intro' in note or 'referral' in note),
            'COMPETITOR_ADOPTION': 'competitor' in note,
            'OTHER_INPUT_EVENT': True,
            'NONE': False,
        }.get(signal_type, False)
        if (source not in ('notes', 'last_touch') or len(quote) < 8
                or quote.casefold() not in original.casefold()
                or not category_gate):
            outcome['ai_buying_signal_basis'] = 'INFERRED_ONLY'
            outcome['ai_signal_source_field'] = 'none'
            outcome['ai_signal_quote'] = ''
    else:
        outcome['ai_signal_source_field'] = 'none'
        outcome['ai_signal_quote'] = ''
        if outcome['ai_buying_signal_type'] == 'NONE':
            outcome['ai_buying_signal_basis'] = 'NO_SIGNAL'
    # Even an exact note quote is evidence only from an unverified synthetic CSV.
    return outcome


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as out:
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description='02 | Enrich cleaned firms using OpenAI on the supplied record only')
    parser.add_argument('--input', type=Path, default=ROOT / 'outputs' / '01_cleaned_leads.csv')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs' / '02_enriched_leads.csv')
    parser.add_argument('--model', default=os.getenv('OPENAI_ENRICH_MODEL') or os.getenv('OPENAI_MODEL') or 'gpt-4.1-mini')
    parser.add_argument('--max-new', type=int, default=None, help='Analyze at most N new rows; others remain NOT_PROCESSED')
    parser.add_argument('--force', action='store_true', help='Reanalyze every row (additional API charges)')
    args = parser.parse_args()
    if args.max_new is not None and args.max_new < 1:
        parser.error('--max-new must be >= 1')
    if not args.input.is_file():
        raise SystemExit(f'Missing cleaned input: {args.input}. Run python 01_clean_leads.py first.')
    with args.input.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        rows = list(reader)
    if not rows or not set(INPUT_FIELDS).issubset(fields):
        raise SystemExit('Expected the cleaned lead CSV created by 01_clean_leads.py')
    if not os.getenv('OPENAI_API_KEY', '').strip():
        raise SystemExit('OPENAI_API_KEY not set. Put your key in a private .env file. No synthetic fallback will be fabricated.')

    # Reuse previous completed analyses when the row and model haven't changed.
    cache = {}
    if args.output.is_file() and not args.force:
        with args.output.open(newline='', encoding='utf-8-sig') as existing:
            for old in csv.DictReader(existing):
                cache[(old.get('firm_name'), old.get('city'), old.get('ai_input_hash'))] = old

    from openai import OpenAI
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=60.0, max_retries=2)
    output_fields = list(dict.fromkeys(fields + AI_COLUMNS))
    fresh = []
    cached = 0
    new_calls = 0
    errors = 0
    for row in rows:
        identity = (row['firm_name'], row['city'], fingerprint(row, args.model))
        old = cache.get(identity)
        item = dict(row)
        if old and old.get('ai_enrichment_status') == 'INPUT_ANALYSIS_COMPLETE':
            item.update({k: old.get(k, '') for k in AI_COLUMNS})
            cached += 1
        elif args.max_new is not None and new_calls >= args.max_new:
            item.update({k: '' for k in AI_COLUMNS})
            item['ai_enrichment_status'] = 'NOT_PROCESSED'
            item['ai_input_hash'] = identity[2]
        else:
            new_calls += 1
            try:
                outcome = analyze(client, row, args.model)
                item.update(outcome)
                item['ai_enrichment_status'] = 'INPUT_ANALYSIS_COMPLETE'
                item['ai_model'] = args.model
                item['ai_input_hash'] = identity[2]
                print(f'  [{new_calls}] {row["firm_name"]}: analyzed ({outcome["ai_buying_signal_basis"]})', flush=True)
            except Exception as exc:
                errors += 1
                item.update({k: '' for k in AI_COLUMNS})
                item['ai_enrichment_status'] = 'ERROR — ' + type(exc).__name__
                item['ai_input_hash'] = identity[2]
                print(f'  [{new_calls}] {row["firm_name"]}: API failed ({type(exc).__name__})', flush=True)
        fresh.append(item)
        # Save progress every row. Interrupted runs can resume without repeating calls.
        if new_calls or not args.output.exists():
            write_csv(args.output, output_fields, fresh + [
                dict(**remaining, ai_enrichment_status='NOT_PROCESSED')
                for remaining in rows[len(fresh):]
            ])
    write_csv(args.output, output_fields, fresh)
    completed = sum(r['ai_enrichment_status'] == 'INPUT_ANALYSIS_COMPLETE' for r in fresh)
    print(f'02 ENRICH: {len(fresh)} firms | {completed} analyzed | {cached} reused | {errors} failures | {new_calls} API attempts')
    print('Source: PROVIDED LEAD DATA ONLY. No web research or independently verified events.')
    print(f'Saved: {args.output}')


if __name__ == '__main__':
    main()
