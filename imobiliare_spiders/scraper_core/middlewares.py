# Fixed WebshareProxyMiddleware for proper HTTPS proxy authentication

from scrapy import signals
from .user_agents import random_user_agent
import logging
import random
import requests
from scrapy.exceptions import NotConfigured
import base64
from urllib.parse import urlparse
import time
from datetime import datetime, timedelta
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from twisted.internet import defer

# useful for handling different item types with a single interface
from itemadapter import is_item, ItemAdapter


class ExponentialBackoffRetryMiddleware(RetryMiddleware):
    """Custom retry middleware with exponential backoff for rate limiting."""
    
    def __init__(self, settings):
        super().__init__(settings)
        self.base_delay = settings.getfloat('RETRY_BACKOFF_BASE', 2.0)
        self.max_delay = settings.getfloat('RETRY_BACKOFF_MAX', 60.0)
        self.logger = logging.getLogger(__name__)
    
    def process_response(self, request, response, spider):
        """Handle rate limiting responses with exponential backoff."""
        if response.status in [429, 503]:  # Rate limiting or service unavailable
            reason = f"Rate limited ({response.status})"
            retry_times = request.meta.get('retry_times', 0) + 1
            
            # Calculate exponential backoff delay
            delay = min(self.base_delay * (2 ** retry_times), self.max_delay)
            
            # Check for Retry-After header
            retry_after = response.headers.get('Retry-After')
            if retry_after:
                try:
                    delay = max(delay, int(retry_after))
                    self.logger.info(f"Server requested retry after {retry_after} seconds")
                except (ValueError, TypeError):
                    pass
            
            self.logger.warning(
                f"Rate limited on {request.url}. Retrying in {delay:.1f} seconds "
                f"(attempt {retry_times}/{self.max_retry_times})"
            )
            
            # Create retry request with delay
            retryreq = self._retry(request, reason, spider)
            if retryreq:
                retryreq.dont_filter = True
                retryreq.meta['download_delay'] = delay
                # Use deferred to implement the delay
                d = defer.Deferred()
                d.addCallback(lambda _: retryreq)
                spider.crawler.engine.download_delay = delay
                return d
            
        return super().process_response(request, response, spider)
    
    def process_exception(self, request, exception, spider):
        """Handle exceptions with exponential backoff."""
        if isinstance(exception, (TimeoutError, ConnectionError)):
            retry_times = request.meta.get('retry_times', 0) + 1
            delay = min(self.base_delay * (2 ** retry_times), self.max_delay)
            
            self.logger.warning(
                f"Connection error on {request.url}. Retrying in {delay:.1f} seconds "
                f"(attempt {retry_times}/{self.max_retry_times})"
            )
            
            retryreq = self._retry(request, exception, spider)
            if retryreq:
                retryreq.meta['download_delay'] = delay
                return retryreq
        
        return super().process_exception(request, exception, spider)


