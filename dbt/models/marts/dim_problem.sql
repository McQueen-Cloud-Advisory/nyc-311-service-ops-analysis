select '{{ var("release_id") }}' as release_id, problem_key, problem_key as problem
from (
    select distinct problem_key from {{ ref('stg_requests') }}
    union distinct select 'UNKNOWN'
)
