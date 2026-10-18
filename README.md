# Equi synthetic lead pipeline — assessment prototype

## Run

1. Open this folder in VS Code and open a terminal.
2. Install packages: `python -m pip install -r requirements.txt`
3. Run without a key to preview cleansing and scoring: `python pipeline.py`
4. Add an OpenAI API key to `.env` and rerun to generate AI message drafts for the top 10 eligible firms.

Output files: `outputs/results.csv` and `outputs/sales_shortlist.csv`.

## Scoring and trade-offs

Maximum points: firm type (25), AUM (20), underlying client wealth (20), alternatives experience (15), decision maker (10), and relationship/trigger (10). Disqualifying firm types and firms above $30B AUM are excluded regardless of score. Missing or ambiguous values remain marked unknown and require research. Exact/near-duplicate firms are merged using similar normalized names, city, type, and (where possible) email domain.

**Limitation:** The supplied input is explicitly synthetic. Normalization and derived fields are performed, but no external facts about these hypothetical firms are invented. `enrichment_status` documents that. A real deployment would verify AUM, SEC filings, company websites, and buyer contacts. `11500` is intentionally treated as ambiguous unless supported by the duplicate `11.5B` row. This prevents silently misreading units.

No emails are sent; all LLM drafts require human review and financial-marketing compliance review.

## A/B hypothesis and measurement

For the eligible top-scored prospect cohort, randomize outreach **at the firm level** into:

- A: tailored observations about the firm's alternatives exposure and clients.
- B: tailored approach focused on advisor differentiation and supporting end-client communication.

Keep sender, send day, audience quality, and CTA comparable. Record deliveries, bounces, relevant replies, accepted meetings, and qualified opportunities. Primary metric: qualified meetings per 100 delivered emails. Use positive response rate as an earlier directional signal. Start with 20–30 contacts per cell when available and treat small samples as exploratory, not statistically conclusive.

## Review checklist

Check that no synthetic firms are represented as verified, that excluded firm types never appear in the sales shortlist, that notes don't imply unverified relationships, and that no AI draft makes investment performance claims.
