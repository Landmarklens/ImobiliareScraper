import uuid
import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator, computed_field
import typing
from unidecode import unidecode
import hashlib
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    DateTime,
    Date,
    ForeignKey,
    UUID,
    Double,
    Boolean,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Mapped
from sqlalchemy import Enum as SQLAlchemyEnum


def hash_string(input_string: str) -> str:
    hash_object = hashlib.md5(input_string.encode())
    return hash_object.hexdigest()


def hash_string_blake2s(input_string: str) -> str:
    hash_object = hashlib.blake2s(input_string.encode(), digest_size=5)
    return hash_object.hexdigest()


Base = declarative_base()


class DealTypeEnum(str, Enum):
    RENT = "rent"
    BUY = "buy"


class PropertyStatusEnum(str, Enum):
    AD_ACTIVE = "ad_active"
    AD_INACTIVE = "non_active"  # Property removed/expired - using DB value
    RENTED = "rented"  # Property has been rented
    BLOCKED = "blocked"  # Cloudflare or other blocking
    NON_ACTIVE = "non_active"  # Same as AD_INACTIVE for DB compatibility
    PENDING_VIEWING = "pending_viewing"


DEFAULT_PROPERTY_STATUS = PropertyStatusEnum.AD_ACTIVE


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    ended_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    total_listings = Column(Integer, nullable=False)
    scraper_name = Column(String, nullable=False)

    results: Mapped[list["SpiderResultRomania"]] = relationship(
        "SpiderResultRomania",
        back_populates="scrape_job",
        cascade="all, delete-orphan",
    )


class SpiderResultBase(Base):
    __abstract__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=True)

    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)

    # Core property details
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Integer, nullable=True)
    square_meters = Column(Integer, nullable=True)
    lot_size = Column(Double, nullable=True)
    year_built = Column(Integer, nullable=True)

    # Location
    country = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    address = Column(String(255), nullable=True)
    zip_code = Column(String(10), nullable=True)
    latitude = Column(Double, nullable=True)
    longitude = Column(Double, nullable=True)

    # Deal and property info
    deal_type = Column(
        SQLAlchemyEnum(
            DealTypeEnum,
            values_callable=lambda x: [e.value for e in x],
            name="property_deal_type_enum",
        ),
        nullable=True,
    )
    property_type = Column(String(100), nullable=True)

    # External tracking
    external_source = Column(String(100), nullable=True)
    external_id = Column(String(100), nullable=True)
    external_url = Column(String(1000), nullable=True)
    fingerprint = Column(String(64), nullable=False, unique=True, index=True)

    # Status
    status = Column(
        SQLAlchemyEnum(
            PropertyStatusEnum,
            values_callable=lambda x: [e.value for e in x],
            name="property_status_enum",
        ),
        nullable=True,
        default=DEFAULT_PROPERTY_STATUS,
    )

    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    job_id = Column(UUID(as_uuid=True), ForeignKey("scrape_jobs.id"))


class SpiderResultRomania(SpiderResultBase):
    __tablename__ = "properties_romania"

    # Price information in Romanian Lei
    price_ron = Column(Double, nullable=True)
    price_eur = Column(Double, nullable=True)  # Euro equivalent
    currency = Column(String(10), default="RON")
    utilities_cost = Column(Integer, nullable=True)
    maintenance_cost = Column(Integer, nullable=True)

    # Romanian specific location
    county = Column(String(100), nullable=True)  # Județ
    neighborhood = Column(String(100), nullable=True)  # Cartier/Sector

    # Building details
    room_count = Column(Integer, nullable=True)
    floor = Column(Integer, nullable=True)
    total_floors = Column(Integer, nullable=True)

    # Romanian specific attributes
    construction_type = Column(String(100), nullable=True)  # Tip construcție
    thermal_insulation = Column(String(100), nullable=True)  # Izolație termică
    comfort_level = Column(String(50), nullable=True)  # Grad de confort
    partitioning = Column(String(50), nullable=True)  # Compartimentare
    orientation = Column(String(50), nullable=True)  # Orientare
    energy_certificate = Column(String(50), nullable=True)  # Certificat energetic
    cadastral_number = Column(String(100), nullable=True)  # Număr cadastral

    # Features
    has_balcony = Column(Boolean, default=False)
    balcony_count = Column(Integer, nullable=True)
    has_terrace = Column(Boolean, default=False)
    has_garden = Column(Boolean, default=False)
    has_garage = Column(Boolean, default=False)
    parking_spaces = Column(Integer, nullable=True)
    has_basement = Column(Boolean, default=False)
    has_attic = Column(Boolean, default=False)

    # Utilities and amenities
    heating_type = Column(String(100), nullable=True)
    has_air_conditioning = Column(Boolean, default=False)
    has_elevator = Column(Boolean, default=False)
    furnished = Column(String(50), nullable=True)  # Mobilat/nemobilat/parțial
    kitchen_equipped = Column(Boolean, default=False)

    # Dates
    available_date = Column(Date, nullable=True)
    listing_date = Column(Date, nullable=True)
    last_updated = Column(Date, nullable=True)

    scrape_job: Mapped["ScrapeJob"] = relationship(
        "ScrapeJob",
        back_populates="results",
    )

    def to_dict(self):
        return {
            c.name: str(getattr(self, c.name)) for c in self.__table__.columns
            if c.name not in ["created_at", "updated_at", "job_id", "id"]
        }