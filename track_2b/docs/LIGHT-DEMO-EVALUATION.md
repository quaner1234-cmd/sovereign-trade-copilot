# Light Harness: first-output evaluation

## Method and limits

Inputs, expected business behavior and prompts were frozen before calls.
Three original synthetic cases with invented company conditions each received one
real CSCS `swiss-ai/Apertus-v1.5-70B` call at temperature 0.1. No generation retries
or best-of selection occurred. `data/light-demo/first-drafts.json` is unchanged.
The lead development agent performed semantic review, not an independent blind
human reviewer. Business focus was curated. Automated HTTP/browser approval tests
are not evidence of human sendability, review speed or daily willingness to use.

Grade A: directly sendable; B: minor edit; C: renderer semantic error; D: upstream
error; E: unacceptable commercial risk in the raw text. Grade describes the raw
draft, not the ease of correcting it once identified.

## Results

| Case | Raw grade | Answers and next move | Commercial boundary |
|---|---|---|---|
| Hero | B | Known terms answered with conditions; two useful requests; explicit assessment-to-costing next move omitted | No detected unauthorized MOQ basis, performance or firm-price claim |
| Quote tiers | E | Category/terms answered; useful priority/design/original-vs-equivalent questions; parallel conditional costing omitted | Invented `240 pcs per style`; no detected order conversion or branded-access guarantee |
| One prototype | E | Normal timing and shipping answered; existing unread file to be reviewed; sample quantity not re-asked; unnecessary permission question | Invented fee coverage of pattern making, grading and initial sewing |

Total: 3 calls, 3,673 tokens (3,278 input; 395 output), 10.340 seconds summed client
call latency; median 3.290 seconds. These are generation measurements, not reviewer
productivity measurements or a matched comparison to earlier cases.

## Exact edits needed

These are proposed operator edits prepared by the development agent. No human has
approved them. They never replace the raw record.

**Hero:** append the approved next move:

> Once we review the priority design and material route, we can prepare a sample-cost basis and conditional preliminary costing.

Optional clarity edit: replace “allocation and minimums are reviewed per project”
with “we would review the style/color allocation for your project.”

**Quote tiers:** remove `per style`. Add:

> In parallel, we can assess preliminary costs at your 120/360/720-piece comparison tiers, subject to the material-route check and internal review of the lower tier.

**One prototype:** replace the fee-inclusions sentence with:

> For this one prototype, we can prepare a preliminary cost estimate in parallel with the material checks; the price and firm timeline can be confirmed once the route and availability are reviewed.

Replace the unnecessary request for permission to proceed with:

> We will review the existing shape notes and material options first. If you have an initial production estimate for after prototype approval, please share it; we can continue assessing this one prototype in the meantime.

“Check available fabrics that can meet ... targets with our suppliers” is verification
intent, not a confirmed result. A clarity edit could say “check current fabric options
and test information against your targets.”

## Warning coverage and post-generation change

At generation time `per style` was flagged, while the fee-inclusions error was missed.
A generic phrase-located `fee_scope_review` was added afterwards for fee inclusion,
refund and credit phrases. It catches `fee to cover` on recorded playback. Inputs,
prompts, gold and raw drafts were unchanged. Generation-time source hashes remain
in the freeze; final warning code differs by this advisory addition.

No quantitative precision/recall claim follows from these cases. No warning does
not mean no risk. Next-move omission still requires human review.

## Prior counterevidence

An earlier three-case / nine-draft blind review supplied by the project owner gave:
full v2/P5.2 E / NONE / D; concise Apertus direct E / E / E; native Codex A / A / A.
The Codex session contained historical human-gold context, so this cannot prove a
clean model superiority or isolate Harness effects. Full-chain records showed
ownership errors, required-answer loss and invalid renderer JSON; direct drafts
fabricated capabilities. Private source packets and drafts are not redistributed.

## Release interpretation

Hero meets the development-agent minor-edit threshold. Boundary drafts remain
commercially incorrect: they demonstrate review needs, not auto-safe success.
A corrected demo is possible with explicit manual edits. Human assessment and
time savings remain unverified. Freeze can cover the reproducible demo, not a
general autonomous First Reply service.
