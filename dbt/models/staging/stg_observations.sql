select
    snapshot_id,
    observed_at,
    extraction_started_at,
    extraction_ended_at,
    source_kind,
    cohort_start,
    cohort_end,
    expected_count,
    source_count,
    target_version,
    scope_hash,
    is_published
from {{ source('raw', 'observations') }}
where cohort_start = date('{{ var("cohort_start") }}')
  and cohort_end = date('{{ var("cohort_end") }}')
  and source_kind = '{{ var("source_kind") }}'
  and scope_hash = '{{ var("scope_hash") }}'
  and observed_at <= timestamp('{{ var("observed_at") }}')
  and (is_published or snapshot_id = '{{ var("snapshot_id") }}')
