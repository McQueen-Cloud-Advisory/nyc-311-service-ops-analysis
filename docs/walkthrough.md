# Three-minute Senior BIE walkthrough

Open the executive report, [priority analysis](../artifacts/analysis/priority-context.json), [briefing checks](../artifacts/report/dsny_20261118/executive_v2/qa/final_csv/briefing_comparison.json), [core SQL/DAX comparison](../artifacts/report/dsny_20261118/executive_v2/qa/final_csv/sql_dax_comparison.json), and [replay evidence](../artifacts/replay/bigquery-replay.json) before starting. The [executive PDF](../artifacts/report/dsny_20261118/executive_v2/NYC311_dsny_20261118_executive.pdf) provides a static alternative; [artifact status](../artifacts/report/dsny_20261118/README.md) distinguishes saved files and executed checks. Review the [contribution note](contribution-note.md) so personal claims match work Scott performed or reviewed with Codex assistance.

The executive CSV report passed 105 briefing checks, 41 core SQL/DAX comparisons, and [33 UTC timestamp checks](../artifacts/report/dsny_20261118/executive_v2/qa/final_csv/timestamps/timestamp_comparison.json). Both pages, Queens drill-through, age-to-worklist filtering, and the exported PDF passed visual review. The [original native BigQuery proof](../artifacts/releases/dsny_20261118/sql_dax_bigquery_comparison.json) covers 41 core comparisons and 33 timestamp checks; the new executive measures have not been reverified in native mode.

## 0:00–0:35 — Make the decision clear

**Show:** the priority headline, aged-backlog share, and segment ranking with the full cohort selected. Point to the as-of and coverage markers.

“The question is where an operations lead should investigate first. Queens Dirty Condition holds 24.3% of this cohort's week-old backlog but only 14.2% of its requests. It has 38 requests still recorded open after 30 days. Queens has fewer requests than Brooklyn for this problem, yet more week-old open requests. That concentration makes it the first review priority. These are 23,101 real DSNY requests in a fixed ten-week creation cohort, observed November 18, 2026.”

## 0:35–1:10 — Turn the finding into a bounded next action

**Show:** Queens / Dirty Condition drill-through, then select an aging bar to narrow the request worklist. Point out that the snapshot cards remain unchanged; clear the selection and show the oldest requests. In a PDF-only presentation, explain the interaction rather than claiming to perform it.

“The investigation keeps the same capture: 181 open requests, including 92 aged at least seven days. Start with the 38 aged at least 30 days; the oldest is 70.5 days. Check later source closure updates and routing. A second capture of the same cohort would support a like-for-like follow-up. One observation cannot establish a backlog trend, fulfillment, or staffing need. The lead gets a specific worklist and a next check.”

## 1:10–1:45 — Explain why the numbers deserve trust

**Show:** target numerator/denominator, the ten complete cohort weeks, the [metric contract](metrics.md), then the recorded comparisons. Distinguish the executive CSV checks from the original core/native checks.

“The 72-hour target is illustrative. Its denominator includes mature overdue-open and late-closed requests; 33 immature Queens cases are excluded. The result is 2,087 out of 3,240, or 64.4%. Intake, closures, and backlog use creation, closure, and observation dates respectively. The trend uses complete cohort weeks. This executive report passed 105 briefing checks and 41 core SQL/DAX comparisons. Separate timestamp checks caught a connector defect that matching counts alone would have missed.”

## 1:45–2:25 — Show ownership when the source or refresh changes

**Show:** the synthetic replay's `backlog_by_captured_snapshot`, failed-candidate checks, and restoration result; link the [release design](architecture.md).

“A weekly report must stay trustworthy after delivery. The live cloud exercise changes one old request from open to closed while keeping its key. The later backlog becomes five; the original capture remains six. Replaying adds no facts or metric changes. An injected validation failure leaves the last good release available. Immutable reporting tables pin every Power BI import to one release. Modest duplicated storage buys reproducibility and a clear recovery boundary. All 24 checks passed on labeled synthetic inputs.”

## 2:25–3:00 — Connect the work to the hiring manager's team

**Show:** [security evidence](security.md), the [benchmark conclusion](benchmark.md), and the [handoff runbook](runbook.md).

“The operating choices are deliberate: private storage, keyless pipeline access, and tested reporter permissions. The owner's Desktop login demonstrates connectivity, not least privilege. The selective benchmark processed 87.2% fewer bytes, but billed bytes were unchanged. For shipment exceptions, the same approach would use verified resolution events and agreed targets. This AI-assisted work sample demonstrates ownership of the decision, metric definitions, delivery, and recovery. It claims no observed improvement at NYC.”

For an engineering follow-up, reproduce the comparisons with `python scripts/analyze_priority_context.py` and use the [verification index](../artifacts/verification-status.json) to select deeper checks. Keep the three-minute presentation focused on the decision and the judgments that make its delivery dependable.
