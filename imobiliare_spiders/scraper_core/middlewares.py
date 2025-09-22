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
import json
from typing import Dict, List, Optional, Set
from collections import defaultdict

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
        self.logger = logging.getLogger(__name__)

        # Proxy pools with intelligent management
        self.proxy_pools = {
            'active': [],        # Currently working proxies
            'quarantine': {},    # {proxy_address: {'until': datetime, 'failures': int}}
            'blacklist': set()   # Permanently failed this session
        }

        # Replacement quota tracking
        self.replacement_quota = {
            'used': 0,
            'limit': 100,  # Default limit, will be updated from API
            'reset_date': None,
            'last_check': None
        }

        # Performance metrics
        self.proxy_metrics = defaultdict(lambda: {
            'success': 0,
            'failures': 0,
            'last_success': None,
            'last_failure': None,
            'response_times': [],
            'blocked_count': 0
        })

        # Quarantine settings
        self.quarantine_durations = [
            timedelta(minutes=30),   # First quarantine
            timedelta(hours=2),      # Second quarantine
            timedelta(hours=6)       # Third quarantine
        ]

        # General tracking
        self.proxy_usage = {}
        self.total_requests = 0
        self.proxied_requests = 0
        self.last_refresh_time = None
        self.refresh_interval = timedelta(hours=refresh_hours)
        self.last_ondemand_refresh = None
        self.ondemand_refresh_cooldown = timedelta(minutes=5)

    def spider_opened(self, spider):
        self.refresh_proxies()  # Initial fetch
        self.check_replacement_quota()  # Check initial quota

        active_count = len(self.proxy_pools['active'])
        if active_count > 0:
            spider.logger.info(f"[PROXY_INIT] Loaded {active_count} active proxies from webshare.io")
            spider.logger.info(f"[PROXY_QUOTA] Replacement quota: {self.replacement_quota['limit'] - self.replacement_quota['used']} remaining")
            spider.logger.info(f"[PROXY_SETTINGS] Refresh interval: {self.refresh_hours}h, Max failures: 3")

            # Show sample proxies
            for i, proxy_info in enumerate(self.proxy_pools['active'][:3]):
                spider.logger.info(f"[PROXY_SAMPLE] Proxy {i+1}: {proxy_info['address']}")
            if active_count > 3:
                spider.logger.info(f"[PROXY_INFO] ...and {active_count-3} more proxies available")

    def spider_closed(self, spider):
        spider.logger.info(f"[PROXY_SUMMARY] === Proxy Usage Summary ===")
        spider.logger.info(f"[PROXY_STATS] Total requests: {self.total_requests}")
        spider.logger.info(
            f"[PROXY_STATS] Proxied requests: {self.proxied_requests} ({self.proxied_requests/max(1, self.total_requests)*100:.1f}%)"
        )

        # Pool status
        spider.logger.info(f"[PROXY_POOLS] Active: {len(self.proxy_pools['active'])}, "
                          f"Quarantined: {len(self.proxy_pools['quarantine'])}, "
                          f"Blacklisted: {len(self.proxy_pools['blacklist'])}")

        # Replacement quota
        spider.logger.info(f"[PROXY_QUOTA] Replacements used: {self.replacement_quota['used']}/{self.replacement_quota['limit']}")

        # Top performing proxies
        if self.proxy_metrics:
            sorted_metrics = sorted(
                self.proxy_metrics.items(),
                key=lambda x: x[1]['success'] / max(1, x[1]['success'] + x[1]['failures']),
                reverse=True
            )
            spider.logger.info("[PROXY_TOP] Top 5 best performing proxies:")
            for proxy_addr, metrics in sorted_metrics[:5]:
                success_rate = metrics['success'] / max(1, metrics['success'] + metrics['failures']) * 100
                spider.logger.info(
                    f"  - {proxy_addr}: {success_rate:.1f}% success "
                    f"({metrics['success']}/{metrics['success'] + metrics['failures']} requests)"
                )

    def fetch_proxies(self):
        """Fetch proxy list from webshare.io API"""
        try:
            url = f"{self.api_url}"
            headers = {"Authorization": f"Token {self.api_key}"}
            params = {"mode": "direct", "page_size": 100}

            self.logger.info(f"[PROXY_FETCH] Fetching proxies from webshare.io API")
            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if "results" in data:
                    new_proxies = []
                    for proxy in data["results"]:
                        if proxy.get("valid"):
                            proxy_info = {
                                'url': f"http://{proxy['username']}:{proxy['password']}@{proxy['proxy_address']}:{proxy['port']}",
                                'host': proxy['proxy_address'],
                                'port': proxy['port'],
                                'username': proxy['username'],
                                'password': proxy['password'],
                                'address': f"{proxy['proxy_address']}:{proxy['port']}",
                                'country_code': proxy.get('country_code', 'Unknown'),
                                'id': proxy.get('id')  # Store ID for replacement API
                            }

                            # Don't add if blacklisted
                            if proxy_info['address'] not in self.proxy_pools['blacklist']:
                                new_proxies.append(proxy_info)

                    # Update active pool, preserving non-blacklisted proxies
                    self.proxy_pools['active'] = new_proxies
                    self.logger.info(f"[PROXY_FETCH] Successfully loaded {len(new_proxies)} proxies")
                else:
                    self.logger.error("[PROXY_FETCH] No proxy results found in response")
            else:
                self.logger.error(
                    f"[PROXY_FETCH] Failed to fetch proxies: {response.status_code} - {response.text}"
                )
        except Exception as e:
            self.logger.error(f"[PROXY_FETCH] Error fetching proxies: {str(e)}")
    
    def should_refresh_proxies(self):
        """Check if it's time to refresh proxies"""
        if not self.last_refresh_time:
            return True
        
        time_since_refresh = datetime.now() - self.last_refresh_time
        return time_since_refresh >= self.refresh_interval
    
    def refresh_proxies(self):
        """Fetch fresh proxy list from webshare.io API"""
        self.logger.info(f"[PROXY_REFRESH] Refreshing proxy list...")

        # Store old proxies in case refresh fails
        old_active = self.proxy_pools['active'].copy()

        try:
            self.fetch_proxies()
            self.last_refresh_time = datetime.now()

            if len(self.proxy_pools['active']) > 0:
                # Clear quarantine on successful refresh (but not blacklist)
                self.proxy_pools['quarantine'].clear()
                self.logger.info(
                    f"[PROXY_REFRESH] Complete. Old: {len(old_active)}, New: {len(self.proxy_pools['active'])}"
                )
            else:
                # Restore old proxies if refresh returned empty
                self.logger.error("[PROXY_REFRESH] No proxies returned! Keeping old proxies.")
                self.proxy_pools['active'] = old_active

        except Exception as e:
            self.logger.error(f"[PROXY_REFRESH] Failed: {e}. Keeping old proxies.")
            self.proxy_pools['active'] = old_active
    
    def get_best_proxy(self) -> Optional[Dict]:
        """Get the best available proxy using intelligent selection"""

        # First, check quarantine and recover proxies if cooldown expired
        self._check_quarantine_recovery()

        # Get available proxies (active + recovered from quarantine)
        available_proxies = self.proxy_pools['active'].copy()

        if not available_proxies:
            # No active proxies, try emergency recovery
            return self._emergency_proxy_recovery()

        # Sort by success rate (best performers first)
        def proxy_score(proxy):
            addr = proxy['address']
            metrics = self.proxy_metrics[addr]
            total = metrics['success'] + metrics['failures']
            if total == 0:
                return 0.5  # Neutral score for unused proxies
            return metrics['success'] / total

        # Sort proxies by performance
        sorted_proxies = sorted(available_proxies, key=proxy_score, reverse=True)

        # Use weighted random selection (better proxies more likely)
        # Top 20% get 50% chance, next 30% get 30% chance, rest get 20%
        total = len(sorted_proxies)
        if total >= 5:
            weights = []
            top_20_percent = max(1, int(total * 0.2))
            next_30_percent = max(1, int(total * 0.3))

            for i in range(total):
                if i < top_20_percent:
                    weights.append(5)  # Higher weight for top performers
                elif i < top_20_percent + next_30_percent:
                    weights.append(3)  # Medium weight
                else:
                    weights.append(1)  # Lower weight for poor performers

            return random.choices(sorted_proxies, weights=weights, k=1)[0]
        else:
            # Too few proxies, just pick randomly
            return random.choice(sorted_proxies)
    
    def mark_proxy_failure(self, proxy_address: str, status_code: int = None):
        """Mark a proxy as having failed with intelligent handling"""
        if not proxy_address or proxy_address == "unknown":
            return

        # Update metrics
        metrics = self.proxy_metrics[proxy_address]
        metrics['failures'] += 1
        metrics['last_failure'] = datetime.now()

        # Handle based on failure type
        if status_code == 403:
            # Cloudflare block - quarantine
            metrics['blocked_count'] += 1
            self._quarantine_proxy(proxy_address, metrics['blocked_count'])

            # Check if replacement needed
            if metrics['blocked_count'] >= 2:
                self._try_replace_proxy(proxy_address)

        elif status_code == 407:
            # Auth failure - likely bad proxy, blacklist immediately
            self.logger.warning(f"[PROXY_AUTH_FAIL] Blacklisting {proxy_address} due to auth failure")
            self._blacklist_proxy(proxy_address)
            self._try_replace_proxy(proxy_address)

        elif status_code in [429, 503]:
            # Rate limit - temporary quarantine
            self._quarantine_proxy(proxy_address, 1)  # Short quarantine

        else:
            # General failure
            if metrics['failures'] >= 3:
                self._quarantine_proxy(proxy_address, 2)  # Medium quarantine

    def _quarantine_proxy(self, proxy_address: str, severity: int = 1):
        """Move proxy to quarantine with time-based recovery"""
        # Find the proxy data before removing
        proxy_data = next(
            (p for p in self.proxy_pools['active'] if p['address'] == proxy_address),
            None
        )

        # Remove from active pool
        self.proxy_pools['active'] = [
            p for p in self.proxy_pools['active']
            if p['address'] != proxy_address
        ]

        # Calculate quarantine duration based on severity
        duration_index = min(severity - 1, len(self.quarantine_durations) - 1)
        duration = self.quarantine_durations[duration_index]
        until = datetime.now() + duration

        # Add to quarantine
        self.proxy_pools['quarantine'][proxy_address] = {
            'until': until,
            'failures': severity,
            'proxy_data': proxy_data
        }

        self.logger.info(
            f"[PROXY_QUARANTINE] {proxy_address} quarantined until {until.strftime('%H:%M:%S')} "
            f"(severity: {severity}, duration: {duration})"
        )

    def _blacklist_proxy(self, proxy_address: str):
        """Permanently blacklist a proxy for this session"""
        # Remove from all pools
        self.proxy_pools['active'] = [
            p for p in self.proxy_pools['active']
            if p['address'] != proxy_address
        ]
        self.proxy_pools['quarantine'].pop(proxy_address, None)
        self.proxy_pools['blacklist'].add(proxy_address)

        self.logger.warning(f"[PROXY_BLACKLIST] {proxy_address} permanently blacklisted")

    def _check_quarantine_recovery(self):
        """Check and recover proxies from quarantine if cooldown expired"""
        now = datetime.now()
        recovered = []

        for proxy_addr, info in list(self.proxy_pools['quarantine'].items()):
            if now >= info['until']:
                # Recover proxy
                proxy_data = info.get('proxy_data')
                if proxy_data and proxy_data not in self.proxy_pools['active']:
                    self.proxy_pools['active'].append(proxy_data)
                    recovered.append(proxy_addr)

                    # Reset some metrics for fresh start
                    metrics = self.proxy_metrics[proxy_addr]
                    metrics['blocked_count'] = max(0, metrics['blocked_count'] - 1)

        # Remove recovered proxies from quarantine
        for addr in recovered:
            del self.proxy_pools['quarantine'][addr]
            self.logger.info(f"[PROXY_RECOVERY] {addr} recovered from quarantine")

    def _emergency_proxy_recovery(self) -> Optional[Dict]:
        """Emergency recovery when no proxies available"""
        self.logger.warning("[PROXY_EMERGENCY] No active proxies available, attempting recovery...")

        # 1. Try to recover from quarantine immediately
        if self.proxy_pools['quarantine']:
            # Get least recently quarantined
            earliest_addr = min(
                self.proxy_pools['quarantine'].keys(),
                key=lambda x: self.proxy_pools['quarantine'][x]['until']
            )
            info = self.proxy_pools['quarantine'][earliest_addr]
            proxy_data = info.get('proxy_data')

            if proxy_data:
                self.logger.info(f"[PROXY_EMERGENCY] Force recovering {earliest_addr} from quarantine")
                del self.proxy_pools['quarantine'][earliest_addr]
                self.proxy_pools['active'].append(proxy_data)
                return proxy_data

        # 2. Try on-demand refresh if cooldown passed
        if self._can_ondemand_refresh():
            self.logger.info("[PROXY_EMERGENCY] Attempting on-demand refresh...")
            self._ondemand_refresh()
            if self.proxy_pools['active']:
                return random.choice(self.proxy_pools['active'])

        # 3. As last resort, clear blacklist and refresh
        if self.proxy_pools['blacklist']:
            self.logger.warning("[PROXY_EMERGENCY] Clearing blacklist and refreshing...")
            self.proxy_pools['blacklist'].clear()
            self.refresh_proxies()
            if self.proxy_pools['active']:
                return random.choice(self.proxy_pools['active'])

        self.logger.error("[PROXY_EMERGENCY] All recovery attempts failed!")
        return None

    def check_replacement_quota(self):
        """Check remaining replacement quota from Webshare API"""
        try:
            headers = {"Authorization": f"Token {self.api_key}"}
            # This endpoint would need to be confirmed with Webshare docs
            response = requests.get(
                "https://proxy.webshare.io/api/v2/proxy/config/",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                # Update quota info based on API response
                # Structure depends on actual API response
                self.replacement_quota['limit'] = data.get('replacement_limit', 100)
                self.replacement_quota['used'] = data.get('replacements_used', 0)
                self.replacement_quota['reset_date'] = data.get('reset_date')
                self.replacement_quota['last_check'] = datetime.now()

                self.logger.info(
                    f"[PROXY_QUOTA] Checked: {self.replacement_quota['limit'] - self.replacement_quota['used']} "
                    f"replacements remaining"
                )
        except Exception as e:
            self.logger.debug(f"[PROXY_QUOTA] Could not check quota: {e}")

    def _try_replace_proxy(self, proxy_address: str):
        """Try to replace a blocked proxy if quota available"""
        # Check if we have quota
        remaining = self.replacement_quota['limit'] - self.replacement_quota['used']

        if remaining <= 0:
            self.logger.warning(f"[PROXY_REPLACE] No replacement quota remaining, keeping {proxy_address}")
            return False

        # Find proxy ID if available
        proxy_data = next(
            (p for p in self.proxy_pools['active'] if p['address'] == proxy_address),
            None
        )

        if not proxy_data or not proxy_data.get('id'):
            self.logger.debug(f"[PROXY_REPLACE] No proxy ID for {proxy_address}, cannot request replacement")
            return False

        try:
            headers = {"Authorization": f"Token {self.api_key}"}

            # Request replacement (actual endpoint needs verification)
            response = requests.post(
                "https://proxy.webshare.io/api/v2/proxy-replacement/proxy_replacement/proxy_replacement_create",
                headers=headers,
                json={
                    "proxy_id": proxy_data['id'],
                    "reason": "blocked"
                },
                timeout=10
            )

            if response.status_code in [200, 201]:
                self.replacement_quota['used'] += 1
                self.logger.info(
                    f"[PROXY_REPLACE] Successfully requested replacement for {proxy_address}. "
                    f"Quota remaining: {self.replacement_quota['limit'] - self.replacement_quota['used']}"
                )

                # Blacklist the old proxy
                self._blacklist_proxy(proxy_address)

                # Trigger proxy refresh to get the replacement
                time.sleep(2)  # Give API time to process
                self.refresh_proxies()
                return True
            else:
                self.logger.error(
                    f"[PROXY_REPLACE] Failed to replace {proxy_address}: "
                    f"{response.status_code} - {response.text[:200]}"
                )
        except Exception as e:
            self.logger.error(f"[PROXY_REPLACE] Error replacing proxy: {e}")

        return False

    def _can_ondemand_refresh(self) -> bool:
        """Check if we can do an on-demand refresh (rate limited)"""
        if not self.last_ondemand_refresh:
            return True

        time_since = datetime.now() - self.last_ondemand_refresh
        return time_since >= self.ondemand_refresh_cooldown

    def _ondemand_refresh(self):
        """Force an on-demand proxy list refresh"""
        if not self._can_ondemand_refresh():
            self.logger.debug("[PROXY_ONDEMAND] Cooldown not expired, skipping")
            return

        try:
            headers = {"Authorization": f"Token {self.api_key}"}
            response = requests.post(
                "https://proxy.webshare.io/api/v2/proxy-list/ondemand_refresh",
                headers=headers,
                timeout=10
            )

            if response.status_code in [200, 201]:
                self.logger.info("[PROXY_ONDEMAND] On-demand refresh triggered successfully")
                self.last_ondemand_refresh = datetime.now()

                # Wait a moment then fetch new proxies
                time.sleep(3)
                self.fetch_proxies()
            else:
                self.logger.error(
                    f"[PROXY_ONDEMAND] Failed: {response.status_code} - {response.text[:200]}"
                )
        except Exception as e:
            self.logger.error(f"[PROXY_ONDEMAND] Error: {e}")

    def process_request(self, request, spider):
        self.total_requests += 1

        # Periodic maintenance checks
        if self.total_requests % 50 == 0:  # Every 50 requests
            # Check quarantine recovery
            self._check_quarantine_recovery()

            # Check if refresh needed
            if self.total_requests % 100 == 0:
                if self.should_refresh_proxies():
                    spider.logger.info("[PROXY_REFRESH] Scheduled refresh interval reached")
                    self.refresh_proxies()

                # Periodically check quota
                if self.total_requests % 500 == 0:
                    self.check_replacement_quota()

        # Check proxy availability
        if not self.proxy_pools['active']:
            spider.logger.warning("[PROXY_WARNING] No active proxies, attempting recovery...")
            proxy_data = self._emergency_proxy_recovery()
            if not proxy_data:
                spider.logger.error("[PROXY_ERROR] No proxies available after recovery attempts")
                return

        # Handle retry scenario - need different proxy
        if "proxy" in request.meta:
            if request.meta.get('retry_times', 0) > 0:
                # This is a retry, mark old proxy as failed
                old_address = request.meta.get('proxy_address', '')
                failure_status = request.meta.get('failure_status_code')

                if request.meta.get('proxy_failed') and old_address:
                    self.mark_proxy_failure(old_address, failure_status)
                    spider.logger.info(
                        f"[PROXY_RETRY] Retry #{request.meta.get('retry_times')} for {request.url} - "
                        f"Previous proxy {old_address} marked as failed (status: {failure_status})"
                    )

                # Get new proxy for retry
                proxy_data = self.get_best_proxy()
                if not proxy_data:
                    spider.logger.error(f"[PROXY_ERROR] No proxies for retry of {request.url}")
                    return

                # Update proxy information
                request.meta["proxy"] = proxy_data['url']
                request.meta["proxy_full_url"] = proxy_data['url']
                request.meta["proxy_address"] = proxy_data['address']
                spider.logger.info(
                    f"[PROXY_RETRY] Using new proxy {proxy_data['address']} for retry"
                )

            # If not retry and already has proxy, skip
            else:
                self.proxied_requests += 1
                return

        # New request without proxy - assign best available
        else:
            proxy_data = self.get_best_proxy()

            if not proxy_data:
                spider.logger.error(f"[PROXY_ERROR] No proxies available for {request.url}")
                return

            # Set proxy metadata
            request.meta["proxy"] = proxy_data['url']
            request.meta["proxy_full_url"] = proxy_data['url']
            request.meta["proxy_address"] = proxy_data['address']
            request.meta["request_start_time"] = time.time()  # Track response time

            self.proxied_requests += 1
            self.proxy_usage[proxy_data['address']] = self.proxy_usage.get(proxy_data['address'], 0) + 1

            spider.logger.info(
                f"[PROXY_ASSIGN] Request #{self.total_requests}: {proxy_data['address']} -> {request.url}"
            )

    def process_response(self, request, response, spider):
        if "proxy" in request.meta:
            proxy_address = request.meta.get("proxy_address", "unknown")
            status = response.status

            # Calculate response time
            if "request_start_time" in request.meta:
                response_time = time.time() - request.meta["request_start_time"]
                metrics = self.proxy_metrics[proxy_address]
                metrics['response_times'].append(response_time)
                # Keep only last 100 response times
                if len(metrics['response_times']) > 100:
                    metrics['response_times'] = metrics['response_times'][-100:]

            # Handle different response codes
            if 200 <= status < 300:
                # Success - update metrics
                metrics = self.proxy_metrics[proxy_address]
                metrics['success'] += 1
                metrics['last_success'] = datetime.now()

                spider.logger.info(
                    f"[PROXY_SUCCESS] {status} from {proxy_address} for {request.url} "
                    f"(response time: {response_time:.2f}s)"
                )

            elif status == 407:
                # Proxy authentication failed - immediate blacklist
                spider.logger.error(
                    f"[PROXY_AUTH_FAIL] 407 Auth failed for {proxy_address} on {request.url}"
                )
                self.mark_proxy_failure(proxy_address, 407)
                request.meta['proxy_failed'] = True
                request.meta['failure_status_code'] = 407

            elif status == 403:
                # Cloudflare block - quarantine and maybe replace
                spider.logger.warning(
                    f"[PROXY_BLOCKED] 403 Blocked for {proxy_address} on {request.url}"
                )
                self.mark_proxy_failure(proxy_address, 403)
                request.meta['proxy_failed'] = True
                request.meta['failure_status_code'] = 403

            elif status == 429:
                # Rate limited - temporary quarantine
                spider.logger.warning(
                    f"[PROXY_RATELIMIT] 429 Rate limited for {proxy_address} on {request.url}"
                )
                self.mark_proxy_failure(proxy_address, 429)
                request.meta['proxy_failed'] = True
                request.meta['failure_status_code'] = 429

            elif status in [500, 502, 503, 504]:
                # Server errors - might not be proxy's fault
                spider.logger.info(
                    f"[PROXY_SERVER_ERROR] {status} from {proxy_address} for {request.url} "
                    "(server error, not counting as proxy failure)"
                )

            else:
                # Other non-success codes
                spider.logger.warning(
                    f"[PROXY_RESPONSE] {status} from {proxy_address} for {request.url}"
                )
                metrics = self.proxy_metrics[proxy_address]
                metrics['failures'] += 1
                metrics['last_failure'] = datetime.now()

        else:
            # Direct request (no proxy)
            spider.logger.info(f"[DIRECT_REQUEST] {response.status} response for {request.url}")

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