{{config(
    materialized='incremental',
    unique_key='order_id',
    incremental_strategy='merge',
    on_schema_change='append_new_columns'
)}}

-- Incremental on LOAD time, not order time: a late-arriving order or a status change has an old
-- order_timestamp but a new _loaded_at, so filtering on order_timestamp would silently drop it.
-- The lookback window re-reads recent loads; MERGE on order_id turns re-reads into updates.
select order_id, order_timestamp, order_date, customer_id, restaurant_id, city, cuisine,
       payment_method, order_status, is_delivered, items_count, sales_qty, subtotal, discount,
       delivery_fee, gst, sales_amount, customer_rating, delivery_time_min,
       _source_file, _loaded_at
from {{ ref('stg_orders') }}

{% if is_incremental() %}
    where _loaded_at > (
        select dateadd(day, -{{ var('lookback_days') }}, coalesce(max(_loaded_at), '1900-01-01'::timestamp_ltz))
        from {{ this }}
    )
{% endif %}
