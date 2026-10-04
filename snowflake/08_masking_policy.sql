-- =====================================================================
-- Mask customer emails (PII) in the marts. Requires Snowflake Enterprise edition or higher:
-- on Standard edition CREATE MASKING POLICY fails with an "unsupported feature" error.
--
-- dbt re-creates MARTS.DIM_CUSTOMER on every run, which drops any policy attached by hand.
-- So this script only CREATES the policy; dbt attaches it after each build through a
-- post_hook in models/marts/dim_customer.sql, enabled with the dbt var pii_masking: true.
-- Safe to re-run.
-- =====================================================================
USE ROLE ACCOUNTADMIN;

CREATE SCHEMA IF NOT EXISTS ZOMATO.GOVERNANCE;   -- policies live apart from the data dbt rebuilds

CREATE MASKING POLICY IF NOT EXISTS ZOMATO.GOVERNANCE.EMAIL_MASK AS (val STRING) RETURNS STRING ->
  CASE
    WHEN IS_ROLE_IN_SESSION('ACCOUNTADMIN') OR IS_ROLE_IN_SESSION('DBT_ROLE') THEN val
    ELSE REGEXP_REPLACE(val, '^[^@]+', '*****')      -- jane.doe@example.com -> *****@example.com
  END
  COMMENT = 'Shows customer emails only to the pipeline (DBT_ROLE) and admins';

-- dbt (DBT_ROLE) attaches the policy in a post_hook, so it needs APPLY on it.
GRANT USAGE ON SCHEMA ZOMATO.GOVERNANCE TO ROLE DBT_ROLE;
GRANT APPLY ON MASKING POLICY ZOMATO.GOVERNANCE.EMAIL_MASK TO ROLE DBT_ROLE;

-- ---------------------------------------------------------------------
-- Next: set  pii_masking: true  in zomato/dbt_project.yml (vars) and run
--   dbt build --select dim_customer
-- Then check (the same query, two roles):
--   USE ROLE DBT_ROLE;        SELECT email FROM ZOMATO.MARTS.DIM_CUSTOMER LIMIT 3;  -- real emails
--   USE ROLE ANALYST_RO_ROLE; SELECT email FROM ZOMATO.MARTS.DIM_CUSTOMER LIMIT 3;  -- *****@domain
-- ---------------------------------------------------------------------
