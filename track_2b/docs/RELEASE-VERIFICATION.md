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
