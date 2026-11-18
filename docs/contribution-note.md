# Contribution note for Scott to review

This implementation was produced with Codex assistance from Scott's project brief
and review requirements. Scott selected the portfolio purpose, GCP/Power BI stack,
dedicated-project approach, cost constraints, and additional security emphasis.

When presenting this work, Scott should review the code and recorded execution evidence and
edit this note to distinguish decisions, implementation, and checks he personally
performed from work he reviewed or completed with assistance. Do not claim sole
authorship or firsthand execution of checks that cannot be substantiated.

Interview preparation:

- Explain why the demo-target denominator contains mature overdue-open and late-closed
  cases, while immature, unknown, and invalid outcomes are excluded and shown separately.
- Walk through the labeled replay: one request key updates, the original backlog stays
  intact, a repeat input adds no facts, and failed publication preserves the last release.
- Explain the immutable-report-table trade-off: a little duplicated storage buys a
  clear release boundary and reproducibility for sequential Power BI imports.
- Explain why a read-only reporter service account does not remove permissions from
  an owner-authenticated Power BI login, and show the actual positive/negative probes.
- Explain why an aged backlog concentration is a reason to investigate, not evidence
  of staffing requirements or unfulfilled service.

An analogous shipment-exception system could replace the 311 key with an exception ID,
use verified resolution event codes as recorded closure, and match targets by exception
class and effective creation date. The same maturity, snapshot, release, and access
contracts would still apply.
