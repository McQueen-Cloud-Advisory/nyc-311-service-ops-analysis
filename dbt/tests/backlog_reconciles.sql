with aggregates as (
    select
        (select countif(is_backlog) from {{ ref('fct_cases') }}) as case_open,
        (select coalesce(sum(open_count), 0) from {{ ref('fct_backlog') }} where is_release_snapshot) as backlog_open,
        (select count(*) from {{ ref('fct_backlog') }}
            where open_count != age_under_24h_count + age_24_to_72h_count
                + age_72_to_168h_count + age_168h_plus_count + age_unknown_count) as invalid_buckets
)
select * from aggregates where case_open != backlog_open or invalid_buckets != 0
