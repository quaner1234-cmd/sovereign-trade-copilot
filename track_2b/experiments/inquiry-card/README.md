# Structured inquiry card experiment

An isolated **synthetic-only interaction prototype**, not the competition runtime.
The existing `/ui`, drafting prompts, checks, company imports and email systems
are unchanged. No model, mail, research or other external service is called.

## Frozen acceptance before implementation

1. Show synthetic customer, inquiry, status, action-specific blockers and next move.
2. A declared source stays unread until explicit simulated review; opening a panel
   alone does not mark it read. Unknown quantity does not block source review.
3. A simulated quantity update changes only that field and dependent card content.
4. Prepare a clearly labelled fixture draft; edit and reject preserve source facts.
5. Explicit simulated approval binds to the current draft and context versions;
   editing or changing context invalidates it. Nothing is sent.
6. Refresh restores context, draft, rejection/approval and action history.
7. Stale actions, unknown actions and invalid payloads are rejected. Corrupt or
   unavailable browser storage produces an explicit error, not a false saved state.
8. Browser interaction and rendered layout must be checked, in addition to tests.

## Run

```powershell
cd track_2b/experiments/inquiry-card
python serve.py
# http://127.0.0.1:8003/
node test.mjs
```

`serve.py` binds to loopback and serves only this prototype's three browser assets
and `/health`. It has no POST endpoints. `--port` can select another local port.

## Contract and boundaries

`model.mjs` holds invented fixture data, a finite action vocabulary and a pure
state reducer. `index.html` renders an allowlisted `InquiryCard` view using text
nodes, forms and buttons. Structured output cannot execute arbitrary HTML or JS.
Actions carry `case_id` and `expected_revision`; context and draft revisions are
separate. Rendering never upgrades source state or grants company authorization.

Only the synthetic state is stored in versioned `localStorage`. Persistence is
per browser, profile and exact origin (scheme, host, port). It survives ordinary
refresh, not clearing browser data or using another device. It is not an audit
store or security boundary. Editing localStorage can forge a simulated approval.
Cross-tab changes are reloaded and stale actions are rejected; this does not
provide transactional multi-user storage. Storage failure retains the last state.
Reset explicitly clears only this prototype's storage key.

The draft and business choices are **fixtures**. They do not measure inference,
trade judgment accuracy, sendability or review speed. Free draft edits are not
semantically checked. A UI approval here is only a simulation, not authorization
to communicate with a customer. No real inquiry entry/upload is offered.

## Why no SDK migration

The project is Python stdlib + native HTML. ChatKit widgets/actions provide the
useful pattern of structured cards and explicit actions, but integration would
add protocol, SDK and storage work. assistant-ui distinguishes fixed tool UI
from model-composed `present` component trees and adds a React toolchain.
This experiment borrows the interaction pattern; it uses neither SDK.

Sources checked 2026-10-09:
- [ChatKit widgets](https://developers.openai.com/api/docs/guides/chatkit-widgets)
- [ChatKit actions](https://developers.openai.com/api/docs/guides/chatkit-actions)
- [assistant-ui Generative UI](https://www.assistant-ui.com/docs/tools/generative-ui)

For competition closeout, adopt only a small optional action card if a user trial
shows it improves comprehension. Keep the reply as the main task. Do not migrate
the stack or claim model-generated UI reliability from this experiment.

## Validation

Runtime and interaction results are recorded in `VALIDATION.md` after execution.
