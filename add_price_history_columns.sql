-- SQL Migration: Add price history tracking to properties_romania table
-- Run this against your PostgreSQL database

-- Add columns for price history tracking
ALTER TABLE properties_romania
ADD COLUMN IF NOT EXISTS price_history JSONB DEFAULT '[]'::jsonb,
ADD COLUMN IF NOT EXISTS previous_price_ron DECIMAL(12,2),
ADD COLUMN IF NOT EXISTS previous_price_eur DECIMAL(12,2),
ADD COLUMN IF NOT EXISTS price_change_ron DECIMAL(12,2),
ADD COLUMN IF NOT EXISTS price_change_eur DECIMAL(12,2),
ADD COLUMN IF NOT EXISTS price_change_percentage DECIMAL(5,2),
ADD COLUMN IF NOT EXISTS price_last_changed TIMESTAMP,
ADD COLUMN IF NOT EXISTS price_change_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS price_drop_alert BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS highest_price_ron DECIMAL(12,2),
ADD COLUMN IF NOT EXISTS lowest_price_ron DECIMAL(12,2);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_properties_romania_price_change
ON properties_romania(price_change_percentage)
WHERE price_change_percentage IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_properties_romania_price_drop_alert
ON properties_romania(price_drop_alert)
WHERE price_drop_alert = TRUE;

CREATE INDEX IF NOT EXISTS idx_properties_romania_price_last_changed
ON properties_romania(price_last_changed);

-- Create a function to analyze price history
CREATE OR REPLACE FUNCTION get_price_trend(p_fingerprint VARCHAR)
RETURNS TABLE(
    current_price DECIMAL(12,2),
    previous_price DECIMAL(12,2),
    highest_price DECIMAL(12,2),
    lowest_price DECIMAL(12,2),
    total_changes INTEGER,
    last_change_date TIMESTAMP,
    change_percentage DECIMAL(5,2),
    trend VARCHAR(20)
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        price_ron as current_price,
        previous_price_ron as previous_price,
        highest_price_ron as highest_price,
        lowest_price_ron as lowest_price,
        price_change_count as total_changes,
        price_last_changed as last_change_date,
        price_change_percentage as change_percentage,
        CASE
            WHEN price_change_percentage < -10 THEN 'MAJOR_DROP'
            WHEN price_change_percentage < -5 THEN 'PRICE_DROP'
            WHEN price_change_percentage < 0 THEN 'MINOR_DROP'
            WHEN price_change_percentage > 10 THEN 'MAJOR_INCREASE'
            WHEN price_change_percentage > 5 THEN 'PRICE_INCREASE'
            WHEN price_change_percentage > 0 THEN 'MINOR_INCREASE'
            ELSE 'STABLE'
        END as trend
    FROM properties_romania
    WHERE fingerprint = p_fingerprint;
END;
$$ LANGUAGE plpgsql;

-- View for properties with recent price drops
CREATE OR REPLACE VIEW romania_recent_price_drops AS
SELECT
    fingerprint,
    external_url,
    title,
    city,
    property_type,
    room_count,
    square_meters,
    price_ron as current_price_ron,
    price_eur as current_price_eur,
    previous_price_ron,
    previous_price_eur,
    price_change_ron,
    price_change_percentage,
    price_last_changed,
    price_history
FROM properties_romania
WHERE price_change_percentage < -5
  AND price_last_changed > NOW() - INTERVAL '7 days'
  AND status = 'ad_active'
ORDER BY price_change_percentage ASC;

-- View for price statistics by city
CREATE OR REPLACE VIEW romania_price_stats_by_city AS
SELECT
    city,
    property_type,
    COUNT(*) as total_properties,
    COUNT(CASE WHEN price_change_percentage < 0 THEN 1 END) as properties_with_drops,
    COUNT(CASE WHEN price_change_percentage > 0 THEN 1 END) as properties_with_increases,
    AVG(price_change_percentage) as avg_price_change,
    MIN(price_change_percentage) as biggest_drop,
    MAX(price_change_percentage) as biggest_increase
FROM properties_romania
WHERE price_change_percentage IS NOT NULL
  AND status = 'ad_active'
GROUP BY city, property_type
ORDER BY city, property_type;

-- Function to get full price history from JSON
CREATE OR REPLACE FUNCTION get_detailed_price_history(p_fingerprint VARCHAR)
RETURNS TABLE(
    history_date TEXT,
    price_ron NUMERIC,
    price_eur NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        (item->>'date')::TEXT as history_date,
        (item->>'ron')::NUMERIC as price_ron,
        (item->>'eur')::NUMERIC as price_eur
    FROM properties_romania,
         jsonb_array_elements(price_history) as item
    WHERE fingerprint = p_fingerprint
    ORDER BY (item->>'date')::TIMESTAMP DESC;
END;
$$ LANGUAGE plpgsql;

-- Example queries after implementation:

-- 1. Find properties with biggest price drops today
-- SELECT * FROM romania_recent_price_drops LIMIT 20;

-- 2. Get price trend for a specific property
-- SELECT * FROM get_price_trend('imobiliare_ro_12345');

-- 3. Get full price history for a property
-- SELECT * FROM get_detailed_price_history('imobiliare_ro_12345');

-- 4. Find properties that dropped price multiple times
-- SELECT fingerprint, title, price_change_count, price_history
-- FROM properties_romania
-- WHERE price_change_count > 2
-- ORDER BY price_change_count DESC;

-- 5. Alert-worthy price drops (for notifications)
-- SELECT * FROM properties_romania
-- WHERE price_drop_alert = TRUE
-- AND price_last_changed > NOW() - INTERVAL '1 day';