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
The UI has no CDN, analytics or third-party browser requests. The server can read
customer-supplied JPEG/PNG links before drafting, using local OCR only. It does
not send images to a separate vision provider.

PORT, IMAGE and CONTAINER can override defaults. make stop stops the named demo.
Only loopback port access is published by default.

### Windows local startup

Reuse Docker Desktop, GNU Make and Git for Windows. `track_2b/start-local.ps1`
calls the same `make run` recipe, reading credentials through environment names
only. It maps the existing Windows `CSCS_BASE_URL` / `CSCS_INFERENCE_API_KEY`
variables when live `LLM_*` configuration is absent. No key is saved in a script,
file or image. Example, with an installed GNU Make executable:

```powershell
.\track_2b\start-local.ps1 -Mode Demo -MakePath C:\tools\make\bin\make.exe
.\track_2b\start-local.ps1 -Mode Live -Port 8012 -Container track2b-live -MakePath C:\tools\make\bin\make.exe
```

The launcher opts into Docker `restart=unless-stopped`; Docker Desktop's engine
must be running. It reuses an owned container without clearing drafts, changing
its endpoint/key or making a model call. Changed mode, port or source-host
configuration requires a different container name; it never silently replaces
an existing service. Code/image updates likewise require an explicit new
container. Docker engine restart resumes a container that was not explicitly
stopped. It does not preserve the Python server's in-memory approval records.

For an already deployed Fake-IP proxy, supply the exact approved source domains
using `-SourceFakeIpHosts`, or set the non-secret `SOURCE_FAKE_IP_HOSTS` environment
variable. Keep customer-specific host lists in private local launch configuration,
not in the repository. This uses the existing source-reader boundary and does not
permit arbitrary private/loopback targets. Source extraction remains OCR only.

To intentionally retire a named local service, first preserve needed drafts,
then `docker stop <name>` and `docker rm <name>`. The launcher never performs
these record-losing actions automatically. Default judge `make run` still uses a
disposable container; `RUN_OPTIONS` is an optional local lifecycle override.

See [current runtime verification](track_2b/docs/RUNTIME-STABILITY.md) for the
clean-checkout, Windows startup, real Apertus and browser recovery evidence,
including the limits of restart persistence and source-image reading.

## Demonstration

For a new inquiry in live mode, paste it and click **Prepare first reply** directly.
Company context is optional; confirmed company statements require explicit
authorization. Demo examples are optional and collapsed by default. Choosing one
automatically fills the inquiry and fictional conditions, with no extra load step.
Editing its inquiry clears the example's fictional context before a new request.
Empty input, confirmation and connection failures are shown beside the button;
generation shows a busy state and preserves the previous draft on failure.
Model failures distinguish HTTP rejection, timeout, connection failure and empty
or invalid responses. **Failed request details** exposes safe status/timing
metadata only; provider error bodies, credentials and request URLs are not shown.
Failures make no automatic retry. Clicking **Prepare first reply** again starts
a new manual attempt.

**Company context (optional)** accepts Markdown, TXT, text-based PDF, a specific
public HTTPS webpage, or plain-language company conditions. JSON is available
only under the advanced controls. Importing reads text locally without a model
call and displays the source, reading coverage and editable text preview. Retain
only relevant sections and state the product/market/project scope in ordinary
language. Preview edits are marked as operator edits; the original source hash
remains attached to the submitted context.

Imported files remain working references and websites remain public references
until the operator explicitly confirms the applicable text and scope for the
current inquiry. Confirmation does not create a persistent company profile.
The configured drafting endpoint receives the selected text when a reply is
prepared. Original uploads are not saved; temporary PDF files are deleted after
local extraction. Up to three sources are supported, 4 MiB per file and 60,000
characters per source. The existing 30-statement context limit still applies;
trim the preview to relevant sections if a combined packet is too large.

PDFs are limited to 30 pages. PDF text extraction does not verify images, diagrams
or visual table layout; image-only scans and protected PDFs produce explicit
errors. Web import reads one page only, including static HTML/text or a PDF URL;
it does not crawl, sign in or execute JavaScript. Unreachable/unsupported sources
leave existing context unchanged. Company sources are separate from customer
attachments and do not establish that customer material was read.

**Additional facts or corrections (optional)** accepts natural-language operational
context, such as which company materials are ready or where an existing customer
reference can be found. The agent chooses the present useful next move itself;
users do not need to write a reply strategy. This field does not authorize a new
company capability, price or commercial term. Use confirmed company conditions
for those facts. The drafting call returns two text fields: the customer email and
an optional operator-only contextual hint. There is no minimum word count.
Relevant ready company material may be proposed for this reply; prospective
attachment wording requires a pre-send reminder. Neither importing context nor
preparing a draft actually attaches a file or sends email.
Invalid output structure preserves the prior draft and records no new approval;
no retry, salvage or substitute draft occurs. Original recorded examples retain
their unchanged historical first drafts and curated business focus.

