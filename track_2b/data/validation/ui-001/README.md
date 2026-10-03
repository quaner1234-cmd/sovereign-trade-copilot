# Operator console, first increment

`ui-console.png` is a full-page capture of `GET /ui` taken in the operator's own
Chromium, after the real interactions below, against the local server with no
model endpoint configured (offline demo mode — the banner is intentional).

Verified in this browser session:

| step | result |
| --- | --- |
| load `GET /ui` | health badge `demo · v4 · (demo)`, offline-mode notice shown |
| click sample `inquiry_zh_mixed`, then `Analyze email` | classification, draft, `guard passed`, speech-act table, evidence store with spans `[20,26]` |
| click `Sample test`, then `Get recommendation` | `action: REWORK`, evidence locators with quotes and span offsets, `needs_human_approval: true` |

Also verified from a copy containing only what the Dockerfile copies
(`src/`, `data/`, `docs/judgment.schema.json`): `GET /ui` 200, `GET /samples` 200,
`GET /health` 200, `POST /process` returns a role-aware draft. `make run` and
`docker build` were NOT executed in this session (no Docker daemon available), so
the container path itself is unverified.
