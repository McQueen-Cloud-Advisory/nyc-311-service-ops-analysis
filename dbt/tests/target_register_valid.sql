select * from {{ ref('stg_targets') }}
where target_hours <= 0
   or (effective_end is not null and effective_end <= effective_start)
   or agency_key = 'UNKNOWN' or problem_key = 'UNKNOWN'
