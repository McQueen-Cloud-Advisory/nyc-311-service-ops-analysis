-- Compare against an UNPARTITIONED, UNCLUSTERED copy with identical rows.
-- Query cache must be disabled for both; record job bytes, result hash, and scope.
-- Inputs are the first seven days of the pinned cohort and Brooklyn.
select agency_key, problem_key, borough_key,
    count(*) as request_count,
    sum(target_numerator) as target_numerator,
    sum(target_denominator) as target_denominator
from {{ ref('fct_cases') }}
where created_date >= date('{{ var("cohort_start") }}')
  and created_date < date_add(date('{{ var("cohort_start") }}'), interval 7 day)
  and borough_key = 'BROOKLYN'
group by agency_key, problem_key, borough_key
order by agency_key, problem_key, borough_key
