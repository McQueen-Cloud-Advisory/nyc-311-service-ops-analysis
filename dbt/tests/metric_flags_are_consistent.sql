select request_id, target_eligibility_reason
from {{ ref('fct_cases') }}
where target_numerator > target_denominator
   or (target_denominator = 1 and (target_hours is null or age_hours < target_hours or temporal_quality != 'valid'))
   or (target_numerator = 1 and (status_class != 'closed' or elapsed_hours > target_hours or elapsed_hours is null))
   or target_denominator + cast(is_immature as int64) + cast(is_missing_target as int64)
        + cast(is_invalid_outcome as int64) + cast(is_unknown_outcome as int64) != 1
   or is_p90_eligible != is_recorded_closure
   or (is_recorded_closure and (closed_at is null or created_at is null or closed_at < created_at or closed_at > observed_at))
   or (elapsed_hours is not null and elapsed_hours < 0)
   or (age_hours is not null and age_hours < 0)
