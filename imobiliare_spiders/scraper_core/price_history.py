# Price History Tracking Module
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class RomaniaPriceHistory(Base):
    """Track price changes for Romanian properties"""
    __tablename__ = 'romania_price_history'

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey('properties_romania.id'))
    fingerprint = Column(String(64), index=True)

    # Old values
    old_price_ron = Column(Numeric(12, 2))
    old_price_eur = Column(Numeric(12, 2))

    # New values
    new_price_ron = Column(Numeric(12, 2))
    new_price_eur = Column(Numeric(12, 2))

    # Calculated changes
    price_change_ron = Column(Numeric(12, 2))
    price_change_eur = Column(Numeric(12, 2))
    change_percentage = Column(Numeric(5, 2))

    # Metadata
    changed_at = Column(DateTime, default=datetime.utcnow)
    scrape_job_id = Column(Integer)

    def __repr__(self):
        return f"<PriceHistory {self.fingerprint}: {self.old_price_ron} -> {self.new_price_ron}>"


class RomaniaChangeLog(Base):
    """Track all field changes for Romanian properties"""
    __tablename__ = 'romania_change_log'

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey('properties_romania.id'))
    fingerprint = Column(String(64), index=True)

    # Store all changes as JSON
    changes = Column(JSON)  # {"field_name": {"old": value, "new": value}, ...}

    # Metadata
    changed_at = Column(DateTime, default=datetime.utcnow)
    scrape_job_id = Column(Integer)
    change_count = Column(Integer, default=0)

    def __repr__(self):
        return f"<ChangeLog {self.fingerprint}: {self.change_count} changes>"


class ChangeDetector:
    """Detect and log changes between existing and new property data"""

    TRACKED_FIELDS = [
        'price_ron', 'price_eur', 'status', 'title', 'description',
        'square_meters', 'room_count', 'floor', 'available_date'
    ]

    @staticmethod
    def detect_changes(existing, new_item: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Compare existing property with new data and return changes

        Returns:
            Dictionary of changes: {"field": {"old": value, "new": value}}
        """
        changes = {}

        for field in ChangeDetector.TRACKED_FIELDS:
            old_value = getattr(existing, field, None)
            new_value = new_item.get(field)

            # Skip if both are None or equal
            if old_value == new_value:
                continue

            # Skip if new value is None (no update)
            if new_value is None:
                continue

            changes[field] = {
                "old": old_value,
                "new": new_value
            }

        return changes

    @staticmethod
    def calculate_price_change(old_price: Optional[float], new_price: Optional[float]) -> Dict[str, float]:
        """Calculate price change metrics"""
        if not old_price or not new_price:
            return {"absolute": 0, "percentage": 0}

        absolute_change = new_price - old_price
        percentage_change = ((new_price - old_price) / old_price) * 100

        return {
            "absolute": round(absolute_change, 2),
            "percentage": round(percentage_change, 2)
        }

    @staticmethod
    def should_notify_price_drop(old_price: float, new_price: float, threshold: float = 5.0) -> bool:
        """Check if price drop is significant enough to notify"""
        if not old_price or not new_price:
            return False

        percentage_drop = ((old_price - new_price) / old_price) * 100
        return percentage_drop >= threshold