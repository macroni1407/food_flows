{{ config(tags=['ai']) }}

-- One row per review with its restaurant and order context, for review search
-- (ai/agent/reviews.py). Filtering by city, date, stars or restaurant rating is a scan of this one
-- table instead of a join over millions of orders at question time, and the table lives in MARTS,
-- so the read-only ANALYST_RO_ROLE can query it. Tagged ai: built after the daily enrichment so it
-- carries the latest LLM labels.
--
-- Restaurant context: the version of the review's own restaurant in effect on the review date.
-- Order context: only when the review's order really belongs to that restaurant. In the original
-- dataset order_id and restaurant_id of a review are unrelated (random), so those reviews get NULL
-- order context; reviews from the daily generator are consistent and get it.
with enriched as (
    select review_id, sentiment_label, topic, key_issue
    from {{ source('ai', 'review_enriched') }}
    qualify row_number() over (partition by review_id order by enrichment_at desc) = 1
)

select
    r.review_id,
    r.review_date,
    r.city,
    r.rating,
    r.comment,
    r.comment_hash,
    r.restaurant_id,
    h.restaurant_name,
    h.cuisine,
    h.rating        as restaurant_rating_at_review,
    h.cost_for_two  as cost_for_two_at_review,
    o.order_id,
    o.order_date,
    o.sales_amount,
    o.delivery_time_min,
    o.payment_method,
    e.sentiment_label,
    e.topic,
    e.key_issue
from {{ ref('stg_reviews') }} r
left join {{ ref('dim_restaurants_history') }} h
       on h.restaurant_id = r.restaurant_id
      and r.review_date::timestamp_ntz >= h.valid_from
      and (r.review_date::timestamp_ntz < h.valid_to or h.valid_to is null)
left join {{ ref('fct_orders') }} o
       on o.order_id = r.order_id
      and o.restaurant_id = r.restaurant_id
left join enriched e
       on e.review_id = r.review_id
