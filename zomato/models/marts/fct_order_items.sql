{{ config(materialized='incremental', unique_key='order_item_id', incremental_strategy='merge', on_schema_change='append_new_columns') }}

-- Incremental on the item's load time with a lookback window (see fct_orders.sql).
select oi.order_item_id, oi.order_id, oi.restaurant_id, oi.f_id, o.order_timestamp as order_ts,
       o.order_date, o.city, oi.price, oi.quantity, oi.line_amount,
       oi._source_file, oi._loaded_at
from {{ ref('stg_order_items') }} oi
inner join {{ ref('stg_orders') }} o using (order_id)

{% if is_incremental() %}
  where oi._loaded_at > (
      select dateadd(day, -{{ var('lookback_days') }}, coalesce(max(_loaded_at), '1900-01-01'::timestamp_ltz))
      from {{ this }}
  )
{% endif %}
