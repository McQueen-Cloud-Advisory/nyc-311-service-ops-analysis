-- Unknown/Unspecified and blank values remain visible as excluded outcomes.
-- A new nonempty source vocabulary blocks publication until its meaning is reviewed.
select distinct normalized_status
from {{ ref('stg_requests') }}
where normalized_status not in (
    'closed', 'open', 'assigned', 'in progress', 'pending', 'started',
    '', 'unknown', 'unspecified'
)
