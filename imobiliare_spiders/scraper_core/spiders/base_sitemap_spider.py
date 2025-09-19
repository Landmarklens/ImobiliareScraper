"""
Base spider class with smart property filtering for sitemap-based spiders
"""
import scrapy
from scrapy.utils.project import get_project_settings
from ..utils.property_filter import SmartPropertyFilter
import logging


class SmartSitemapSpider(scrapy.Spider):
    """Base spider with intelligent property filtering"""
    
    def __init__(self, *args, **kwargs):
        # Extract single URL mode parameters
        self.single_url = kwargs.pop('single_url', None)
        self.property_id = kwargs.pop('property_id', None)
        self.job_id = kwargs.pop('job_id', None)
        self.owner_id = kwargs.pop('owner_id', None)
        
        super().__init__(*args, **kwargs)
        
        # Log single URL mode if active
        if self.single_url:
            self.logger.info(f"[SingleURL] Running in single URL mode for: {self.single_url}")
            self.logger.info(f"[SingleURL] Property ID: {self.property_id}, Job ID: {self.job_id}, Owner ID: {self.owner_id}")
        
        # Initialize property filter if database is configured
        settings = get_project_settings()
        db_url = settings.get('DATABASE_URL') or settings.get('DB_CONNECTION_STRING')
        
        self.property_filter = None
        self.filter_stats = {}
        
        # Disable filter in single URL mode
        if self.single_url:
            self.logger.info("[SingleURL] Smart filter disabled in single URL mode")
        elif db_url and hasattr(self, 'external_source'):
            try:
                self.property_filter = SmartPropertyFilter(db_url, self.external_source)
                self.property_filter.load_property_states()
                self.filter_stats = self.property_filter.get_stats()
                
                self.logger.info(f"[SmartFilter] Initialized with {self.filter_stats['total_existing']} existing properties")
                self.logger.info(f"[SmartFilter] Will skip {self.filter_stats['skip_count']} properties (rented/sold/blacklisted)")
                self.logger.info(f"[SmartFilter] Will recheck {self.filter_stats['recheck_count']} properties")
                
            except Exception as e:
                self.logger.warning(f"[SmartFilter] Failed to initialize: {e}")
                self.property_filter = None
        
        # Track filtering metrics
        self.properties_filtered = 0
        self.properties_allowed = 0
    
    def should_process_url(self, url: str) -> bool:
        """Check if a URL should be processed based on smart filtering"""
        if not self.property_filter:
            return True
        
        # Extract property ID from URL
        property_id = self.extract_property_id(url)
        if not property_id:
            return True
        
        # Check with smart filter
        should_process = self.property_filter.should_process_property(property_id)
        
        # Update metrics
        if should_process:
            self.properties_allowed += 1
        else:
            self.properties_filtered += 1
            
        # Log filtering progress periodically
        total_checked = self.properties_filtered + self.properties_allowed
        if total_checked % 100 == 0:
            self.logger.info(f"[SmartFilter] Checked {total_checked} URLs: "
                           f"Allowed {self.properties_allowed}, Filtered {self.properties_filtered} "
                           f"({self.properties_filtered/total_checked*100:.1f}% filtered)")
        
        return should_process
    
    def extract_property_id(self, url: str) -> str:
        """Extract property ID from URL - must be implemented by child classes"""
        raise NotImplementedError("Child classes must implement extract_property_id()")
    
    def closed(self, reason):
        """Log final filtering statistics when spider closes"""
        if self.property_filter:
            total_checked = self.properties_filtered + self.properties_allowed
            if total_checked > 0:
                filter_rate = self.properties_filtered / total_checked * 100
                self.logger.info(f"[SmartFilter] Final stats: {total_checked} URLs checked")
                self.logger.info(f"[SmartFilter] {self.properties_allowed} allowed, "
                               f"{self.properties_filtered} filtered ({filter_rate:.1f}% filter rate)")
                self.logger.info(f"[SmartFilter] Saved approximately {self.properties_filtered} unnecessary requests")