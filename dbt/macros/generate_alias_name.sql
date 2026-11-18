{% macro generate_alias_name(custom_alias_name=none, node=none) -%}
  {%- set release_id = var('release_id', 'unconfigured') -%}
  {%- if not modules.re.match('^[a-z0-9_]{1,64}$', release_id) -%}
    {{ exceptions.raise_compiler_error('release_id must match ^[a-z0-9_]{1,64}$') }}
  {%- endif -%}
  {%- set base_name = custom_alias_name if custom_alias_name is not none else node.name -%}
  {{ base_name | trim }}__r_{{ release_id }}
{%- endmacro %}
