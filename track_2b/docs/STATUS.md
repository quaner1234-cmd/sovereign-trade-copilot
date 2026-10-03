# Development snapshot

The current default HTTP pipeline is v4: semantic classification, deterministic
candidate spans, model-selected candidate IDs, an evidence store, and guarded
reply drafting. It provides a draft for human review and has no email-sending
integration. V2 remains available through `PIPELINE_VERSION=v2` when running
the Python server directly.

Version names: HTTP `/health` and processing metadata report `v4`. The existing
`pipeline_v3.py` and `prompts/v3.json` filenames are retained for import/benchmark
compatibility; `PIPELINE_VERSION=v3` is an alias for the current v4 implementation.
No prompt content was changed during this task.

## 2026-10-03 matcher correction and backend re-freeze

Only `_value_in` changed at runtime, verified by an AST comparison against
`0ba31f2`. It now matches complete date/numeric tokens instead of flattened digit
substrings, preserves decimal shape and thousands formatting, and excludes
identifier digits. Normal money/percentage and month-name-to-Chinese-date matches
have regression coverage; bare one-digit values retain their conservative behavior.
The targeted date/identifier fallback regression now passes on its first,
role-aware candidate. Semantics, prompts, Judgment, case expectations and the
three drift detectors are unchanged. Min/max qualifier checking remains out of scope.

Seven matcher test groups and all four requested offline commands (`selftest`,
`selftest_v3`, `selftest_safety`, `acceptance`) pass. `selftest` is the legacy v2
fixture smoke, not v4 business-quality evidence. Offline replay of all nine
`v4-live-002` recorded model conversations reproduces the same final drafts,
final guard verdicts and call paths. There were zero new CSCS calls and no full benchmark.

All five current demo samples pass their final guard. Contrary to the prior
diagnosis, the two reduced-detail demos have **not** recovered: `inquiry_en` stays
`review_only` and `complaint_zh` stays `legacy`, both due to the separate
`restates_customer_asserted_value` guard. All five final drafts equal the pre-fix
baseline. Fixing those two independently would exceed the matcher-only scope.

Backend is re-frozen by the normalized source hashes and acceptance evidence in
`data/validation/matcher-fix-001/summary.json`; the commit adding this section
identifies the corrected source. Original live records are preserved.

## 2026-10-03 final semantic guard: three drift classes, and the backend freeze

The v4-live-001 source-to-draft review found three SYSTEMATIC classes of semantic
drift in the model's own drafts. `guard_drift` (stage 6b) now detects exactly those
three, and nothing else:

| class | drift | detected as |
| --- | --- | --- |
| A hedge fidelity | an exact value softened ("约 500 pcs" out of "500 pcs"), or a hedged value hardened back to a flat number | `hedge_invented` / `hedge_dropped` |
| B role framing | the business act changes: a price they asked us to confirm read as their target, a price from OUR invoice read as their proposal, a claimed prior agreement read as a target | `role_framing_conflict` / `role_framing_missing` |
| C identifier kind | a PO/PI number read as a product code, or a style number read as an order number | `identifier_kind_conflict` |

Each class is a rule about a VALUE, never about a sentence or an email: no product,
customer, price or document appears in the code, and attribution is resolved by
BINDING (a label attaches to the value it most immediately introduces), so
"贵司目标价格 USD 2.05" is caught while "贵司目标价格 USD 45，要求交期 Dec 20 前" is
allowed. Where a value cannot be located safely — a bare one-digit number — the
check stays silent rather than guessing. The same change made the deterministic
fallback render `单据号 PO-8821` / `款号 TS-770` instead of calling both a 款号;
without that the guard would have rejected its own compliant fallback.

Cases, expectations, prompts, `semantics.py` and the Judgment Layer are unchanged;
the run's `case_hash` equals v4-live-001's. No benchmark was run and no scenario
was added.

### v4-live-002: 9 cases x 1 run, real CSCS Apertus v1.5 70B

