# -*- coding: utf-8 -*-
"""
Imobiliare.ro scraper for Romanian real estate properties
"""
import scrapy
import re
import json
from datetime import datetime, date
from urllib.parse import urljoin, urlparse, parse_qs

from ...helper import safe_int, safe_float
from ...models import DealTypeEnum, PropertyStatusEnum
from ...property_type_mapping_ro import standardize_property_type
from ...utils.property_status_detector import PropertyStatusDetector
from ..base_sitemap_spider import SmartSitemapSpider
from ..geocoding_mixin import GeocodingMixin


class ImobiliareRoSpider(GeocodingMixin, SmartSitemapSpider):
    name = "imobiliare_ro"
    country = "romania"
    locale = "ro"
    external_source = "imobiliare_ro"

    # Custom settings
    custom_settings = {
        'CONCURRENT_REQUESTS': 8,
        'DOWNLOAD_DELAY': 1.0,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'ROBOTSTXT_OBEY': True,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.limit = int(kwargs.get('limit', float('inf'))) if 'limit' in kwargs else float('inf')
        self.scraped_count = 0
        self.deal_type = kwargs.get('deal_type', 'rent').lower()

        # Base URLs for different deal types
        if self.deal_type == 'rent':
            self.start_urls = [
                'https://www.imobiliare.ro/inchirieri-apartamente',
                'https://www.imobiliare.ro/inchirieri-case-vile',
                'https://www.imobiliare.ro/inchirieri-garsoniere',
            ]
        else:  # buy
            self.start_urls = [
                'https://www.imobiliare.ro/vanzare-apartamente',
                'https://www.imobiliare.ro/vanzare-case-vile',
                'https://www.imobiliare.ro/vanzare-garsoniere',
            ]

        # Initialize status detector
        self.status_detector = PropertyStatusDetector()

    def start_requests(self):
        """Start requests for property listings"""
        if self.single_url:
            self.logger.info(f"[SingleURL] Processing single URL: {self.single_url}")
            yield scrapy.Request(
                url=self.single_url,
                callback=self.parse_property,
                meta={'single_url_mode': True}
            )
        else:
            # Regular crawling mode
            for url in self.start_urls:
                yield scrapy.Request(url=url, callback=self.parse_listing)

    def parse_listing(self, response):
        """Parse listing page with multiple properties"""
        if self.scraped_count >= self.limit:
            self.logger.info(f"Reached limit of {self.limit} properties")
            return

        # Extract property URLs
        property_urls = response.css('div.box-anunt a.mobile-container-url::attr(href)').getall()

        if not property_urls:
            # Try alternative selector
            property_urls = response.css('a[itemprop="url"]::attr(href)').getall()

        for url in property_urls:
            if self.scraped_count >= self.limit:
                break

            full_url = urljoin(response.url, url)
            yield scrapy.Request(
                url=full_url,
                callback=self.parse_property,
                meta={'listing_url': response.url}
            )
            self.scraped_count += 1

        # Follow pagination
        if self.scraped_count < self.limit:
            next_page = response.css('a.pager-next::attr(href)').get()
            if not next_page:
                next_page = response.css('a[rel="next"]::attr(href)').get()

            if next_page:
                next_url = urljoin(response.url, next_page)
                yield scrapy.Request(url=next_url, callback=self.parse_listing)

    def parse_property(self, response):
        """Parse individual property page"""
        # Extract property ID from URL
        url_parts = response.url.split('/')
        external_id = url_parts[-1] if url_parts[-1] else url_parts[-2]

        # Check if property exists (404, etc.)
        if response.status != 200:
            self.logger.warning(f"Property not available: {response.url} (status: {response.status})")
            return

        # Initialize item
        item = {}

        # Basic information
        item['external_source'] = self.external_source
        item['external_url'] = response.url
        item['external_id'] = external_id

        # Title and description
        item['title'] = response.css('h1.titlu::text').get()
        if not item['title']:
            item['title'] = response.css('h1::text').get()

        description_parts = response.css('div.descriere div.collapsible_content::text').getall()
        if not description_parts:
            description_parts = response.css('div#b_detalii_text::text').getall()
        item['description'] = ' '.join(description_parts).strip() if description_parts else ''

        # Property type
        property_type_raw = response.css('span.tip-proprietate::text').get()
        if not property_type_raw:
            # Try to extract from breadcrumbs
            breadcrumbs = response.css('div.breadcrumb a::text').getall()
            for crumb in breadcrumbs:
                if any(word in crumb.lower() for word in ['apartament', 'casa', 'vila', 'garsoniera']):
                    property_type_raw = crumb
                    break

        item['property_type'] = standardize_property_type(property_type_raw) if property_type_raw else 'apartment'

        # Price
        price_text = response.css('div.pret span.numero::text').get()
        if not price_text:
            price_text = response.css('div.pret-zona-info div.pret::text').get()

        if price_text:
            # Remove non-numeric characters except comma and dot
            price_clean = re.sub(r'[^\d,.]', '', price_text)
            price_clean = price_clean.replace(',', '.')
            item['price_ron'] = safe_float(price_clean)

            # Check currency
            currency = response.css('div.pret span.moneda::text').get()
            if currency and '€' in currency:
                item['price_eur'] = item['price_ron']
                item['price_ron'] = item['price_eur'] * 4.98  # Approximate conversion
                item['currency'] = 'EUR'
            else:
                item['currency'] = 'RON'
                item['price_eur'] = item['price_ron'] / 4.98 if item['price_ron'] else None

        # Deal type
        item['deal_type'] = 'rent' if 'inchir' in response.url else 'buy'

        # Location
        self._extract_location(response, item)

        # Property details
        self._extract_property_details(response, item)

        # Features
        self._extract_features(response, item)

        # Dates
        self._extract_dates(response, item)

        # Status detection
        status = self.status_detector.detect_status(
            response=response,
            description=item.get('description', ''),
            external_source=self.external_source
        )
        item['status'] = status.value if status else PropertyStatusEnum.AD_ACTIVE.value

        # Generate fingerprint
        fingerprint_string = f"{self.external_source}_{external_id}"
        item['fingerprint'] = self._generate_fingerprint(fingerprint_string)

        yield item

    def _extract_location(self, response, item):
        """Extract location information"""
        # Address from meta or structured data
        address = response.css('span.adresa::text').get()
        if not address:
            address = response.css('div.localizare::text').get()
        item['address'] = address.strip() if address else None

        # City
        city = response.css('span.localitate::text').get()
        if not city:
            # Try from breadcrumbs
            breadcrumbs = response.css('div.breadcrumb a::text').getall()
            for crumb in breadcrumbs:
                if any(word in crumb.lower() for word in ['bucuresti', 'cluj', 'timisoara', 'iasi', 'constanta']):
                    city = crumb
                    break
        item['city'] = city.strip() if city else None

        # County (Județ)
        county = response.css('span.judet::text').get()
        item['county'] = county.strip() if county else item.get('city')
        item['state'] = item['county']  # Use county as state for consistency

        # Neighborhood
        neighborhood = response.css('span.zona::text').get()
        if not neighborhood:
            neighborhood = response.css('span.cartier::text').get()
        item['neighborhood'] = neighborhood.strip() if neighborhood else None

        # Country
        item['country'] = 'Romania'

        # Coordinates (if available in page)
        lat = response.css('div#map::attr(data-lat)').get()
        lng = response.css('div#map::attr(data-lng)').get()

        if lat and lng:
            item['latitude'] = safe_float(lat)
            item['longitude'] = safe_float(lng)
        else:
            # Try geocoding
            address_components = []
            if item.get('address'):
                address_components.append(item['address'])
            if item.get('neighborhood'):
                address_components.append(item['neighborhood'])
            if item.get('city'):
                address_components.append(item['city'])
            if item.get('county'):
                address_components.append(item['county'])
            address_components.append('Romania')

            if address_components:
                full_address = ', '.join(filter(None, address_components))
                coords = self.geocode_address(full_address)
                if coords:
                    item['latitude'] = coords['latitude']
                    item['longitude'] = coords['longitude']

        # Zip code (rarely available)
        item['zip_code'] = response.css('span.cod-postal::text').get()

    def _extract_property_details(self, response, item):
        """Extract detailed property information"""
        # Find characteristics section
        characteristics = {}

        # Try to find characteristics list
        char_items = response.css('ul.lista-caracteristici li')
        for char in char_items:
            label = char.css('span::text').get()
            value = char.css('span:nth-child(2)::text').get()
            if label and value:
                characteristics[label.strip().lower()] = value.strip()

        # Alternative extraction method
        if not characteristics:
            details_section = response.css('div#b_detalii_specificatii')
            labels = details_section.css('dt::text').getall()
            values = details_section.css('dd::text').getall()
            for label, value in zip(labels, values):
                characteristics[label.strip().lower()] = value.strip()

        # Extract from characteristics
        # Rooms
        room_count = characteristics.get('nr. camere') or characteristics.get('camere')
        if room_count:
            item['room_count'] = safe_int(room_count)
            # Estimate bedrooms (rooms - 1 for living room)
            item['bedrooms'] = max(1, item['room_count'] - 1) if item['room_count'] else None

        # Bathrooms
        bathrooms = characteristics.get('nr. bai') or characteristics.get('bai')
        item['bathrooms'] = safe_int(bathrooms) if bathrooms else None

        # Square meters
        area = characteristics.get('suprafata utila') or characteristics.get('suprafata')
        if area:
            area_clean = re.sub(r'[^\d,.]', '', area)
            item['square_meters'] = safe_int(safe_float(area_clean.replace(',', '.')))

        # Floor
        floor = characteristics.get('etaj')
        if floor:
            floor_match = re.search(r'(\d+)', floor)
            if floor_match:
                item['floor'] = safe_int(floor_match.group(1))
            elif 'parter' in floor.lower():
                item['floor'] = 0

        # Total floors
        total_floors = characteristics.get('nr. etaje')
        item['total_floors'] = safe_int(total_floors) if total_floors else None

        # Year built
        year = characteristics.get('an constructie') or characteristics.get('an finalizare')
        item['year_built'] = safe_int(year) if year else None

        # Lot size
        lot = characteristics.get('suprafata teren')
        if lot:
            lot_clean = re.sub(r'[^\d,.]', '', lot)
            item['lot_size'] = safe_float(lot_clean.replace(',', '.'))

        # Romanian specific attributes
        item['construction_type'] = characteristics.get('tip constructie')
        item['thermal_insulation'] = characteristics.get('izolatie termica')
        item['comfort_level'] = characteristics.get('confort')
        item['partitioning'] = characteristics.get('compartimentare')
        item['orientation'] = characteristics.get('orientare')
        item['energy_certificate'] = characteristics.get('certificat energetic')

        # Utilities cost
        utilities = characteristics.get('intretinere')
        if utilities:
            utilities_clean = re.sub(r'[^\d]', '', utilities)
            item['utilities_cost'] = safe_int(utilities_clean)

        # Heating type
        item['heating_type'] = characteristics.get('tip incalzire') or characteristics.get('incalzire')

        # Furnished status
        item['furnished'] = characteristics.get('mobilier')

    def _extract_features(self, response, item):
        """Extract property features and amenities"""
        # Features list
        features = response.css('div.dotari li::text').getall()
        if not features:
            features = response.css('ul.facilitati li::text').getall()

        features_text = ' '.join(features).lower() if features else ''

        # Balcony
        item['has_balcony'] = 'balcon' in features_text or response.css('li:contains("Balcon")').get() is not None
        balcony_count = response.css('li:contains("balcoane")::text').re_first(r'(\d+)')
        item['balcony_count'] = safe_int(balcony_count) if balcony_count else None

        # Other features
        item['has_terrace'] = 'terasa' in features_text or 'terasă' in features_text
        item['has_garden'] = 'gradina' in features_text or 'grădină' in features_text
        item['has_garage'] = 'garaj' in features_text
        item['has_basement'] = 'subsol' in features_text or 'pivnita' in features_text or 'pivniță' in features_text
        item['has_attic'] = 'mansarda' in features_text or 'mansardă' in features_text or 'pod' in features_text

        # Parking
        parking = response.css('li:contains("Parcare")::text').get()
        if parking:
            parking_match = re.search(r'(\d+)', parking)
            item['parking_spaces'] = safe_int(parking_match.group(1)) if parking_match else 1
        else:
            item['parking_spaces'] = 1 if 'parcare' in features_text else 0

        # Amenities
        item['has_air_conditioning'] = 'aer conditionat' in features_text or 'aer condiționat' in features_text
        item['has_elevator'] = 'lift' in features_text or 'ascensor' in features_text
        item['kitchen_equipped'] = 'bucatarie echipata' in features_text or 'bucătărie echipată' in features_text

    def _extract_dates(self, response, item):
        """Extract relevant dates"""
        # Listing date
        listing_date_text = response.css('span.publicat::text').get()
        if listing_date_text:
            # Parse Romanian date format
            date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', listing_date_text)
            if date_match:
                day, month, year = date_match.groups()
                item['listing_date'] = date(int(year), int(month), int(day))

        # Last updated
        updated_text = response.css('span.actualizat::text').get()
        if updated_text:
            date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', updated_text)
            if date_match:
                day, month, year = date_match.groups()
                item['last_updated'] = date(int(year), int(month), int(day))

        # Available date (usually immediate for rentals)
        available_text = response.css('span.disponibil::text').get()
        if available_text:
            if 'imediat' in available_text.lower():
                item['available_date'] = date.today()
            else:
                date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', available_text)
                if date_match:
                    day, month, year = date_match.groups()
                    item['available_date'] = date(int(year), int(month), int(day))

    def _generate_fingerprint(self, input_string):
        """Generate unique fingerprint for property"""
        import hashlib
        return hashlib.sha256(input_string.encode()).hexdigest()