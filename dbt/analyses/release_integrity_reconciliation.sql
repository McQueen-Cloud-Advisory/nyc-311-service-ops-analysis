-- Matches section E of powerbi/reconciliation.dax.
select
    '{{ var("release_id") }}' as release_id,
    (select count(*) from {{ ref('release_metadata') }}) as release_rows,
    (select count(distinct release_id) from {{ ref('fct_cases') }}) as case_release_count,
    (select count(distinct snapshot_id) from {{ ref('fct_cases') }}) as case_snapshot_count,
    (select count(distinct snapshot_id) from {{ ref('fct_backlog') }} where is_release_snapshot) as backlog_snapshot_count,
    (select countif(is_backlog) from {{ ref('fct_cases') }}) as open_case_rows,
    (select coalesce(sum(open_count), 0) from {{ ref('fct_backlog') }} where is_release_snapshot) as observed_backlog
