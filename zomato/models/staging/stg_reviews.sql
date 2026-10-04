select
r.review_id,
r.order_id,
r.user_id::number as customer_id,
r.restaurant_id::number as restaurant_id,
r.rating::number as rating,
r.comment::string as comment,
sha2(r.comment::string, 256) as comment_hash,   -- key of AI.REVIEW_EMBEDDINGS (one vector per distinct text)
r.review_date::DATE as review_date,
res.city as city,
r._source_file,
{{ loaded_at('r') }} as _loaded_at
from {{ source('raw', 'reviews') }} r
left join {{ ref('stg_restaurants') }} res on r.restaurant_id = res.restaurant_id
where r.comment is not null
{{ dedup_latest('r.review_id', 'r') }}
