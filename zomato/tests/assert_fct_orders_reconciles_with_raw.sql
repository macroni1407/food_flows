-- Reconciliation: fct_orders must hold exactly the latest version of every order in RAW.
-- Returns a row (= test failure) when order count, delivered GMV or refunded count drift,
-- e.g. late-arriving orders or status changes missed by the incremental filter.
with raw_latest as (
    select src.order_id, src.order_status, src.sales_amount
    from {{ source('raw', 'orders') }} as src
    {{ dedup_latest('src.order_id', 'src') }}
),
raw_totals as (
    select count(*)                                                as orders,
           sum(iff(order_status = 'Delivered', sales_amount, 0))  as delivered_gmv,
           count_if(order_status = 'Refunded')                     as refunded
    from raw_latest
),
fct_totals as (
    select count(*)                                                as orders,
           sum(iff(is_delivered, sales_amount, 0))                 as delivered_gmv,
           count_if(order_status = 'Refunded')                     as refunded
    from {{ ref('fct_orders') }}
)
select r.orders as raw_orders, f.orders as fct_orders,
       r.delivered_gmv as raw_delivered_gmv, f.delivered_gmv as fct_delivered_gmv,
       r.refunded as raw_refunded, f.refunded as fct_refunded
from raw_totals r cross join fct_totals f
where r.orders != f.orders
   or r.delivered_gmv != f.delivered_gmv
   or r.refunded != f.refunded
