# Inquiry card validation — 2026-10-09

**PASS for the frozen synthetic interaction acceptance.** This is not a model,
business-quality or Generative UI SDK integration result.

## Actual implementation

| File | Responsibility |
|---|---|
| `index.html` | Native HTML/CSS, one inquiry card and review controls |
| `model.mjs` | Three invented fixtures, card view, finite actions, state/version validation |
| `app.mjs` | DOM rendering, localStorage, errors, dirty text and cross-tab handling |
| `serve.py` | Python stdlib, loopback static resource allowlist and health |
| `test.mjs` | Node built-in assertions, state/persistence failure tests |
| `README.md` | Frozen acceptance, run commands, scope and official references |
| `VALIDATION.md` | Observed execution and remaining gaps |

No dependencies were installed. No React, ChatKit SDK or assistant-ui was added.
No production/runtime source file, prompt or business rule was modified.

## Runtime evidence

Started `python serve.py --port 8003` as a hidden local process.
- `GET http://127.0.0.1:8003/health`: 200, `synthetic_card`, model calls 0,
  `sending_enabled: false`.
- HTML and both JavaScript modules: 200 with correct content types.
- Arbitrary README file request: 404. `POST /process`: 501, unsupported.
- CSP prohibits external connections, arbitrary scripts and form submission.
- Existing 8002 health remained `ok`, `light-harness-1.3`.

`node test.mjs`: **18/18 state/persistence checks passed**. These cover useful
advance with Unknown, explicit source review, quantity ownership, context/draft
version invalidation, approval/rejection preservation, corruption, stale actions,
invalid payloads, newer-tab protection and simulated storage write failure.

## Actual browser actions

Used the Codex in-app browser at `http://127.0.0.1:8003/`. These observations came
from controls and displayed state, not invoking the reducer directly.

| Interaction | Observed result |
|---|---|
| Open source | Text appears; state remains provided/unread |
| Confirm simulated review | Source and Next Action update; Unknown quantity remains |
| Prepare fixture draft | Useful review-first fixture appears; no model call is claimed |
| Add estimated total 360 pcs | Card updates; previous draft becomes stale and cannot be approved |
| Prepare, explicitly review, simulate approval, refresh | Exact quantity, source state, draft and approval version restored |
| Edit and save | Previous approval invalidated; facts remain unchanged |
| Reject, refresh | Exact edited text and rejection restored |
| Modify without saving | Main status and footer say unsaved/unapproved; approval disabled |
| Restore unchanged saved text | Previously saved status restored accurately |
| Known-quantity fixture | 480 pcs retained; no quantity re-ask |
| Protective-use fixture | Technical verification retained; no protective capability guaranteed |
| Second tab | Saved state restored; selection change propagates |
| Change another tab while first has unsaved text | Text retained, approval paused, explicit conflict message |
| Explicit reset, refresh | Only prototype state returns to original fixtures |

Browser console errors/warnings: none observed. Desktop rendering was inspected
using a browser screenshot. Initial hidden full-page capture failed; visible
viewport capture worked. Mobile layouts were not separately exercised.

An independent code review found that unsaved text initially left the approved
status and saved-state footer visible. This UI bug was fixed and the exact
approved → unsaved edit → restore text sequence was retested successfully.

The test tab was closed; one user-facing Demo tab remains open. Test state was
explicitly reset and the first unapproved fixture draft was prepared for trial.

## Limits and decision

- Only synthetic fixtures are used. No real mailbox, customer, company seed,
  uploaded document, research endpoint or drafting API is connected.
- This demonstrates schema-driven UI + a controlled action loop. It does not
  demonstrate model-composed layout, Apertus schema reliability, SDK integration,
  improved reply correctness or human review speed.
- Browser storage is per origin/profile and locally editable. It is not durable
  server-side persistence or a trusted approval ledger. Simultaneous multi-tab
  writes are not transactionally serialized. Quota/corrupt-state tests were run at
  the state layer; browser storage was not forcibly corrupted during UI acceptance.
- Fixture replies and business decisions are authored examples; arbitrary draft
  edits have no semantic safety checks. Approval is visibly a simulation only.
- This separate process must be started again after stopping/rebooting. The
  final Docker `make run` and current `/ui` do not include this experiment.

**Competition recommendation:** keep this as an isolated prototype. If Alex
finds it quicker to understand, borrow an optional small action card in the
conversation. Do not replace the stack, resume the full Harness, or make
Generative UI a new competition deliverable. First-reply usefulness remains the
main criterion; interactive presentation cannot repair incorrect trade judgment.
