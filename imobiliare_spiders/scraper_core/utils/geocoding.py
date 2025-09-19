# -*- coding: utf-8 -*-
"""
OpenCage Data Geocoding utility for extracting coordinates from addresses
"""
import os
import requests
import logging
from typing import Optional, Tuple, Dict, Any
from urllib.parse import quote
import time
import json
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class OpenCageGeocoder:
    """Geocode addresses using OpenCage Data API with caching and quota management"""
    
    def __init__(self, api_key: Optional[str] = None, proxy_url: Optional[str] = None):
        """Initialize geocoder with API key
        
        Args:
            api_key: OpenCage API key. If not provided, will try to get from environment
            proxy_url: Optional proxy URL for requests
        """
        self.api_key = api_key or os.environ.get('OPENCAGE_API_KEY')
        if not self.api_key:
            logger.warning("No OpenCage API key found. Geocoding will be disabled.")
        
        self.base_url = "https://api.opencagedata.com/geocode/v1/json"
        self._request_count = 0
        self._last_request_time = 0
        self.proxy_url = proxy_url
        
        # Quota management
        self._quota_exceeded = False
        self._quota_reset_time = None
        self._daily_request_count = 0
        self._daily_limit = 2500  # Free tier limit
        
        # Cache setup
        self._cache_dir = Path.home() / '.homeai' / 'geocache'
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self._cache_dir / 'opencage_cache.json'
        self._load_cache()
        
    def _load_cache(self):
        """Load cache from disk"""
        self._cache = {}
        self._quota_info = {}
        
        if self._cache_file.exists():
            try:
                with open(self._cache_file, 'r') as f:
                    data = json.load(f)
                    self._cache = data.get('cache', {})
                    self._quota_info = data.get('quota_info', {})
                    
                    # Check if quota info is from today
                    last_date = self._quota_info.get('date')
                    today = datetime.now().strftime('%Y-%m-%d')
                    if last_date != today:
                        # Reset daily counter for new day
                        self._quota_info = {'date': today, 'count': 0}
                        self._quota_exceeded = False
                        self._daily_request_count = 0
                    else:
                        self._daily_request_count = self._quota_info.get('count', 0)
                        if self._daily_request_count >= self._daily_limit:
                            self._quota_exceeded = True
                            logger.warning(f"OpenCage quota already exceeded today ({self._daily_request_count}/{self._daily_limit})")
                            
                logger.info(f"Loaded {len(self._cache)} cached geocoding results")
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error loading geocache: {e}")
                self._cache = {}
                self._quota_info = {'date': datetime.now().strftime('%Y-%m-%d'), 'count': 0}
                self._daily_request_count = 0
        else:
            self._quota_info = {'date': datetime.now().strftime('%Y-%m-%d'), 'count': 0}
            self._daily_request_count = 0
    
    def _save_cache(self):
        """Save cache to disk"""
        try:
            with open(self._cache_file, 'w') as f:
                json.dump({
                    'cache': self._cache,
                    'quota_info': self._quota_info
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving geocache: {e}")
    
    def _get_cache_key(self, address: str, city: str, zip_code: str, country: str) -> str:
        """Generate cache key for an address"""
        parts = [str(p).lower().strip() for p in [address, city, zip_code, country] if p]
        return '|'.join(parts)
    
    def geocode(self, address: str, city: Optional[str] = None, 
                zip_code: Optional[str] = None, country: str = "Switzerland") -> Optional[Tuple[float, float]]:
        """Geocode an address to get latitude and longitude
        
        Args:
            address: Street address
            city: City name
            zip_code: Postal code
            country: Country name (default: Switzerland)
            
        Returns:
            Tuple of (latitude, longitude) or None if geocoding fails
        """
        if not self.api_key:
            return None
        
        # Check if quota is exceeded
        if self._quota_exceeded:
            # Check if it's a new day
            today = datetime.now().strftime('%Y-%m-%d')
            if self._quota_info.get('date') != today:
                # Reset for new day
                self._quota_exceeded = False
                self._daily_request_count = 0
                self._quota_info = {'date': today, 'count': 0}
                logger.info("New day - OpenCage quota reset")
            else:
                logger.debug(f"Geocoding skipped - quota exceeded ({self._daily_request_count}/{self._daily_limit})")
                return None
        
        # Check cache first
        cache_key = self._get_cache_key(address, city, zip_code, country)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            logger.debug(f"Using cached geocoding result for '{cache_key}'")
            return tuple(cached) if cached else None
            
        # Build full address
        address_parts = []
        if address:
            address_parts.append(address)
        if zip_code:
            address_parts.append(str(zip_code))
        if city:
            address_parts.append(city)
        if country:
            address_parts.append(country)
            
        if not address_parts:
            return None
            
        full_address = ", ".join(address_parts)
        
        # Rate limiting - OpenCage free tier allows 1 request per second
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < 1.0:  # 1 request/second for free tier
            time.sleep(1.0 - time_since_last)
        
        # Retry logic for geocoding
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                # Make request to OpenCage API
                params = {
                    'q': full_address,
                    'key': self.api_key,
                    'countrycode': 'ch',  # Restrict to Switzerland
                    'limit': 1,
                    'no_annotations': 1  # Reduce response size
                }
                
                # Disable proxy for geocoding to avoid authentication issues
                # OpenCage API calls will work directly without proxy
                proxies = None
                
                # Increase timeout for retries
                timeout = 5 * (attempt + 1)
                
                response = requests.get(self.base_url, params=params, proxies=proxies, timeout=timeout)
                response.raise_for_status()
                
                data = response.json()
                
                if data.get('results') and len(data['results']) > 0:
                    # Get the first result
                    result = data['results'][0]
                    geometry = result.get('geometry', {})
                    lat = geometry.get('lat')
                    lng = geometry.get('lng')
                    
                    if lat is not None and lng is not None:
                        # Log the geocoding result
                        logger.debug(f"Geocoded '{full_address}' to ({lat}, {lng})")
                        
                        self._request_count += 1
                        self._last_request_time = time.time()
                        
                        # Update daily request count
                        self._daily_request_count += 1
                        self._quota_info['count'] = self._daily_request_count
                        
                        # Cache the result
                        self._cache[cache_key] = [lat, lng]
                        try:
                            self._save_cache()
                        except Exception as e:
                            logger.debug(f"Failed to save cache: {e}")
                        
                        # Check if approaching limit
                        if self._daily_request_count >= self._daily_limit - 100:
                            logger.warning(f"Approaching OpenCage daily limit: {self._daily_request_count}/{self._daily_limit} requests used")
                        
                        return (lat, lng)
                    else:
                        logger.warning(f"No coordinates in response for '{full_address}'")
                        return None
                elif data.get('status', {}).get('code') == 402:
                    # Quota exceeded
                    self._quota_exceeded = True
                    self._quota_info['count'] = self._daily_limit
                    try:
                        self._save_cache()
                    except Exception as e:
                        logger.debug(f"Failed to save cache after quota exceeded: {e}")
                    logger.warning(f"OpenCage API quota exceeded for '{full_address}'. Daily limit reached ({self._daily_limit} requests)")
                    
                    # Cache the failed result to avoid retrying
                    self._cache[cache_key] = None
                    return None  # Don't retry when quota exceeded
                else:
                    logger.warning(f"Geocoding failed for '{full_address}': {data.get('status', {}).get('message', 'No results found')}")
                    return None
                    
            except requests.exceptions.Timeout as e:
                logger.warning(f"Timeout geocoding '{full_address}' (attempt {attempt + 1}/{max_retries + 1}): {e}")
                if attempt < max_retries:
                    time.sleep(1)
                    continue
            except requests.exceptions.RequestException as e:
                logger.warning(f"Error geocoding '{full_address}' (attempt {attempt + 1}/{max_retries + 1}): {e}")
                if attempt < max_retries:
                    time.sleep(1)
                    continue
            except (KeyError, IndexError) as e:
                logger.error(f"Unexpected response format for '{full_address}': {e}")
                return None
        
        logger.error(f"Failed to geocode '{full_address}' after {max_retries + 1} attempts")
        return None
    
    def geocode_from_components(self, components: dict) -> Optional[Tuple[float, float]]:
        """Geocode using structured components
        
        Args:
            components: Dict with keys like 'street', 'city', 'zip_code', 'canton'
            
        Returns:
            Tuple of (latitude, longitude) or None if geocoding fails
        """
        address = components.get('address') or components.get('street')
        city = components.get('city')
        zip_code = components.get('zip_code') or components.get('postal_code')
        
        # For Swiss addresses, we might have canton
        if components.get('canton') and not city:
            city = components.get('canton')
            
        return self.geocode(
            address=address,
            city=city,
            zip_code=zip_code,
            country="Switzerland"
        )
    
    @property
    def is_available(self) -> bool:
        """Check if geocoding is available (API key is set and quota not exceeded)"""
        return bool(self.api_key) and not self._quota_exceeded
    
    @property
    def request_count(self) -> int:
        """Get the number of geocoding requests made"""
        return self._request_count
    
    @property
    def daily_requests_remaining(self) -> int:
        """Get the number of requests remaining today"""
        return max(0, self._daily_limit - self._daily_request_count)
    
    @property
    def quota_status(self) -> Dict[str, Any]:
        """Get current quota status"""
        return {
            'daily_limit': self._daily_limit,
            'requests_used': self._daily_request_count,
            'requests_remaining': self.daily_requests_remaining,
            'quota_exceeded': self._quota_exceeded,
            'cache_size': len(self._cache),
            'date': self._quota_info.get('date')
        }
    
    def clear_cache(self):
        """Clear the geocoding cache"""
        self._cache = {}
        self._save_cache()
        logger.info("Geocoding cache cleared")


# Singleton instance
_geocoder_instance = None


def get_geocoder(api_key: Optional[str] = None, proxy_url: Optional[str] = None) -> OpenCageGeocoder:
    """Get or create a geocoder instance
    
    Args:
        api_key: Optional API key to use
        proxy_url: Optional proxy URL for requests
        
    Returns:
        OpenCageGeocoder instance
    """
    global _geocoder_instance
    
    if _geocoder_instance is None or (api_key and api_key != _geocoder_instance.api_key) or (proxy_url != getattr(_geocoder_instance, 'proxy_url', None)):
        _geocoder_instance = OpenCageGeocoder(api_key, proxy_url)
    
    return _geocoder_instance


def geocode_address(address: str, city: Optional[str] = None, 
                   zip_code: Optional[str] = None, country: str = "Switzerland") -> Optional[Tuple[float, float]]:
    """Convenience function to geocode an address
    
    Args:
        address: Street address
        city: City name
        zip_code: Postal code
        country: Country name (default: Switzerland)
        
    Returns:
        Tuple of (latitude, longitude) or None if geocoding fails
    """
    geocoder = get_geocoder()
    return geocoder.geocode(address, city, zip_code, country)


# Backward compatibility alias
GoogleMapsGeocoder = OpenCageGeocoder