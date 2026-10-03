# UI hero demonstration

The backend remains frozen at `58b7740`. This increment changes the single HTML
console and its demonstration records only. No guard, prompt, semantic adapter,
Judgment rule or business scenario changes.

## Start and check the runtime

From `track_2b`, `make run` starts Docker. Open `http://localhost:8000/ui`.
With no `LLM_BASE_URL`, the page explicitly shows **Offline demo**.
For live inference, supply `LLM_NAME=swiss-ai/Apertus-v1.5-70B`, `LLM_BASE_URL`
and `LLM_API_KEY` in the runtime environment before `make run`. The Makefile
passes variable names into Docker. Do not place credentials in a file, browser
form, command argument or demonstration capture. Check `/health` and inspect
model IDs, usage and provider errors in Technical Details after the analysis.

## The 30-second explanation, after inference completes

1. Click **Load hero case**, then **Analyze inquiry**. The synthetic buyer asks
   for about 420 canvas totes, a USD 12.50 target, FOB Shanghai and delivery
   before Nov 15. None of these terms has company approval.
2. Start with **Recommended Action**: Sales must request missing specifications
   before internal costing. **Uncertainty** separates the missing input from
   customer positions and pending company approvals.
3. Click the target-price evidence card. The original email highlights the exact
   quote. The amount remains a **Customer target**, with confirmation pending.
4. Show **Guard** and the actual checked output path, then the draft. The draft
   is for human review. **Human Approval** remains pending, even if the guard
   passes. Copying does not approve or send it.

The timing is a presentation target, not a measured newcomer comprehension result.
Inference runs before this explanation; its latency is displayed in the saved
validation record. Do not promise a particular retry or fallback: the live model
may take any checked path. Failed final checks withhold the draft and disable copy.

## Source and interface boundaries

The hero and its expectations are fixed in `data/validation/ui-002/hero-case.json`.
They were fixed before live inference. There are no prefilled model results.
**Draft evidence** comes from `/process`; **Decision evidence** independently
comes from the existing deterministic Judgment email adapter. The two views and
Technical Details expose that separation. English interface copy translates known
contract explanations; original backend responses remain available unchanged.
The draft remains in the backend's output language; the frontend does not rewrite it.

Changing the email, workflow or sample clears the prior result. Older email
samples run in drafting-only mode to avoid silently treating complaints as new
inquiries. Payment and sample-test source-card workflows remain under a separate
collapsed section. Their cards are operator-attested, not authenticated, and are
not automatically extracted from the email.

Configured guard checks do not establish draft completeness. Some frozen demo
fixtures still use reduced-detail recovery paths; min/max draft fidelity remains
prompt-only. This UI increment does not address those backend limits.

## Observed live hero result

The clean staged source export ran through Docker and the actual browser in real
CSCS Apertus v1.5 70B mode. One hero analysis took approximately 10.0 seconds,
4 model calls and 4,360 tokens. The first draft triggered `unsupported_number:11`
and `requested_date_stated_as_our_delivery:f004`; the retry passed the final guard.
The recommendation was `REQUEST_INFORMATION`, owned by Sales, with human approval
required. See `data/validation/ui-002/` for unchanged raw responses and verification. Rendered screenshots are retained in local validation artifacts.

The retry omitted the numeric quantity, the target price and the question asking
for specifications. This is a visible backend completeness limitation. Present the
recommended action and uncertainty as the human review task; do not claim that the
model wrote a complete customer follow-up. The UI leaves the actual draft unchanged.