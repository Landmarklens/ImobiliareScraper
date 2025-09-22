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
import json


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
                spider.logger.info(f"[DB_UPDATE_PRICES] Current DB prices - RON: {existing.price_ron}, EUR: {existing.price_eur}")
                spider.logger.info(f"[DB_UPDATE_PRICES] New prices - RON: {item.get('price_ron')}, EUR: {item.get('price_eur')}")
                self._update_property(existing, item)
            else:
                # Create new property
                spider.logger.info(f"[DB_PIPELINE] Creating NEW property: {item['external_id']}")
                spider.logger.info(f"[DB_NEW_PRICES] Setting prices - RON: {item.get('price_ron')}, EUR: {item.get('price_eur')}")
                property_obj = self._create_property(item)
                self.session.add(property_obj)

            self.session.commit()
            self.processed_count += 1

            # Verify what was actually saved
            saved = self.session.query(SpiderResultRomania).filter_by(
                fingerprint=item['fingerprint']
            ).first()
            if saved:
                spider.logger.info(f"[DB_VERIFIED] Property {item['fingerprint']} in DB with prices - RON: {saved.price_ron}, EUR: {saved.price_eur}")

            spider.logger.info(f"[DB_PIPELINE] Successfully saved item {item['external_id']} (Total: {self.processed_count})")

        except Exception as e:
            spider.logger.error(f"Database error processing item {item.get('external_id')}: {e}")
            spider.logger.error(f"[DB_ERROR] Exception type: {type(e).__name__}")
            spider.logger.error(f"[DB_ERROR] Item prices - RON: {item.get('price_ron')}, EUR: {item.get('price_eur')}")
            spider.logger.debug(f"[DB_ERROR_FULL] Full item: {item}")
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

            # Initialize price tracking fields
            highest_price_ron=item.get('price_ron'),
            lowest_price_ron=item.get('price_ron'),
            price_change_count=0,
            price_history=json.dumps([]),  # Start with empty history
            price_drop_alert=False,

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
        """Update existing property with new data and track price changes"""

        # Track price changes BEFORE updating
        old_price_ron = existing.price_ron
        old_price_eur = existing.price_eur
        new_price_ron = item.get('price_ron')
        new_price_eur = item.get('price_eur')

        price_changed = False

        # Check if RON price changed
        if old_price_ron and new_price_ron and old_price_ron != new_price_ron:
            price_changed = True

            # Initialize price history if needed
            if existing.price_history is None or existing.price_history == '':
                price_history_list = []
            else:
                # Parse existing JSON string
                try:
                    price_history_list = json.loads(existing.price_history)
                except:
                    price_history_list = []

            # Append to price history
            history_entry = {
                'date': datetime.utcnow().isoformat(),
                'ron': float(old_price_ron),
                'eur': float(old_price_eur) if old_price_eur else None
            }
            price_history_list.append(history_entry)

            # Convert back to JSON string
            existing.price_history = json.dumps(price_history_list)

            # Store previous price
            existing.previous_price_ron = old_price_ron
            existing.previous_price_eur = old_price_eur

            # Calculate changes
            existing.price_change_ron = new_price_ron - old_price_ron
            existing.price_change_percentage = ((new_price_ron - old_price_ron) / old_price_ron) * 100

            # Update tracking fields
            existing.price_last_changed = datetime.utcnow()
            existing.price_change_count = (existing.price_change_count or 0) + 1

            # Update high/low tracking
            if existing.highest_price_ron is None or new_price_ron > existing.highest_price_ron:
                existing.highest_price_ron = new_price_ron
            if existing.lowest_price_ron is None or new_price_ron < existing.lowest_price_ron:
                existing.lowest_price_ron = new_price_ron

            # Set alert for significant drops
            if existing.price_change_percentage <= -5:
                existing.price_drop_alert = True
                logging.info(f"[PRICE_DROP_ALERT] {existing.fingerprint}: {old_price_ron} -> {new_price_ron} ({existing.price_change_percentage:.1f}%)")
            else:
                existing.price_drop_alert = False

        # Check if EUR price changed (if no RON change detected)
        elif old_price_eur and new_price_eur and old_price_eur != new_price_eur and not price_changed:
            price_changed = True

            # Initialize price history if needed
            if existing.price_history is None or existing.price_history == '':
                price_history_list = []
            else:
                # Parse existing JSON string
                try:
                    price_history_list = json.loads(existing.price_history)
                except:
                    price_history_list = []

            # Append to price history
            history_entry = {
                'date': datetime.utcnow().isoformat(),
                'ron': float(old_price_ron) if old_price_ron else None,
                'eur': float(old_price_eur)
            }
            price_history_list.append(history_entry)

            # Convert back to JSON string
            existing.price_history = json.dumps(price_history_list)

            # Store previous price
            existing.previous_price_eur = old_price_eur
            existing.price_change_eur = new_price_eur - old_price_eur
            existing.price_change_percentage = ((new_price_eur - old_price_eur) / old_price_eur) * 100
            existing.price_last_changed = datetime.utcnow()
            existing.price_change_count = (existing.price_change_count or 0) + 1

            # Set alert for significant drops
            if existing.price_change_percentage <= -5:
                existing.price_drop_alert = True
                logging.info(f"[PRICE_DROP_ALERT] {existing.fingerprint}: EUR {old_price_eur} -> {new_price_eur} ({existing.price_change_percentage:.1f}%)")
            else:
                existing.price_drop_alert = False

        # Log if price changed
        if price_changed:
            logging.info(f"[PRICE_CHANGE] Property {existing.fingerprint}: RON {old_price_ron} -> {new_price_ron}, EUR {old_price_eur} -> {new_price_eur}")

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