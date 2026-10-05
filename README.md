# Sovereign Trade Copilot

**AI prepares a traceable first reply for human approval.**

This Track 2B prototype uses a Light Harness: original inquiry, source-backed
company conditions, explicit source state and a short business focus go to
Apertus v1.5 70B in one drafting call. Small phrase-located warnings assist a
person who edits and explicitly approves the current draft. Nothing sends email,
executes a payment or starts production automatically.

## Run from a clean checkout

Docker and GNU Make are required. Both commands use the same final entrypoint:

```sh
make run
# alternatively: cd track_2b && make run
```

Open http://localhost:8000/ui. Without an endpoint, the app explicitly plays back
unchanged synthetic Apertus first drafts. It does not claim offline inference.
Changed inquiries need a real endpoint.

For live generation, export the official runtime variables before make run:

```sh
export LLM_NAME=swiss-ai/Apertus-v1.5-70B
export LLM_BASE_URL=https://your-authorized-endpoint/v1
# Set LLM_API_KEY through your shell's secure environment mechanism.
make run
```

The key is passed by environment name, never written into an image or file.
An on-premise OpenAI-compatible Apertus server may replace the hosted endpoint.
Use host.docker.internal when it runs on the Docker host. Model weights, GPU
provisioning and a local weights server are not included or verified.
The UI has no CDN, analytics or third-party browser requests.

PORT, IMAGE and CONTAINER can override defaults. make stop stops the named demo.
Only loopback port access is published by default.

## Demonstration

1. Load the synthetic hero and review/authorize its invented company conditions.
2. Prepare the first reply. Mode distinguishes live Apertus from recorded playback.
3. Review the business focus and authorized conditions under **Why this reply?**
4. Edit the draft. Technical details preserves the raw first draft.
5. Enter a reviewer name, acknowledge review and approve this version or copy it.
   Editing invalidates the UI's prior approval. No sending integration exists.

Two boundary examples deliberately retain first-draft failures: an invented
per-style MOQ basis and unsupported sample-fee inclusions. The hero also needs
an explicit next-move sentence. Warnings are incomplete review aids, not safety
certification. See [evaluation and exact required edits](track_2b/docs/LIGHT-DEMO-EVALUATION.md).

## API and checks

- GET /health: pipeline/model/mode; sending disabled.
- GET /samples: three synthetic input packets, excluding evaluation gold.
- POST /process: inquiry, optional source-backed company_context,
  context_authorized, source_state and a text business_brief.
- POST /approve: existing draft_id, current draft, actor, reviewed: true.
  Approval binds to that draft version and its input hash.

```sh
cd track_2b
python src/selftest_light.py
```

Drafts/approvals live only in bounded server memory. Restart clears them.
This is a local prototype, not an authenticated multi-user service.
Referenced unread material stays explicitly unread; the final UI does not parse
binary attachments. Paste a reviewed extract with its source where appropriate.

## Evidence and deliverables

- [Technical report](track_2b/technical_report.md)
- track_2b/SovereignTradeCopilot_Report.pdf (maximum six pages)
- track_2b/demo.mp4 (maximum two minutes; local artifact, URL publication pending)
- [Frozen synthetic inputs, prompts and first outputs](track_2b/data/light-demo/)
- [Original competition contract](track_2b/README.md)

Private mail, company seeds and studies are not public assets. The final image
copies only the Light Harness and new synthetic data. Older source/experiments
are historical and excluded from the final image. Frozen v4 remains reproducible
at v4-frozen-7276cd2.

A previous three-case blind review found no directly sendable full-chain draft;
direct Apertus also failed all three. A native strong-model baseline produced three
preferred drafts, but contained previous human calibration in its session. This
was not an isolated causal model comparison. These negative findings motivated a
smaller drafting boundary and human approval, not a claim of solved safety.

Code: repository LICENSE. New synthetic data and report: CC-BY-4.0.
