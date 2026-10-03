-- parse the messy dimension (-- -> null, 50+ rating -> 50, ₹ 200 -> 200, city after comma -> city, etc)
-- One row per restaurant: the latest version wins (daily price / rating changes from the generator).

select 
    src.id::number as restaurant_id,
    src.name as restaurant_name,
    trim(coalesce(regexp_substr(src.city, '[^,]+$'), src.city)) as city,
    try_to_decimal(nullif(src.rating, '--'), 3, 1) as rating,
    try_to_number(regexp_substr(src.rating_count, '[0-9]+')) as rating_count,
    try_to_number(regexp_substr(src.cost, '[0-9]+')) as cost_for_two,
    src.cuisine, src.lic_no as license_no,
    src._source_file, {{ loaded_at('src') }} as _loaded_at
from {{ source('raw', 'restaurants') }} as src
where try_to_number(src.id) is not null
{{ dedup_latest('src.id', 'src') }}
