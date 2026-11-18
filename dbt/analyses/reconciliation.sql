-- dbt compile --select reconciliation --vars '<the release vars>'
-- Execute the compiled query with cache disabled and a maximum-bytes-billed limit.
-- This returns overall, a meaningful slice, an empty slice, and separate creation/
-- closure date roles. P90 is continuous interpolation over case rows.
with slices as (
    select 'overall' as slice, cast(null as string) as agency_filter,
        cast(null as string) as problem_filter, cast(null as string) as borough_filter
    union all select 'DSNY / Dirty Condition / BROOKLYN', 'DSNY', 'Dirty Condition', 'BROOKLYN'
    union all select 'empty', null, null, '__NO_SUCH_BOROUGH__'
), expanded as (
    select s.slice, c.*
    from slices s
    left join {{ ref('fct_cases') }} c
      on (s.agency_filter is null or c.agency_key = s.agency_filter)
     and (s.problem_filter is null or c.problem_key = s.problem_filter)
     and (s.borough_filter is null or c.borough_key = s.borough_filter)
), percentiles as (
    select distinct slice,
        percentile_cont(if(is_p90_eligible, elapsed_hours, null), 0.9) over (partition by slice) as p90_elapsed_hours
    from expanded
), totals as (
    select slice,
        count(request_id) as case_count,
        countif(created_date is not null) as intake,
        countif(is_recorded_closure) as recorded_closures,
        countif(is_backlog) as observed_backlog,
        coalesce(sum(target_numerator), 0) as target_numerator,
        coalesce(sum(target_denominator), 0) as target_denominator,
        safe_divide(sum(target_numerator), sum(target_denominator)) as target_rate,
        countif(is_p90_eligible) as p90_eligible_count,
        countif(is_missing_target) as missing_target_cases,
        countif(is_invalid_outcome) as invalid_outcome_cases,
        countif(is_unknown_outcome) as unknown_outcome_cases,
        countif(is_immature) as immature_cases
    from expanded group by slice
)
select '{{ var("release_id") }}' as release_id, '{{ var("snapshot_id") }}' as snapshot_id,
    totals.*, percentiles.p90_elapsed_hours
from totals left join percentiles using (slice)
order by slice
