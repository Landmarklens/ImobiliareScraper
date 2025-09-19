-- Migration: Create properties_romania table for Romanian real estate data
-- Date: 2025-01-19
-- Description: Creates dedicated table for imobiliare.ro scraped properties

BEGIN;

-- Create table for Romanian properties
CREATE TABLE IF NOT EXISTS properties_romania (
    -- Core identification
    id SERIAL PRIMARY KEY,
    fingerprint VARCHAR(64) UNIQUE NOT NULL,
    external_source VARCHAR(100) DEFAULT 'imobiliare_ro',
    external_id VARCHAR(100),
    external_url VARCHAR(1000),

    -- Property details
    title VARCHAR(255),
    description TEXT,
    property_type VARCHAR(100),
    square_meters INTEGER,
    bedrooms INTEGER,
    bathrooms INTEGER,
    room_count INTEGER,
    floor INTEGER,
    total_floors INTEGER,
    year_built INTEGER,
    lot_size DOUBLE PRECISION,

    -- Price information
    price_ron DOUBLE PRECISION,  -- Romanian Lei
    price_eur DOUBLE PRECISION,  -- Euro equivalent
    currency VARCHAR(10) DEFAULT 'RON',
    utilities_cost INTEGER,
    maintenance_cost INTEGER,

    -- Location
    country VARCHAR(100) DEFAULT 'Romania',
    county VARCHAR(100),  -- Județ
    state VARCHAR(100),   -- Same as county for consistency
    city VARCHAR(100),
    neighborhood VARCHAR(100),  -- Cartier/Sector
    address VARCHAR(255),
    zip_code VARCHAR(10),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,

    -- Romanian specific attributes
    construction_type VARCHAR(100),  -- Tip construcție (brick, concrete, etc.)
    thermal_insulation VARCHAR(100),  -- Izolație termică
    comfort_level VARCHAR(50),  -- Grad de confort (I, II, III)
    partitioning VARCHAR(50),  -- Compartimentare (decomandat, semidecomandat)
    orientation VARCHAR(50),  -- Orientare (N, S, E, W)
    energy_certificate VARCHAR(50),  -- Certificat energetic
    cadastral_number VARCHAR(100),  -- Număr cadastral

    -- Features
    has_balcony BOOLEAN DEFAULT FALSE,
    balcony_count INTEGER,
    has_terrace BOOLEAN DEFAULT FALSE,
    has_garden BOOLEAN DEFAULT FALSE,
    has_garage BOOLEAN DEFAULT FALSE,
    parking_spaces INTEGER,
    has_basement BOOLEAN DEFAULT FALSE,
    has_attic BOOLEAN DEFAULT FALSE,

    -- Utilities and amenities
    heating_type VARCHAR(100),  -- Centrală proprie, termoficare, etc.
    has_air_conditioning BOOLEAN DEFAULT FALSE,
    has_elevator BOOLEAN DEFAULT FALSE,
    furnished VARCHAR(50),  -- Mobilat, nemobilat, parțial mobilat
    kitchen_equipped BOOLEAN DEFAULT FALSE,

    -- Status and availability
    deal_type property_deal_type_enum,  -- Using existing enum from main properties table
    status property_status_enum DEFAULT 'ad_active',  -- Using existing enum
    available_date DATE,
    listing_date DATE,
    last_updated DATE,

    -- Metadata
    owner_id INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    job_id UUID REFERENCES scrape_jobs(id),

    -- Constraints
    CONSTRAINT valid_price CHECK (price_ron >= 0 OR price_ron IS NULL),
    CONSTRAINT valid_square_meters CHECK (square_meters > 0 OR square_meters IS NULL),
    CONSTRAINT valid_coordinates CHECK (
        (latitude IS NULL AND longitude IS NULL) OR
        (latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)
    )
);

-- Create indexes for better query performance
CREATE INDEX idx_properties_romania_fingerprint ON properties_romania(fingerprint);
CREATE INDEX idx_properties_romania_external_id ON properties_romania(external_id);
CREATE INDEX idx_properties_romania_external_source ON properties_romania(external_source);
CREATE INDEX idx_properties_romania_city ON properties_romania(city);
CREATE INDEX idx_properties_romania_county ON properties_romania(county);
CREATE INDEX idx_properties_romania_neighborhood ON properties_romania(neighborhood);
CREATE INDEX idx_properties_romania_price_ron ON properties_romania(price_ron);
CREATE INDEX idx_properties_romania_price_eur ON properties_romania(price_eur);
CREATE INDEX idx_properties_romania_property_type ON properties_romania(property_type);
CREATE INDEX idx_properties_romania_deal_type ON properties_romania(deal_type);
CREATE INDEX idx_properties_romania_status ON properties_romania(status);
CREATE INDEX idx_properties_romania_created_at ON properties_romania(created_at);
CREATE INDEX idx_properties_romania_updated_at ON properties_romania(updated_at);
CREATE INDEX idx_properties_romania_square_meters ON properties_romania(square_meters);
CREATE INDEX idx_properties_romania_bedrooms ON properties_romania(bedrooms);
CREATE INDEX idx_properties_romania_job_id ON properties_romania(job_id);

-- Spatial index for geographic queries (if PostGIS is available)
-- CREATE INDEX idx_properties_romania_location ON properties_romania USING GIST(ST_MakePoint(longitude, latitude));

-- Add comments for documentation
COMMENT ON TABLE properties_romania IS 'Romanian real estate properties scraped from imobiliare.ro';
COMMENT ON COLUMN properties_romania.fingerprint IS 'Unique hash identifier for duplicate detection';
COMMENT ON COLUMN properties_romania.county IS 'Romanian county (Județ)';
COMMENT ON COLUMN properties_romania.neighborhood IS 'Romanian neighborhood (Cartier/Sector)';
COMMENT ON COLUMN properties_romania.price_ron IS 'Price in Romanian Lei';
COMMENT ON COLUMN properties_romania.price_eur IS 'Price converted to Euro';
COMMENT ON COLUMN properties_romania.comfort_level IS 'Romanian comfort classification (I, II, III, IV)';
COMMENT ON COLUMN properties_romania.partitioning IS 'Room layout type (decomandat, semidecomandat, etc.)';

-- Grant permissions (adjust based on your database users)
-- GRANT SELECT, INSERT, UPDATE ON properties_romania TO scraper_user;
-- GRANT SELECT ON properties_romania TO readonly_user;

COMMIT;

-- Rollback script (save as 001_rollback_romania_table.sql)
-- DROP TABLE IF EXISTS properties_romania CASCADE;