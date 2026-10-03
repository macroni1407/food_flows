{#
  Helpers for the load-metadata columns added to RAW in snowflake/06_add_load_metadata.sql.

  Rows loaded before those columns existed have NULL _source_file / _loaded_at; they are
  treated as the initial load (var initial_load_at).
#}

{% macro loaded_at(alias) -%}
    coalesce({{ alias }}._loaded_at, to_timestamp_ltz('{{ var("initial_load_at") }}'))
{%- endmacro %}


{# The day a file belongs to, from its dt=YYYY-MM-DD folder (NULL for the initial load). #}
{% macro file_date(alias) -%}
    try_to_date(regexp_substr({{ alias }}._source_file, 'dt=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1, 1, 'e', 1))
{%- endmacro %}


{#
  Keep only the latest version of each key. "Latest" is decided by the date of the file's
  dt= folder first, then by load time, so a re-loaded or back-filled older day can never
  override a newer one. Rows from the initial load (no dt= folder) rank last.
#}
{% macro dedup_latest(key, alias) -%}
    qualify row_number() over (
        partition by {{ key }}
        order by {{ file_date(alias) }} desc nulls last,
                 {{ alias }}._loaded_at desc nulls last
    ) = 1
{%- endmacro %}
