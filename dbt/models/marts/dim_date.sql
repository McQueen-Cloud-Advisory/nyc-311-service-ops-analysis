with bounds as (
    select date('{{ var("cohort_start") }}') as first_date,
        greatest(date(timestamp('{{ var("observed_at") }}'), 'America/New_York'),
            date_sub(date('{{ var("cohort_end") }}'), interval 1 day)) as last_date
)
select
    '{{ var("release_id") }}' as release_id,
    d as date_key,
    extract(year from d) as year,
    extract(month from d) as month,
    format_date('%B', d) as month_name,
    date_trunc(d, week(monday)) as week_start
from bounds, unnest(generate_date_array(first_date, last_date)) d
