-- Reconciliation: every RAW order item whose order exists must be in fct_order_items,
-- with the same total line amount. Returns a row (= test failure) on any drift.
with raw_items as (
    select src.order_item_id, src.line_amount
    from {{ source('raw', 'order_items') }} as src
    where src.order_id in (select order_id from {{ source('raw', 'orders') }})
    {{ dedup_latest('src.order_item_id', 'src') }}
),
raw_totals as (select count(*) as items, sum(line_amount) as amount from raw_items),
fct_totals as (select count(*) as items, sum(line_amount) as amount from {{ ref('fct_order_items') }})
select r.items as raw_items, f.items as fct_items, r.amount as raw_amount, f.amount as fct_amount
from raw_totals r cross join fct_totals f
where r.items != f.items or r.amount != f.amount
