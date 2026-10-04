-- Reviews per day and city, based on star ratings only (available for every review, no LLM
-- labels needed). Lets text-to-SQL spot spikes of unhappy customers, e.g. a jump in 1-2 star
-- reviews in one city on one day.
select
    review_date,
    city,
    count(*)                                        as reviews,
    count_if(rating <= 2)                           as negative_reviews,
    round(div0(count_if(rating <= 2), count(*)), 4) as negative_share,
    round(avg(rating), 2)                           as avg_rating
from {{ ref('stg_reviews') }}
group by 1, 2