31 model calls, 34,543 tokens, 59.6 s cumulative pipeline time. Full records, the
frozen changed sources and portable hashes are in `data/validation/v4-live-002/`.

**RAW BUSINESS CORRECTNESS (what the MODEL wrote, guard verdict excluded)**

* frozen business rubric on the raw draft: **8/9** (only acc07 fails, on
  `draft_must_not_contain '已确认'`)
* raw drafts carrying at least one of the three drift classes: **6/9**
  (A in 5, B in 3, C in 2; acc08 carries all three)

The old rubric alone catches 1 of those 6, which is why the second number is the
one that matters: the model reliably reproduces the right NUMBER and the right
value's provenance, and still drifts on the business meaning around it.

**FINAL SYSTEM SAFETY (what SHIPS)**

* **9/9**: every shipped draft passes the full guard, and 0 of the 9 carry any of
  the three drift classes. Nothing was withheld.
* path taken: raw 3 (acc03/04/09), retry 3 (acc01/02/07), deterministic fallback 3
  (acc05/06/08)
* interception: **6 of 6** drifted raw drafts were stopped. acc05 and acc08 drifted
  again in the retry and were caught a second time, then dropped to the
  deterministic fallback.
* independent check: replaying the three detectors over the v4-live-001 drafts
  flags the same 6 cases the source-to-draft review marked FAIL and stays silent on
  the 3 it marked PASS.

### What the guard costs, and what is still open

Safety here is partly bought by refusing to say too much. The retry instruction
("remove every number, date, price and commitment not present in FACTS") makes the
model over-correct: acc02's shipped reply drops the customer's target price and
3,000 pcs entirely (frozen rubric 8/9 on the shipped text), and acc01 and acc07
ship correct but commercially empty text. Nothing unsafe reaches the customer, but
three of nine replies are weaker than a salesperson would write. A completeness
rule — every admitted value must appear or be explicitly deferred — is the obvious
next backend change and is NOT part of these three classes.

Two further findings are recorded rather than fixed, because they are outside the
three observed classes:

1. `_value_in` matches on digits alone, so "Dec 20" is "found" inside the clause
   "款号 TS-201" (`20` inside `201`). That pre-existing matcher can make
   `requested_date_stated_as_our_delivery` fire on the system's own compliant
   fallback and push it down the fallback ladder. The new detectors are immune —
   they match literal tokens. This matcher finding is resolved by the correction
   above; it does not resolve the separate demo attribution failures.
2. `_value_spans` treats `min`/`max` qualifiers as unchecked: only `approx` has a
   mechanical rendering rule. 至少/至多 framing is still prompt-only.

**Freeze.** On this evidence the backend is frozen: the three high-risk drift
classes are mechanically intercepted in every case where they occurred, and the
next work is the operator UI over the existing HTTP surface. A pass here is a
safety measurement on nine synthetic cases, not human business-owner approval and
not a claim about model accuracy.

## 2026-10-03 operator console (first UI increment, after the freeze)

`GET /ui` serves one self-contained page (`src/ui/index.html`, no CDN, no build
step, stdlib only) plus `GET /samples` for the synthetic fixtures. The console
shows what the pipeline actually did rather than a summary: classification, the
speech-act table (role / stance / status / qualifier), the evidence store with
every fact's source span, the draft with its guard verdict and the path that
produced it (`raw` / `retry` / `deterministic_fallback` / `withheld`), and the
Judgment Layer with evidence quotes and span offsets. The offline-demo banner is
deliberate: a demo run must never be mistaken for model quality.

Verified in the operator's browser: page load, sample picker -> `Analyze email`,
and `Sample test` -> `Get recommendation` (`REWORK`, `needs_human_approval:
true`). Capture and the interaction table are in `data/validation/ui-001/`. Also
verified from a directory containing only what the Dockerfile copies. `make run`
and `docker build` were not executed here (no Docker daemon in this session), so
the container path for `/ui` is unverified. No pipeline, guard, semantic or
Judgment code changed for the UI; `server.py` gained two read-only routes.

