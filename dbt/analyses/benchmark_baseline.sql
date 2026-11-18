-- The runner must create this candidate-only unpartitioned copy before executing:
-- CREATE TABLE `<project>.nyc311_work.benchmark_baseline__r_<release_id>` AS
-- SELECT * FROM `<project>.nyc311_work.fct_cases__r_<release_id>`;
-- Do not publish the baseline table. Copy setup costs are separate from query costs.
select agency_key, problem_key, borough_key,
    count(*) as request_count,
    sum(target_numerator) as target_numerator,
    sum(target_denominator) as target_denominator
from `{{ target.project }}.{{ target.schema }}.benchmark_baseline__r_{{ var("release_id") }}`
where created_date >= date('{{ var("cohort_start") }}')
  and created_date < date_add(date('{{ var("cohort_start") }}'), interval 7 day)
  and borough_key = 'BROOKLYN'
group by agency_key, problem_key, borough_key
order by agency_key, problem_key, borough_key
