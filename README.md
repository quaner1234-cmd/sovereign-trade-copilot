# Sovereign Trade Copilot

An evidence-first garment trade email prototype for Hack Apertus Track 2B.
The default v4 pipeline selects exact parser candidate IDs, keeps per-fact
source spans and business roles, and checks reply drafts for human review.
It does not send customer emails or make commercial commitments automatically.

The project root is `track_2b/`. It uses Python's standard library and the
Apertus model family through a configurable OpenAI-compatible endpoint.

```sh
cd track_2b
make run
```

Open `http://localhost:8000/ui`, load the synthetic hero and click **Analyze inquiry**.
Recommended Action, Evidence, Uncertainty and Human Approval lead the workspace;
model output and metadata are under Technical Details. See the [UI demo guide](track_2b/docs/UI-DEMO.md).

The service listens on port 8000: `GET /health`, `POST /process` with an `email`
string, `GET /ui` for the operator console (paste an email, see every value with
its source span, the draft and the guard verdict) and `GET /samples` for the
demonstration fixtures. `POST /judgment` returns source-backed advice for three
narrow workflows; see the [Judgment Contract](track_2b/docs/JUDGMENT-CONTRACT.md).
Set
`LLM_NAME`, `LLM_BASE_URL`, and `LLM_API_KEY` in the runtime
environment for real inference. With no endpoint it runs a deterministic
offline demonstration, which does not use Apertus or measure its quality.
Never place an actual API key in a tracked file.

See [current status and limitations](track_2b/docs/STATUS.md) for tests,
benchmark commands, synthetic data scope and remaining submission deliverables.
Local Docker execution is verified in offline and real CSCS Apertus modes.

## Official template contract

Template repository for [Hack Apertus](https://hackapertus.ch/) submissions.
Every project keeps almost the same layout, so organizers and judges find the
same things in the same place.

## Select your track

This repository holds one example project per track:

- `track_1a/`
- `track_1b/`
- `track_2a/`
- `track_2b/`

Keep the directory for the track you are competing in **exactly as it is** —
don't rename it or move its files — and delete the other track directories.
That directory is your project root. Keep the files and directories as shown
below.

## The structure

| Path | What it is |
| --- | --- |
| `README.md` | The challenge description and submission requirements for your track |
| `technical_report.md` | The deeper write-up: architecture, evaluation, limitations |
| `Makefile` | `make run` must spin up your project |
| `src/` | Your code |
| `data/` | Datasets — `track_1a`, `track_2a` and `track_2b` only; max. 100 MB |
| `findings/` | Issue files — `track_1a` only |
| `docs/` | Diagrams, notes, longer write-ups |

## Run it

Judges run `make run` from the root of the project, on a clean checkout:

```bash
make run
```

`make run` is expected to run the project using Docker, since that
is how the judges will run it.
- If you used other local open-weight models, include instructions for running the project in your technical report.
- Use the following environment variables:
```
LLM_NAME — name and version of the model
LLM_BASE_URL — endpoint base URL
LLM_API_KEY — your API key
```

## Getting started

1. Click **Use this template** to create your own repository.
2. Delete the other track directories. Don't rename or restructure yours.
3. Read its `README.md` and fill in `technical_report.md`.
4. Make `make run` work from the root of the project, on a clean checkout.

## License

All Hack Apertus projects are open-sourced. Please check our Terms & Conditions for specific licensing details (6. What you build is open source): https://hackapertus.ch/terms-and-conditions
