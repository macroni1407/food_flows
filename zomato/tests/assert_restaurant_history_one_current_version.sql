-- Every restaurant must have exactly one current version in dim_restaurants_history,
-- and the same number of restaurants as stg_restaurants. Returns rows on failure.
select restaurant_id, count_if(is_current) as current_versions
from {{ ref('dim_restaurants_history') }}
group by restaurant_id
having count_if(is_current) != 1

union all

select null, abs((select count(distinct restaurant_id) from {{ ref('dim_restaurants_history') }})
               - (select count(*) from {{ ref('stg_restaurants') }}))
where (select count(distinct restaurant_id) from {{ ref('dim_restaurants_history') }})
   != (select count(*) from {{ ref('stg_restaurants') }})
