-- Match the Date slicer in Power BI to this half-open local-date interval.
-- Optional vars reconciliation_start/end default to the final full cohort week,
-- matching the checked-in Power BI DAX reconciliation query.
with bounds as (
    select date('{{ var("reconciliation_start", "2026-11-09") }}') as from_date,
           date('{{ var("reconciliation_end", "2026-11-16") }}') as to_date
), created_slice as (
    select c.* from {{ ref('fct_cases') }} c cross join bounds b
    where c.created_date >= b.from_date and c.created_date < b.to_date
), closure_slice as (
    select c.* from {{ ref('fct_cases') }} c cross join bounds b
    where c.is_p90_eligible and c.closed_date >= b.from_date and c.closed_date < b.to_date
), p90 as (
    select percentile_cont(elapsed_hours, 0.9) over () as value from closure_slice
)
select '{{ var("release_id") }}' as release_id,
    (select count(*) from created_slice) as intake_creation_slice,
    (select count(*) from closure_slice) as closures_closure_slice,
    (select coalesce(sum(target_numerator), 0) from created_slice) as target_numerator_creation_slice,
    (select coalesce(sum(target_denominator), 0) from created_slice) as target_denominator_creation_slice,
    (select count(*) from closure_slice) as p90_eligible_closure_slice,
    (select value from p90 limit 1) as p90_hours_closure_slice,
    (select coalesce(sum(open_count), 0) from {{ ref('fct_backlog') }} where is_release_snapshot) as backlog_observation,
    (select coalesce(sum(open_count), 0) from {{ ref('fct_backlog') }} where is_release_snapshot) as backlog_without_period
