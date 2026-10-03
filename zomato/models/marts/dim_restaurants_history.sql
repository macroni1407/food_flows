-- Event-time SCD2 history of restaurants, rebuilt from RAW on every run.
-- valid_from is the day a change belongs to (the dt= folder of its file), not the time dbt ran,
-- so an order can be joined to the version that was in effect when it was placed. The original
-- load has no dt= folder and is treated as valid since the beginning of time.
-- (restaurants_snapshot is the processing-time view instead: when the warehouse saw a change.)
with versions as (
    select
        restaurant_id, restaurant_name, city, cuisine, rating, rating_count, cost_for_two, _source_file,
        coalesce(_file_date::timestamp_ntz, '1900-01-01'::timestamp_ntz) as valid_from,
        hash(restaurant_name, city, cuisine, rating, rating_count, cost_for_two) as row_hash
    from {{ ref('stg_restaurant_versions') }}
),

changes as (
    -- drop versions that repeat the previous values (e.g. a price that rounds back to the same)
    select * from versions
    qualify row_hash is distinct from lag(row_hash) over (partition by restaurant_id order by valid_from)
)

select
    restaurant_id || '-' || to_char(valid_from, 'YYYYMMDD') as restaurant_version_key,
    restaurant_id, restaurant_name, city, cuisine, rating, rating_count, cost_for_two,
    valid_from,
    lead(valid_from) over (partition by restaurant_id order by valid_from) as valid_to,
    lead(valid_from) over (partition by restaurant_id order by valid_from) is null as is_current,
    _source_file
from changes
