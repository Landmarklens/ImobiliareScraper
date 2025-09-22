# -*- coding: utf-8 -*-
"""
Selenium middleware using undetected-chromedriver to bypass Cloudflare
"""
import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from scrapy.http import HtmlResponse
from scrapy import signals
from scrapy.exceptions import IgnoreRequest
import logging
import time
import random
from typing import Optional


class UndetectedChromeMiddleware:
    """Middleware to use undetected-chromedriver for bypassing Cloudflare"""

    def __init__(self, driver_path=None, headless=True, proxy_enabled=False):
        self.logger = logging.getLogger(__name__)
        self.driver_path = driver_path
        self.headless = headless
        self.proxy_enabled = proxy_enabled
        self.driver: Optional[uc.Chrome] = None
        self.request_count = 0
        self.max_requests_per_driver = 50  # Recreate driver after N requests

    @classmethod
    def from_crawler(cls, crawler):
        """Initialize from crawler settings"""
        middleware = cls(
            driver_path=crawler.settings.get('CHROME_DRIVER_PATH'),
            headless=crawler.settings.getbool('SELENIUM_HEADLESS', True),
            proxy_enabled=crawler.settings.getbool('SELENIUM_PROXY_ENABLED', False)
        )
        crawler.signals.connect(middleware.spider_closed, signal=signals.spider_closed)
        return middleware

    def _create_driver(self, proxy_url=None):
        """Create a new undetected Chrome driver instance"""
        try:
            # Chrome options for stealth
            chrome_options = uc.ChromeOptions()

            # Add stealth options
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-web-security')
            chrome_options.add_argument('--disable-features=VizDisplayCompositor')
            chrome_options.add_argument('--disable-extensions')

            # Random window size to appear more human
            window_sizes = [(1920, 1080), (1366, 768), (1440, 900), (1536, 864)]
            width, height = random.choice(window_sizes)
            chrome_options.add_argument(f'--window-size={width},{height}')

            # User agent rotation
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            ]
            chrome_options.add_argument(f'user-agent={random.choice(user_agents)}')

            # Add proxy if provided
            if proxy_url and self.proxy_enabled:
                # Format: http://user:pass@host:port
                chrome_options.add_argument(f'--proxy-server={proxy_url}')
                self.logger.info(f"[SELENIUM] Using proxy: {proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url}")

            # Headless mode for production
            if self.headless:
                chrome_options.add_argument('--headless=new')  # New headless mode
                self.logger.info("[SELENIUM] Running in headless mode")

            # Create driver with undetected-chromedriver
            driver = uc.Chrome(
                options=chrome_options,
                driver_executable_path=self.driver_path,
                version_main=None  # Auto-detect Chrome version
            )

            # Set additional stealth settings
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": driver.execute_script("return navigator.userAgent").replace("Headless", "")
            })

            # Remove webdriver property
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            # Add random delays to appear more human
            driver.implicitly_wait(random.uniform(2, 4))

            self.logger.info("[SELENIUM] Created new undetected Chrome driver")
            return driver

        except Exception as e:
            self.logger.error(f"[SELENIUM] Failed to create driver: {e}")
            return None

    def _wait_for_page_load(self, driver, timeout=30):
        """Wait for page to fully load and bypass Cloudflare if needed"""
        try:
            # Wait for basic page load
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # Check for Cloudflare challenge
            if "checking your browser" in driver.page_source.lower() or "cloudflare" in driver.page_source.lower():
                self.logger.info("[SELENIUM] Cloudflare challenge detected, waiting...")
                time.sleep(5)  # Wait for challenge to complete

                # Wait for redirect or content change
                WebDriverWait(driver, 15).until_not(
                    EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "checking your browser")
                )

            # Additional wait for dynamic content
            time.sleep(random.uniform(1, 2))

            # Check if we have actual content
            body_text = driver.find_element(By.TAG_NAME, "body").text
            if len(body_text) < 100:
                self.logger.warning(f"[SELENIUM] Page has minimal content: {len(body_text)} chars")

        except Exception as e:
            self.logger.error(f"[SELENIUM] Error waiting for page load: {e}")

    def process_request(self, request, spider):
        """Process request using Selenium for property pages only"""

        # Only use Selenium for individual property pages
        if '/oferta/' not in request.url or request.url.endswith('.xml'):
            spider.logger.debug(f"[SELENIUM_SKIP] Not a property page, skipping: {request.url}")
            return None  # Let Scrapy handle sitemaps normally

        spider.logger.info(f"[SELENIUM] Intercepting property page request: {request.url}")
        self.logger.info(f"[SELENIUM] Processing property page: {request.url}")

        try:
            # Check if we need to recreate driver
            if self.request_count >= self.max_requests_per_driver:
                if self.driver:
                    self.driver.quit()
                    self.driver = None
                self.request_count = 0

            # Create driver if needed
            if not self.driver:
                proxy_url = request.meta.get('proxy')
                self.driver = self._create_driver(proxy_url)
                if not self.driver:
                    self.logger.error(f"[SELENIUM] Failed to create driver for {request.url}")
                    # Return an error response instead of None
                    return HtmlResponse(
                        url=request.url,
                        status=500,
                        body=b'<html><body>Selenium driver creation failed</body></html>',
                        encoding='utf-8',
                        request=request
                    )

            # Load the page
            self.driver.get(request.url)
            self.request_count += 1

            # Wait for page to load and handle Cloudflare
            self._wait_for_page_load(self.driver)

            # Check if we got the actual property page
            current_url = self.driver.current_url
            page_source = self.driver.page_source

            # Log success metrics
            self.logger.info(f"[SELENIUM_SUCCESS] Loaded {current_url} - {len(page_source)} bytes")

            # Check for price indicators to confirm it's a real property page
            has_price = any(indicator in page_source for indicator in ['EUR', 'RON', 'listing_price', '"price"'])
            if has_price:
                self.logger.info(f"[SELENIUM_VALID] Property page confirmed with price data")
            else:
                self.logger.warning(f"[SELENIUM_WARNING] No price indicators found on page")

            # Return the response
            return HtmlResponse(
                url=current_url,
                body=page_source.encode('utf-8'),
                encoding='utf-8',
                request=request
            )

        except Exception as e:
            self.logger.error(f"[SELENIUM_ERROR] Failed to process {request.url}: {e}")
            # Return error response instead of None to prevent fallback to regular request
            return HtmlResponse(
                url=request.url,
                status=500,
                body=f'<html><body>Selenium error: {str(e)}</body></html>'.encode('utf-8'),
                encoding='utf-8',
                request=request
            )

    def spider_closed(self, spider):
        """Clean up when spider closes"""
        if self.driver:
            try:
                self.driver.quit()
                self.logger.info("[SELENIUM] Driver closed")
            except:
                pass