with normalized as (
    select
        r.snapshot_id,
        r.request_id,
        r.created_date as source_created_date,
        r.closed_date as source_closed_date,
        r.created_at,
        r.closed_at,
        r.created_local_date as created_date,
        r.closed_local_date as closed_date,
        coalesce(nullif(r.temporal_quality, ''), 'unknown') as temporal_quality,
        coalesce(nullif(trim(r.status), ''), 'Unknown') as status,
        lower(trim(coalesce(r.status, ''))) as normalized_status,
        coalesce(nullif(upper(trim(r.agency)), ''), 'UNKNOWN') as agency_key,
        coalesce(nullif(trim(r.problem), ''), 'UNKNOWN') as problem_key,
        case when upper(trim(r.borough)) in ('BRONX', 'BROOKLYN', 'MANHATTAN', 'QUEENS', 'STATEN ISLAND')
            then upper(trim(r.borough)) else 'UNKNOWN' end as borough_key,
        coalesce(nullif(trim(r.channel), ''), 'UNKNOWN') as channel,
        r.payload_hash,
        o.observed_at,
        o.source_kind
    from {{ source('raw', 'observation_requests') }} r
    inner join {{ ref('stg_observations') }} o using (snapshot_id)
)
select *,
    case
        when normalized_status = 'closed' then 'closed'
        when normalized_status in ('open', 'assigned', 'in progress', 'pending', 'started') then 'open'
        else 'unknown'
    end as status_class
from normalized
