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


class ImobiliareSitemapSpider(SitemapSpider):
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

    # Custom settings - WITH PROXIES to bypass DataDome
    custom_settings = {
        'CONCURRENT_REQUESTS': 4,  # Can increase with proxies
        'DOWNLOAD_DELAY': 2.0,  # Shorter delay with proxies
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'ROBOTSTXT_OBEY': False,  # Skip robots.txt for now
        'PROXY_ENABLED': True,  # Enable proxy middleware
        'COOKIES_ENABLED': True,  # Enable cookie handling
        'COOKIES_DEBUG': False,  # Set to True for cookie debugging
        'LOG_LEVEL': 'INFO',  # Changed from DEBUG to reduce logs
        'DOWNLOADER_MIDDLEWARES': {
            'scrapy.downloadermiddlewares.cookies.CookiesMiddleware': 350,  # Enable cookies
            'scraper_core.middlewares.CustomUserAgentMiddleware': 400,
            'scraper_core.middlewares.WebshareProxyMiddleware': 410,  # Enable residential proxies
            'scraper_core.middlewares.ExponentialBackoffRetryMiddleware': 500,
            'scraper_core.middlewares.HeadersMiddleware': 550,
        },
        # Add specific headers to mimic browser
        'DEFAULT_REQUEST_HEADERS': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
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
        self.logger.info(f"[PARSE_HEADERS] Headers sent: {response.request.headers}")
        self.logger.info(f"[PARSE_COOKIES] Cookies: {response.request.cookies}")
        self.logger.info(f"[PARSE_META] Request meta: {response.request.meta}")

        # Check if property exists (404, etc.)
        if response.status != 200:
            self.logger.warning(f"[PARSE_PROPERTY] Property not available: {response.url} (status: {response.status})")
            return

        # Extract property ID from URL
        url_parts = response.url.split('/')
        property_id = url_parts[-1] if url_parts[-1] else url_parts[-2]

        # Check for DataDome challenge or minimal content
        if 'datadome' in response.text.lower() or 'cloudflare' in response.text.lower():
            self.logger.error(f"[BLOCKED] Blocked by anti-bot on property page: {response.url}")
            # Log what we're actually getting
            self.logger.info(f"[BLOCKED_CONTENT] Response length: {len(response.text)} bytes")
            self.logger.info(f"[BLOCKED_HEADERS] Response headers: {response.headers}")
            self.logger.info(f"[BLOCKED_STATUS] Response status: {response.status}")
            self.logger.info(f"[BLOCKED_COOKIES] Response cookies: {response.cookies}")
            self.logger.info(f"[BLOCKED_SAMPLE] First 1000 chars: {response.text[:1000]}")
            # Save a sample for inspection
            import os
            debug_path = '/tmp/blocked_response_sample.html'
            with open(debug_path, 'w') as f:
                f.write(response.text)
            self.logger.info(f"[DEBUG] Saved blocked response to {debug_path}")
            return

        # Debug: Check what we're getting
        if len(response.text) < 1000:
            self.logger.warning(f"[MINIMAL_CONTENT] Page has very little content ({len(response.text)} bytes): {response.url}")
            self.logger.debug(f"[CONTENT_SAMPLE] First 500 chars: {response.text[:500]}")
            return

        # Log successful response details
        self.logger.info(f"[SUCCESS_PARSE] Processing {response.url} - Content length: {len(response.text)} bytes")
        self.logger.info(f"[SUCCESS_HEADERS] Response headers: {response.headers}")
        self.logger.info(f"[SUCCESS_COOKIES] Response cookies: {response.cookies}")

        # Check for various page indicators
        has_title_tag = '<title>' in response.text
        has_body_tag = '<body' in response.text
        has_imobiliare_text = 'imobiliare.ro' in response.text
        self.logger.info(f"[PAGE_CHECK] Has title tag: {has_title_tag}, Has body tag: {has_body_tag}, Has imobiliare text: {has_imobiliare_text}")

        # Check for price indicators in the response
        price_indicators = ['EUR', 'RON', 'lei', '€', 'euro']
        has_price_text = any(indicator in response.text for indicator in price_indicators)
        self.logger.info(f"[PRICE_CHECK] Has price indicators: {has_price_text}")

        # Check for specific price patterns
        import re
        has_listing_price = 'listing_price' in response.text
        has_price_json = '"price"' in response.text
        has_wire_snapshot = 'wire:snapshot' in response.text
        self.logger.info(f"[PRICE_PATTERNS] Has listing_price: {has_listing_price}, Has price JSON: {has_price_json}, Has Livewire: {has_wire_snapshot}")

        # Debug: Log available selectors to understand page structure
        self.logger.debug(f"[DEBUG] H1 found: {response.css('h1::text').get()}")
        self.logger.debug(f"[DEBUG] Title tag: {response.css('title::text').get()}")
        json_ld_selector = 'script[type="application/ld+json"]'
        self.logger.debug(f"[DEBUG] JSON-LD scripts: {len(response.css(json_ld_selector).getall())}")
        meta_og_selector = 'meta[property="og:title"]::attr(content)'
        self.logger.debug(f"[DEBUG] Meta og:title: {response.css(meta_og_selector).get()}")

        # Initialize item
        item = {}

        # Basic information
        item['external_source'] = self.external_source
        item['external_url'] = response.url
        item['external_id'] = property_id

        # Try multiple selectors for title - expanded for proxy pages
        item['title'] = (response.css('h1::text').get() or
                         response.css('h1 *::text').get() or  # Sometimes text is in nested elements
                         response.css('[class*="title"]::text').get() or
                         response.css('[class*="Title"]::text').get() or
                         response.css('[data-testid*="title"]::text').get() or
                         response.css('.listing-title::text').get() or
                         response.css('.property-title::text').get() or
                         response.css('meta[property="og:title"]::attr(content)').get() or
                         response.css('meta[name="twitter:title"]::attr(content)').get() or
                         response.css('title::text').get() or
                         "Property " + property_id)

        # Try to extract from JSON-LD structured data
        json_ld = response.css('script[type="application/ld+json"]::text').get()
        if json_ld:
            self.logger.info(f"[JSON_LD] Found JSON-LD data, length: {len(json_ld)}")
            try:
                import json
                data = json.loads(json_ld)
                if isinstance(data, dict):
                    self.logger.info(f"[JSON_LD] Keys in JSON-LD: {list(data.keys())}")
                    item['title'] = item['title'] or data.get('name')
                    item['description'] = data.get('description')
                    if 'offers' in data:
                        price_info = data['offers']
                        self.logger.info(f"[JSON_LD_PRICE] Found offers: {price_info}")
                        if 'price' in price_info:
                            item['price'] = float(price_info['price'])
                            item['currency'] = price_info.get('priceCurrency', 'RON')
                            self.logger.info(f"[JSON_LD_EXTRACTED] Price from JSON-LD: {item['price']} {item['currency']}")
            except Exception as e:
                self.logger.error(f"[JSON_LD_ERROR] Failed to parse JSON-LD: {e}")

        # Try to extract from dataLayer JavaScript (fallback for when JSON-LD is not available)
        if not item.get('price') and not item.get('price_ron') and not item.get('price_eur'):
            # Try dataLayer first
            datalayer_match = re.search(r'window\.dataLayer\.push\((.*?)\);', response.text, re.DOTALL)
            if datalayer_match:
                self.logger.info(f"[DATALAYER] Found dataLayer.push, extracting...")
                try:
                    # Extract the JavaScript object
                    js_obj = datalayer_match.group(1)
                    self.logger.debug(f"[DATALAYER_CONTENT] First 500 chars: {js_obj[:500]}")

                    # Look for price and currency in the object
                    price_match = re.search(r'"listing_price"\s*:\s*"([0-9.]+)"', js_obj)
                    currency_match = re.search(r'"listing_currency"\s*:\s*"([A-Z]+)"', js_obj)

                    self.logger.info(f"[DATALAYER_REGEX] Price match: {bool(price_match)}, Currency match: {bool(currency_match)}")

                    if price_match:
                        price = float(price_match.group(1))
                        currency = currency_match.group(1) if currency_match else 'RON'
                        self.logger.info(f"[DATALAYER_VALUES] Extracted price: {price}, currency: {currency}")

                        if currency == 'EUR':
                            item['price_eur'] = price
                        else:
                            item['price_ron'] = price
                        item['currency'] = currency
                        self.logger.info(f"[PRICE_FROM_DATALAYER] Found price {price} {currency} from dataLayer")
                    else:
                        self.logger.warning(f"[DATALAYER_NO_PRICE] No price found in dataLayer")
                except Exception as e:
                    self.logger.error(f"[DATALAYER_ERROR] Could not extract price from dataLayer: {e}")
            else:
                self.logger.info(f"[DATALAYER_NOT_FOUND] No dataLayer.push found in response")

            # Try Livewire data as another fallback
            if not item.get('price_ron') and not item.get('price_eur'):
                self.logger.info(f"[LIVEWIRE_SEARCH] Searching for Livewire data...")
                # Look for Livewire wire:snapshot data
                livewire_match = re.search(r'wire:snapshot="([^"]+)"', response.text)
                if livewire_match:
                    self.logger.info(f"[LIVEWIRE_FOUND] Found wire:snapshot attribute")
                    try:
                        import html
                        # Decode the HTML entities
                        livewire_data = html.unescape(livewire_match.group(1))
                        self.logger.debug(f"[LIVEWIRE_CONTENT] First 500 chars: {livewire_data[:500]}")

                        # Look for price in the JSON-like structure
                        price_match = re.search(r'"price":(\d+)', livewire_data)
                        currency_match = re.search(r'"price_currency":"([A-Z]+)"', livewire_data)

                        self.logger.info(f"[LIVEWIRE_REGEX] Price match: {bool(price_match)}, Currency match: {bool(currency_match)}")

                        if price_match:
                            price = float(price_match.group(1))
                            currency = currency_match.group(1) if currency_match else 'RON'
                            self.logger.info(f"[LIVEWIRE_VALUES] Extracted price: {price}, currency: {currency}")

                            if currency == 'EUR':
                                item['price_eur'] = price
                            else:
                                item['price_ron'] = price
                            item['currency'] = currency
                            self.logger.info(f"[PRICE_FROM_LIVEWIRE] Found price {price} {currency} from Livewire data")
                        else:
                            self.logger.warning(f"[LIVEWIRE_NO_PRICE] No price found in Livewire data")
                    except Exception as e:
                        self.logger.error(f"[LIVEWIRE_ERROR] Could not extract price from Livewire data: {e}")
                else:
                    self.logger.info(f"[LIVEWIRE_NOT_FOUND] No wire:snapshot found in response")

        # Description from meta or content
        if not item.get('description'):
            item['description'] = (response.css('meta[property="og:description"]::attr(content)').get() or
                                   response.css('meta[name="description"]::attr(content)').get() or
                                   response.css('[class*="description"]::text').get())

        # Price - try multiple selectors - expanded for proxy pages
        if not item.get('price') and not item.get('price_ron') and not item.get('price_eur'):
            # Try various price selectors
            price_selectors = [
                '[class*="price"]::text',
                '[class*="Price"]::text',
                '[class*="pret"]::text',
                '[class*="Pret"]::text',
                '[data-testid*="price"]::text',
                '.listing-price::text',
                '.property-price::text',
                '[class*="cost"]::text',
                'span[class*="price"] *::text',  # Nested price
                'div[class*="price"] *::text',   # Nested price
                'meta[property="og:price:amount"]::attr(content)',
                'meta[property="product:price:amount"]::attr(content)'
            ]

            price_text = None
            for selector in price_selectors:
                price_text = response.css(selector).get()
                if price_text:
                    self.logger.debug(f"[DEBUG] Price found with selector {selector}: {price_text}")
                    break

            if price_text:
                self.logger.info(f"[PRICE_FOUND] Found price text: {price_text}")
                # Clean price text and extract number
                price_match = re.search(r'([\d,\.]+)', price_text.replace(' ', ''))
                if price_match:
                    price = float(price_match.group(1).replace(',', '').replace('.', ''))
                    self.logger.info(f"[PRICE_EXTRACTED] Extracted price value: {price}")

                    # Determine currency
                    currency_meta = response.css('meta[property="og:price:currency"]::attr(content)').get()
                    if currency_meta:
                        item['currency'] = currency_meta
                        if currency_meta == 'EUR':
                            item['price_eur'] = price
                        else:
                            item['price_ron'] = price
                    elif '€' in price_text or 'EUR' in price_text:
                        item['price_eur'] = price
                        item['currency'] = 'EUR'
                    else:
                        item['price_ron'] = price
                        item['currency'] = 'RON'

                    self.logger.info(f"[PRICE_SET] Set price - RON: {item.get('price_ron')}, EUR: {item.get('price_eur')}")
                else:
                    self.logger.warning(f"[PRICE_NO_MATCH] Could not extract number from price text: {price_text}")
            else:
                self.logger.warning(f"[NO_PRICE] No price found for {response.url}")
                # Log additional debug info when no price is found
                self.logger.debug(f"[NO_PRICE_DEBUG] Checked selectors: {price_selectors}")
                self.logger.debug(f"[NO_PRICE_DEBUG] Page title: {response.css('title::text').get()}")
                self.logger.debug(f"[NO_PRICE_DEBUG] Has any price text in HTML: {'EUR' in response.text or 'RON' in response.text or 'lei' in response.text}")

        # Property type - multiple approaches
        property_type_text = None

        # Try table-based selectors
        property_type_text = response.css('ul.lista-tabelara li:contains("Tip") span::text').get()

        # Try other common patterns
        if not property_type_text:
            property_type_text = (response.css('[class*="property-type"]::text').get() or
                                 response.css('[class*="tip-proprietate"]::text').get() or
                                 response.css('[data-testid*="property-type"]::text').get())

        # Extract from URL if not found
        if not property_type_text:
            if 'apartament' in response.url:
                property_type_text = 'apartament'
            elif 'garsoniera' in response.url:
                property_type_text = 'garsoniera'
            elif 'casa' in response.url or 'vila' in response.url:
                property_type_text = 'casa'

        if property_type_text:
            item['property_type'] = standardize_property_type(property_type_text)

        # Deal type
        if 'inchiriat' in response.url or 'rent' in response.url:
            item['deal_type'] = DealTypeEnum.RENT.value
        elif 'vanzare' in response.url or 'vinde' in response.url:
            item['deal_type'] = DealTypeEnum.BUY.value

        # Area/Size - multiple approaches
        area_text = response.css('ul.lista-tabelara li:contains("Suprafață") span::text').get()

        # Try other selectors if not found
        if not area_text:
            area_selectors = [
                '[class*="suprafata"]::text',
                '[class*="surface"]::text',
                '[class*="area"]::text',
                '[class*="mp"]::text',
                '[class*="sqm"]::text',
                '[data-testid*="area"]::text',
                'span:contains("mp")::text',
                'span:contains("m²")::text'
            ]
            for selector in area_selectors:
                try:
                    area_text = response.css(selector).get()
                    if area_text:
                        break
                except:
                    pass

        if area_text:
            area_match = re.search(r'(\d+)', area_text)
            if area_match:
                item['square_meters'] = int(area_match.group(1))
                self.logger.debug(f"[DEBUG] Area found: {item['square_meters']} sqm")

        # Rooms - multiple approaches
        rooms_text = response.css('ul.lista-tabelara li:contains("Număr camere") span::text').get()

        if not rooms_text:
            rooms_text = response.css('ul.lista-tabelara li:contains("camere") span::text').get()

        if not rooms_text:
            # Try other selectors
            rooms_selectors = [
                '[class*="camere"]::text',
                '[class*="rooms"]::text',
                '[data-testid*="rooms"]::text',
                'span:contains("camere")::text'
            ]
            for selector in rooms_selectors:
                try:
                    rooms_text = response.css(selector).get()
                    if rooms_text:
                        break
                except:
                    pass

        if rooms_text:
            item['room_count'] = safe_int(rooms_text)
            self.logger.debug(f"[DEBUG] Rooms found: {item['room_count']}")

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

        # Try to extract city from URL patterns
        if not item.get('city'):
            # URLs often contain city name: /oferta/apartament-de-inchiriat-CITY-...
            url_parts = response.url.split('/')[-1].split('-')
            # Common patterns: apartament-de-inchiriat-CITY or garsoniera-de-inchiriat-CITY
            if 'inchiriat' in response.url or 'vanzare' in response.url:
                for i, part in enumerate(url_parts):
                    if part in ['inchiriat', 'vanzare', 'vinde']:
                        # City is usually the next part
                        if i + 1 < len(url_parts):
                            city_candidate = url_parts[i + 1]
                            # Filter out common non-city words
                            if city_candidate not in ['mobilat', 'mobilata', 'nemobilat', 'nemobilata', 'central', 'ultracentral']:
                                item['city'] = city_candidate.capitalize()
                                break

        # Try meta tags for location
        if not item.get('city'):
            location_meta = response.css('meta[property="og:locality"]::attr(content)').get()
            if location_meta:
                item['city'] = location_meta

        # Address from meta
        item['address'] = response.css('meta[property="og:street-address"]::attr(content)').get()

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
        # Extract numeric ID from the property_id to ensure it fits in database field
        import re
        numeric_id_match = re.search(r'\d+$', property_id)
        if numeric_id_match:
            numeric_id = numeric_id_match.group()
        else:
            # Fallback to using last 10 chars if no numeric ID found
            numeric_id = property_id[-10:] if len(property_id) > 10 else property_id

        # Ensure fingerprint fits in varchar(64)
        item['fingerprint'] = f"{self.external_source}_{numeric_id}"[:64]

        # Final logging before yielding
        self.logger.info(f"[ITEM_FINAL] Final item for {property_id}:")
        self.logger.info(f"[ITEM_PRICE] Price RON: {item.get('price_ron')}, Price EUR: {item.get('price_eur')}, Currency: {item.get('currency')}")
        self.logger.info(f"[ITEM_BASIC] Title: {item.get('title', 'No title')[:100]}")
        self.logger.info(f"[ITEM_LOCATION] City: {item.get('city')}, Country: {item.get('country')}")
        self.logger.info(f"[ITEM_PROPERTY] Type: {item.get('property_type')}, Deal: {item.get('deal_type')}")
        self.logger.info(f"[ITEM_SIZE] Area: {item.get('size')}, Rooms: {item.get('room_count')}, Floor: {item.get('floor')}")
        self.logger.info(f"[ITEM_STATUS] Status: {item.get('status')}, Fingerprint: {item.get('fingerprint')}")

        # Summary log
        price_str = f"{item.get('price_ron')} RON" if item.get('price_ron') else (f"{item.get('price_eur')} EUR" if item.get('price_eur') else "No price")
        self.logger.info(f"[PARSE_PROPERTY] Scraped: Property {property_id} - {price_str} - {item.get('city', 'No city')}")

        yield item