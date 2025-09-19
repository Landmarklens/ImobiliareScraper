"""Property filter utilities for smart scraping"""
import re
from typing import Optional, Dict, Any
from datetime import datetime, timedelta


class SmartPropertyFilter:
    """Smart filtering for property listings"""

    def __init__(self, settings: Dict[str, Any] = None):
        self.settings = settings or {}
        self.max_age_days = self.settings.get('MAX_LISTING_AGE_DAYS', 90)
        self.min_price = self.settings.get('MIN_PRICE', 0)
        self.max_price = self.settings.get('MAX_PRICE', float('inf'))

    def should_scrape(self, url: str, metadata: Dict[str, Any] = None) -> bool:
        """Determine if a property URL should be scraped"""
        # Always scrape if no metadata
        if not metadata:
            return True

        # Check listing age if available
        if 'listing_date' in metadata:
            try:
                listing_date = datetime.fromisoformat(metadata['listing_date'])
                if datetime.now() - listing_date > timedelta(days=self.max_age_days):
                    return False
            except (ValueError, TypeError):
                pass

        # Check price range if available
        if 'price' in metadata:
            try:
                price = float(metadata['price'])
                if price < self.min_price or price > self.max_price:
                    return False
            except (ValueError, TypeError):
                pass

        return True

    def is_duplicate(self, fingerprint: str, existing_fingerprints: set) -> bool:
        """Check if property is a duplicate"""
        return fingerprint in existing_fingerprints