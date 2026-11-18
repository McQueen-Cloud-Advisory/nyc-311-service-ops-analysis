with checked as (
    select count(*) as metadata_rows,
        countif(snapshot_id = '{{ var("snapshot_id") }}'
            and observed_at = timestamp('{{ var("observed_at") }}')
            and target_version = '{{ var("target_version") }}'
            and expected_count = source_count
            and source_count = (select count(*) from {{ ref('fct_cases') }})
            and extraction_started_at <= extraction_ended_at
            and observed_at = extraction_ended_at
        ) as valid_rows
    from {{ ref('release_metadata') }}
)
select * from checked where metadata_rows != 1 or valid_rows != 1
