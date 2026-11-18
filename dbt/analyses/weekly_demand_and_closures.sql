-- Creation and closure date series are separate event counts from the fixed cohort.
with created as (
    select date_trunc(created_date, week(monday)) as week_start,
        agency_key, problem_key, borough_key, count(*) as intake
    from {{ ref('fct_cases') }}
    where created_date is not null
    group by week_start, agency_key, problem_key, borough_key
), closed as (
    select date_trunc(closed_date, week(monday)) as week_start,
        agency_key, problem_key, borough_key, count(*) as recorded_closures
    from {{ ref('fct_cases') }}
    where is_recorded_closure
    group by week_start, agency_key, problem_key, borough_key
)
select '{{ var("release_id") }}' as release_id,
    week_start, agency_key, problem_key, borough_key,
    coalesce(intake, 0) as intake, coalesce(recorded_closures, 0) as recorded_closures
from created full outer join closed using (week_start, agency_key, problem_key, borough_key)
order by week_start, agency_key, problem_key, borough_key