## 2026-10-03 validation and Judgment 1.0

The nine existing realistic acceptance cases were run once each against real
CSCS Apertus v1.5 70B: 28 model calls, 28,753 tokens, 50.813 seconds cumulative
pipeline time. The frozen assertion suite passed 9/9; case acc05 required one
guard-directed retry. No deterministic fallback was used in this run.

**This is not nine business successes.** Separate agent source-to-draft review
passed acc03/04/09 and failed acc01/02/05/06/07/08: invented approximate quantities,
SKU/PO type confusion, QUESTION or claimed prior COMMITMENT rewritten as TARGET,
and invoice price rewritten as a customer proposal. These are missing semantic
checks in the inherited suite/guard. Cases, expectations and prompts were not
changed to hide them; this is not human business-owner approval. Full stage records,
frozen changed source, and the separate review are under `data/validation/v4-live-001/`.

Final safety now checks role-aware, legacy and review-only fallback candidates with
the complete guard. If every candidate fails, the draft is withheld and validation
is false. Retry success replaces the earlier failed final status instead of merely
changing `via`. Offline fault injection covers these paths.

Judgment Contract 1.0 (`docs/JUDGMENT-CONTRACT.md`, `docs/judgment.schema.json`) is
implemented as `POST /judgment`. One resolver and declarative policy evaluator cover
inquiry, payment and a single sample-test metric. All outputs include exact source
locators and mandatory human approval. Missing approvals do not block preliminary
costing; customer payment claims do not prove receipt; date boundaries and numeric
limits are checked independently of wording. Operational state uses operator-provided
JSON fact cards; arbitrary payment/test prose is not automatically extracted. Source
party is attested by the caller, not authenticated by the prototype.

New tests: `python -B src/selftest_safety.py`, `python -B src/selftest_judgment.py`.
The judgment fixtures include three synthetic cases per scenario plus equivalent
wording/serialization checks and targeted authority, date and measurement boundaries.
`data/judgment/cases.sha256` hashes UTF-8 text with LF-normalized line endings.
Judgment passed 34 tests, fallback/retry safety passed 6, and actual HTTP checks
passed 3. These checks also passed inside the Linux Docker runtime. Customer-only
payment-date requests cannot establish or extend a company payment node.

Docker `make run` was exercised in a clean local clone of the base commit and a
clean export of the candidate Git index. Host HTTP checks passed in demo and real CSCS
70B modes, including three Judgment scenarios. The v4 live Docker request used a
guard-directed retry and independently returned a passing final status. Runtime
environment injection uses variable names only; index/image metadata/history checks
found no API key. See `data/validation/docker-v4/` for synthetic HTTP records and
source hashes. A later clean clone can verify the committed text against these hashes.

## v4 semantic layer (business fact model)

v3 proved a value was *evidenced*; it could not say what the customer was *doing*
with it. The v4 layer (`src/semantics.py`) types every validated fact along
three independent axes, downstream of evidence validation:

| axis | values | why |
| --- | --- | --- |
| `semantic_role` | FACT / REQUEST / TARGET / QUESTION / COMMITMENT / UNKNOWN | the speech act the value performs |
| `stance` | customer / customer_claimed_prior / company / unattributed | whose position it is. In an inbound mail the first person is the CUSTOMER, so "we agreed" is their stance, never ours |
| `status` | supported / unconfirmed / not_stated | whether it is settled fact |

Qualifiers (`approx` / `min` / `max`), delivery relations (`before` / `by` /
`after`) and an Incoterm's named place now travel with the value, so
"around 300 pcs", "before Dec 20" and "FOB Qingdao" survive as claims instead of
flattening into `300`, `Dec 20` and `FOB`. Merchandise named with a common noun
("ski jackets") is extracted too — the candidate set could previously only see
identifier shapes.

