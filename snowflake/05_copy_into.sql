-- =====================================================================
-- Loads the plain CSVs you uploaded to each raw/<table>/ folder. The header
-- row is skipped by the file format (SKIP_HEADER=1), and rows load by position.
-- =====================================================================
USE ROLE ACCOUNTADMIN;
USE DATABASE ZOMATO;
USE SCHEMA RAW;
USE WAREHOUSE ZOMATO_WH;

-- Each COPY selects the CSV columns by position ($1, $2, ...) and adds two load-metadata
-- columns: _source_file (which file the row came from) and _loaded_at (when it was loaded).
-- Snowflake remembers which files were already loaded into a table and skips them.

-- Dimensions = messy real source data -> tolerate & skip bad rows (CONTINUE).
COPY INTO RAW.restaurants (_idx, id, name, city, rating, rating_count, cost, cuisine, lic_no, link, address, menu, _source_file, _loaded_at)
  FROM (SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, METADATA$FILENAME, METADATA$START_SCAN_TIME
        FROM @ZOMATO_RAW_STAGE/restaurants/)
  ON_ERROR = 'CONTINUE';
COPY INTO RAW.users (_idx, user_id, name, email, password, age, gender, marital_status, occupation, monthly_income, education, family_size, _source_file, _loaded_at)
  FROM (SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, METADATA$FILENAME, METADATA$START_SCAN_TIME
        FROM @ZOMATO_RAW_STAGE/users/)
  ON_ERROR = 'CONTINUE';
COPY INTO RAW.food (_idx, f_id, item, veg_or_non_veg, _source_file, _loaded_at)
  FROM (SELECT $1, $2, $3, $4, METADATA$FILENAME, METADATA$START_SCAN_TIME
        FROM @ZOMATO_RAW_STAGE/food/)
  ON_ERROR = 'CONTINUE';
COPY INTO RAW.menu (_idx, menu_id, r_id, f_id, cuisine, price, _source_file, _loaded_at)
  FROM (SELECT $1, $2, $3, $4, $5, $6, METADATA$FILENAME, METADATA$START_SCAN_TIME
        FROM @ZOMATO_RAW_STAGE/menu/)
  ON_ERROR = 'CONTINUE';

-- Facts = clean generated data -> stay strict so counts are exact.
COPY INTO RAW.orders (order_id, order_timestamp, order_date, user_id, r_id, restaurant_city, cuisine, items_count, sales_qty, subtotal, discount, delivery_fee, gst, sales_amount, currency, payment_method, order_status, customer_rating, delivery_time_min, _source_file, _loaded_at)
  FROM (SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, METADATA$FILENAME, METADATA$START_SCAN_TIME
        FROM @ZOMATO_RAW_STAGE/orders/)
  ON_ERROR = 'ABORT_STATEMENT';
COPY INTO RAW.order_items (order_item_id, order_id, r_id, f_id, price, quantity, line_amount, _source_file, _loaded_at)
  FROM (SELECT $1, $2, $3, $4, $5, $6, $7, METADATA$FILENAME, METADATA$START_SCAN_TIME
        FROM @ZOMATO_RAW_STAGE/order_items/)
  ON_ERROR = 'ABORT_STATEMENT';
COPY INTO RAW.reviews (review_id, order_id, user_id, restaurant_id, rating, comment, review_date, _source_file, _loaded_at)
  FROM (SELECT $1, $2, $3, $4, $5, $6, $7, METADATA$FILENAME, METADATA$START_SCAN_TIME
        FROM @ZOMATO_RAW_STAGE/reviews/)
  ON_ERROR = 'ABORT_STATEMENT';

-- Sanity check.
SELECT 'restaurants' t, COUNT(*) n FROM RAW.restaurants
UNION ALL SELECT 'users',       COUNT(*) FROM RAW.users
UNION ALL SELECT 'food',        COUNT(*) FROM RAW.food
UNION ALL SELECT 'menu',        COUNT(*) FROM RAW.menu
UNION ALL SELECT 'orders',      COUNT(*) FROM RAW.orders
UNION ALL SELECT 'order_items', COUNT(*) FROM RAW.order_items
UNION ALL SELECT 'reviews',     COUNT(*) FROM RAW.reviews
ORDER BY t;
-- Expect: orders = 10,000,000 · order_items ≈ 23,000,000 · restaurants ≈ 148,541 ...

-- ---------------------------------------------------------------------
-- OPTIONAL — auto-ingest new files with Snowpipe (teach this on camera):
-- CREATE PIPE RAW.orders_pipe AUTO_INGEST = TRUE AS
--   COPY INTO RAW.orders FROM @ZOMATO_RAW_STAGE/orders/;
-- then wire the pipe's SQS ARN to an S3 event notification.
-- ---------------------------------------------------------------------
