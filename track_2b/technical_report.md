# Sovereign Trade Copilot
## A traceable first reply for human approval
Track 2B | Online Hack Apertus | Team: Sovereign Trade Copilot | 13 October 2026

Report and new synthetic data: CC-BY-4.0

## 1. Purpose
A professional-looking reply can invent company capabilities or commercial terms.
This prototype prepares a useful first reply for a person, rather than certifying
it safe to send. It processes one new inquiry, with no automatic sending,
quotation execution, payment, production, CRM or memory expansion.

## 2. Final architecture and Apertus role
Original inquiry + source-backed company conditions + declared source state
+ company-neutral Trade Judgment guidance -> short business brief
-> explicit context confirmation when needed -> one Apertus draft
-> small phrase-located warnings -> human editing and explicit approval.

<!-- architecture -->

The brief preserves original source statements and applicable scope. Operator
facts/corrections are optional, not a required reply strategy. They cannot
authorize absent company claims. The demo examples contain a curated business
focus. Guidance prioritizes reliable current answers, up to three decision-changing
questions, No Re-ask, reversible advances and conditional rough costing. Unknown
is not automatically a blocker. Performance targets are not company achievements.
Unread material must not become reviewed or missing.

This is not full typed extraction, deterministic judgment, AUTO message planning,
slot rendering, generation retry or fresh-audit authority. Apertus writes plain
customer-facing text and an optional operator hint from the complete inquiry and
compact brief, returned as two JSON fields. Requested and
returned model: swiss-ai/Apertus-v1.5-70B through CSCS; temperature 0.1; maximum
1,100 output tokens; one transport attempt.

Company conditions retain statement, source, scope and status. The UI imports
Markdown/TXT/text-based PDF or one public HTTPS company page, previews relevant
text, and requires operator authorization before treating it as company truth.
It does not create a persistent profile. Public/working references remain
separate. Mechanical checks validate input shape, source declaration,
authorization, review and draft-version identity. Natural-language warnings are
advisory, incomplete and phrase-located; no automated safe-to-send label exists.
Version 1.3 exposes actual reading coverage under an optional review card, rather
than presenting an inferred business action as a validated decision.

<!-- page -->

## 3. Synthetic data and first-output evaluation
Three original synthetic cases and invented company conditions cover known terms,
quotation-tier purpose/branded sourcing, and one prototype with unread material.
No private customer record, company seed or string-redacted real inquiry is released.

Inputs, business gold and complete prompts were frozen before model calls.
Each case received one first draft: no retries or best-of selection.
The development agent performed semantic review; this is not independent blind
human review. Business focus was curated. Automated UI approvals are not evidence
of human sendability, review speed or daily usefulness.

| Case | Raw grade | Key result |
|---|---|---|
| Hero | B: minor edit | Reliable terms/conditions answered; two useful request groups; explicit assessment-to-costing next move missing |
| Quote tiers | E: commercial risk | General MOQ became per style; parallel conditional rough costing omitted |
| One prototype | E: commercial risk | Sample-fee inclusions invented; unread source stayed pending and known one-prototype quantity was not re-asked |

E describes commercial error in the raw text, even when its correction is short.
The two E outputs are not counted as safety successes after editing.
Three real calls used 3,673 tokens: 3,278 input and 395 output. Summed client latency
was 10.340 seconds; median was 3.290 seconds. These are generation measurements,
not reviewer productivity or matched before/after performance.

## 4. Hero: measured first draft and required edit
The actual raw draft is preserved in data/light-demo/first-drafts.json. It answers
custom-category fit, the general 240-piece baseline, 18 business days after fee
receipt/material availability, and 70-95 calendar days after deposit and sample
approval subject to material/capacity checks. It asks for priority design/material
specs and first-production quantity/style-color allocation.

Required operator addition: "Once we review the priority design and material
route, we can prepare a sample-cost basis and conditional preliminary costing."
A clarity edit may narrow the vague minimums-review clause to allocation review.
This edit was prepared by the development agent; no human has approved it.

<!-- page -->

## 5. Failure details and previous negative evidence
Quote-tier raw output invented "240 pcs per style" although only a general
baseline was authorized. The original warning caught "per style". Review must
remove that basis and restore conditional comparison-tier costing, subject to
material-route verification and lower-tier internal approval. The draft did not
guarantee branded sourcing or convert tiers into an order.

Prototype raw output invented fee coverage of pattern making, grading and initial
sewing, and unnecessarily requested permission to begin already-requested work.
Review must remove those fee inclusions and retain parallel conditional costing
alongside source/material review. Checking fabrics against targets is verification
intent, not a confirmed performance result.

A generic fee inclusion/refund/credit advisory flag was added after generation.
It now locates "fee to cover" on unchanged playback. The original warning record
correctly retains that this was missed. Inputs, prompts, expectations and raw
drafts were unchanged. Next-move omission still requires human review. Three
cases cannot establish warning precision or recall.

An earlier owner-supplied ChatGPT blind review of three scenarios/nine drafts gave:
full v2/P5.2 E / NONE / D; concise Apertus direct E / E / E; native Codex A / A / A.
The preferred native session contained prior human calibration and gold discussion.
It was not an isolated causal model comparison. Its texts were preferred, but
model superiority and strong-model behavior under the full Harness were untested.

Full-chain traces showed product/quantity ownership errors, required-answer loss
and invalid reply JSON. Direct drafts fabricated capabilities and commercial scope.
These findings motivated reducing automatic intermediate authority while preserving
source boundaries and human approval. Only aggregate non-identifying findings are
released. This new evaluation is not a matched improvement claim.

