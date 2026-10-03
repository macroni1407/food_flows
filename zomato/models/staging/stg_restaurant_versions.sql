-- Every version of every restaurant ever loaded: the original load plus each daily change file.
-- parse the messy dimension (-- -> null, 50+ rating -> 50, ₹ 200 -> 200, city after comma -> city, etc)
-- stg_restaurants keeps only the latest version; dim_restaurants_history turns them into SCD2 ranges.

select 
    src.id::number as restaurant_id,
    src.name as restaurant_name,
    trim(coalesce(regexp_substr(src.city, '[^,]+$'), src.city)) as city,
    try_to_decimal(nullif(src.rating, '--'), 3, 1) as rating,
    try_to_number(regexp_substr(src.rating_count, '[0-9]+')) as rating_count,
    try_to_number(regexp_substr(src.cost, '[0-9]+')) as cost_for_two,
    src.cuisine, src.lic_no as license_no,
    {{ file_date('src') }} as _file_date,
    src._source_file, {{ loaded_at('src') }} as _loaded_at
from {{ source('raw', 'restaurants') }} as src
where try_to_number(src.id) is not null
-- one version per restaurant per file day (guards against the same day being loaded twice)
qualify row_number() over (
    partition by src.id, {{ file_date('src') }}
    order by src._loaded_at desc nulls last
) = 1