This decision-first contract remains experimental. In a frozen six-case synthetic
live trial, four first drafts returned and two requests failed to connect; returned
drafts still contained unsupported range wording, avoidable questions and internal
authorization language. A separate browser catalogue case produced a useful
selection-first draft, but does not establish general reliability. No failed case
was retried or replaced. Attachment reminders can repeat, and the application-side
attachment phrase check currently covers English only. Human business review is
still necessary; these checks do not certify a reply for sending.

1. Load the synthetic hero and review/authorize its invented company conditions.
2. Prepare the first reply. Mode distinguishes live Apertus from recorded playback.
3. Open **Why this reply? · Review card (optional)** only when needed. It shows
   actual source coverage, supplied company conditions and located review flags.
   Its next action is a reviewer action, not a validated business decision.
4. Edit the draft. Technical details preserves the raw first draft.
5. Enter a reviewer name, acknowledge review and approve this version or copy it.
   Editing invalidates the UI's prior approval. No sending integration exists.

Two boundary examples deliberately retain first-draft failures: an invented
per-style MOQ basis and unsupported sample-fee inclusions. The hero also needs
an explicit next-move sentence. Warnings are incomplete review aids, not safety
certification. See [evaluation and exact required edits](track_2b/docs/LIGHT-DEMO-EVALUATION.md).

A later same-context calibration also failed: neither adding stage-specific
decision principles nor a separate shortened revision reliably preserved MOQ
basis, NDA order and responsibility for performance verification. All synthetic
first outputs are preserved in [the calibration record](track_2b/docs/DECISION-CALIBRATION.md).
The attempted prompts were rolled back. Light Harness 1.3 retains advisory review
aids and shows actual link-reading coverage under **Why this reply?**, explicitly
including **public buyer search: not run**. It does not claim improved business
acceptance. A list-based question warning is heuristic and may miss grouped
requests or flag an answer list; it never rewrites or blocks the draft.

## API and checks

- GET /health: pipeline/model/mode; sending disabled.
- GET /samples: three synthetic input packets, excluding evaluation gold.
- POST /process: inquiry, optional source-backed company_context,
  context_authorized, source_state and a text business_brief.
- Optional operator_context is factual text; optional reply_materials declare
  name, source and available / planned_for_reply / not_ready state. These are
  operational facts, not company authorization or evidence of dispatch.
- POST /approve: existing draft_id, current draft, actor, reviewed: true.
  Approval binds to that draft version and its input hash.
- POST /context/import: one Markdown/TXT/PDF upload (base64 file bytes) or one
  HTTPS website URL. Returns local text/coverage/provenance only; no model call,
  company authorization, draft or approval is created by import.

```sh
cd track_2b
python src/selftest_light.py
```

Server draft records and approvals live in bounded memory. Restart clears them.
The UI optionally recovers inquiry, selected company text/scope and the latest
draft from tab-scoped `sessionStorage` across refresh. It does not store original
upload bytes, raw provider output or approval objects. Refresh requires re-review;
an expired server token cannot be approved. **Forget tab recovery** removes this
page's cache and keeps recovery off across refresh. On a shared computer, use it
before leaving: browser session restoration may retain a tab cache. This cache
is not a persistent Company Context or a trusted ledger.
See [browser and Docker verification](track_2b/docs/CONVERSATION-CARD-VERIFICATION.md).
This is a local prototype, not an authenticated multi-user service.
JPEG/PNG links in an inquiry are detected automatically. At most two are fetched,
with a 2 MiB limit per image, and readable English text is extracted by Tesseract.
Evidence includes content hash, access time and exact reading coverage. OCR means
**partially read**, not full visual understanding: appearance, material, size and
manufacturability remain unverified. PDF/ZIP/cloud-share pages and binary uploads
are not supported. Failed or unsupported references remain explicitly unread;
the written inquiry can still support a draft. Signed URLs are used for retrieval
but removed from the model input. Temporary images are deleted after OCR.

For disconnected deployments, set `SOURCE_READ_ENABLED=0`. Core drafting can
still use an on-premise Apertus endpoint; no source retrieval is attempted.
The Docker image now includes Tesseract and must be built online once before
air-gapped deployment. A deployed local Fake-IP proxy may need an explicit
`SOURCE_FAKE_IP_HOSTS` list of operator-approved hostnames. This permits only its
reserved Fake-IP range for those exact hosts; ordinary private/loopback addresses
remain forbidden. No system proxy or DNS configuration is changed.

Project-specific operator-confirmed capabilities and prices can be supplied in
company_context with their project scope. Reading a customer image never creates
company authorization, confirms an order quantity or supplies an outgoing photo.

## Evidence and deliverables

- [Technical report](track_2b/technical_report.md)
- [Clean-checkout and artifact verification](track_2b/docs/RELEASE-VERIFICATION.md)
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
