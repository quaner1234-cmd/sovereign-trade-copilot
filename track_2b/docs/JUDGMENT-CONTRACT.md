# Judgment Contract 1.0

This layer recommends a next action. It never sends mail, pays, releases goods,
starts production or changes a source record. Every result requires human approval.

## Input and trust boundary

`POST /judgment` accepts `scenario` (`inquiry`, `payment`, `sample_test`), a
`subject` identifier, `sources`, and an optional ISO date `as_of`. Payment
decisions need `as_of`; it is operator-supplied context, not a model-invented date.

Each source has a unique `id`, `party` (`customer`, `company`, `lab`), `format`
(`email` or `fact_card`), and `text`. Source party is the operator's attestation;
the service does not authenticate an employer, laboratory or sender.

Email sources are inbound customer messages. They use the existing parser,
FactStore and semantic layer; a customer target or request never becomes a company
confirmation. Common product names and quantities can support preliminary
internal costing, including explicitly approximate quantities.

Operational states not covered by the v4 email parser are explicit JSON fact
cards. A card is a human-provided source, not an LLM extraction result. Its
`subject` must match the request. The program parses and type-checks it, attaches
literal key/value spans, and keeps party and confirmation status. It does not
accept a client flag such as `validated: true` as proof.

Example payment source text:

```json
{"subject":"ORDER-101","payment_status":"pending","payment_due":"2026-10-05","payment_checked_at":"2026-10-04","pi_sent":true}
```

Example paired sample cards:

```json
{"subject":"SAMPLE-101","metric":"shrinkage","unit":"percent","test_value":6}
{"subject":"SAMPLE-101","metric":"shrinkage","unit":"percent","test_min":0,"test_max":3}
```

The first sample card comes from the laboratory or company; approved limits come
from the company. Numeric facts need their own metric and unit in the same card.
Conflicting values or mismatched units/metrics are preserved and escalated.
Customer reports of payment are claims; only a company card can establish receipt.
Customer requests to change a due date remain unconfirmed; only a company card
can establish the payment node used by WAIT/RECHECK.
This prototype does not infer arbitrary payment or laboratory states from prose.

## Output schema

The machine-readable schema is `judgment.schema.json`. All scenarios return:

```json
{
  "schema_version": "1.0",
  "scenario": "payment",
  "action": "RECHECK",
  "owner": "finance",
  "reason": "约定付款节点已过去；先核查到账状态。",
  "evidence": [{"fact_id":"finance:payment_due","source_id":"finance","field":"payment_due","value":"2026-10-05","quote":"\"payment_due\":\"2026-10-05\"","span":[50,76],"semantic_role":"FACT","stance":"company","status":"supported"}],
  "blocking_conditions": [],
  "needs_human_approval": true,
  "next_customer_action": "财务复查后，由业务员决定是否联系客户确认。",
  "confidence": "medium"
}
```

The source above has id `finance` and party `company`; runtime offsets are checked
against the exact source. `blocking_conditions` entries carry `field`, `reason`, `evidence_ids`,
`blocks_current_action`, and `scope`. A missing quote approval can block a binding
commercial commitment without blocking preliminary internal costing. No source
is fabricated for a missing value.

`confidence` describes rule coverage and source completeness, not calibrated
probability or human business approval. Unknown/unconfirmed/conflicting states
remain visible even when another low-risk action can proceed.

## Minimal architecture

1. Source adapters create typed facts from validated email spans or typed JSON cards.
2. A common resolver checks subject, authority, dimensions, freshness and conflicts.
3. One ordered policy evaluator matches declarative conditions across all scenarios.
4. One output builder supplies action, owner, reason, evidence, unmet conditions and approval.
5. A final validator checks every evidence locator and keeps approval mandatory.

There are no scenario-specific execution agents or external action tools.
The judgment policy is deterministic; Apertus remains in the v4 email pipeline.
The judgment API does not make additional model calls. All source records stay
unchanged.

## Narrow policies

| Scenario | Required basis | Possible recommendation |
| --- | --- | --- |
| Inquiry | Product, positive quantity, specification | INTERNAL_COSTING or REQUEST_INFORMATION; conflict → ESCALATE |
| Payment | Company payment status; date context and relevant node/check | WAIT, RECHECK, REQUEST_CONFIRMATION, CONTINUE_REVIEW or ESCALATE |
| Sample | Tested value and company-approved range with matching metric/unit | PASS, REWORK, REQUEST_CONFIRMATION or ESCALATE |

Payment nodes are dates, inclusive through that day: overdue means `as_of` is
strictly later. A received-payment card must have a same-day check before a
CONTINUE_REVIEW recommendation; stale/future checks do not authorize it. A missing
or explicitly unsent PI is surfaced before asking a customer to pay. PASS and
CONTINUE_REVIEW are review recommendations; neither authorizes production.

## Acceptance and limits

Each scenario has normal, missing-information and conflict/boundary synthetic
cases. Equivalent email phrasing and card serialization must preserve decisions;
changed business facts must change them where relevant. Tests also reject forged
locators, wrong subjects, customer-as-company promotion and mismatched measurement
units. Fixtures are public synthetic data, not customer or internal records.

Remaining scope: no authenticated source identity, email-chain state reconciliation,
arbitrary prose operational extraction, costing calculation, complete commercial
approval matrix or autonomous execution. Human business review remains required.
Sample measurements are finite nonnegative scalars for one metric at a time;
negative-valued metrics, unit conversion and multi-metric release are outside this scope.
