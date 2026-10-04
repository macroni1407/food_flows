-- =====================================================================
-- Read-only role for the text-to-SQL app (ai/text_to_sql.py)
-- The SQL that app runs is written by an LLM. Under this role Snowflake itself refuses
-- anything but SELECT on the MARTS schema, so a DROP / DELETE / UPDATE that slips past the
-- keyword check in the app still cannot change or read anything else.
-- Safe to re-run.
-- =====================================================================
USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS ANALYST_RO_ROLE
  COMMENT = 'Read-only access to ZOMATO.MARTS (text-to-SQL, analysts)';

GRANT USAGE ON WAREHOUSE ZOMATO_WH   TO ROLE ANALYST_RO_ROLE;
GRANT USAGE ON DATABASE  ZOMATO      TO ROLE ANALYST_RO_ROLE;
GRANT USAGE ON SCHEMA    ZOMATO.MARTS TO ROLE ANALYST_RO_ROLE;

GRANT SELECT ON ALL TABLES IN SCHEMA ZOMATO.MARTS TO ROLE ANALYST_RO_ROLE;
GRANT SELECT ON ALL VIEWS  IN SCHEMA ZOMATO.MARTS TO ROLE ANALYST_RO_ROLE;

-- dbt re-creates most mart tables on every run; future grants cover the new objects.
-- Note: schema-level future grants take precedence over the database-level ones from
-- 01_setup.sql for this schema. That is fine here: dbt (DBT_ROLE) creates and therefore owns
-- every object in MARTS, so it does not rely on those database-level grants.
GRANT SELECT ON FUTURE TABLES IN SCHEMA ZOMATO.MARTS TO ROLE ANALYST_RO_ROLE;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA ZOMATO.MARTS TO ROLE ANALYST_RO_ROLE;

-- Review search (ai/agent/reviews.py) also reads the embeddings in schema AI.
-- Tables there are created by the pipeline role (embeddings, enrichment, agent logs); none is sensitive.
-- As for MARTS, the schema-level future grant overrides the database-level one for AI; fine because
-- the pipeline role (DBT_ROLE) creates, and so owns, the tables in AI.
GRANT USAGE  ON SCHEMA ZOMATO.AI TO ROLE ANALYST_RO_ROLE;
GRANT SELECT ON ALL TABLES    IN SCHEMA ZOMATO.AI TO ROLE ANALYST_RO_ROLE;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ZOMATO.AI TO ROLE ANALYST_RO_ROLE;

-- Let your login use the role.
SET my_user = CURRENT_USER();
GRANT ROLE ANALYST_RO_ROLE TO USER IDENTIFIER($my_user);

-- ---------------------------------------------------------------------
-- Check (run as the new role):
USE ROLE ANALYST_RO_ROLE;
USE WAREHOUSE ZOMATO_WH;
SELECT COUNT(*) FROM ZOMATO.MARTS.FCT_ORDERS;          -- works
-- Each of these must FAIL (run them one by one to see the errors):
-- SELECT COUNT(*) FROM ZOMATO.RAW.ORDERS;             -- no access to RAW
-- INSERT INTO ZOMATO.AI.AGENT_LOGS (log_id) SELECT 'x'; -- read-only in AI too
-- DELETE FROM ZOMATO.MARTS.FCT_ORDERS WHERE 1 = 0;    -- insufficient privileges
-- DROP TABLE ZOMATO.MARTS.DIM_DATE;                   -- insufficient privileges
USE ROLE ACCOUNTADMIN;
