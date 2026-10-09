# Conversation + optional review card

This integrates presentation into the real Light Harness UI. It is not the
synthetic-only 8003 card experiment. No business extraction, judgment, message
plan builder, patch automation, research tool, new model call or sending path is
added. Existing one-call messages, prompts and draft checks remain unchanged.

## Acceptance frozen before runtime validation

1. Paste an inquiry directly. Company context is optional/collapsed. Real or
   recorded draft appears first; the review card stays collapsed.
2. Card shows actual source state, supplied company conditions and phrase-located
   advisory flags. It does not invent identity, business stage, a validated next
   action or a blocker from free text. Next reviewer action is labelled as such.
3. Existing edit/context/manual prepare/approve/copy controls actually work.
   Viewing sources never marks them read. There is no new model call for a card.
4. Refresh restores selected input, company text/scope and latest draft through
   tab-scoped sessionStorage. It makes no inference or approval request.
5. Refresh never restores approved styling, reviewer identity or review checkbox.
   Any input/context/draft change invalidates approval eligibility or review.
6. An expired server record returns the existing 409: text is retained, approval
   disabled, and manual preparation required. No substitute or automatic retry.
7. Failed generation and browser storage failure retain visible text. Forget tab
   recovery removes only this page's cache and disables further automatic writes.
8. Real Docker deployment and browser interaction, including one live Apertus
   synthetic first draft, are required. Scripted approvals are test evidence only.

## Privacy and limits

The cache is plain browser **sessionStorage**, isolated by tab and origin. It
contains inquiry and selected company text, not original upload bytes, provider
raw output, API credentials or approval objects. It is not a company profile or a
trusted ledger. Browser session restoration may retain a tab cache after closing
the browser; use **Forget tab recovery** on a shared computer. Clearing browser
data or losing the tab can lose drafts. Corrupt/unavailable storage is reported;
the application cannot guarantee recovery when storage is denied.

Server records remain bounded, ephemeral memory. A restored draft's token may
expire after restart or eviction. Refresh deliberately requires human re-review;
the server remains the authority for whether a token can be approved.

The card shows company conditions supplied for the draft, not automatically
verified claims actually used in its wording. Flags remain incomplete and refer
to the preserved first draft. Edited text needs fresh human review. The card
does not repair previously observed business failures or certify sendability.

## Validation results

Executed on 2026-10-09. Status: **PASS for the UI/recovery contract**; business
sendability and time saved are not established by this test.

- Actual embedded-cache and approval-handler checks: `node src/selftest_review_ui.cjs`,
  9/9. Includes a late 409 from an older approval not invalidating a newer draft,
  unavailable/malformed/oversized storage, and exclusion of unselected document
  text and approval/provider fields. A separate read-only review confirmed the
  three recovery/approval fixes and independently ran the nine checks.
- Existing Python regression: `python -m unittest selftest_light selftest_sources
  selftest_company_import selftest_llm_client`, 42/42. The Windows sandbox denied
  local test sockets (WinError 10013); the unchanged tests passed outside that
  socket restriction. No prompt, harness, server, source reader or Dockerfile
  change is included in this task.
- Built the final Docker source and ran a separate, key-free container at 8010.
  Real in-app browser interactions verified draft-first display, collapsed review
  card, accurate source/company evidence, edit, explicit scripted approval,
  refresh preserving latest text while clearing reviewer/reviewed/approval UI,
  context changes invalidating approval eligibility/authorization, copy retaining
  the exact draft, and manual-generation failure keeping the previous text.
- Restarted only that disposable container. Approval of its restored old token
  returned 409; text stayed visible and approval was disabled. Forget + refresh
  produced blank input and kept recovery off.
- Uploaded a synthetic TXT, removed an obsolete paragraph in the preview and
  changed scope. Refresh restored the selected text and scope exactly; unchecked
  company authorization stayed unchecked. This was not a real company document.
- Final source image built successfully as
  `sha256:97a94a13b87925995e6429d9e783aac92620f70f3410c76aacaaed4265af3c5a`.
- Updated only `/app/src/ui/light.html` in the existing 8002 container. Its ID,
  original start time and restart count (0) were unchanged. Health remained
  `light-harness-1.3`, live Apertus, sending disabled. Old page code was backed up
  privately. A normal later image build includes the source file change; this
  update does not modify the existing image underneath the running container.
- One real Apertus draft from the existing synthetic hero packet returned on
  8002: 4,442 ms; 1 transport attempt; 1 new model call; 1,620 prompt + 177
  completion = 1,797 tokens; finish reason `stop`. No retry or replacement. Card
  expansion/edit/reload made no further drafting request. A greeting was added
  only to exercise editing; reload restored that text exactly, unapproved.
- The model returned literal `None` for its hint. The UI hides that placeholder;
  the first draft and provider result remain unchanged. Browser console reported
  no error/warning entries during this verification.

### Preserved live first draft and counterevidence

The completely synthetic input and authorized conditions are the existing hero
in `data/light-demo/cases.json`. The returned first draft was:

> We can develop custom cycling jackets and commuter vests based on your designs. Our usual MOQ baseline is 240 pieces, but no per-style or per-color minimum is set—final allocation will be reviewed for your project. Sample development typically takes 18 business days after sample fee receipt and material availability confirmation. Production lead time is normally 70–95 calendar days after both deposit receipt and sample approval, subject to material and capacity checks.
>
> To move forward, please share:
> 1. The priority style to develop first;
> 2. Any design files or material preferences you already have;
> 3. Your estimated initial production quantity and intended style/color allocation.
>
> We will then provide a sample-cost basis and conditional preliminary costing.

**Requires human correction:** “no per-style or per-color minimum is set” turns
“no such minimum is authorized in the supplied context” into a negative company
policy. Keep the general baseline and say allocation requires project review.
The explicit review of the priority design/material route also belongs before
costing. No advisory flag detected this issue. This UI task neither repairs nor
conceals that business failure; one live result cannot establish general draft
quality, reviewer usefulness or review-time savings.

The card is a fixed view of returned evidence/state. It is not model-generated
layout, typed business judgment, an autonomous action executor or a substitute
for human approval. No real email, private company truth or customer experiment
output was added to the repository. No push.