Consequences enforced mechanically in `guard_semantics`:

  * an inquiry is never written as "已收到贵司订单" unless a PO anchor and a live
    commitment both exist
  * a TARGET is only ever framed as the customer's target
  * a requested date is only ever framed as their requirement
  * commitment words are blocked inside any sentence holding an unsettled value

**Known limits.** `company_commitments` is expected to be EMPTY for inbound
email — that is the design, not a gap; a first-person commitment in a customer's
mail is theirs. Semantic roles are assigned deterministically and the model may
never upgrade one, so an unusual phrasing falls back to the less committal role
rather than being recognised correctly. REQUEST-role framing is enforced in the
prompt but only TARGET and requested-DEADLINE framing are hard-enforced, because
enforcing the rest over-blocked legitimate replies. The full 144-call benchmark
has not been re-run since the refactor.

With no `LLM_BASE_URL`, v4 runs a deterministic parser/evidence demonstration.
Its classification is a placeholder and no Apertus inference occurs. This mode
must not be used as evidence of model quality. Configure the official `LLM_*`
variables for real inference; API credentials belong in the runtime environment.

## Validation and scope

Run from `track_2b/`, using Python 3.12 or later:

```sh
python -B src/selftest.py
python -B src/selftest_v3.py
python -B src/acceptance.py
python -B src/server.py
```

`src/acceptance.py` is the inherited development acceptance suite: nine realistic
synthetic emails covering TARGET vs COMMITMENT, REQUEST vs CONFIRMED and
INQUIRY vs ORDER, plus guard tests and phrasings that appear in no case (the
anti-hardcode checks). It is deliberately separate from `data/bench/cases.json`
so the benchmark ground truth never has to move when the semantic model changes.

`src/snapshot_extraction.py` prints a deterministic extraction snapshot of all 48
benchmark cases, so a refactor can be diffed against a baseline without spending
model calls.

`GET /health` reports the mode and pipeline. `POST /process` accepts
`{"email": "a synthetic email"}` and returns classification, extraction,
draft, validation, per-field evidence and processing metadata.

Validated in the formal checkout on 2026-10-02: v3 offline self-tests passed,
including 132/132 reference-value parser reachability; the HTTP demo processed
all five sample fixtures; one synthetic HTTP request completed real CSCS
Apertus v1.5 70B inference; empty-email requests returned 400 in both modes.
The benchmark packaging smoke checked standalone imports, the two-case comma
filter and gitignored local output in demo mode. These are smoke/regression
checks, not a full model benchmark or business-owner acceptance.

The 48-case adversarial benchmark is synthetic (dataset v1.2, twelve categories
with four cases each). Its fictional names, company names, orders and figures
are fixtures, not actual customer/company records. Samples are demonstration
fixtures. No internal trade skill or private customer archive is included.

```sh
python -B src/bench_v3.py --runs 3 --tag evaluation
```

Configure the `LLM_*` variables before claiming a model benchmark. Generated
records stay in `experiments/records/bench-slice/<tag>/` within this project and
are gitignored. The legacy HF Space research harness is deliberately excluded;
the formal benchmark uses the configured OpenAI-compatible endpoint.

The benchmark's historical `raw_model` label is only a partial RAW view:
classification and draft precede the final reply guard, but extraction is the
validated store on both surfaces. Its G4/G5 cannot measure unvalidated selector
quality. The G1-G7 thresholds are project engineering targets, not competition
requirements. A successful schema/guard check does not prove business accuracy.

## Remaining deliverables

This is a development code snapshot, not a finished competition submission.
The technical report is still the official placeholder; the six-page PDF,
two-minute video and the operator UI beyond its first increment remain to be
completed. A complete Swiss deployment has not been verified. Local Docker demo
and real Apertus end-to-end execution are verified; this does not verify a
production deployment.

The imported source commit and per-file hashes are in `sync-provenance.json`.
Runtime code was imported from committed research code; raw responses, temporary
logs, local configuration and unrelated research scripts were excluded.