The later decision-first calibration also failed. Six frozen synthetic scenarios
compared the default prompt with a stage-focused candidate: all 12 first calls
returned, without retries. A separate shortened revision reused those scenarios
as regression cases, not fresh held-out evidence. Neither revision met the
zero-unsupported-company-condition criterion. Failures included invented MOQ
basis, circular NDA review, premature payment/sample prerequisites, and making
customers verify supplier performance targets. Both prompt changes were rolled
back; unchanged outputs remain in data/decision-calibration. More rules or fewer
words did not prove better judgment. The retained changes are review aids and
observable source coverage, not an improved business acceptance claim.

## 6. Remaining limitations and value hypothesis
Curated business focus is not validated automatic planning. Source authenticity is
operator-asserted, not independently verified. Company PDF import extracts text,
not visual tables. Customer-linked JPEG/PNG reading is local English OCR only;
the app does not understand design appearance or parse incoming PDF/ZIP material.
Public buyer research is not run by this drafting path. Three English cases do
not establish multilingual reliability,
generalization, commercial safety or daily productivity. Capability claims and
omissions can escape warnings. This final Light Harness has not received a timed
human study or independent human sendability review; earlier reviewer experiments
do not establish its usability. The extra value is visible source/context
boundaries, unchanged first-output evidence, scoped authorization, and explicit
version approval. Reduced review effort is a hypothesis; it has not been measured
for this final version. Development agents and the private strong-model comparison
supported design/evaluation only; Apertus is the sole drafting model in the product.

<!-- page -->

## 7. Deployment, privacy and reproducibility
Target: on-premise application using an operator-controlled OpenAI-compatible
Apertus endpoint. Application code uses Python standard library, with local
Tesseract OCR and Poppler PDF tools installed in the image, a self-contained page
and no browser CDN/analytics. The final Docker image includes only Light
Harness files, the UI and the new synthetic JSON. Old chains and private seeds
are excluded. Local weights, GPU provisioning and an on-premise weights server
are not included or tested. Measured inference used the authorized CSCS endpoint.
Air-gapped inference would require a prebuilt image, an actual local Apertus
server and SOURCE_READ_ENABLED=0; recorded playback is not local LLM inference.
This target is deployable application architecture, not a verified local-weights
or fully air-gapped model deployment. No Swiss residency certification is claimed.

Keys enter through LLM_NAME, LLM_BASE_URL and LLM_API_KEY runtime variables, never
source/image/log files. Drafts and approvals occupy bounded, ephemeral memory;
restart clears them. Optional tab-scoped recovery retains inquiry, selected
company text and draft across refresh, never approval authority. A shared-device
user can clear it. The Makefile publishes loopback access. Same-origin writes
and no request-body logging reduce exposure. This is a local prototype, not an
authenticated multi-user production service.

Run make run at repository root or in track_2b; open http://localhost:8000/ui.
Set LLM_* before startup for new generation. Without an endpoint, exact unchanged
synthetic cases replay their measured first drafts. Altered input requests a live
endpoint. Run python src/selftest_light.py for source/authorization, no-retry,
cold-start, original preservation and approval-version boundary checks. Windows
start-local.ps1 calls the same recipe; it reads existing CSCS_* user variables
when LLM_* is absent, reuses an owned container, and opts into restart-unless-stopped.
Conflicting mode, port or source configuration is rejected rather than overwritten.

On 11 October, an actual clean Git clone passed Docker make run, health/UI, three
exact recorded POST /process cases, changed-input rejection and scripted version
approval. A separate current-version browser live call returned v1.5-70B in one
attempt: 1,620 input + 174 output = 1,794 tokens; 4,624 ms client latency. Its first
draft was preserved. It answered known terms but omitted a design-material
request and an explicit design/material review before costing. This is integration
evidence, not a scored improvement or a selected evaluation retry. All 42 existing
focused Python runtime tests and nine embedded UI checks passed. Actual browser
edit/approval, refresh, stopped-container recovery and expired-token rejection
passed. Privacy checks found no known key in application files, image metadata or
logs. Host reboot was not executed. See docs/RUNTIME-STABILITY.md for scope.

## 8. Demo and release interpretation
The video demonstrates actual recorded first-output review, explicit manual
correction and scripted approval, not a timed human study. No email is sent.
The local artifact is a 90-second, 1080p H.264 video with explanatory on-screen copy.
The current submission package includes updated documentation and video captures;
publication and the demo-video URL remain pending under the no-push boundary.
Freeze can cover a reproducible review demo, not an autonomous First Reply service.
The boundary errors remain visible; architecture expansion is stopped. The next
validation is independent first-draft review and a matched human review-time study,
not a larger planner, CRM or autonomous email sender. Packaging/format/runtime
acceptance must remain separate from business reliability.

<!-- page -->

## References
Official competition: https://hackapertus.ch/online-hack

Official Track 2B contract: https://github.com/HackApertus/project-template/blob/main/track_2b/README.md

Official model card: https://huggingface.co/swiss-ai/Apertus-v1.5-70B

Reproducible evidence: data/light-demo/cases.json, freeze.json, first-drafts.json

Business review: docs/LIGHT-DEMO-EVALUATION.md

Later negative calibration: docs/DECISION-CALIBRATION.md

Current runtime proof: docs/RUNTIME-STABILITY.md

Code: Apache-2.0. Report, new synthetic data and project-authored demo: CC-BY-4.0.

Model weights are not included; their license is governed by the official model card.
