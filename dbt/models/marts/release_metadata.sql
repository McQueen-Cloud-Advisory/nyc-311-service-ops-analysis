select
    '{{ var("release_id") }}' as release_id,
    snapshot_id, observed_at, extraction_started_at, extraction_ended_at,
    source_kind, cohort_start, cohort_end, target_version, expected_count, source_count
from {{ ref('stg_observations') }}
where snapshot_id = '{{ var("snapshot_id") }}'
