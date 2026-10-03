-- SCD2 history of the restaurant dimension: a new version is recorded whenever
-- rating, price, cuisine, name or city changes (dbt_valid_from / dbt_valid_to).
{% snapshot restaurants_snapshot %}

{{
    config(
        unique_key='restaurant_id',
        strategy='check',
        check_cols=['restaurant_name', 'city', 'cuisine', 'rating', 'rating_count', 'cost_for_two'],
    )
}}

select * from {{ ref('stg_restaurants') }}

{% endsnapshot %}
