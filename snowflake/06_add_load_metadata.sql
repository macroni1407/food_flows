-- =====================================================================
-- Adds two columns to every RAW table:
--   _source_file : stage path of the file a row came from (METADATA$FILENAME)
--   _loaded_at   : when the COPY that loaded the row started (METADATA$START_SCAN_TIME)
-- Rows loaded before this change keep NULL in both columns; staging handles that.
-- Fresh setups get the columns directly from 04_raw_tables.sql, so they can skip this.
-- Safe to re-run: ADD COLUMN IF NOT EXISTS.
-- =====================================================================
USE ROLE ACCOUNTADMIN;
USE DATABASE ZOMATO;
USE SCHEMA RAW;

ALTER TABLE RAW.restaurants ADD COLUMN IF NOT EXISTS _source_file STRING;
ALTER TABLE RAW.restaurants ADD COLUMN IF NOT EXISTS _loaded_at   TIMESTAMP_LTZ;

ALTER TABLE RAW.users       ADD COLUMN IF NOT EXISTS _source_file STRING;
ALTER TABLE RAW.users       ADD COLUMN IF NOT EXISTS _loaded_at   TIMESTAMP_LTZ;

ALTER TABLE RAW.food        ADD COLUMN IF NOT EXISTS _source_file STRING;
ALTER TABLE RAW.food        ADD COLUMN IF NOT EXISTS _loaded_at   TIMESTAMP_LTZ;

ALTER TABLE RAW.menu        ADD COLUMN IF NOT EXISTS _source_file STRING;
ALTER TABLE RAW.menu        ADD COLUMN IF NOT EXISTS _loaded_at   TIMESTAMP_LTZ;

ALTER TABLE RAW.orders      ADD COLUMN IF NOT EXISTS _source_file STRING;
ALTER TABLE RAW.orders      ADD COLUMN IF NOT EXISTS _loaded_at   TIMESTAMP_LTZ;

ALTER TABLE RAW.order_items ADD COLUMN IF NOT EXISTS _source_file STRING;
ALTER TABLE RAW.order_items ADD COLUMN IF NOT EXISTS _loaded_at   TIMESTAMP_LTZ;

ALTER TABLE RAW.reviews     ADD COLUMN IF NOT EXISTS _source_file STRING;
ALTER TABLE RAW.reviews     ADD COLUMN IF NOT EXISTS _loaded_at   TIMESTAMP_LTZ;

-- Check: every table should list _SOURCE_FILE and _LOADED_AT as its last two columns.
SELECT table_name, column_name, data_type
FROM ZOMATO.INFORMATION_SCHEMA.COLUMNS
WHERE table_schema = 'RAW' AND column_name IN ('_SOURCE_FILE', '_LOADED_AT')
ORDER BY table_name, column_name;
