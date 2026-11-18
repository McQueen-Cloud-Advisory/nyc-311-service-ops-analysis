select '{{ var("release_id") }}' as release_id, agency_key, agency_key as agency
from (
    select distinct agency_key from {{ ref('stg_requests') }}
    union distinct select 'UNKNOWN'
)
