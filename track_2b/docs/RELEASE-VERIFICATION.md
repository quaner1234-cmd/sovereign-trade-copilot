# Final demo verification

Status: PASS for the reproducible review-demo runtime and local artifacts.
Business reliability remains bounded by the B / E / E raw results. This is not a
human usability PASS, a commercial-safety certificate or a published submission.

## Clean checkout

An actual local Git clone of runtime commit `ceb7b6c` was used, not a copied working
directory. Docker Engine 29.8.1, GNU Make and Linux containers were available.
The final entrypoint was tested with both `cd track_2b && make run` and repository
root `make run`; both started the same Light Harness service.

| Check | Result |
|---|---|
| Docker build + make run readiness | PASS |
| GET /health + GET /ui | PASS in recorded and live modes |
| POST /process, 3 unchanged synthetic recorded cases | PASS: exact original raw text, 0 new calls |
| Changed input without endpoint | PASS: endpoint_required, no substitute generation |
| Unauthorized company-context input | PASS: confirmation_required before inference |
| Scripted edit/approval version binding | PASS; no sending; not human quality evidence |
| Docker-contained live CSCS Apertus generation | PASS: 1 transport attempt, returned v1.5-70B, finish_reason stop |
| Live integration usage/latency | 1,093 input + 152 output = 1,245 tokens; 5,208 ms |
| Runtime boundary selftests from clone | PASS: 6 grouped checks |

The separate live call proves container end-to-end connectivity only. It is not a
retry selected for the three-case evaluation and does not replace its first drafts.

## Browser, privacy and artifacts

Actual Chrome interactions were verified in an owned test window: load example,
authorize synthetic context, prepare, edit, acknowledge review, approve, then
change case and observe approval invalidation. Reviewer actor was explicitly
scripted. Boundary warnings/hint and preservation of the raw draft were checked.

The Docker application inventory contained only the Light Harness, client,
guidance, UI and three synthetic JSON files. Known CSCS secret was absent from
application files, image configuration/history and container logs. Runtime credentials are environment-only;
no request body logging, sending connector or private seed is copied into the image.
The index scan checks known credentials, token patterns, machine paths, private
company markers and temporary logs; pattern scanning cannot certify arbitrary data.
Binary assets receive a raw known-secret scan plus extracted PDF text, metadata
and visual review; drive-path regexes are not applied to compressed pixel/video
bytes. Synthetic source provenance was reviewed separately.

Inputs and prompts still match the pre-call freeze. Raw drafts are unchanged.
The only post-generation advisory addition is documented fee-scope phrase review.

README and technical report are complete. The PDF was rendered and visually
reviewed, including page count and clipping. The video is silent with readable
explanatory copy: H.264, 1920 x 1080, 24 fps, 90 seconds, 6,252,717 bytes. Early,
draft, approval and boundary frames were decoded from the final MP4 and inspected.
It uses actual synthetic UI screenshots and discloses recorded playback/scripted
approval. Its source is pinned to HyperFrames 0.8.133.

Publication, public video URL and competition submission are pending. This round
is local only; no push or upload was performed.

## 6 October 2026: Prepare-button follow-up

The original UI required a separate Load action after choosing an example, and
empty inquiries reached a generic HTTP 400 response. An owned Chrome window
reproduced that path. The running local app was also in recorded-replay mode.

The example picker is now optional/collapsed and selection autofills. Empty input
and unconfirmed company context receive specific visible feedback before a model
request. Progress is visible; connection errors are explicit; the request has a
bounded timeout with no automatic retry. Switching from an example to a newly
typed inquiry clears its fictional company terms and invalidates approval.

Browser checks passed: empty-input feedback; select/autofill; authorization
prompt; exact offline hero replay; changed input in offline mode gives an explicit
endpoint-required message and keeps the previous draft. The actual outgoing
request after replacing an example carried an empty company_context.

After configuring the existing CSCS credentials through runtime environment only,
the direct-paste path with no sample selection and no Company Context returned a
real Apertus v1.5-70B draft: one call/attempt, 647 input + 219 output tokens,
5,295 ms client latency. The browser displayed the draft and restored the button.
This is UI/integration evidence, not a new scored business case or a replacement
for the frozen three first drafts. No prompt, guard, judgment or frozen output
was changed. The earlier video records the UI before this interaction fix.

A task-local browser rule blocked one additional request to test connection
failure. The UI showed a specific error, restored the button and preserved the
previous live draft. This was a controlled failure simulation, not an actual API
outage or another model call. The 75-second timeout is implemented but was not
tested by waiting for the full timeout interval.

In-app-browser automation could not be inspected because the Codex tool's Windows
sandbox helper failed; that does not establish an application/browser failure.
Browser execution evidence above comes from Chrome. The local service is left in
live mode for review; a fresh page shows Live Apertus.
