select request_id, count(*) as row_count
from {{ ref('int_case_metrics') }}
group by request_id
having count(*) != 1
