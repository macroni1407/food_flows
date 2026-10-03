-- One row per order: the latest version wins (an order re-sent later, e.g. Delivered -> Refunded,
-- replaces the earlier one). See macros/load_metadata.sql.
select src.order_id, src.order_timestamp, src.order_date, src.user_id as customer_id, src.r_id as restaurant_id,
    trim(coalesce(regexp_substr(src.restaurant_city, '[^,]+$'), src.restaurant_city)) as city,
    src.cuisine, src.items_count, src.sales_qty, src.subtotal, src.discount, src.delivery_fee, src.gst, src.sales_amount,
    src.currency, src.payment_method, src.order_status, (src.order_status='Delivered') as is_delivered,
    src.customer_rating, src.delivery_time_min,
    src._source_file, {{ loaded_at('src') }} as _loaded_at
from {{ source('raw', 'orders') }} as src
{{ dedup_latest('src.order_id', 'src') }}
