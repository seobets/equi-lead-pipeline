# Equi — three-step, AI-enriched lead qualification

**Three Python scripts, three CSV outputs, one straightforward workflow.** This is a working assessment prototype, not a production deployment or a real outreach campaign.

| Step | Run | Input | Output |
| --- | --- | --- | --- |
| Clean and dedupe | `python 01_clean_leads.py` | `sample-leads-SYNTHETIC.csv` (50 messy records) | `outputs/01_cleaned_leads.csv` (45 firms) |
| OpenAI enrichment | `python 02_enrich_leads.py` | `outputs/01_cleaned_leads.csv` | `outputs/02_enriched_leads.csv` (45 records + AI context) |
| Score, route, draft | `python 03_score_leads.py` | `outputs/02_enriched_leads.csv` | `outputs/03_scored_leads.csv` (all firms and draft emails) |

**No before-and-after file or second shortlist.** Filter `route = SALES REVIEW` in `03_scored_leads.csv` to see sales priorities.

## Setup — Windows PowerShell / VS Code

1. Extract the ZIP into your preferred folder and open **that folder** in VS Code.
2. Install dependencies (Python 3.10+):

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env`, set `OPENAI_API_KEY` to your private API key, and keep `.env` off GitHub. Optional models: `OPENAI_ENRICH_MODEL=gpt-4.1-mini`, `OPENAI_MODEL=gpt-4.1-mini`.
4. First try **five AI enrichments**, then finish all 45 without repeating the first five:

   ```powershell
   python 01_clean_leads.py
   python 02_enrich_leads.py --max-new 5
   python 02_enrich_leads.py
   python 03_score_leads.py --max-ai-drafts 5
   ```

Once enrichment has completed, the shorter daily workflow is:

```powershell
python 01_clean_leads.py
python 02_enrich_leads.py
python 03_score_leads.py
```

`02_enrich_leads.py` **caches completed analyses** in its output CSV using a fingerprint of the relevant input fields and model. Running it again does not repeat paid API calls if the input is unchanged. Use `python 02_enrich_leads.py --force` ONLY when you intentionally want to reanalyze all rows and incur charges. Use `--max-new 5` to limit new calls while testing. Progress is saved as it runs, so interruptions can be resumed. The scorer's `--max-ai-drafts 0` suppresses paid drafting calls.

If there is no API key, stage 2 exits with a helpful error rather than quietly replacing AI with fictional scenarios. This version does **not** generate simulated MFO announcements.

## What OpenAI does in stage 2

It receives only the supplied, normalized record (firm type, AUM, client wealth band, alternatives exposure, decision-maker title and CRM notes). Using the Responses API with Pydantic structured outputs, it produces:

- `ai_potential_need`, `ai_opportunity_hypothesis`: **hypotheses**, not company-verified facts.
- `ai_buying_signal_type`, `ai_buying_signal_basis`: categorization and separation of **explicit provided CRM notes**, inference, or no event.
- `ai_signal_source_field`, `ai_signal_quote`: the exact provided note supporting an explicit signal; invalid claims are downgraded to inference.
- `ai_decision_maker_strategy`, `ai_outreach_angle`: how a founder, CIO, or research champion might best be approached.
- `ai_evidence_basis`, `ai_research_limits`, `ai_confidence`: explainability and uncertainty.
- `ai_enrichment_status`: `INPUT_ANALYSIS_COMPLETE`, `NOT_PROCESSED`, or an error status. `ai_model` and `ai_input_hash` support reproducibility and caching.

**Important limitation:** The supplied company names are **synthetic**. Stage 2 intentionally makes **no web-search calls**, does not guess company websites, and does not claim to have discovered recent real events. This is real LLM analysis of the supplied data, not real-world factual enrichment. Expanding to real firms would require identity-verified websites/public filings, source dates/URLs, a human verification queue, and privacy/compliance review.

## Stage 3: commercial decisions, not black-box AI ranking

Deterministic scoring: up to **25** firm type, **20** AUM, **20** client base, **15** alternatives exposure, **10** decision-maker access, **10** documented buying/relationship trigger. Exclusions for unsuitable firm types and >$30B AUM are independent of point totals. An AI **inference alone gets no buying-signal points**. An event clearly written in the original CRM notes may count, with its exact source text; this is still **not externally verified**. This avoids manufacturing urgency out of thin air.

The model's commercial hypotheses instead inform the `score_explanation`, `enrichment_status`, and, especially, the **AI outreach prompt**. Stage 3 chooses the highest-scoring `SALES REVIEW` leads (default top 5), asks OpenAI to draft thoughtful, role-aware email bodies using the enriched angle, and labels all synthetic drafts **DO NOT SEND**. No emails are actually sent. Everyone should receive a human and financial-compliance review before real outreach.

The input's limited client-eligibility information, informal notes, and score weights are **assumptions to validate with Equi**, not ground truth. Some records have missing AUM or contact information; these are routed for research instead of being overconfidently scored.

## A/B test and operating metrics

**Hypothesis:** Providing a relevant, evidence-grounded buying angle increases *qualified conversations*, not just opens.

- **A:** Decision-maker and firm-type personalization using verified ICP fields.
- **B:** Same length and CTA, but use a **verified, time-relevant external event** when available. For the synthetic dataset, this is a **proposed experiment**—it cannot be executed as a real campaign.
- **Primary outcome:** Qualified meetings per contacted account; report positive replies, meeting attendance, and pipeline opportunities as secondary measures.
- **Quality guardrails:** Wrong-firm matches, invented facts, compliance rejection rate, bounced emails, opt-outs, research minutes per usable insight, and cost per qualified meeting.
- **Scale/kill:** Review after several weeks and enough contacted accounts for a useful directional comparison. Stop a variant that creates low-quality meetings, misleading claims, or uneconomic research overhead. Small samples are not statistically conclusive.

## Design trade-offs

- **Why separate scripts?** Every stage can be inspected, retried, or replaced without running the whole workflow.
- **Why CSV instead of a database?** Easy to audit and demonstrate within five minutes; less robust at scale.
- **Why one LLM request per firm?** Easy to trace/debug and cache; could later use batch processing for cost.
- **Why input-only enrichment?** Fictional companies have no reliable public records. Attaching real companies' websites would contaminate the demo.
- **Why no automatic sends?** Wealth-management suitability and investment claims need human approval.
- **Why deterministic scoring?** Equi can debate the weights and explanations. AI supplies context, not unquestionable ground truth.

**For the complete assessment:** this repository addresses Part 2. Part 1's demand plan, its working slice, and the five-minute video are separate submission deliverables.
