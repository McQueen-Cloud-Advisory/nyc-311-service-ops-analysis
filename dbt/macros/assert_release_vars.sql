{% macro assert_release_vars() %}
  {% for name in ['release_id', 'snapshot_id', 'target_version', 'source_kind', 'scope_hash'] %}
    {% set value = var(name, 'unconfigured') %}
    {% if value == 'unconfigured' or not modules.re.match('^[A-Za-z0-9_.:-]{1,128}$', value) %}
      {{ exceptions.raise_compiler_error(name ~ ' must be configured using safe identifier characters') }}
    {% endif %}
  {% endfor %}
  {% if not modules.re.match('^[a-f0-9]{64}$', var('scope_hash')) %}
    {{ exceptions.raise_compiler_error('scope_hash must be the SHA-256 of the captured scope') }}
  {% endif %}
  {% if not modules.re.match('^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$', var('observed_at')) %}
    {{ exceptions.raise_compiler_error('observed_at must be an explicit UTC ISO timestamp') }}
  {% endif %}
  {% for name in ['cohort_start', 'cohort_end'] %}
    {% if not modules.re.match('^\d{4}-\d{2}-\d{2}$', var(name)) %}
      {{ exceptions.raise_compiler_error(name ~ ' must be an ISO local date') }}
    {% endif %}
  {% endfor %}
  {% if var('cohort_start') >= var('cohort_end') %}
    {{ exceptions.raise_compiler_error('cohort_start must be before exclusive cohort_end') }}
  {% endif %}
  {% for name in ['reconciliation_start', 'reconciliation_end'] %}
    {% if not modules.re.match('^\d{4}-\d{2}-\d{2}$', var(name, '2026-11-09')) %}
      {{ exceptions.raise_compiler_error(name ~ ' must be an ISO local date') }}
    {% endif %}
  {% endfor %}
  {% if not modules.re.match('^[A-Za-z_][A-Za-z0-9_]*$', var('raw_dataset')) %}
    {{ exceptions.raise_compiler_error('raw_dataset must be a BigQuery dataset identifier') }}
  {% endif %}
  {{ return('select 1 as release_configuration_valid') }}
{% endmacro %}