class WebshareProxyMiddleware:
    """Fixed middleware to properly handle Webshare.io proxy authentication"""

    @classmethod
    def from_crawler(cls, crawler):
        if not crawler.settings.getbool("PROXY_ENABLED"):
            raise NotConfigured("WebshareProxyMiddleware is disabled")

        api_key = crawler.settings.get("WEBSHARE_API_KEY")
        if not api_key:
            raise NotConfigured("WEBSHARE_API_KEY is not set")

        # Get refresh interval from settings (default 3 hours)
        refresh_hours = crawler.settings.getfloat("PROXY_REFRESH_HOURS", 3.0)
        
        middleware = cls(
            api_key=api_key, 
            api_url=crawler.settings.get("WEBSHARE_API_URL"),
            refresh_hours=refresh_hours
        )
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signal=signals.spider_closed)
        return middleware

    def __init__(self, api_key, api_url, refresh_hours=3.0):
        self.api_key = api_key
        self.api_url = api_url
        self.refresh_hours = refresh_hours
        self.proxies = []
        self.logger = logging.getLogger(__name__)
        self.proxy_usage = {}
        self.total_requests = 0
        self.proxied_requests = 0
        self.last_refresh_time = None
        self.refresh_interval = timedelta(hours=refresh_hours)
        self.failed_proxy_attempts = {}  # Track failed attempts per proxy
        self.max_proxy_failures = 3  # Max failures before removing a proxy

    def spider_opened(self, spider):
        self.refresh_proxies()  # Use refresh instead of fetch to set timestamp
        if self.proxies:
            spider.logger.info(f"Loaded {len(self.proxies)} proxies from webshare.io")
            spider.logger.info(f"Proxies will refresh every {self.refresh_hours} hours")
            # Show sample proxies
            for i, proxy_info in enumerate(self.proxies[:3]):
                spider.logger.info(f"Proxy {i+1}: {proxy_info['address']}")
            if len(self.proxies) > 3:
                spider.logger.info(f"...and {len(self.proxies)-3} more proxies")

    def spider_closed(self, spider):
        spider.logger.info(f"Proxy usage summary:")
        spider.logger.info(f"- Total requests: {self.total_requests}")
        spider.logger.info(
            f"- Requests with proxy: {self.proxied_requests} ({self.proxied_requests/max(1, self.total_requests)*100:.1f}%)"
        )

        if self.proxy_usage:
            sorted_usage = sorted(
                self.proxy_usage.items(), key=lambda x: x[1], reverse=True
            )
            spider.logger.info("Top 5 most used proxies:")
            for proxy_domain, count in sorted_usage[:5]:
                spider.logger.info(f"- {proxy_domain}: {count} requests")

    def fetch_proxies(self):
        """Fetch proxy list from webshare.io API"""
        try:
            url = f"{self.api_url}"
            headers = {"Authorization": f"Token {self.api_key}"}
            params = {"mode": "direct", "page_size": 100}  # Add required mode parameter

            self.logger.info(f"Fetching proxies from webshare.io API")
            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if "results" in data:
                    self.proxies = []
                    for proxy in data["results"]:
                        if proxy.get("valid"):
                            # Store proxy info in a structured way
                            proxy_info = {
                                'url': f"http://{proxy['username']}:{proxy['password']}@{proxy['proxy_address']}:{proxy['port']}",
                                'host': proxy['proxy_address'],
                                'port': proxy['port'],
                                'username': proxy['username'],
                                'password': proxy['password'],
                                'address': f"{proxy['proxy_address']}:{proxy['port']}",
                                'country_code': proxy.get('country_code', 'Unknown')
                            }
                            self.proxies.append(proxy_info)

                    self.logger.info(f"Successfully loaded {len(self.proxies)} proxies")
                else:
                    self.logger.error("No proxy results found in webshare.io response")
            else:
                self.logger.error(
                    f"Failed to fetch proxies: {response.status_code} - {response.text}"
                )
        except Exception as e:
            self.logger.error(f"Error fetching webshare proxies: {str(e)}")
    
    def should_refresh_proxies(self):
        """Check if it's time to refresh proxies"""
        if not self.last_refresh_time:
            return True
        
        time_since_refresh = datetime.now() - self.last_refresh_time
        return time_since_refresh >= self.refresh_interval
    
    def refresh_proxies(self):
        """Fetch fresh proxy list from webshare.io API"""
        self.logger.info(f"Refreshing proxy list from webshare.io...")
        
        # Store old proxies in case refresh fails
        old_proxies = self.proxies.copy() if self.proxies else []
        
        try:
            self.fetch_proxies()
            self.last_refresh_time = datetime.now()
            
            if len(self.proxies) > 0:
                self.failed_proxy_attempts.clear()  # Reset failure tracking on successful refresh
                self.logger.info(
                    f"Proxy refresh complete. Old count: {len(old_proxies)}, New count: {len(self.proxies)}"
                )
            else:
                # Restore old proxies if refresh returned empty
                self.logger.error("Refresh returned no proxies! Keeping old proxies.")
                self.proxies = old_proxies
            
        except Exception as e:
            self.logger.error(f"Failed to refresh proxies: {e}. Keeping old proxies.")
            self.proxies = old_proxies
    
    def get_random_proxy(self):
        """Get a random working proxy, filtering out failed ones"""
        if not self.proxies:
            return None
        
        # Handle both string and dict proxy formats
        if isinstance(self.proxies[0], str):
            # Legacy format: proxies are strings
            # Convert to dict format for consistency
            proxy_url = random.choice(self.proxies)
            return {
                'url': proxy_url,
                'address': proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url,
                'host': '',
                'port': '',
                'username': '',
                'password': ''
            }
        
        # Modern format: proxies are dicts
        # Filter out proxies that have failed too many times
        working_proxies = [
            p for p in self.proxies 
            if self.failed_proxy_attempts.get(p['address'], 0) < self.max_proxy_failures
        ]
        
        if not working_proxies:
            # All proxies have failed, reset failure counts and try again
            self.logger.warning("All proxies have failed. Resetting failure counts.")
            self.failed_proxy_attempts.clear()
            working_proxies = self.proxies
        
        return random.choice(working_proxies) if working_proxies else None
    
    def mark_proxy_failure(self, proxy_address):
        """Mark a proxy as having failed"""
        if not proxy_address or proxy_address == "unknown":
            return
            
        self.failed_proxy_attempts[proxy_address] = self.failed_proxy_attempts.get(proxy_address, 0) + 1
        failure_count = self.failed_proxy_attempts[proxy_address]
        
        if failure_count >= self.max_proxy_failures:
            self.logger.warning(f"Proxy {proxy_address} has failed {failure_count} times and will be avoided")

    def process_request(self, request, spider):
        self.total_requests += 1

        # Check if we need to refresh proxies (but not on every request to avoid overhead)
        if self.total_requests % 100 == 0:  # Check every 100 requests
            if self.should_refresh_proxies():
                spider.logger.info("Proxy refresh interval reached, refreshing proxy list...")
                self.refresh_proxies()

        if not self.proxies:
            spider.logger.warning(
                "No proxies available, attempting to fetch..."
            )
            self.refresh_proxies()
            
            if not self.proxies:
                spider.logger.error(
                    "No proxies available after refresh attempt. Check WEBSHARE_API_KEY."
                )
                return

        # Handle retry scenario - need to assign a new proxy
        if "proxy" in request.meta:
            if request.meta.get('retry_times', 0) > 0:
                # This is a retry, we need to get a different proxy
                old_proxy = request.meta.get('proxy', '')
                
                # Mark old proxy as failed if it was a proxy error
                if request.meta.get('proxy_failed'):
                    old_address = request.meta.get('proxy_address', '')
                    if old_address:
                        self.mark_proxy_failure(old_address)
                        spider.logger.info(f"[PROXY_RETRY] Retry #{request.meta.get('retry_times')} for {request.url} - Previous proxy {old_address} marked as failed")
                
                # Select a new proxy for the retry
                proxy_data = self.get_random_proxy()
                if not proxy_data:
                    spider.logger.error(f"[PROXY_ERROR] No working proxies available for retry of {request.url}")
                    return
                
                # Update proxy information
                request.meta["proxy"] = proxy_data['url']
                request.meta["proxy_full_url"] = proxy_data['url']
                request.meta["proxy_address"] = proxy_data['address']
                spider.logger.info(f"[PROXY_RETRY] Using new proxy {proxy_data['address']} for retry of {request.url}")
                
            # If not a retry and already has proxy, skip
            else:
                self.proxied_requests += 1
                return

        # New request without proxy - assign one
        else:
            proxy_data = self.get_random_proxy()
            
            if not proxy_data:
                spider.logger.error(f"[PROXY_ERROR] No working proxies available for {request.url}")
                return
            
            # Set proxy for request (proxy_data is always a dictionary from get_random_proxy)
            request.meta["proxy"] = proxy_data['url']
            request.meta["proxy_full_url"] = proxy_data['url']
            request.meta["proxy_address"] = proxy_data['address']
            
            self.proxied_requests += 1
            self.proxy_usage[proxy_data['address']] = self.proxy_usage.get(proxy_data['address'], 0) + 1
            
            spider.logger.info(f"[PROXY_ASSIGN] Request #{self.total_requests}: Using proxy {proxy_data['address']} for {request.url}")

    def process_response(self, request, response, spider):
        if "proxy" in request.meta:
            proxy_address = request.meta.get("proxy_address", "unknown")
            status = response.status
            
            # Log all responses with proxy info
            if status == 200:
                spider.logger.info(f"[PROXY_SUCCESS] {status} response for {request.url} using proxy {proxy_address}")
            else:
                spider.logger.warning(f"[PROXY_RESPONSE] {status} response for {request.url} using proxy {proxy_address}")

            if 200 <= status < 300:
                # Success - reset failure count for this proxy
                if proxy_address in self.failed_proxy_attempts and proxy_address != "unknown":
                    self.failed_proxy_attempts[proxy_address] = 0
                    
            elif status == 407:
                # Proxy authentication failed
                spider.logger.error(f"[PROXY_AUTH_FAIL] Authentication failed (407) for {proxy_address} on {request.url}")
                self.mark_proxy_failure(proxy_address)
                
                # Force refresh if too many proxies are failing auth
                failed_count = sum(1 for v in self.failed_proxy_attempts.values() if v >= 2)
                total_proxies = len(self.proxies) if self.proxies else 1  # Avoid division by zero
                
                if failed_count > total_proxies / 2:
                    spider.logger.warning(f"[PROXY_REFRESH] {failed_count}/{total_proxies} proxies failing auth, forcing refresh...")
                    self.refresh_proxies()
                
                # Mark for retry with different proxy
                request.meta['proxy_failed'] = True
                
            elif status in [403, 429]:
                # Blocked or rate limited
                spider.logger.warning(f"[PROXY_BLOCKED] {status} - Blocked/Rate limited for {request.url} using proxy {proxy_address}")
                self.mark_proxy_failure(proxy_address)
                request.meta['proxy_failed'] = True
        else:
            # Log direct requests (no proxy)
            spider.logger.info(f"[DIRECT_REQUEST] {response.status} response for {request.url} (no proxy)")

        return response

    def process_exception(self, request, exception, spider):
        if "proxy" in request.meta:
            proxy_address = request.meta.get("proxy_address", "unknown")
            
            # Log the exception type for debugging
            exception_type = type(exception).__name__
            spider.logger.error(f"[PROXY_EXCEPTION] {exception_type} for {request.url} using proxy {proxy_address}: {str(exception)[:200]}")
            
            # Mark proxy as failed
            self.mark_proxy_failure(proxy_address)
            request.meta['proxy_failed'] = True
            
            # If it's a proxy-specific error, we might want to refresh
            if "407" in str(exception) or "ProxyError" in exception_type:
                spider.logger.warning(f"[PROXY_ERROR] Proxy-specific error detected for {proxy_address}, may need to refresh proxy list")
        else:
            # Log exceptions for direct requests
            exception_type = type(exception).__name__
            spider.logger.error(f"[DIRECT_EXCEPTION] {exception_type} for {request.url} (no proxy): {str(exception)[:200]}")
                
        return None  # Let Scrapy's retry middleware handle the retry


