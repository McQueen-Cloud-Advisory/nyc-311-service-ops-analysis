-- This gate is specific to labeled synthetic fixtures; real cohorts need not contain both.
{% if var('source_kind') in ['synthetic', 'fixture', 'synthetic_fixture'] %}
select
    countif(is_backlog and target_denominator = 1 and target_numerator = 0) as overdue_open_cases,
    countif(is_immature) as immature_cases
from {{ ref('fct_cases') }}
having overdue_open_cases = 0 or immature_cases = 0
{% else %}
select 1 as failure from unnest(array<int64>[])
{% endif %}
