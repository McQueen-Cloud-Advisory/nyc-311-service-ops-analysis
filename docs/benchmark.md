# Same-output BigQuery benchmark

The selected-date query processed **87.2% fewer bytes** on the partitioned and clustered fact. Both queries reported **10,485,760 billed bytes (10 MiB)**, so this demonstration shows **no billed-byte saving**. It does not establish production cost savings or a repeatable speed improvement.

Executed on November 18, 2026 at 12:13 UTC against real release `dsny_20261118`. [Machine-readable results, exact SQL, job IDs, and output hash](../artifacts/releases/dsny_20261118/benchmark.json).

| Measurement | Unpartitioned baseline | Partitioned/clustered fact |
| --- | ---: | ---: |
| Source rows | 23,101 | 23,101 |
| Dry-run bytes | 1,304,253 | 166,973 |
| Actual bytes processed | 1,304,253 | 166,973 |
| Bytes billed | 10,485,760 | 10,485,760 |
| Query-cache hit | False | False |
| Output rows | 2 | 2 |

The baseline is a complete copy of the release's case fact with no partitioning or clustering. The reporting fact partitions by `created_date` daily and clusters by `agency_key`, `problem_key`, and `borough_key`. Metadata verified both designs and equal source row counts.

Both queries select creation dates **September 7–13, 2026** (`[2026-09-07, 2026-09-14)`) and **BROOKLYN**, grouping by agency/problem/borough. They return identical request counts and demo-target numerators/denominators:

| Problem | Requests | Target numerator | Target denominator |
| --- | ---: | ---: | ---: |
| Dirty Condition | 712 | 343 | 712 |
| Illegal Dumping | 379 | 172 | 379 |

The runner verifies equality before recording a successful result. Output hash: `d33b781f5d3c22e02cc013b0c8aa1410ee841acd10ed41bcf2b84d242a748d5a`. Both actual queries used disabled caching, prior dry runs, and a configured maximum-bytes-billed limit. The artifact contains the verified job limit, timestamps, elapsed milliseconds, and slot milliseconds. One query execution per design cannot establish stable latency differences or isolate clustering's contribution from partition pruning.

Creating the baseline separately processed **8,310,097 bytes** and reported **10,485,760 billed bytes**. That setup cost is excluded from the paired-query comparison, retained in `setup_job`, and must not be hidden when discussing total work. The baseline remains in the work dataset for inspection; it does not modify the reporting release or its publication pointer.

The report's full-release Import refresh does not use this selective date predicate. Do not apply the measured reduction to its refresh cost. No invoice dollars or realized credit usage are inferred from these job statistics.

Reproduce from the repository root after a successful cloud release:

```powershell
.\.venv\Scripts\python.exe -m nyc311 benchmark --cloud-config .local/cloud.json --release-id dsny_20261118
```

This replaces only the dedicated work-dataset baseline table and records a new benchmark artifact. See [storage design](../dbt/models/marts/fct_cases.sql), [benchmark runner](../nyc311/cloud.py), and the [runbook](runbook.md).
