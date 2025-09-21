# -*- coding: utf-8 -*-
"""
Imobiliare.ro scraper using curl-cffi for TLS fingerprint bypass
This spider uses curl-cffi which impersonates real browsers at the TLS level
"""
import scrapy
from scrapy.http import HtmlResponse
from curl_cffi import requests as curl_requests
import random
import time
import json
from datetime import datetime

from ...helper import safe_int, safe_float
from ...models import DealTypeEnum, PropertyStatusEnum
from ...property_type_mapping_ro import standardize_property_type


class ImobiliareCurlCffiSpider(scrapy.Spider):
    name = "imobiliare_curlcffi"
    country = "romania"
    locale = "ro"
    external_source = "imobiliare_ro"

    custom_settings = {
        'CONCURRENT_REQUESTS': 2,
        'DOWNLOAD_DELAY': 3,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'ROBOTSTXT_OBEY': False,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.limit = int(kwargs.get('limit', 20))
        self.deal_type = kwargs.get('deal_type', 'rent').lower()
        self.scraped_count = 0

        # Create session with browser impersonation
        self.session = curl_requests.Session(
            impersonate="chrome120",  # Impersonate Chrome 120
            timeout=30,
            verify=True
        )

        # Set headers that match real Chrome
        self.session.headers.update({
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'accept-language': 'ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    def start_requests(self):
        """Start with sitemap or listing pages"""
        # First, try to establish a session
        self.logger.info("[CURL-CFFI] Establishing session...")

        # Visit homepage first to get cookies
        try:
            home_response = self.session.get('https://www.imobiliare.ro')
            self.logger.info(f"[CURL-CFFI] Homepage status: {home_response.status_code}")

            # Store cookies
            self.cookies = home_response.cookies

        except Exception as e:
            self.logger.error(f"[CURL-CFFI] Failed to establish session: {e}")

        # Try sitemap approach first
        yield scrapy.Request(
            url='https://www.imobiliare.ro/sitemap-listings-index-ro.xml',
            callback=self.parse_sitemap_index,
            meta={'curlcffi': True}
        )

    def download_with_curlcffi(self, url):
        """Download a page using curl-cffi"""
        try:
            # Add random delay
            time.sleep(random.uniform(2, 5))

            # Rotate user agents
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ]

            self.session.headers['user-agent'] = random.choice(user_agents)

            # Make request
            response = self.session.get(url, cookies=self.cookies)

            self.logger.info(f"[CURL-CFFI] Downloaded {url}: Status {response.status_code}")

            return response

        except Exception as e:
            self.logger.error(f"[CURL-CFFI] Error downloading {url}: {e}")
            return None

    def parse_sitemap_index(self, response):
        """Parse sitemap index"""
        if response.meta.get('curlcffi'):
            # Download with curl-cffi
            cffi_response = self.download_with_curlcffi(response.url)
            if cffi_response and cffi_response.status_code == 200:
                # Create Scrapy response
                response = HtmlResponse(
                    url=response.url,
                    body=cffi_response.content,
                    encoding='utf-8'
                )

        # Parse sitemap for rental properties
        if self.deal_type == 'rent':
            patterns = ['apartments-for-rent', 'houses-villas-for-rent', 'studios-for-rent']
        else:
            patterns = ['apartments-for-sale', 'houses-villas-for-sale', 'studios-for-sale']

        sitemaps = response.xpath('//loc/text()').getall()
        for sitemap_url in sitemaps:
            if any(pattern in sitemap_url for pattern in patterns):
                yield scrapy.Request(
                    url=sitemap_url,
                    callback=self.parse_property_sitemap,
                    meta={'curlcffi': True}
                )

    def parse_property_sitemap(self, response):
        """Parse property sitemap"""
        if response.meta.get('curlcffi'):
            # Download with curl-cffi
            cffi_response = self.download_with_curlcffi(response.url)
            if cffi_response and cffi_response.status_code == 200:
                response = HtmlResponse(
                    url=response.url,
                    body=cffi_response.content,
                    encoding='utf-8'
                )

        # Get property URLs
        property_urls = response.xpath('//loc/text()').getall()

        for url in property_urls[:self.limit]:
            if '/oferta/' in url:
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_property,
                    meta={'curlcffi': True}
                )

    def parse_property(self, response):
        """Parse individual property with curl-cffi"""
        # Download with curl-cffi
        cffi_response = self.download_with_curlcffi(response.url)

        if not cffi_response:
            return

        if cffi_response.status_code != 200:
            self.logger.warning(f"[CURL-CFFI] Failed to get property: {response.url} (Status: {cffi_response.status_code})")
            return

        # Create Scrapy response
        response = HtmlResponse(
            url=response.url,
            body=cffi_response.content,
            encoding='utf-8'
        )

        # Check if blocked
        if 'datadome' in cffi_response.text.lower() or 'captcha' in cffi_response.text.lower():
            self.logger.warning(f"[CURL-CFFI] Blocked by DataDome on: {response.url}")
            return

        self.logger.info(f"[CURL-CFFI] Successfully accessed property: {response.url}")

        # Extract property data
        item = {}

        # Basic information
        item['external_source'] = self.external_source
        item['external_url'] = response.url
        item['external_id'] = response.url.split('-')[-1]

        # Title
        item['title'] = response.css('h1::text').get() or response.css('[class*="title"]::text').get()

        # Description
        item['description'] = response.css('[class*="description"]::text').get()

        # Price
        price_elem = response.css('[class*="price"]::text').get()
        if price_elem:
            import re
            price_match = re.search(r'([\d,\.]+)', price_elem.replace(' ', ''))
            if price_match:
                price = float(price_match.group(1).replace(',', '').replace('.', ''))
                if '€' in price_elem or 'EUR' in price_elem:
                    item['price_eur'] = price
                    item['currency'] = 'EUR'
                else:
                    item['price_ron'] = price
                    item['currency'] = 'RON'

        # Property details from structured data
        json_ld = response.css('script[type="application/ld+json"]::text').get()
        if json_ld:
            try:
                data = json.loads(json_ld)
                if isinstance(data, dict):
                    # Extract from JSON-LD
                    item['title'] = item.get('title') or data.get('name')
                    item['description'] = item.get('description') or data.get('description')

                    if 'offers' in data:
                        offer = data['offers']
                        if 'price' in offer:
                            price = float(offer['price'])
                            currency = offer.get('priceCurrency', 'RON')
                            if currency == 'EUR':
                                item['price_eur'] = price
                            else:
                                item['price_ron'] = price
                            item['currency'] = currency

                    # Address
                    if 'address' in data:
                        addr = data['address']
                        item['address'] = addr.get('streetAddress')
                        item['city'] = addr.get('addressLocality')
                        item['country'] = addr.get('addressCountry', 'Romania')

            except json.JSONDecodeError:
                pass

        # Property features
        features = response.css('[class*="features"] li')
        for feature in features:
            label = feature.css('::text').get()
            if label:
                label_lower = label.lower()
                if 'camere' in label_lower:
                    item['room_count'] = safe_int(label)
                elif 'mp' in label_lower or 'suprafață' in label_lower:
                    item['square_meters'] = safe_int(label)
                elif 'etaj' in label_lower:
                    item['floor'] = safe_int(label)
                elif 'băi' in label_lower:
                    item['bathrooms'] = safe_int(label)

        # Deal type
        if 'inchiriat' in response.url or 'inchirieri' in response.url:
            item['deal_type'] = DealTypeEnum.RENT.value
        else:
            item['deal_type'] = DealTypeEnum.BUY.value

        # Property type
        if 'apartament' in response.url:
            item['property_type'] = 'apartment'
        elif 'casa' in response.url or 'vila' in response.url:
            item['property_type'] = 'house'
        elif 'garsoniera' in response.url:
            item['property_type'] = 'studio'
        else:
            item['property_type'] = 'apartment'

        # Status
        item['status'] = PropertyStatusEnum.AD_ACTIVE.value

        # Fingerprint
        item['fingerprint'] = f"{self.external_source}_{item['external_id']}"

        # Country
        item['country'] = 'Romania'

        self.logger.info(f"[CURL-CFFI] Scraped: {item.get('title')} - Price: {item.get('price_ron', item.get('price_eur'))}")

        self.scraped_count += 1
        yield item