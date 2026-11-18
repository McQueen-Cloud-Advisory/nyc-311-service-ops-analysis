select a.agency_key, a.problem_key, a.target_key as first_target, b.target_key as second_target
from {{ ref('stg_targets') }} a
inner join {{ ref('stg_targets') }} b
  on a.agency_key = b.agency_key and a.problem_key = b.problem_key
 and a.target_key < b.target_key
 and a.effective_start < coalesce(b.effective_end, date '9999-12-31')
 and b.effective_start < coalesce(a.effective_end, date '9999-12-31')
