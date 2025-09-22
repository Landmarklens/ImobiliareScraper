"""
Enhanced Database Pipeline with Price History and Change Tracking
"""

import logging
from datetime import datetime
from typing import Optional

from scrapy.exceptions import DropItem
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import SpiderResultRomania, ScrapeJob, PropertyStatusEnum
from .settings import DB_CONNECTION_STRING
from .price_history import RomaniaPriceHistory, RomaniaChangeLog, ChangeDetector


class EnhancedRomaniaDatabasePipeline:
    """Enhanced pipeline that tracks price history and field changes"""

    def __init__(self):
        self.engine = None
        self.session_maker = None
        self.session = None
        self.scrape_job = None
        self.processed_count = 0
        self.error_count = 0
        self.price_changes_count = 0
        self.change_detector = ChangeDetector()

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

            spider.logger.info(f"Enhanced Database pipeline initialized. Job ID: {self.scrape_job.id}")
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
            f"Pipeline closed. Processed: {self.processed_count}, "
            f"Price changes: {self.price_changes_count}, Errors: {self.error_count}"
        )

    def process_item(self, item, spider):
        """Process and save item to database with change tracking"""
        title = item.get('title', 'No title')
        title_preview = title[:50] if title and isinstance(title, str) else str(title)[:50] if title else 'No title'
        spider.logger.info(f"[DB_PIPELINE] Processing item: {item.get('external_id')} - {title_preview}")

        try:
            # Check if property already exists
            existing = self.session.query(SpiderResultRomania).filter_by(
                fingerprint=item['fingerprint']
            ).first()

            if existing:
                # Detect and log changes BEFORE updating
                changes = self.change_detector.detect_changes(existing, item)

                if changes:
                    spider.logger.info(f"[CHANGES] Detected {len(changes)} changes for {item['external_id']}")

                    # Log price changes specifically
                    if 'price_ron' in changes or 'price_eur' in changes:
                        self._log_price_change(existing, item, spider)
                        self.price_changes_count += 1

                    # Log all changes
                    self._log_all_changes(existing, item, changes, spider)

                # Now update the existing property
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

    def _log_price_change(self, existing, item, spider):
        """Log price changes to history table"""
        old_price_ron = existing.price_ron
        new_price_ron = item.get('price_ron')
        old_price_eur = existing.price_eur
        new_price_eur = item.get('price_eur')

        # Calculate changes
        change_ron = None
        change_eur = None
        change_percentage = None

        if old_price_ron and new_price_ron and old_price_ron != new_price_ron:
            change_ron = new_price_ron - old_price_ron
            change_percentage = ((new_price_ron - old_price_ron) / old_price_ron) * 100

        if old_price_eur and new_price_eur and old_price_eur != new_price_eur:
            change_eur = new_price_eur - old_price_eur
            if not change_percentage:
                change_percentage = ((new_price_eur - old_price_eur) / old_price_eur) * 100

        # Create history record
        price_history = RomaniaPriceHistory(
            property_id=existing.id,
            fingerprint=existing.fingerprint,
            old_price_ron=old_price_ron,
            new_price_ron=new_price_ron,
            old_price_eur=old_price_eur,
            new_price_eur=new_price_eur,
            price_change_ron=change_ron,
            price_change_eur=change_eur,
            change_percentage=change_percentage,
            changed_at=datetime.utcnow(),
            scrape_job_id=self.scrape_job.id if self.scrape_job else None
        )

        self.session.add(price_history)

        # Log significant price drops
        if change_percentage and change_percentage <= -5:
            spider.logger.warning(
                f"[PRICE_DROP] Property {existing.fingerprint}: "
                f"{old_price_ron or old_price_eur} -> {new_price_ron or new_price_eur} "
                f"({change_percentage:.1f}%)"
            )

    def _log_all_changes(self, existing, item, changes, spider):
        """Log all field changes to change log table"""
        if not changes:
            return

        change_log = PropertyChangeLog(
            property_id=existing.id,
            fingerprint=existing.fingerprint,
            changes=changes,
            changed_at=datetime.utcnow(),
            scrape_job_id=self.scrape_job.id if self.scrape_job else None,
            change_count=len(changes)
        )

        self.session.add(change_log)

        # Log the changes
        spider.logger.info(f"[CHANGE_LOG] Property {existing.fingerprint} changed fields: {list(changes.keys())}")

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

            # Location
            country=item.get('country', 'Romania'),
            city=item.get('city'),
            address=item.get('address'),

            # Property details
            square_meters=item.get('square_meters'),
            room_count=item.get('room_count'),
            floor=item.get('floor'),

            # Metadata
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

        # Update metadata
        existing.updated_at = datetime.utcnow()
        existing.job_id = self.scrape_job.id if self.scrape_job else existing.job_id