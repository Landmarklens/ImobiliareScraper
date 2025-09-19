# -*- coding: utf-8 -*-
"""
Unified property status detection for all scrapers
Detects if properties are active, inactive, rented, or blocked
"""
from ..models import PropertyStatusEnum
import re
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class PropertyStatusDetector:
    """Unified property status detection for all scrapers"""
    
    # Multi-language keywords indicating property is no longer available
    INACTIVE_KEYWORDS = {
        'en': [
            'no longer available', 
            'already rented', 
            'listing expired', 
            'removed', 
            'not found',
            'this property has been',
            'listing has been removed',
            'property is no longer',
            'ad has been deleted'
        ],
        'de': [
            'nicht mehr verfügbar', 
            'bereits vermietet', 
            'angebot beendet', 
            'vermietet',
            'nicht gefunden',
            'wurde entfernt',
            'inserat wurde gelöscht',
            'objekt ist nicht mehr'
        ],
        'fr': [
            'plus disponible', 
            'déjà loué', 
            'annonce expirée', 
            'loué',
            'introuvable',
            'a été supprimé',
            'annonce a été retirée'
        ],
        'it': [
            'non più disponibile', 
            'già affittato', 
            'annuncio scaduto', 
            'affittato',
            'non trovato',
            'è stato rimosso'
        ]
    }
    
    # Keywords indicating property is rented but might still show details
    RENTED_KEYWORDS = {
        'en': ['already rented', 'let agreed', 'under offer', 'no longer available for rent'],
        'de': ['bereits vermietet', 'nicht mehr verfügbar', 'vergeben'],
        'fr': ['déjà loué', 'n\'est plus disponible', 'sous offre'],
        'it': ['già affittato', 'non più disponibile', 'in trattativa']
    }
    
    # CSS selectors for site-specific status indicators
    SITE_SPECIFIC_SELECTORS = {
        'immoscout24': {
            'removed': [
                '.property-removed-message',
                '.listing-not-available',
                '[data-testid="property-not-found"]',
                '.error-page'
            ],
            'rented': [
                '.property-status-rented',
                '[data-testid="status-rented"]'
            ]
        },
        'homegate': {
            'removed': [
                '.listing-removed',
                '.property-not-available',
                '.error-message'
            ],
            'rented': [
                '.badge-rented',
                '.status-unavailable'
            ]
        },
        'flatfox': {
            'removed': [
                '.property-removed',
                '.listing-expired'
            ],
            'rented': [
                '.property-rented-overlay',
                '.rented-badge',
                '.status-rented'
            ]
        }
    }
    
    @classmethod
    def detect_status(cls, response, item: Optional[Dict[str, Any]] = None) -> str:
        """
        Detect property status from response
        
        Args:
            response: Scrapy Response object
            item: Optional parsed item dictionary
            
        Returns:
            PropertyStatusEnum value
        """
        logger.debug(f"Detecting status for {response.url}")
        
        # 1. HTTP Status Code Checks
        status_code_result = cls._check_http_status(response)
        if status_code_result:
            logger.info(f"Status detected from HTTP code {response.status}: {status_code_result}")
            return status_code_result
        
        # 2. Redirect Detection
        redirect_result = cls._check_redirects(response)
        if redirect_result:
            logger.info(f"Status detected from redirect: {redirect_result}")
            return redirect_result
        
        # 3. Special Response Checks (Cloudflare, etc.)
        special_result = cls._check_special_responses(response)
        if special_result:
            logger.info(f"Special response detected: {special_result}")
            return special_result
        
        # 4. Content-Based Detection
        content_result = cls._check_content(response)
        if content_result != PropertyStatusEnum.AD_ACTIVE.value:
            logger.info(f"Status detected from content: {content_result}")
            return content_result
        
        # 5. Data Completeness Check
        if item:
            completeness_result = cls._check_data_completeness(item)
            if completeness_result != PropertyStatusEnum.AD_ACTIVE.value:
                missing_fields = []
                if not item.get('title'):
                    missing_fields.append('title')
                if not item.get('external_id'):
                    missing_fields.append('external_id')
                logger.info(f"[STATUS_DETECTION] Status: {completeness_result} - Missing critical fields: {', '.join(missing_fields) if missing_fields else 'incomplete data'}")
                return completeness_result
        
        # Default to active if no issues found
        logger.debug(f"Property appears active: {response.url}")
        return PropertyStatusEnum.AD_ACTIVE.value
    
    @classmethod
    def _check_http_status(cls, response) -> Optional[str]:
        """Check HTTP status codes"""
        if response.status == 404:
            return PropertyStatusEnum.AD_INACTIVE.value
        elif response.status == 410:  # Gone
            return PropertyStatusEnum.AD_INACTIVE.value
        elif response.status >= 500:  # Server errors
            return PropertyStatusEnum.BLOCKED.value
        return None
    
    @classmethod
    def _check_redirects(cls, response) -> Optional[str]:
        """Check for redirects to search/home pages"""
        # Check redirect chain
        if hasattr(response, 'meta') and response.meta.get('redirect_urls'):
            redirect_urls = response.meta['redirect_urls']
            
            # If redirected to search or results page, property is gone
            search_patterns = ['/search', '/results', '/rent/', '/buy/', '/home']
            for url in redirect_urls:
                if any(pattern in url.lower() for pattern in search_patterns):
                    return PropertyStatusEnum.AD_INACTIVE.value
        
        # Check if final URL is different from requested URL
        if response.url != response.request.url:
            # Check if redirected to a search/listing page
            if any(pattern in response.url.lower() for pattern in ['/search', '/rent/', '/home', '/results']):
                # Make sure it's not just a property URL that contains these words
                if not re.search(r'/\d{5,}/?$', response.url):  # No property ID at end
                    return PropertyStatusEnum.AD_INACTIVE.value
        
        return None
    
    @classmethod
    def _check_special_responses(cls, response) -> Optional[str]:
        """Check for special responses like Cloudflare"""
        page_text = response.text
        
        # Cloudflare detection
        cloudflare_indicators = [
            "Just a moment",
            "cf-browser-verification", 
            "Checking your browser",
            "DDoS protection by Cloudflare",
            "ray ID"
        ]
        
        if any(indicator in page_text for indicator in cloudflare_indicators):
            return PropertyStatusEnum.BLOCKED.value
        
        return None
    
    @classmethod
    def _check_content(cls, response) -> str:
        """Check page content for status keywords"""
        page_text = response.text.lower()
        
        # Extract site name from URL
        site_name = None
        for site in ['immoscout24', 'homegate', 'flatfox']:
            if site in response.url:
                site_name = site
                break
        
        # Check CSS selectors for site-specific indicators
        if site_name and site_name in cls.SITE_SPECIFIC_SELECTORS:
            selectors = cls.SITE_SPECIFIC_SELECTORS[site_name]
            
            # Check removed selectors
            for selector in selectors.get('removed', []):
                if response.css(selector).get():
                    return PropertyStatusEnum.AD_INACTIVE.value
            
            # Check rented selectors
            for selector in selectors.get('rented', []):
                if response.css(selector).get():
                    return PropertyStatusEnum.RENTED.value
        
        # Check for rented keywords (check these first as they're more specific)
        # But be more careful - just having "vermietet" in the page doesn't mean it's rented
        # It could be part of the rental listing description
        for lang, keywords in cls.RENTED_KEYWORDS.items():
            for keyword in keywords:
                if keyword in page_text:
                    # Look for strong indicators that THIS property is rented
                    # Not just the word appearing somewhere on the page
                    rented_patterns = [
                        f'<[^>]*class="[^"]*status[^"]*"[^>]*>{keyword}',  # In a status element
                        f'<[^>]*class="[^"]*badge[^"]*"[^>]*>{keyword}',   # In a badge
                        f'property[^>]+{keyword}',  # Near "property" and the keyword
                        f'this[^>]+{keyword}',      # "This property is rented"
                    ]
                    
                    for pattern in rented_patterns:
                        if re.search(pattern, page_text, re.IGNORECASE):
                            return PropertyStatusEnum.RENTED.value
        
        # Check for inactive keywords
        for lang, keywords in cls.INACTIVE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in page_text:
                    if cls._is_keyword_relevant(keyword, page_text):
                        return PropertyStatusEnum.AD_INACTIVE.value
        
        return PropertyStatusEnum.AD_ACTIVE.value
    
    @classmethod
    def _check_data_completeness(cls, item: Dict[str, Any]) -> str:
        """Check if parsed data is complete enough to be valid"""
        # Must have ID and title at minimum
        if not item.get('external_id') or not item.get('title'):
            return PropertyStatusEnum.AD_INACTIVE.value
        
        # Don't mark as inactive based on missing price
        # Many valid properties have "price on request"
        # The price field being None or 0 is acceptable
        
        # If we have very little data, property might be removed
        # Don't count price as a required field
        # Also don't count metadata fields that are often auto-filled
        metadata_fields = ['external_source', 'country', 'deal_type', 'price_chf', 'rent', 'price',
                          'status', 'scraped_at', 'last_seen', 'fingerprint', 'deal_type']
        
        filled_fields = sum(1 for k, v in item.items() 
                          if v and k not in metadata_fields)
        
        # Reduce threshold from 4 to 2 - if we have ID and title plus any other field, it's likely active
        # This prevents false negatives where valid properties are marked inactive
        if filled_fields < 2:  # Less than 2 fields with data (excluding metadata)
            return PropertyStatusEnum.AD_INACTIVE.value
        
        return PropertyStatusEnum.AD_ACTIVE.value
    
    @classmethod
    def _is_keyword_relevant(cls, keyword: str, page_text: str) -> bool:
        """
        Check if a keyword appears in a relevant context
        Helps avoid false positives from navigation, headers, etc.
        """
        # Find keyword position
        keyword_pos = page_text.find(keyword)
        if keyword_pos == -1:
            return False
        
        # Check surrounding context (200 chars before and after)
        start = max(0, keyword_pos - 200)
        end = min(len(page_text), keyword_pos + len(keyword) + 200)
        context = page_text[start:end]
        
        # If keyword appears near property-related terms, it's likely relevant
        property_terms = ['property', 'listing', 'apartment', 'house', 'flat', 
                         'objekt', 'wohnung', 'immobilie', 'annonce', 'appartement']
        
        return any(term in context for term in property_terms)
    
    @classmethod
    def get_status_name(cls, status_value: str) -> str:
        """Get human-readable status name"""
        status_map = {
            PropertyStatusEnum.AD_ACTIVE.value: "Active",
            PropertyStatusEnum.AD_INACTIVE.value: "Inactive", 
            PropertyStatusEnum.RENTED.value: "Rented",
            PropertyStatusEnum.BLOCKED.value: "Blocked"
        }
        return status_map.get(status_value, "Unknown")