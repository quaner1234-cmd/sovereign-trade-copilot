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
two-minute video and user-facing workflow remain to be completed. A complete
Swiss deployment has not been verified. Local Docker demo and real Apertus
end-to-end execution are verified; this does not verify a production deployment.

The imported source commit and per-file hashes are in `sync-provenance.json`.
Runtime code was imported from committed research code; raw responses, temporary
logs, local configuration and unrelated research scripts were excluded.
