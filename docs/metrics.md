# Source and metric contracts

## What this report measures

This project describes service requests and **agency-recorded closure**. It does
not measure handle time, queue wait, staffing requirements, service fulfillment,
or actual improvements in city operations. NYC's definition explicitly cautions
that recorded closure does not establish when the request was fulfilled.
[NYC 311 reporting definitions](https://www.nyc.gov/site/311reporting/faq/faq.page)

The configured creation cohort is a half-open interval `[cohort_start, cohort_end)`
in New York local calendar dates. The initial real-data scope is DSNY, **Dirty
Condition** and **Illegal Dumping**, created from **2026-09-07 through 2026-11-15**
inclusive (`cohort_end = 2026-11-16`). Exact capture timestamps and counts belong
to the release manifest and `release_metadata`; this contract does not assert
that a cloud or Desktop check has run.

The two problem categories have **72-hour demonstration targets**. These are
invented thresholds for demonstrating effective-dated business rules, not city
service commitments. Every dashboard label uses **demo target**.

Closures and backlog cover only this creation cohort. Requests created earlier
or later are absent. After the creation window ends, later observations can show
updates to these requests but cannot measure new citywide demand. No historical
backlog observation is reconstructed from today's status.

## Input contract

Source: official NYC Open Data dataset `erm2-nwe9`, retrieved with only the approved
fields. The display name is **Problem**; its API column remains `complaint_type`
at initial profiling. Python maps it to `problem`. Addresses, coordinates,
descriptors, and resolution text never enter the model.

`raw.observation_requests` has one row per `snapshot_id × request_id`:

| Field | BigQuery type | Meaning |
| --- | --- | --- |
| `snapshot_id`, `request_id` | STRING | Stable observation identifier and source request key |
| `created_date`, `closed_date` | STRING | Original source timestamp text; null closure is allowed |
| `created_at`, `closed_at` | TIMESTAMP | Unambiguous UTC instants from the ingestion time validator |
| `created_local_date`, `closed_local_date` | DATE | Source-local calendar dates when parseable |
| `temporal_quality` | STRING | Time-validation outcome below |
| `status`, `agency`, `problem`, `borough`, `channel` | STRING | Minimal source attributes |
| `payload_hash` | STRING | Hash of canonical source payload, independent of extraction clock |

`raw.observations` has one row per `snapshot_id`: `observed_at`,
`extraction_started_at`, `extraction_ended_at` (TIMESTAMP); `source_kind` (STRING);
`cohort_start`, `cohort_end` (DATE); `expected_count`, `source_count` (INT64);
`target_version`, `scope_hash` (STRING); and `is_published` (BOOL). `scope_hash`
hashes the complete captured scope including agency and problem choices, so
different populations sharing the same date window cannot mix in backlog history.
`observed_at` is the original
extraction end timestamp. A replay must preserve it. Paging a live API does not
produce a transactionally atomic source snapshot; the recorded extraction
interval makes that limitation visible.

`raw.requests_current` has one current row per request and supports the
payload-hash MERGE demonstration. The reporting model deliberately reads captured
observations, so a later MERGE cannot rewrite an earlier published result.

Before building a candidate, the runner compares request keys with the preceding
complete extract for the same cohort. An unexplained disappearance blocks
publication while the last good release stays available. An absent row does not
establish closure and is never converted into a closed case.

`raw.targets` stores `target_version`, `agency`, `problem` (STRING),
`effective_start`, `effective_end` (DATE), and `target_hours` (INT64). The same
normalized schema applies to the checked-in CSV and read-only Google Sheets input.
The version is the captured register's content hash. Target matching uses the
request's **local creation date**, not closure or observation date.

## Time and status rules

- Interpret source timestamps as `America/New_York` local wall-clock values.
  Convert unambiguous instants to UTC before measuring elapsed hours.
- A fall-back timestamp occurring twice or a spring-forward timestamp that does
  not exist cannot be resolved from naive source text alone. Ingestion flags it
  rather than inventing an offset. Preserve its local date if parseable; exclude
  the outcome from elapsed-duration and target-rate eligibility.
- `temporal_quality` is one of `valid`, `missing_created`, `invalid_created`,
  `invalid_closed`, `ambiguous_created`, `ambiguous_closed`, `nonexistent_created`,
  `nonexistent_closed`, `negative_elapsed`, `future_created`, or `future_closed`.
  The Python validator owns precedence when more than one issue exists. Every
  non-`valid` outcome is ineligible for duration and target metrics.
- Missing closure text on an open request is valid. A closed status with no
  closure instant is invalid. An open status with a nonnull closure instant is
  also inconsistent and invalid for outcome metrics.
- Normalize status case and surrounding whitespace. `Closed` means `closed`.
  `Open`, `Assigned`, `In Progress`, `Pending`, and `Started` mean `open`.
  Blank, `Unknown`, and `Unspecified` mean `unknown`. A new source status blocks
  the release until its meaning is reviewed (`source_status_contract.sql`).
- Duration is `TIMESTAMP_DIFF(end, start, MICROSECOND) / 3,600,000,000` hours.
  Date slicers use New York local dates. UTC elapsed time correctly treats the
  spring-forward example 01:30 → 03:30 as one hour and the fall-back example
  00:30 → 02:30 as three hours. The SQL test uses 2026 transition examples.

The ingestion tests must also exercise ambiguous and nonexistent local times,
invalid dates, and reversed timestamps. The dbt tests verify their downstream
exclusion and valid UTC/local-date correspondence; those tests alone do not
prove the ingestion timezone converter ran correctly.

## Model grains and dimensions

| Model | Grain and business key |
| --- | --- |
| `fct_cases` | One request at this release's snapshot; `request_id` |
| `fct_backlog` | One captured snapshot × agency × problem × borough; all four keys |
| `dim_agency` | One normalized agency code; `agency_key` |
| `dim_problem` | One normalized problem label; `problem_key` |
| `dim_borough` | Each of five boroughs plus `UNKNOWN`; `borough_key` |
| `dim_date` | One local calendar date; `date_key` |
| `release_metadata` | Exactly one release scope; `release_id` |

Every reporting table carries `release_id`. Physical tables use
`<model>__r_<release_id>` inside the work/reporting datasets. Python builds and
tests in work, copies only passing marts to reporting, then publishes the
manifest. Staging views remain private in work. Power BI reads one explicit
release, never independently resolves a mutable latest pointer for each table.

Agency codes are uppercased and trimmed; problem labels are trimmed. Missing
agency/problem use `UNKNOWN`. Missing, unrecognized, or unspecified boroughs
use `UNKNOWN` and remain in totals. Null dates stay blank rather than acquiring
a misleading date. Reporting creation dates outside the configured cohort are
blank. Reporting closure dates are populated only for eligible recorded closures;
invalid/ambiguous/future closure dates remain preserved in raw/staging but are
blank in the fact's date role. The calendar is bounded from cohort start through
the later of cohort end minus one day or the observation's New York date. Invalid
source years therefore cannot expand the calendar. Date relationships ignore
blanks; outcome exclusions remain visible in coverage metrics.

The backlog fact includes previously published observations from the exact same
cohort and source kind, plus the candidate snapshot. **Only the release snapshot
is imported for request-level investigation.** Earlier investigation changes
`pReleaseId` and refreshes every table together. This preserves case grain and
prevents showing today's request details behind yesterday's backlog.

## Metric definitions

| Metric | Definition | Date context |
| --- | --- | --- |
| Intake | Count requests with a known local creation date in the configured cohort and selected creation-date slice | Creation date |
| Recorded closures | Count coherent, valid closed cases with a nonnull recorded closure instant at/before observation | Closure date |
| Observed backlog | Count `open` cases with no recorded closure instant at the selected completed capture | Exactly one snapshot |
| Backlog age | UTC elapsed hours from creation to observation for open cases; unresolvable creation times remain `Unknown age` | Exactly one snapshot |
| P90 elapsed time to recorded closure | Continuous interpolated 90th percentile of `elapsed_hours` over eligible closed case rows | Closure date |
| P90 eligible count | Count rows used in the p90 calculation | Same closure-date and segment filters |
| Within demo target | Sum of mature-case pass flags divided by sum of mature-case eligibility flags | Creation date |

Backlog buckets are `[0,24)`, `[24,72)`, `[72,168)`, `[168,infinity)` elapsed hours,
plus unknown age. Their counts sum to observed backlog. These are age buckets,
independent of a problem's assigned target hours. A seven-day age is not labeled
an official service failure.

For targets, a register row applies when
`effective_start <= created_date < effective_end`; null end means unbounded.
Target hours must be a positive integer. Duplicate or overlapping intervals for
the same agency/problem fail validation. Each request matches at most one row.

Assign one mutually exclusive `target_eligibility_reason` in this order:

1. `invalid_outcome`: invalid/uncertain time, future chronology, closed without
   a closure timestamp, or open with a closure timestamp.
2. `unknown_outcome`: status meaning is unknown.
3. `missing_target`: no target applies on the local creation date.
4. `immature`: fewer than `target_hours` have elapsed by observation, even if the
   case already closed quickly.
5. `eligible_mature`: the threshold has elapsed and all preceding checks pass.

`target_denominator = 1` only for an eligible mature case.
`target_numerator = 1` only when that case is closed and
`elapsed_hours <= target_hours`; exact-boundary closures pass. Mature overdue
open cases and mature late closed cases remain in the denominator with zero
numerator. The four exclusion/immaturity flags are exclusive and, together with
the denominator flag, partition the case population. Coverage counts describe
the primary exclusion reason; raw `temporal_quality` and target columns support
deeper inspection of overlapping issues.

Percentages aggregate by **summing numerators and denominators**, never by
averaging segment percentages. P90 is recomputed across case rows, never averaged
across segment p90s. Backlog counts are never summed across observations.

An empty slice produces zero counts, blank p90, and blank target rate when its
denominator is zero. Counts reconcile exactly. BigQuery `PERCENTILE_CONT(...,0.9)`
and Power BI `PERCENTILEX.INC(...,0.9)` use continuous interpolation; reconcile
unrounded results within **0.000001 hours**, then round only for presentation.

## Verification and performance

`dbt build` runs key, relationship, accepted-value, target-interval, fanout,
population, release metadata, timestamp, eligibility, backlog, and DST checks.
The synthetic fixture additionally requires at least one overdue open and one
immature case. Schema and data-test definitions are in `dbt/models/schema.yml`
and `dbt/tests/`; request-level logic is `int_case_metrics.sql`.

Use these compiled analyses with the same release vars as the build:

- `reconciliation.sql`: overall, DSNY / Dirty Condition / Brooklyn, and a
  deliberately empty slice, matching the checked-in DAX query.
- `date_role_reconciliation.sql`: `[2026-11-09, 2026-11-16)` by default; creation
  and closure roles are evaluated separately, backlog is unchanged.
- `release_integrity_reconciliation.sql`: checks that request details and
  selected backlog belong to one release observation, matching DAX section E.
- `segment_investigation.sql`: ranks older observed backlog and reports sample
  counts and target numerator/denominator; the ranking is an investigation cue.
- `weekly_demand_and_closures.sql`: separates intake and closure event dates.
- `benchmark_optimized.sql` and `benchmark_baseline.sql`: identical query outputs
  on partitioned/clustered cases and an unpartitioned/unclustered copy.

The case fact partitions by creation date and clusters by agency, problem, and
borough. Backlog partitions by local snapshot date with the same clustering.
Partition filters are not mandatory for this intentionally small Import model;
Power BI imports the whole bounded release. The benchmark's first-week date and
borough filters test selective access. Disable query cache for both benchmark
jobs and record result hashes, processed bytes, billed bytes, timings, and scope.
Copy/build costs are recorded separately. A small dataset may show little or no
benefit; no improvement is claimed until measured.

Official implementation references:
[dbt BigQuery partitioning and clustering](https://docs.getdbt.com/reference/resource-configs/bigquery-configs),
[GoogleSQL percentile functions](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/navigation_functions#percentile_cont).

Local mirror outputs are useful reviewer fixtures; they do not substitute for
executed BigQuery SQL or Power BI DAX evidence. Execution status belongs to the
release evidence manifest, with local, BigQuery, and Desktop results separate.

Run dbt with `RUN_CACHE_DISABLED=true` and
`DBT_SEND_ANONYMOUS_USAGE_STATS=false`; the project also disables anonymous
usage statistics in its flags. The managed dbt State integration is not part of
this local/dbt Core architecture, and no dbt Cloud credential is required.
