-- One row per restaurant: its latest version (daily price / rating changes from the generator).
-- Parsing lives in stg_restaurant_versions.

select
    v.restaurant_id, v.restaurant_name, v.city, v.rating, v.rating_count, v.cost_for_two,
    v.cuisine, v.license_no,
    v._source_file, v._loaded_at
from {{ ref('stg_restaurant_versions') }} as v
{{ dedup_latest('v.restaurant_id', 'v') }}
