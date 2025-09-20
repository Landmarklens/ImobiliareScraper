# -*- coding: utf-8 -*-
"""
Imobiliare.ro Playwright-based scraper for bypassing DataDome protection
This spider uses browser automation with stealth techniques
"""
import scrapy
from scrapy import signals
from scrapy.http import HtmlResponse
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
import random
import time
import json
from datetime import datetime

from ...helper import safe_int, safe_float
from ...models import DealTypeEnum, PropertyStatusEnum
from ...property_type_mapping_ro import standardize_property_type
from ..geocoding_mixin import GeocodingMixin


class ImobiliarePlaywrightSpider(GeocodingMixin, scrapy.Spider):
    name = "imobiliare_playwright"
    country = "romania"
    locale = "ro"
    external_source = "imobiliare_ro"

    custom_settings = {
        'CONCURRENT_REQUESTS': 1,  # Sequential for browser
        'DOWNLOAD_DELAY': 5,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'ROBOTSTXT_OBEY': False,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.limit = int(kwargs.get('limit', 20))
        self.deal_type = kwargs.get('deal_type', 'rent').lower()
        self.browser = None
        self.context = None
        self.page = None

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(spider.spider_closed, signal=signals.spider_closed)
        return spider

    def spider_opened(self, spider):
        """Initialize Playwright browser with stealth"""
        self.playwright = sync_playwright().start()

        # Launch browser with anti-detection args
        self.browser = self.playwright.chromium.launch(
            headless=True,  # Can set to False for debugging
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-accelerated-2d-canvas',
                '--disable-gpu',
                '--window-size=1920,1080',
                '--start-maximized',
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ]
        )

        # Create context with realistic viewport and settings
        self.context = self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='ro-RO',
            timezone_id='Europe/Bucharest',
            permissions=['geolocation'],
            geolocation={'latitude': 44.4268, 'longitude': 26.1025},  # Bucharest
            device_scale_factor=1,
            has_touch=False,
            is_mobile=False,
        )

        # Add cookies if needed
        self.context.add_cookies([
            {
                'name': 'cookieconsent_status',
                'value': 'dismiss',
                'domain': '.imobiliare.ro',
                'path': '/'
            }
        ])

        self.page = self.context.new_page()

        # Apply stealth techniques
        stealth_sync(self.page)

        # Additional evasion techniques
        self.page.add_init_script("""
            // Override navigator properties
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Override chrome property
            window.chrome = {
                runtime: {}
            };

            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );

            // Override plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ro-RO', 'ro', 'en-US', 'en']
            });
        """)

        self.logger.info(f"[PLAYWRIGHT] Browser initialized with stealth")

    def spider_closed(self, spider):
        """Clean up browser resources"""
        if self.page:
            self.page.close()
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def start_requests(self):
        """Generate initial requests based on deal type"""
        if self.deal_type == 'rent':
            urls = [
                'https://www.imobiliare.ro/inchirieri-apartamente/bucuresti',
                'https://www.imobiliare.ro/inchirieri-case-vile/bucuresti',
            ]
        else:  # buy
            urls = [
                'https://www.imobiliare.ro/vanzare-apartamente/bucuresti',
                'https://www.imobiliare.ro/vanzare-case-vile/bucuresti',
            ]

        for url in urls:
            yield scrapy.Request(
                url=url,
                callback=self.parse_with_playwright,
                meta={'playwright': True}
            )

    def parse_with_playwright(self, response):
        """Handle the request with Playwright browser"""
        try:
            # Navigate to the page
            self.logger.info(f"[PLAYWRIGHT] Navigating to: {response.url}")

            # Random delay before navigation
            time.sleep(random.uniform(2, 5))

            # Go to page with timeout
            self.page.goto(response.url, wait_until='networkidle', timeout=30000)

            # Wait for content to load
            self.page.wait_for_load_state('domcontentloaded')

            # Random mouse movements to appear human
            self.simulate_human_behavior()

            # Check if we got blocked
            if self.is_blocked():
                self.logger.warning(f"[PLAYWRIGHT] Blocked on {response.url}, trying to solve...")
                self.handle_challenge()

            # Get page content
            content = self.page.content()

            # Create a Scrapy response from the browser content
            playwright_response = HtmlResponse(
                url=self.page.url,
                body=content.encode('utf-8'),
                encoding='utf-8'
            )

            # Check if this is a listing page or property page
            if '/oferta/' in playwright_response.url:
                # Parse individual property
                yield from self.parse_property(playwright_response)
            else:
                # Parse listing page
                yield from self.parse_listing(playwright_response)

        except Exception as e:
            self.logger.error(f"[PLAYWRIGHT] Error processing {response.url}: {e}")

    def simulate_human_behavior(self):
        """Simulate human-like behavior"""
        # Random mouse movements
        for _ in range(random.randint(2, 5)):
            x = random.randint(100, 1820)
            y = random.randint(100, 980)
            self.page.mouse.move(x, y)
            time.sleep(random.uniform(0.1, 0.3))

        # Random scroll
        scroll_distance = random.randint(100, 500)
        self.page.evaluate(f"window.scrollBy(0, {scroll_distance})")
        time.sleep(random.uniform(0.5, 1.5))

    def is_blocked(self):
        """Check if we're blocked by DataDome"""
        indicators = [
            'datadome',
            'dd-challenge',
            'captcha',
            'Access denied',
            '403 Forbidden',
            'Just a moment'
        ]

        content = self.page.content().lower()
        return any(indicator.lower() in content for indicator in indicators)

    def handle_challenge(self):
        """Try to solve DataDome challenge"""
        self.logger.info("[PLAYWRIGHT] Attempting to solve challenge...")

        # Wait for potential redirect
        time.sleep(5)

        # Check for captcha iframe
        captcha_frame = self.page.query_selector('iframe[src*="captcha"]')
        if captcha_frame:
            self.logger.warning("[PLAYWRIGHT] Captcha detected - manual solve needed")
            # Here you could integrate with captcha solving service
            # like 2captcha or Anti-Captcha

        # Try clicking any challenge buttons
        challenge_button = self.page.query_selector('button:has-text("Continue")')
        if challenge_button:
            challenge_button.click()
            time.sleep(3)

    def parse_listing(self, response):
        """Parse listing page for property URLs"""
        property_links = response.css('a[href*="/oferta/"]::attr(href)').getall()

        self.logger.info(f"[PLAYWRIGHT] Found {len(property_links)} properties")

        count = 0
        for link in property_links:
            if count >= self.limit:
                break

            full_url = response.urljoin(link)
            yield scrapy.Request(
                url=full_url,
                callback=self.parse_with_playwright,
                meta={'playwright': True}
            )
            count += 1

        # Check for next page
        next_page = response.css('a[rel="next"]::attr(href)').get()
        if next_page and count < self.limit:
            yield scrapy.Request(
                url=response.urljoin(next_page),
                callback=self.parse_with_playwright,
                meta={'playwright': True}
            )

    def parse_property(self, response):
        """Parse individual property page"""
        self.logger.info(f"[PLAYWRIGHT] Parsing property: {response.url}")

        # Extract data (reuse extraction logic from sitemap spider)
        item = {}

        # Basic information
        item['external_source'] = self.external_source
        item['external_url'] = response.url
        item['external_id'] = response.url.split('-')[-1]

        # Title and description
        item['title'] = response.css('h1::text').get()
        item['description'] = response.css('.collapsible__content::text').get()

        # Price
        price_text = response.css('.info__price::text').get()
        if price_text:
            import re
            price_match = re.search(r'([\d,\.]+)', price_text.replace(' ', ''))
            if price_match:
                price = float(price_match.group(1).replace(',', '').replace('.', ''))
                if '€' in price_text:
                    item['price_eur'] = price
                    item['currency'] = 'EUR'
                else:
                    item['price_ron'] = price
                    item['currency'] = 'RON'

        # Property details
        details = response.css('.features__item')
        for detail in details:
            label = detail.css('.features__item__label::text').get()
            value = detail.css('.features__item__value::text').get()

            if label and value:
                label_lower = label.lower()

                if 'suprafață' in label_lower:
                    item['square_meters'] = safe_int(value)
                elif 'camere' in label_lower:
                    item['room_count'] = safe_int(value)
                elif 'etaj' in label_lower:
                    item['floor'] = safe_int(value)
                elif 'an construcție' in label_lower:
                    item['year_built'] = safe_int(value)
                elif 'băi' in label_lower:
                    item['bathrooms'] = safe_int(value)

        # Location
        item['country'] = 'Romania'
        item['city'] = response.css('.location__text::text').get()

        # Deal type
        if 'inchiriat' in response.url or 'inchirieri' in response.url:
            item['deal_type'] = DealTypeEnum.RENT.value
        else:
            item['deal_type'] = DealTypeEnum.BUY.value

        # Property type
        property_type_text = response.css('.property-type::text').get()
        if property_type_text:
            item['property_type'] = standardize_property_type(property_type_text)

        # Generate fingerprint
        item['fingerprint'] = f"{self.external_source}_{item['external_id']}"

        self.logger.info(f"[PLAYWRIGHT] Extracted: {item.get('title')} - {item.get('price_ron', item.get('price_eur'))}")

        yield item