class CustomUserAgentMiddleware(object):
    """Middleware to set custom User-Agent headers"""

    def __init__(self, user_agent=''):
        self.user_agent = user_agent

    @classmethod
    def from_crawler(cls, crawler):
        user_agent = crawler.settings.get('IMOBILIARE_USER_AGENT',
                                         crawler.settings.get('USER_AGENT', ''))
        return cls(user_agent=user_agent)

    def process_request(self, request, spider):
        if self.user_agent:
            request.headers.setdefault('User-Agent', self.user_agent)
        else:
            # Fall back to random user agent if no custom one set
            ua = random_user_agent()
            if ua:
                request.headers.setdefault("User-Agent", ua)


class RandomUserAgentMiddleware(object):
    def process_request(self, request, spider):
        ua = random_user_agent()
        if ua:
            request.headers.setdefault("User-Agent", ua)


class PythonSpidersSpiderMiddleware:
    # Not all methods need to be defined. If a method is not defined,
    # scrapy acts as if the spider middleware does not modify the
    # passed objects.

    @classmethod
    def from_crawler(cls, crawler):
        # This method is used by Scrapy to create your spiders.
        s = cls()
        crawler.signals.connect(s.spider_opened, signal=signals.spider_opened)
        return s

    def process_spider_input(self, response, spider):
        # Called for each response that goes through the spider
        # middleware and into the spider.

        # Should return None or raise an exception.
        return None

    def process_spider_output(self, response, result, spider):
        # Called with the results returned from the Spider, after
        # it has processed the response.

        # Must return an iterable of Request, or item objects.
        for i in result:
            yield i

    def process_spider_exception(self, response, exception, spider):
        # Called when a spider or process_spider_input() method
        # (from other spider middleware) raises an exception.

        # Should return either None or an iterable of Request or item objects.
        pass

    def process_start_requests(self, start_requests, spider):
        # Called with the start requests of the spider, and works
        # similarly to the process_spider_output() method, except
        # that it doesn't have a response associated.

        # Must return only requests (not items).
        for r in start_requests:
            yield r

    def spider_opened(self, spider):
        spider.logger.info("Spider opened: %s" % spider.name)


