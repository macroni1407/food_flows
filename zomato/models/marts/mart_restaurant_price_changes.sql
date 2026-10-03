-- One row per restaurant price change: orders and delivered revenue in the 7 days before vs after.
-- days_observed_after < 7 means the "after" window is still open (later days not loaded yet),
-- so compare per-day averages rather than raw totals for recent changes.
with history as (
    select restaurant_id, valid_from, cost_for_two,
           lag(cost_for_two) over (partition by restaurant_id order by valid_from) as previous_cost
    from {{ ref('dim_restaurants_history') }}
),

price_changes as (
    select restaurant_id, valid_from as changed_at,
           previous_cost as old_cost_for_two, cost_for_two as new_cost_for_two
    from history
    where previous_cost is not null and cost_for_two is distinct from previous_cost
),

last_order as (
    select max(order_timestamp) as max_order_ts from {{ ref('fct_orders') }}
)

select
    pc.restaurant_id, r.restaurant_name, r.city,
    pc.changed_at::date as changed_on,
    pc.old_cost_for_two, pc.new_cost_for_two,
    round(div0(pc.new_cost_for_two - pc.old_cost_for_two, pc.old_cost_for_two), 3) as price_change_pct,
    count_if(o.order_timestamp <  pc.changed_at) as orders_7d_before,
    count_if(o.order_timestamp >= pc.changed_at) as orders_7d_after,
    sum(iff(o.is_delivered and o.order_timestamp <  pc.changed_at, o.sales_amount, 0)) as revenue_7d_before,
    sum(iff(o.is_delivered and o.order_timestamp >= pc.changed_at, o.sales_amount, 0)) as revenue_7d_after,
    greatest(0, least(7, datediff(day, pc.changed_at, lo.max_order_ts) + 1)) as days_observed_after
from price_changes pc
cross join last_order lo
left join {{ ref('dim_restaurants') }} r on pc.restaurant_id = r.restaurant_id
left join {{ ref('fct_orders') }} o
       on o.restaurant_id = pc.restaurant_id
      and o.order_timestamp >= dateadd(day, -7, pc.changed_at)
      and o.order_timestamp <  dateadd(day,  7, pc.changed_at)
group by all
