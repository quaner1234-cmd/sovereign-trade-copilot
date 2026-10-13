# Competition submission handoff

Prepared 13 October 2026. Track **2B - Own Project**. Local packaging is not
publication or submission. Do not submit the ZIP in place of the required URLs.

Publication check on 13 October: the repository is PUBLIC and was created from
`HackApertus/project-template` on 2 October. Its public `main` still points to
`7276cd2a4ff78e5a52876025f237a0a8ae47f9fd` (the old v4 implementation). It does
not yet contain this local Light Harness submission. Push the final package
commit and verify the public branch before submitting that repository URL.

## Required fields and files

| Official form field | Prepared value / remaining action |
|---|---|
| Project name | Sovereign Trade Copilot |
| Team name | Sovereign Trade Copilot, unless the registered team name differs |
| Model | Apertus v1.5 70B; exact runtime ID `swiss-ai/Apertus-v1.5-70B` |
| GitHub repository URL | https://github.com/quaner1234-cmd/sovereign-trade-copilot |
| Technical report upload | `SovereignTradeCopilot_Report.pdf`, five pages including references |
| Demo video URL | Publish `demo.mp4` to a judge-accessible URL after review; local MP4 alone does not satisfy this field |
| Hugging Face dataset URL | Optional; leave empty. Synthetic test data are in the repository; no separate dataset release is prepared |
| First/last name, signup email, members, student-team status | Enter actual registration information privately; it is not included in the public package |
| GitHub username | `quaner1234-cmd`, if this is the submitter's registered account |
| Terms and Conditions | Read and accept personally before submitting |

If the registered team name differs, rename the report to `<TeamName>_Report.pdf`
and align the report's team heading before upload. Do not invent registration
details or claim a Swiss student status from the model/deployment location.

Submission is through https://hackapertus.ch/online-hack/submissions, not Devpost.
Deadline: **16 October 2026, 12:00 CEST / 18:00 Asia/Shanghai**, no extensions.
One submission per project. Current form fields and deadline were read directly
on 13 October. The Track 2B template is authoritative:
https://github.com/HackApertus/project-template/blob/main/track_2b/README.md.

## Suggested optional participant message

Sovereign Trade Copilot prepares a traceable first reply for human approval using
Apertus v1.5 70B. A compact brief preserves selected company statements, scope
and source state. One model draft is followed by advisory warnings and explicit
human review; nothing is sent automatically. The video shows the current UI
using synthetic recorded first outputs, a visible edit and scripted approval.
Live CSCS inference was separately verified. Known commercial errors and failed
calibration are preserved in the report. Recorded playback is not offline model
inference, and local model-weight deployment is not included.

## Reviewer run path

Docker's Linux engine and GNU Make are required. Both root `make run` and
`cd track_2b; make run` use the same Docker entrypoint. Open `/ui` on localhost
port 8000. Set `LLM_NAME`, `LLM_BASE_URL`, `LLM_API_KEY` in the shell environment
for new Apertus generation. The key must not be written into a file or image.

Without an endpoint, select an optional example, confirm its fictional company
conditions, and prepare the exact original recorded first draft. Editing the
input requires a live endpoint; the app never invents an offline substitute.
Try the hero, edit its missing next-move sentence, acknowledge review and approve
that version. The two boundary cases deliberately retain commercial errors.

The Docker image copies only the Light Harness and synthetic assets. Older v4/v2
code and evaluation are historical repository evidence, not the default runtime.
Source-reading coverage is partial; public buyer search is not run. Warnings
cannot certify safety. A fully local Apertus weights server is still unverified.

## Publication sequence

1. Review the PDF, video, negative findings and team identity.
2. Publish the final verified commit to the existing public repository only when
   authorized. Confirm the public branch contains that commit and required files.
3. Publish the 90-second MP4 at a stable URL and check it while signed out.
4. Fill the official form with the repository URL, video URL and report PDF.
5. Personally accept the terms, submit once, and retain the confirmation.

The current task prepares local artifacts only. No push, video upload, contact
message, Terms acceptance or competition submission is performed by this guide.

## Rebuild the local package

Rebuild the PDF with `python scripts/build_report.py` in an environment with
ReportLab. Rebuild the video from `track_2b/docs/demo-video-source/` with its pinned
HyperFrames scripts and FFmpeg. After committing verified changes locally:

```sh
python scripts/build_submission.py --output /path/to/local-delivery --ffprobe ffprobe
```

The packager requires `pypdf`, a clean Git checkout and FFprobe. It exports only
committed files, checks PDF/video limits and ZIP integrity, and writes a manifest
and SHA-256 hashes. It does not connect to GitHub, upload data, read API keys or
change the application. The archive is a local handoff/backup; the judges need
the actual public URLs.
