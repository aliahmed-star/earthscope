-- Add explicit country identity to archived point locations.
-- This is location/country metadata, not a country-wide area average.
PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;

ALTER TABLE locations ADD COLUMN country_name TEXT NOT NULL DEFAULT '';
ALTER TABLE locations ADD COLUMN country_code TEXT NOT NULL DEFAULT '';

UPDATE locations SET country_name = CASE location_id
    WHEN 'cairo-eg' THEN 'Egypt'
    WHEN 'phoenix-us' THEN 'United States'
    WHEN 'tokyo-jp' THEN 'Japan'
    WHEN 'sydney-au' THEN 'Australia'
    WHEN 'manila-ph' THEN 'Philippines'
    WHEN 'nairobi-ke' THEN 'Kenya'
    WHEN 'london-gb' THEN 'United Kingdom'
    WHEN 'delhi-in' THEN 'India'
    WHEN 'sao-paulo-br' THEN 'Brazil'
    WHEN 'reykjavik-is' THEN 'Iceland'
    WHEN 'jakarta-id' THEN 'Indonesia'
    WHEN 'toronto-ca' THEN 'Canada'
    ELSE country_name
END;

UPDATE locations SET country_code = CASE location_id
    WHEN 'cairo-eg' THEN 'EG'
    WHEN 'phoenix-us' THEN 'US'
    WHEN 'tokyo-jp' THEN 'JP'
    WHEN 'sydney-au' THEN 'AU'
    WHEN 'manila-ph' THEN 'PH'
    WHEN 'nairobi-ke' THEN 'KE'
    WHEN 'london-gb' THEN 'GB'
    WHEN 'delhi-in' THEN 'IN'
    WHEN 'sao-paulo-br' THEN 'BR'
    WHEN 'reykjavik-is' THEN 'IS'
    WHEN 'jakarta-id' THEN 'ID'
    WHEN 'toronto-ca' THEN 'CA'
    ELSE country_code
END;

PRAGMA user_version = 3;
COMMIT;
PRAGMA foreign_keys = ON;
