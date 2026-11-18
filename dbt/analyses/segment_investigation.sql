-- Rank segments by observed open requests aged at least seven elapsed days.
-- This identifies a review priority, not a causal explanation or staffing need.
with segment_p90 as (
    select distinct agency_key, problem_key, borough_key,
        percentile_cont(if(is_p90_eligible, elapsed_hours, null), 0.9)
            over (partition by agency_key, problem_key, borough_key) as p90_elapsed_hours
    from {{ ref('fct_cases') }}
), cases as (
    select agency_key, problem_key, borough_key,
        countif(created_date is not null) as intake,
        countif(is_recorded_closure) as recorded_closures,
        countif(is_p90_eligible) as p90_eligible_count,
        sum(target_numerator) as target_numerator,
        sum(target_denominator) as target_denominator,
        countif(is_missing_target) as missing_target_cases,
        countif(is_invalid_outcome or is_unknown_outcome) as invalid_or_unknown_cases,
        countif(is_immature) as immature_cases
    from {{ ref('fct_cases') }}
    group by agency_key, problem_key, borough_key
)
select '{{ var("release_id") }}' as release_id,
    b.snapshot_id, b.observed_at, c.*, b.open_count, b.age_168h_plus_count, p.p90_elapsed_hours,
    safe_divide(c.target_numerator, c.target_denominator) as within_demo_target
from cases c
join {{ ref('fct_backlog') }} b using (agency_key, problem_key, borough_key)
left join segment_p90 p using (agency_key, problem_key, borough_key)
where b.is_release_snapshot
order by b.age_168h_plus_count desc, b.open_count desc, c.intake desc,
    c.agency_key, c.problem_key, c.borough_key
