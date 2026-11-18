# Review Queens’ oldest Dirty Condition requests

Decision memo, 18 November 2026. Portfolio demonstration.

**Recommendation.** Prioritize a review of Queens Dirty Condition requests aged seven days or more. At the captured observation, this segment had **181 open requests**, including **92 aged at least 168 hours**—the largest aged backlog among the analyzed agency/problem/borough segments.[^1]

**Why this segment.** Recorded-closure p90 was **126.7 hours** across 3,092 eligible closures. The illustrative 72-hour target was met by **2,087 of 3,240 eligible requests (64.4%)**; 33 still-immature requests were excluded. The denominator includes valid overdue open requests as well as eligible closed requests. These targets are portfolio assumptions, not official DSNY commitments.

**Recent activity.** From November 2–8 to November 9–15, intake fell from 335 to 287 (14.3%), while recorded closures fell from 338 to 228 (32.5%). These are creation-date and closure-date events within a fixed creation cohort. They do not measure a change in observed backlog; only one live observation has been captured.

**Next review.** Inspect the oldest request IDs for later source closure updates and operational routing. Proposed owner: the service-operations analyst, with an agency contact validating interpretation. Capture the same cohort again in one week, then compare aged backlog using the new observation. Retain the first capture and target version for comparison.

**Decision limits.** The data cannot establish cause, staffing need, actual field completion, or citywide service performance. Older requests created before September 7 and requests created after November 15 are outside this cohort. Do not infer a staffing intervention from these figures.

**Scope and evidence.** DSNY Dirty Condition and Illegal Dumping, created September 7–November 15, 2026, using America/New_York dates. Observed November 18 at 11:31:28 UTC. Release: `dsny_20261118`. BigQuery SQL matches the local reference; all 60 dbt data tests passed. Desktop CSV and native BigQuery Import each matched all 41 SQL comparisons; 33 native timestamp checks passed. The owner OAuth login does not demonstrate read-only access.

[^1]: NYC Open Data, [*311 Service Requests from 2020 to Present*](https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9), captured November 18, 2026, dataset `erm2-nwe9`. Portfolio calculations: release `dsny_20261118`, [executed SQL and outputs](../artifacts/releases/dsny_20261118/sql_reconciliation.json), [dbt results](../artifacts/releases/dsny_20261118/dbt_results.json), [CSV SQL–DAX comparison](../artifacts/releases/dsny_20261118/sql_dax_comparison.json), [native BigQuery SQL–DAX comparison](../artifacts/releases/dsny_20261118/sql_dax_bigquery_comparison.json), [native timestamp checks](../artifacts/releases/dsny_20261118/powerbi_bigquery/timestamp_comparison.json); definitions in [metrics.md](metrics.md). Demo targets: 72 hours for both selected problems.

Editable [Google Doc](https://docs.google.com/document/d/1gXshrmescOyhcQ2xDN1RHLpTedZ_XVzDpJuDxVOiGo8) and [demo-target Google Sheet](https://docs.google.com/spreadsheets/d/1n88jxFlbe-H2ZwDIAA-GAxsmxoEkQE6Hfz8JtoGrRn0). Artifact details and verification status: [workspace-artifacts.json](workspace-artifacts.json).
