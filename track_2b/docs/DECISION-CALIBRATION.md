# Decision-first calibration: negative result, 2026-10-08

The requested business improvement has **not passed acceptance**. The default
drafting prompt remains the one from `58014e6`. Version 1.3 adds review aids and
observable reading coverage, not a claim of better business judgment.

## Method

Six wholly invented cross-product cases and their evaluation expectations were
frozen before editing the candidate. The control was `58014e6`; the first
candidate added stage contrasts and current-action question filtering to the
Skill. Inputs and authorized company conditions were identical, business_brief
was empty, and evaluation gold never went to Apertus. Control/candidate order
alternated. Each route received one live Apertus v1.5 70B call per case, with one
transport attempt. All 12 returned; none was retried or replaced.

After the first candidate failed, one explicitly separate second revision
shortened repeated policy and simplified the drafting context. The same six cases
were then regression cases, **not fresh held-out evidence**. All six second
outputs are retained separately. Two older synthetic failures were also replayed
once per candidate, privately; they did not pass either revision. No further
prompt optimization followed. No customer records or private company seed were
used. This is developer semantic review, not measured human sendability, a blind
review or a strong-model capability comparison.

## Business findings

| Case | Control | First candidate | Separate shortened revision |
| --- | --- | --- | --- |
| S01 ready selection material | Correct selection-first sequence | Wrongly offers company fabric-weight options before customer specifications | Restores sequence; repeats attachments and uses signature placeholders |
| S02 NDA/design package | Unnecessary permission and commercial checklist; NDA-first step unclear | Asks for a signed NDA before review | Still makes review circular with confidentiality already agreed; asks permission again |
| S03 construction/target/MOQ | Invents style/colour MOQ basis | Same unauthorized basis | Still invents per-style basis; operator hint falsely attributes it to the company source |
| S04 specialist-use concept | Asks exposure/context details; does not establish whether protection is required | Misses the protection decision and asks comfort/fabric inputs | More relevant exposure questions, but still lacks explicit protection clarification and adds excessive/internal wording |
| S05 complete costing inputs | Moves sample prerequisite to initial costing | Moves deposit/sample prerequisites to firm quote | Starts quotation without that blocker, but still asks permission and unnecessary sample preferences |
| S06 existing unread PDF/one prototype | Adds permission and internal authorization language | Adds more customer requirements before source review | Treats a performance target as a customer claim requiring customer test reports; wrong responsibility and prerequisite |

Both attempted revisions fail the zero-unsupported-company-condition criterion.
The shortened revision's MOQ hint demonstrates that an operator hint is not source
truth. It must never authorize or amend a company statement. Longer rules did not
produce better decisions; shortening alone did not resolve ownership or action
selection. Neither result supports claiming the business problem fixed.

Raw first outputs, immutable input hash, prompts, model identity, latency and token
usage are in `data/decision-calibration/`. The second results have a separate
filename and route. Evaluation expectations and first outputs were not edited.

## Changes actually retained

- Preserve original company wording, scope, unit, conditions and provenance in
  the model packet. Tests check this boundary. The six default prompt packets
  are exactly equal to the frozen control packets after rollback.
- Show actual source coverage under **Why this reply?**: tracked links, retrieval
  attempts, successful downloads and local text OCR. A failed fetch is now
  `attempted`, not `not_attempted`; unread stays unread. Public buyer search is
  explicitly **not run**. No search integration or identity transfer was added.
- Locate operator/internal labels in customer text. Locate a fourth listed item
  alongside a request for details, even without question marks. Both are advisory
  and leave the raw draft unchanged; no automatic repair, retry or certification.

The list warning is an English heuristic: answer lists near a request can cause
false positives, and grouped/inline/multilingual requests can evade it. It cannot
decide whether a question is necessary. Existing checks still miss quotation
prerequisite errors, some unsupported claims and supplier/customer ownership drift.
Coverage counters describe only up to eight tracked links and do not prove all
referenced material was read. Hints may repeat and must also be reviewed.

## Release decision

Do not promote either attempted prompt. Keep human review and narrow the demo to
explicitly confirmed business boundaries. This work does not establish an
autonomous trade colleague, solved first-reply judgment, general sendability or
readiness to freeze the competition release. No public push is authorized in this
phase. Original competition report/video and recorded examples remain historical;
they were not regenerated to hide these failures.

Verification: all 42 focused Light Harness, source, import and LLM-client tests
passed with the local HTTP/temp-file access required by the test stack. Docker
`make run`, unchanged recorded-hero playback, the expanded reading explanation
and disabled approval before review were verified in a real browser. An additional
live HTTP smoke on the deployed default returned a draft in one Apertus call;
that repeated control input is excluded from evaluation. The trial runs version
1.3; the older main service was left unchanged. No email was sent or approved in
the browser verification. Console evidence contained an extension resource error
and a missing favicon, with no drafting-interaction error observed.
