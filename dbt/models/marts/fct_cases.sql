{{ config(
    partition_by={'field': 'created_date', 'data_type': 'date', 'granularity': 'day'},
    cluster_by=['agency_key', 'problem_key', 'borough_key']
) }}
select
    '{{ var("release_id") }}' as release_id,
    request_id, snapshot_id, observed_at,
    case when created_date >= date('{{ var("cohort_start") }}')
        and created_date < date('{{ var("cohort_end") }}') then created_date end as created_date,
    case when is_recorded_closure then closed_date end as closed_date,
    created_at, closed_at,
    agency_key, problem_key, borough_key,
    status, status_class, temporal_quality, channel,
    elapsed_hours, age_hours, age_bucket,
    target_hours, target_version, target_numerator, target_denominator,
    is_backlog, is_p90_eligible, is_recorded_closure,
    is_missing_target, is_immature, is_invalid_outcome, is_unknown_outcome,
    target_eligibility_reason, payload_hash
from {{ ref('int_case_metrics') }}
