# Current runtime verification — 11 October 2026

Status: PASS for the tested clean-checkout Docker and Windows startup paths.
This verifies operation and recovery boundaries, not general business accuracy,
human sendability, endpoint uptime or a completed competition submission.

Runtime source: local main `1ab4cb3`, following startup/verifier commit `965e4cd`.
The Windows entrypoint was corrected after a real first attempt selected cmd
instead of Git Bash for Make's shell readiness loop. Neither prompts, business
rules, advisory checks, recorded drafts nor UI source changed in this work.

## Reproduction

Start Docker Desktop's Linux engine. From a clean Git clone:

```sh
cd track_2b
make run
```

The Windows launcher calls that same recipe. Supply an existing GNU Make path:

```powershell
.\track_2b\start-local.ps1 -Mode Demo -MakePath C:\tools\make\bin\make.exe
.\track_2b\start-local.ps1 -Mode Live -Port 8012 -Container track2b-live -MakePath C:\tools\make\bin\make.exe
```

Live mode reads existing `LLM_*`, or maps Windows `CSCS_BASE_URL` and
`CSCS_INFERENCE_API_KEY`. Credentials are passed by environment name, never
written into a file or image. Customer-specific source host configuration belongs
in a private local command; exact-host Fake-IP support remains opt-in.

## Observed results

| Path | Result and actual evidence |
|---|---|
| Actual Git clean checkout, Docker build, `cd track_2b; make run` | PASS, isolated demo container and loopback port |
| `/health`, `/ui`, `/process` in demo mode | PASS, version `light-harness-1.3`, sending disabled |
| Three unchanged synthetic examples | Exact historical first-draft playback, zero model calls; their earlier business grades remain unchanged |
| Unauthorized company conditions | Explicit confirmation required before inference |
| Changed offline inquiry | Explicit endpoint-required failure, prior draft retained; no substitute |
| Windows PowerShell 5.1 new live startup | PASS from clean checkout through the same Make recipe |
| Repeated live startup | Same container ID/start time; retained configuration; no model call |
| Wrong mode/port/source configuration or unmanaged name | Rejected; original service retained |
| Stopped owned live container | Same container recovered by launcher; live health restored |
| Real browser live generation | One CSCS Apertus v1.5 70B first draft, one transport attempt, finish reason `stop` |
| Returned usage and client latency | 1,620 prompt + 174 completion = 1,794 tokens; 4,624 ms |
| Edit, acknowledge, explicit approval | PASS in demo and live browsers; scripted actor, nothing sent |
| Browser refresh | Text restored; reviewer acknowledgement and approval reset |
| Controlled server restart | Old draft record rejected for approval; text kept, manual preparation required |
| Actual approved source-image retrieval | Downloaded; partial local text extraction only, visual understanding unverified |
| Container runtime regression | Existing 42 focused Python tests passed with network disabled |
| Embedded UI recovery contract | Existing 9 Node checks passed |
| Source identity | All seven application/runtime asset hashes match the clean source checkout |
| Known-key/privacy boundary | Known credential absent from application files, image configuration/history and logs; application inventory contains only current runtime and synthetic demo assets |

The live first draft and complete safe API metadata were preserved before any
edit. Scripted editing added only a neutral synthetic signature. No retry or
replacement output was selected. Provider request ID and confirmed quota change
were not returned by this application; token usage is not a quota deduction.

The live draft answered the authorized category, general MOQ, sample timing and
production timing, and asked two relevant questions. It omitted the requested
invitation to share design material and did not explicitly state design/material
review before costing. Those are business-review limitations, not repaired or
scored as a new acceptance experiment here.

## Boundaries and remaining work

- `restart=unless-stopped` was inspected; stopped-container recovery was executed.
  A full host reboot or Docker-engine restart was not executed. Docker Desktop
  must itself be running; this work did not install a system auto-start task.
- Python draft/approval records are in memory. Server restart expires them.
  Browser tab recovery preserves text, not approval authority or a company profile.
- Reuse retains the container's existing image, endpoint and credentials.
  Upgrades require an explicit new container; no automatic destructive replacement.
- The default judge Make recipe remains disposable. Local restart persistence is
  an explicit lifecycle option, not permanent server record storage.
- Image reading is JPEG/PNG plus local English OCR, not full visual understanding.
  An exact approved domain handles the existing Fake-IP deployment route only;
  it does not permit arbitrary private or loopback destinations.
- Network or model failures still receive explicit feedback without automatic
  retry or substitute generation. A successful call does not guarantee later
  availability or draft correctness.
- Privacy checks cover the known key and inspected markers/inventory. They do not
  certify arbitrary secrets. Runtime credentials still exist in the container's
  protected environment, accessible to a Docker administrator.
- Historical negative business results remain valid. This work did not rerun the
  full benchmark, change evaluation expectations, or regenerate report/video.
- Verification and commits are local only. No push or publication was performed.
