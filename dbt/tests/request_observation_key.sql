select snapshot_id, request_id, count(*) as row_count
from {{ ref('stg_requests') }}
group by snapshot_id, request_id
having count(*) != 1
