"""
Pipelines for processing Romanian real estate data
Mostly reused from Swiss scraper with Romania-specific modifications
"""

import logging
from datetime import datetime
from typing import Optional

from scrapy.exceptions import DropItem
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import SpiderResultRomania, ScrapeJob, PropertyStatusEnum
from .settings import DB_CONNECTION_STRING


class ValidationPipeline:
    """Validate required fields before processing"""

    required_fields = [
        'external_source',
        'external_url',
        'fingerprint'
    ]

    def process_item(self, item, spider):
        # Check required fields
        for field in self.required_fields:
            if field not in item or item[field] is None:
                raise DropItem(f"Missing required field: {field}")

        # Ensure property type
        if not item.get('property_type'):
            item['property_type'] = 'apartment'

        # Ensure deal type
        if not item.get('deal_type'):
            item['deal_type'] = 'rent'

        # Ensure status
        if not item.get('status'):
            item['status'] = PropertyStatusEnum.AD_ACTIVE.value

        # Ensure country
        if not item.get('country'):
            item['country'] = 'Romania'

        return item


class RomaniaDatabasePipeline:
    """Save items to Romania-specific database table"""

    def __init__(self):
        self.engine = None
        self.session_maker = None
        self.session = None
        self.scrape_job = None
        self.processed_count = 0
        self.error_count = 0

    def open_spider(self, spider):
        """Initialize database connection and create scrape job"""
        try:
            self.engine = create_engine(DB_CONNECTION_STRING, echo=False)
            self.session_maker = sessionmaker(bind=self.engine)
            self.session = self.session_maker()

            # Create scrape job
            self.scrape_job = ScrapeJob(
                scraper_name=spider.name,
                started_at=datetime.utcnow(),
                total_listings=0
            )
            self.session.add(self.scrape_job)
            self.session.commit()

            spider.logger.info(f"Database pipeline initialized. Job ID: {self.scrape_job.id}")
        except Exception as e:
            spider.logger.error(f"Failed to initialize database: {e}")
            raise

    def close_spider(self, spider):
        """Close database connection and update scrape job"""
        if self.scrape_job:
            self.scrape_job.ended_at = datetime.utcnow()
            self.scrape_job.total_listings = self.processed_count
            self.session.commit()

        if self.session:
            self.session.close()

        spider.logger.info(
            f"Database pipeline closed. Processed: {self.processed_count}, Errors: {self.error_count}"
        )

    def process_item(self, item, spider):
        """Process and save item to database"""
        title = item.get('title', 'No title')
        title_preview = title[:50] if title and isinstance(title, str) else str(title)[:50] if title else 'No title'
        spider.logger.info(f"[DB_PIPELINE] Processing item: {item.get('external_id')} - {title_preview}")
        spider.logger.info(f"[DB_PIPELINE] URL: {item.get('external_url')}")

        try:
            # Check if property already exists
            existing = self.session.query(SpiderResultRomania).filter_by(
                fingerprint=item['fingerprint']
            ).first()

            if existing:
                # Update existing property
                spider.logger.info(f"[DB_PIPELINE] Updating existing property: {item['external_id']}")
                self._update_property(existing, item)
            else:
                # Create new property
                spider.logger.info(f"[DB_PIPELINE] Creating NEW property: {item['external_id']}")
                property_obj = self._create_property(item)
                self.session.add(property_obj)

            self.session.commit()
            self.processed_count += 1
            spider.logger.info(f"[DB_PIPELINE] Successfully saved item {item['external_id']} (Total: {self.processed_count})")

        except Exception as e:
            spider.logger.error(f"Database error processing item {item.get('external_id')}: {e}")
            self.session.rollback()
            self.error_count += 1
            raise DropItem(f"Database error: {e}")

        return item

    def _create_property(self, item) -> SpiderResultRomania:
        """Create new property object"""
        property_obj = SpiderResultRomania(
            # Identification
            fingerprint=item['fingerprint'],
            external_source=item['external_source'],
            external_id=item.get('external_id'),
            external_url=item['external_url'],

            # Basic info
            title=item.get('title'),
            description=item.get('description'),
            property_type=item.get('property_type'),
            deal_type=item.get('deal_type'),
            status=item.get('status', PropertyStatusEnum.AD_ACTIVE.value),

            # Price
            price_ron=item.get('price_ron'),
            price_eur=item.get('price_eur'),
            currency=item.get('currency', 'RON'),
            utilities_cost=item.get('utilities_cost'),
            maintenance_cost=item.get('maintenance_cost'),

            # Location
            country=item.get('country', 'Romania'),
            county=item.get('county'),
            state=item.get('state') or item.get('county'),
            city=item.get('city'),
            neighborhood=item.get('neighborhood'),
            address=item.get('address'),
            zip_code=item.get('zip_code'),
            latitude=item.get('latitude'),
            longitude=item.get('longitude'),

            # Property details
            square_meters=item.get('square_meters'),
            bedrooms=item.get('bedrooms'),
            bathrooms=item.get('bathrooms'),
            room_count=item.get('room_count'),
            floor=item.get('floor'),
            total_floors=item.get('total_floors'),
            year_built=item.get('year_built'),
            lot_size=item.get('lot_size'),

            # Romanian specific
            construction_type=item.get('construction_type'),
            thermal_insulation=item.get('thermal_insulation'),
            comfort_level=item.get('comfort_level'),
            partitioning=item.get('partitioning'),
            orientation=item.get('orientation'),
            energy_certificate=item.get('energy_certificate'),
            cadastral_number=item.get('cadastral_number'),

            # Features
            has_balcony=item.get('has_balcony', False),
            balcony_count=item.get('balcony_count'),
            has_terrace=item.get('has_terrace', False),
            has_garden=item.get('has_garden', False),
            has_garage=item.get('has_garage', False),
            parking_spaces=item.get('parking_spaces'),
            has_basement=item.get('has_basement', False),
            has_attic=item.get('has_attic', False),

            # Amenities
            heating_type=item.get('heating_type'),
            has_air_conditioning=item.get('has_air_conditioning', False),
            has_elevator=item.get('has_elevator', False),
            furnished=item.get('furnished'),
            kitchen_equipped=item.get('kitchen_equipped', False),

            # Dates
            available_date=item.get('available_date'),
            listing_date=item.get('listing_date'),
            last_updated=item.get('last_updated'),

            # Metadata
            job_id=self.scrape_job.id if self.scrape_job else None,
            created_at=datetime.utcnow()
        )

        return property_obj

    def _update_property(self, existing: SpiderResultRomania, item):
        """Update existing property with new data"""
        # Update basic fields
        fields_to_update = [
            'title', 'description', 'property_type', 'deal_type', 'status',
            'price_ron', 'price_eur', 'currency', 'utilities_cost', 'maintenance_cost',
            'square_meters', 'bedrooms', 'bathrooms', 'room_count',
            'floor', 'total_floors', 'year_built', 'lot_size',
            'construction_type', 'thermal_insulation', 'comfort_level',
            'partitioning', 'orientation', 'energy_certificate',
            'has_balcony', 'balcony_count', 'has_terrace', 'has_garden',
            'has_garage', 'parking_spaces', 'has_basement', 'has_attic',
            'heating_type', 'has_air_conditioning', 'has_elevator',
            'furnished', 'kitchen_equipped',
            'available_date', 'listing_date', 'last_updated'
        ]

        for field in fields_to_update:
            if field in item and item[field] is not None:
                setattr(existing, field, item[field])

        # Update location if better data available
        if item.get('latitude') and item.get('longitude'):
            if not existing.latitude or not existing.longitude:
                existing.latitude = item['latitude']
                existing.longitude = item['longitude']

        # Update metadata
        existing.updated_at = datetime.utcnow()
        existing.job_id = self.scrape_job.id if self.scrape_job else existing.job_id


class MetricsPipeline:
    """Track scraping metrics"""

    def __init__(self):
        self.stats = {
            'items_scraped': 0,
            'items_dropped': 0,
            'items_error': 0
        }

    def process_item(self, item, spider):
        self.stats['items_scraped'] += 1
        spider.logger.debug(f"Metrics: {self.stats}")
        return item

    def close_spider(self, spider):
        spider.logger.info(f"Final metrics: {self.stats}")