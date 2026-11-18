{{ config(
    partition_by={'field': 'snapshot_date', 'data_type': 'date', 'granularity': 'day'},
    cluster_by=['agency_key', 'problem_key', 'borough_key']
) }}
with aged as (
    select *,
        case when created_at is not null and created_at <= observed_at
            then timestamp_diff(observed_at, created_at, microsecond) / 3600000000.0 end as age_hours
    from {{ ref('stg_requests') }}
), grouped as (
    select
        snapshot_id, observed_at, agency_key, problem_key, borough_key,
        countif(status_class = 'open' and closed_at is null) as open_count,
        countif(status_class = 'open' and closed_at is null and age_hours < 24) as age_under_24h_count,
        countif(status_class = 'open' and closed_at is null and age_hours >= 24 and age_hours < 72) as age_24_to_72h_count,
        countif(status_class = 'open' and closed_at is null and age_hours >= 72 and age_hours < 168) as age_72_to_168h_count,
        countif(status_class = 'open' and closed_at is null and age_hours >= 168) as age_168h_plus_count,
        countif(status_class = 'open' and closed_at is null and age_hours is null) as age_unknown_count
    from aged
    group by snapshot_id, observed_at, agency_key, problem_key, borough_key
)
select
    '{{ var("release_id") }}' as release_id,
    snapshot_id, observed_at,
    date(observed_at, 'America/New_York') as snapshot_date,
    snapshot_id = '{{ var("snapshot_id") }}' as is_release_snapshot,
    agency_key, problem_key, borough_key,
    open_count, age_under_24h_count, age_24_to_72h_count,
    age_72_to_168h_count, age_168h_plus_count, age_unknown_count
from grouped
