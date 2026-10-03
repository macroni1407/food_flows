{{ config(materialized='view') }}

-- Each order with the restaurant attributes that were in effect WHEN it was placed
-- (point-in-time join on dim_restaurants_history), next to the restaurant's current values.
-- Joining fct_orders to dim_restaurants instead would show today's price on last month's orders.
select
    o.order_id, o.order_timestamp, o.order_date, o.restaurant_id, o.city,
    o.order_status, o.is_delivered, o.sales_amount,
    h.restaurant_version_key,
    h.cost_for_two  as cost_for_two_at_order,
    h.rating        as rating_at_order,
    cur.cost_for_two as cost_for_two_current,
    cur.rating       as rating_current
from {{ ref('fct_orders') }} o
left join {{ ref('dim_restaurants_history') }} h
       on o.restaurant_id = h.restaurant_id
      and o.order_timestamp >= h.valid_from
      and (o.order_timestamp < h.valid_to or h.valid_to is null)
left join {{ ref('dim_restaurants') }} cur
       on o.restaurant_id = cur.restaurant_id
