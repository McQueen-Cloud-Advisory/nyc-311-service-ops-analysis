with cases as (
    select * from {{ ref('stg_requests') }}
    where snapshot_id = '{{ var("snapshot_id") }}'
), matched as (
    select c.*, t.target_hours, t.target_key,
        '{{ var("target_version") }}' as target_version,
        case when c.created_at is not null and c.created_at <= c.observed_at
            then timestamp_diff(c.observed_at, c.created_at, microsecond) / 3600000000.0 end as age_hours,
        case when c.created_at is not null and c.closed_at >= c.created_at and c.closed_at <= c.observed_at
            then timestamp_diff(c.closed_at, c.created_at, microsecond) / 3600000000.0 end as elapsed_hours,
        c.temporal_quality != 'valid'
            or c.created_at is null
            or c.created_at > c.observed_at
            or (c.closed_at is not null and (c.closed_at < c.created_at or c.closed_at > c.observed_at))
            or (c.status_class = 'closed' and c.closed_at is null)
            or (c.status_class = 'open' and c.closed_at is not null) as invalid_outcome
    from cases c
    left join {{ ref('stg_targets') }} t
      on c.agency_key = t.agency_key
     and c.problem_key = t.problem_key
     and c.created_date >= t.effective_start
     and (t.effective_end is null or c.created_date < t.effective_end)
), classified as (
    select *,
        case
            when invalid_outcome then 'invalid_outcome'
            when status_class = 'unknown' then 'unknown_outcome'
            when target_hours is null then 'missing_target'
            when age_hours < target_hours then 'immature'
            else 'eligible_mature'
        end as target_eligibility_reason,
        status_class = 'open' and closed_at is null as is_backlog,
        not invalid_outcome and status_class = 'closed' and closed_at is not null as is_recorded_closure,
        case
            when age_hours is null then 'Unknown age'
            when age_hours < 24 then 'Under 24 hours'
            when age_hours < 72 then '24 to under 72 hours'
            when age_hours < 168 then '72 to under 168 hours'
            else '168 hours or more'
        end as age_bucket
    from matched
)
select *,
    is_recorded_closure as is_p90_eligible,
    cast(target_eligibility_reason = 'eligible_mature' as int64) as target_denominator,
    cast(target_eligibility_reason = 'eligible_mature' and status_class = 'closed'
        and elapsed_hours <= target_hours as int64) as target_numerator,
    target_eligibility_reason = 'missing_target' as is_missing_target,
    target_eligibility_reason = 'immature' as is_immature,
    target_eligibility_reason = 'invalid_outcome' as is_invalid_outcome,
    target_eligibility_reason = 'unknown_outcome' as is_unknown_outcome
from classified
