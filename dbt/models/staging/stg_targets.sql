select
    target_version,
    coalesce(nullif(upper(trim(agency)), ''), 'UNKNOWN') as agency_key,
    coalesce(nullif(trim(problem), ''), 'UNKNOWN') as problem_key,
    effective_start,
    effective_end,
    target_hours,
    to_hex(sha256(to_json_string(struct(
        target_version, upper(trim(agency)), trim(problem), effective_start, effective_end, target_hours
    )))) as target_key
from {{ source('raw', 'targets') }}
where target_version = '{{ var("target_version") }}'
