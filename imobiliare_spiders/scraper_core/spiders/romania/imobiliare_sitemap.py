# -*- coding: utf-8 -*-
"""
Imobiliare.ro sitemap-based scraper for Romanian real estate properties
This spider bypasses DataDome/Cloudflare protection by using sitemaps
"""
import scrapy
from scrapy.spiders import SitemapSpider
import re
import json
from datetime import datetime
from urllib.parse import urljoin, urlparse

from ...helper import safe_int, safe_float
from ...models import DealTypeEnum, PropertyStatusEnum
from ...property_type_mapping_ro import standardize_property_type
from ...utils.property_status_detector import PropertyStatusDetector
from ..geocoding_mixin import GeocodingMixin


class ImobiliareSitemapSpider(GeocodingMixin, SitemapSpider):
    name = "imobiliare_sitemap"
    country = "romania"
    locale = "ro"
    external_source = "imobiliare_ro"

    # Sitemap URLs - start with the index
    sitemap_urls = [
        'https://www.imobiliare.ro/sitemap-listings-index-ro.xml'
    ]

    # Rules for following sitemap URLs
    sitemap_rules = [
        # Match property URLs - they end with a numeric ID
        (r'/oferta/.*-\d+$', 'parse'),
    ]

    # Follow sitemaps in the index
    sitemap_follow = [
        # Follow regional sitemaps for apartments
        r'sitemap-listings-apartments-',
        # Follow regional sitemaps for houses
        r'sitemap-listings-houses-',
        # Follow regional sitemaps for studios
        r'sitemap-listings-studios-',
    ]

    # Custom settings - NO PROXIES for individual pages
    custom_settings = {
        'CONCURRENT_REQUESTS': 2,  # Lower concurrency to avoid detection
        'DOWNLOAD_DELAY': 3.0,  # Longer delay
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'ROBOTSTXT_OBEY': False,  # Skip robots.txt for now
        'DOWNLOADER_MIDDLEWARES': {
            'scraper_core.middlewares.CustomUserAgentMiddleware': 400,
            # Disable proxy middleware for this spider
            'scraper_core.middlewares.WebshareProxyMiddleware': None,
            'scraper_core.middlewares.RetryMiddleware': 500,
            'scraper_core.middlewares.HeadersMiddleware': 550,
        },
        # Add specific headers to mimic browser
        'DEFAULT_REQUEST_HEADERS': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.limit = int(kwargs.get('limit', 10))  # Default to 10 for testing
        self.scraped_count = 0
        self.deal_type = kwargs.get('deal_type', 'rent').lower()
        self.region = kwargs.get('region', None)  # Optional: filter by region

        # Initialize status detector
        self.status_detector = PropertyStatusDetector()

        self.logger.info(f"[SITEMAP_SPIDER] Starting {self.name} spider")
        self.logger.info(f"[SITEMAP_SPIDER] Deal type: {self.deal_type}")
        self.logger.info(f"[SITEMAP_SPIDER] Limit: {self.limit}")
        self.logger.info(f"[SITEMAP_SPIDER] Region filter: {self.region or 'None'}")

    def sitemap_filter(self, entries):
        """Filter sitemap entries based on deal type and limit"""
        count = 0
        for entry in entries:
            if count >= self.limit:
                self.logger.info(f"[SITEMAP_FILTER] Reached limit of {self.limit} properties")
                break

            url = entry['loc']

            # Log progress
            if count < 5 or count % 100 == 0:
                self.logger.info(f"[SITEMAP_FILTER] Entry {count}: {url}")

            # For property URLs (not sitemap XMLs), apply deal type filter
            if '/oferta/' in url:
                # This is an actual property URL
                if self.deal_type == 'rent' and 'inchiriat' in url:
                    count += 1
                    self.logger.info(f"[SITEMAP_FILTER] Accepting rental property {count}/{self.limit}: {url}")
                    yield entry
                elif self.deal_type == 'buy' and ('vanzare' in url or 'vinde' in url):
                    count += 1
                    self.logger.info(f"[SITEMAP_FILTER] Accepting sale property {count}/{self.limit}: {url}")
                    yield entry
                elif self.deal_type == 'all':
                    count += 1
                    self.logger.info(f"[SITEMAP_FILTER] Accepting property {count}/{self.limit}: {url}")
                    yield entry
            else:
                # For sitemap XML URLs, always yield them (they contain properties)
                yield entry

    def parse(self, response):
        """Parse individual property page from sitemap"""
        self.logger.info(f"[PARSE_PROPERTY] Processing: {response.url} (Status: {response.status})")

        # Check if property exists (404, etc.)
        if response.status != 200:
            self.logger.warning(f"[PARSE_PROPERTY] Property not available: {response.url} (status: {response.status})")
            return

        # Extract property ID from URL
        url_parts = response.url.split('/')
        property_id = url_parts[-1] if url_parts[-1] else url_parts[-2]

        # Check for DataDome challenge
        if 'datadome' in response.text.lower() and response.status == 403:
            self.logger.error(f"[DATADOME] Blocked by DataDome on property page: {response.url}")
            return

        # Initialize item
        item = {}

        # Basic information
        item['external_source'] = self.external_source
        item['external_url'] = response.url
        item['external_id'] = property_id

        # Title
        item['title'] = response.css('h1.titlu::text').get() or response.css('h1::text').get()

        # Description
        description_parts = response.css('div.descriere div.row div::text').getall()
        item['description'] = ' '.join(description_parts).strip() if description_parts else None

        # Price
        price_text = response.css('span.pret-mare::text').get()
        if price_text:
            # Clean price text and extract number
            price_match = re.search(r'([\d,\.]+)', price_text.replace(' ', ''))
            if price_match:
                price = float(price_match.group(1).replace(',', '').replace('.', ''))

                # Determine currency
                if '€' in price_text or 'EUR' in price_text:
                    item['price_eur'] = price
                    item['currency'] = 'EUR'
                elif 'lei' in price_text.lower() or 'ron' in price_text:
                    item['price_ron'] = price
                    item['currency'] = 'RON'
                else:
                    item['price'] = price

        # Property type
        property_type_text = response.css('ul.lista-tabelara li:contains("Tip") span::text').get()
        if property_type_text:
            item['property_type'] = standardize_property_type(property_type_text)

        # Deal type
        if 'inchiriat' in response.url or 'rent' in response.url:
            item['deal_type'] = DealTypeEnum.RENT.value
        elif 'vanzare' in response.url or 'vinde' in response.url:
            item['deal_type'] = DealTypeEnum.BUY.value

        # Area/Size
        area_text = response.css('ul.lista-tabelara li:contains("Suprafață") span::text').get()
        if area_text:
            area_match = re.search(r'(\d+)', area_text)
            if area_match:
                item['square_meters'] = int(area_match.group(1))

        # Rooms
        rooms_text = response.css('ul.lista-tabelara li:contains("Număr camere") span::text').get()
        if rooms_text:
            item['room_count'] = safe_int(rooms_text)

        # Floor
        floor_text = response.css('ul.lista-tabelara li:contains("Etaj") span::text').get()
        if floor_text:
            floor_match = re.search(r'(\d+)', floor_text)
            if floor_match:
                item['floor'] = int(floor_match.group(1))

        # Year built
        year_text = response.css('ul.lista-tabelara li:contains("An construcție") span::text').get()
        if year_text:
            year_match = re.search(r'(\d{4})', year_text)
            if year_match:
                item['year_built'] = int(year_match.group(1))

        # Location information
        item['country'] = 'Romania'

        # County/Județ
        county_text = response.css('ul.breadcrumb li a[href*="judet"]::text').get()
        if county_text:
            item['county'] = county_text.replace('Județul', '').strip()

        # City
        city_text = response.css('ul.breadcrumb li a[href*="oras"]::text').get()
        if city_text:
            item['city'] = city_text
        else:
            # Try to get from address
            address_parts = response.css('div.localizare span::text').getall()
            if address_parts:
                item['city'] = address_parts[0] if address_parts else None

        # Neighborhood
        neighborhood_text = response.css('ul.breadcrumb li:last-child a::text').get()
        if neighborhood_text and neighborhood_text != item.get('city'):
            item['neighborhood'] = neighborhood_text

        # Full address
        address_parts = response.css('div.localizare::text').getall()
        if address_parts:
            item['address'] = ', '.join(address_parts).strip()

        # Features
        features = response.css('ul.lista-tabelara li')
        for feature in features:
            label = feature.css('::text').get()
            if label:
                label_lower = label.lower()

                # Bathrooms
                if 'băi' in label_lower or 'bai' in label_lower:
                    value = feature.css('span::text').get()
                    if value:
                        item['bathrooms'] = safe_int(value)

                # Balconies
                if 'balcon' in label_lower:
                    value = feature.css('span::text').get()
                    if value and value.strip() != '0':
                        item['has_balcony'] = True
                        item['balcony_count'] = safe_int(value)

                # Parking
                if 'parcare' in label_lower:
                    value = feature.css('span::text').get()
                    if value and 'da' in value.lower():
                        item['has_garage'] = True

                # Comfort level
                if 'confort' in label_lower:
                    value = feature.css('span::text').get()
                    if value:
                        item['comfort_level'] = value.strip()

                # Construction type
                if 'compartimentare' in label_lower:
                    value = feature.css('span::text').get()
                    if value:
                        item['partitioning'] = value.strip()

        # Images - just count them, don't store
        images = response.css('div.galerie img::attr(src)').getall()
        if images:
            item['photo_count'] = len(images)

        # Agency info
        agency_name = response.css('div.contact-agentie h3::text').get()
        if agency_name:
            item['agency'] = agency_name.strip()

        # Listing date
        listing_date = response.css('span.data-actualizare::text').get()
        if listing_date:
            # Parse Romanian date format
            try:
                # Example: "Actualizat la 15 septembrie 2024"
                date_match = re.search(r'(\d+)\s+(\w+)\s+(\d{4})', listing_date)
                if date_match:
                    item['listing_date'] = date_match.group(0)
            except:
                pass

        # Status - check if property is still active
        status_text = response.css('div.status-anunt::text').get()
        if status_text and ('indisponibil' in status_text.lower() or 'inchiriat' in status_text.lower()):
            item['status'] = PropertyStatusEnum.AD_INACTIVE.value
        else:
            item['status'] = PropertyStatusEnum.AD_ACTIVE.value

        # Generate fingerprint for deduplication
        item['fingerprint'] = f"{self.external_source}_{property_id}"

        self.logger.info(f"[PARSE_PROPERTY] Scraped: {item.get('title', 'No title')} - {item.get('price_ron', item.get('price_eur', 'No price'))} - {item.get('city', 'No city')}")

        yield item