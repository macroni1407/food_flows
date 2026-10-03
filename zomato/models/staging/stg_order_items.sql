select 
src.order_item_id, src.order_id, src.r_id as restaurant_id, src.f_id, src.price::decimal(10,2) as price,
src.quantity::number as quantity, src.line_amount::decimal(10,2) as line_amount,
src._source_file, {{ loaded_at('src') }} as _loaded_at
from {{ source('raw', 'order_items') }} as src
{{ dedup_latest('src.order_item_id', 'src') }}
