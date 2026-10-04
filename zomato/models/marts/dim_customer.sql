-- The table is re-created on every run, so the email masking policy is re-attached after each
-- build. Enable it with the var pii_masking once snowflake/08_masking_policy.sql has been run
-- (needs Snowflake Enterprise edition). An empty hook is skipped by dbt.
{{ config(post_hook=[
    "{% if var('pii_masking') %}alter table {{ this }} modify column email set masking policy ZOMATO.GOVERNANCE.EMAIL_MASK force{% endif %}"
]) }}

select
customer_id,
customer_name,
email,
age,
CASE WHEN age < 25 THEN 'Gen Z'
     WHEN age >= 25 AND age < 40 THEN 'Millennial'
     WHEN age >= 40 AND age < 55 THEN 'Gen X'
     WHEN age is null THEN 'Unknown'
     ELSE 'Boomer' END AS age_segment,
gender,
marital_status,
occupation,
income_band,
education,
family_size
from {{ ref('stg_users') }}