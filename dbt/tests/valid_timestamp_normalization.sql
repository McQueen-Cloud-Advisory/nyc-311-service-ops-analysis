select snapshot_id, request_id
from {{ ref('stg_requests') }}
where temporal_quality = 'valid'
  and (created_at is null or created_date is null
    or created_date != date(created_at, 'America/New_York')
    or (closed_at is not null and (closed_date is null or closed_date != date(closed_at, 'America/New_York')))
    or created_at > observed_at
    or (closed_at is not null and (closed_at < created_at or closed_at > observed_at)))
