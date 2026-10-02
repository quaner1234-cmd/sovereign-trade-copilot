# Development snapshot

The current default HTTP pipeline is v3: semantic classification, deterministic
candidate spans, model-selected candidate IDs, an evidence store, and guarded
reply drafting. It provides a draft for human review and has no email-sending
integration. V2 remains available through `PIPELINE_VERSION=v2` when running
the Python server directly.

With no `LLM_BASE_URL`, v3 runs a deterministic parser/evidence demonstration.
Its classification is a placeholder and no Apertus inference occurs. This mode
must not be used as evidence of model quality. Configure the official `LLM_*`
variables for real inference; API credentials belong in the runtime environment.

## Validation and scope

Run from `track_2b/`, using Python 3.12 or later:

```sh
python -B src/selftest.py
python -B src/selftest_v3.py
python -B src/server.py
```

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
Swiss deployment has not been verified. Docker execution also needs independent
verification when a Docker host is available; Python smoke checks do not prove
`make run` works inside a container.

The imported source commit and per-file hashes are in `sync-provenance.json`.
Runtime code was imported from committed research code; raw responses, temporary
logs, local configuration and unrelated research scripts were excluded.
