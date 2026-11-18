select snapshot_id, agency_key, problem_key, borough_key, count(*) as row_count
from {{ ref('fct_backlog') }}
group by snapshot_id, agency_key, problem_key, borough_key
having count(*) != 1