class PythonSpidersDownloaderMiddleware:
    # Not all methods need to be defined. If a method is not defined,
    # scrapy acts as if the downloader middleware does not modify the
    # passed objects.

    @classmethod
    def from_crawler(cls, crawler):
        # This method is used by Scrapy to create your spiders.
        s = cls()
        crawler.signals.connect(s.spider_opened, signal=signals.spider_opened)
        return s

    def process_request(self, request, spider):
        # Called for each request that goes through the downloader
        # middleware.

        # Must either:
        # - return None: continue processing this request
        # - or return a Response object
        # - or return a Request object
        # - or raise IgnoreRequest: process_exception() methods of
        #   installed downloader middleware will be called
        return None

    def process_response(self, request, response, spider):
        # Called with the response returned from the downloader.

        # Must either;
        # - return a Response object
        # - return a Request object
        # - or raise IgnoreRequest
        return response

    def process_exception(self, request, exception, spider):
        # Called when a download handler or a process_request()
        # (from other downloader middleware) raises an exception.

        # Must either:
        # - return None: continue processing this exception
        # - return a Response object: stops process_exception() chain
        # - return a Request object: stops process_exception() chain
        pass

    def spider_opened(self, spider):
        spider.logger.info("Spider opened: %s" % spider.name)


class ProxyMiddleware(object):
    def __init__(self, settings):
        super(ProxyMiddleware, self).__init__()
        self.proxy_host = settings.get("PROXY_HOST")
        self.proxy_username = settings.get("PROXY_USERNAME")
        self.proxy_password = settings.get("PROXY_PASSWORD")
        self.proxy_on = settings.get("PROXY_ON", False)

    @classmethod
    def from_crawler(cls, crawler):
        obj = cls(crawler.settings)
        return obj

    def process_request(self, request, spider):

        if self.proxy_on:

            proxy_user_pass = f"{self.proxy_username}:{self.proxy_password}"
            request.meta["proxy"] = f"http://{proxy_user_pass}@{self.proxy_host}"


class RetryMiddleware(ExponentialBackoffRetryMiddleware):
    """Alias for ExponentialBackoffRetryMiddleware for backward compatibility"""
    pass


class HeadersMiddleware:
    """Middleware to handle custom headers for requests"""

    def __init__(self, settings):
        self.custom_headers = settings.getdict('CUSTOM_HEADERS', {})

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings)

    def process_request(self, request, spider):
        for header, value in self.custom_headers.items():
            request.headers.setdefault(header.encode(), value.encode())


class StartUrlValidationMiddleware:
    """Spider middleware to validate start URLs"""

    def process_start_requests(self, start_requests, spider):
        for request in start_requests:
            spider.logger.info(f"Processing start URL: {request.url}")
            yield request