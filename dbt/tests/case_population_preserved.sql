with counts as (
    select
        (select count(*) from {{ ref('stg_requests') }} where snapshot_id = '{{ var("snapshot_id") }}') as source_rows,
        (select count(*) from {{ ref('fct_cases') }}) as case_rows
)
select * from counts where source_rows != case_rows
