# -*- coding: utf-8 -*-
"""
Metrics tracking system for scrapers
Logs performance metrics, status distributions, and errors
"""
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
import logging
import scrapy
from scrapy import signals
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class ScraperMetrics:
    """Track and log scraper performance metrics"""
    
    def __init__(self, spider_name: str):
        self.spider_name = spider_name
        self.start_time = datetime.now()
        
        # Initialize counters
        self.counters = {
            'requests_sent': 0,
            'responses_received': 0,
            'items_scraped': 0,
            'items_dropped': 0,
            'errors': 0,
            'status_counts': {
                'ad_active': 0,
                'ad_inactive': 0,
                'rented': 0,
                'blocked': 0
            },
            'http_status_counts': {},
            'response_times': [],
            'price_ranges': {
                '0-1000': 0,
                '1000-2000': 0,
                '2000-3000': 0,
                '3000-5000': 0,
                '5000+': 0
            }
        }
        
        # Database connection (optional)
        self.db_engine = None
        db_url = os.getenv('DB_CONNECTION_STRING')
        if db_url:
            try:
                self.db_engine = create_engine(db_url)
                self.Session = sessionmaker(bind=self.db_engine)
            except Exception as e:
                logger.warning(f"Failed to connect to metrics database: {e}")
    
    def increment(self, metric: str, value: int = 1):
        """Increment a counter metric"""
        if metric in self.counters:
            self.counters[metric] += value
        else:
            self.counters[metric] = value
    
    def track_item(self, item: Dict[str, Any]):
        """Track metrics from a scraped item"""
        self.increment('items_scraped')
        
        # Track status
        status = item.get('property_status', 'unknown')
        if status in self.counters['status_counts']:
            self.counters['status_counts'][status] += 1
        
        # Track price range
        rent = item.get('rent', 0)
        if rent > 0:
            if rent < 1000:
                self.counters['price_ranges']['0-1000'] += 1
            elif rent < 2000:
                self.counters['price_ranges']['1000-2000'] += 1
            elif rent < 3000:
                self.counters['price_ranges']['2000-3000'] += 1
            elif rent < 5000:
                self.counters['price_ranges']['3000-5000'] += 1
            else:
                self.counters['price_ranges']['5000+'] += 1
    
    def track_response(self, response):
        """Track response metrics"""
        self.increment('responses_received')
        
        # Track HTTP status
        status = str(response.status)
        if status in self.counters['http_status_counts']:
            self.counters['http_status_counts'][status] += 1
        else:
            self.counters['http_status_counts'][status] = 1
        
        # Track response time if available
        if hasattr(response, 'meta') and 'download_latency' in response.meta:
            self.counters['response_times'].append(response.meta['download_latency'])
    
    def track_error(self, failure):
        """Track error metrics"""
        self.increment('errors')
        
        # Track error types
        error_type = failure.type.__name__ if hasattr(failure, 'type') else 'Unknown'
        error_key = f'error_{error_type}'
        self.increment(error_key)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all metrics"""
        elapsed_time = (datetime.now() - self.start_time).total_seconds()
        
        # Calculate averages
        avg_response_time = 0
        if self.counters['response_times']:
            avg_response_time = sum(self.counters['response_times']) / len(self.counters['response_times'])
        
        # Calculate rates
        items_per_second = self.counters['items_scraped'] / max(elapsed_time, 1)
        success_rate = (self.counters['items_scraped'] / max(self.counters['responses_received'], 1)) * 100
        
        # Active property percentage
        total_status = sum(self.counters['status_counts'].values())
        active_percentage = 0
        if total_status > 0:
            active_percentage = (self.counters['status_counts']['ad_active'] / total_status) * 100
        
        summary = {
            'spider': self.spider_name,
            'start_time': self.start_time.isoformat(),
            'elapsed_seconds': elapsed_time,
            'performance': {
                'items_scraped': self.counters['items_scraped'],
                'items_per_second': round(items_per_second, 2),
                'success_rate': round(success_rate, 2),
                'avg_response_time_ms': round(avg_response_time * 1000, 2),
                'total_errors': self.counters['errors']
            },
            'status_distribution': self.counters['status_counts'],
            'active_percentage': round(active_percentage, 2),
            'price_distribution': self.counters['price_ranges'],
            'http_status_distribution': self.counters['http_status_counts'],
            'counters': self.counters
        }
        
        return summary
    
    def log_summary(self):
        """Log metrics summary"""
        summary = self.get_summary()
        
        logger.info("="*80)
        logger.info(f"METRICS SUMMARY - {self.spider_name}")
        logger.info("="*80)
        
        # Performance metrics
        perf = summary['performance']
        logger.info(f"Items scraped: {perf['items_scraped']}")
        logger.info(f"Rate: {perf['items_per_second']} items/second")
        logger.info(f"Success rate: {perf['success_rate']}%")
        logger.info(f"Avg response time: {perf['avg_response_time_ms']}ms")
        
        # Status distribution
        logger.info("\nProperty Status Distribution:")
        for status, count in summary['status_distribution'].items():
            logger.info(f"  {status}: {count}")
        logger.info(f"Active properties: {summary['active_percentage']}%")
        
        # Price distribution
        logger.info("\nPrice Distribution:")
        for range_key, count in summary['price_distribution'].items():
            if count > 0:
                logger.info(f"  CHF {range_key}: {count}")
        
        # Errors
        if summary['performance']['total_errors'] > 0:
            logger.info(f"\nErrors: {summary['performance']['total_errors']}")
    
    def save_to_database(self):
        """Save metrics to database"""
        if not self.db_engine:
            return
        
        session = self.Session()
        try:
            summary = self.get_summary()
            
            # Insert metrics record
            insert_query = """
                INSERT INTO scraper_metrics 
                (spider_name, run_date, elapsed_seconds, items_scraped, 
                 items_per_second, success_rate, active_percentage, 
                 total_errors, metrics_json)
                VALUES 
                (:spider, :run_date, :elapsed, :items, :rate, 
                 :success_rate, :active_pct, :errors, :json)
            """
            
            session.execute(text(insert_query), {
                'spider': self.spider_name,
                'run_date': self.start_time,
                'elapsed': summary['elapsed_seconds'],
                'items': summary['performance']['items_scraped'],
                'rate': summary['performance']['items_per_second'],
                'success_rate': summary['performance']['success_rate'],
                'active_pct': summary['active_percentage'],
                'errors': summary['performance']['total_errors'],
                'json': json.dumps(summary)
            })
            
            session.commit()
            logger.info("Metrics saved to database")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save metrics to database: {e}")
        finally:
            session.close()
    
    def save_to_file(self, filename: Optional[str] = None):
        """Save metrics to JSON file"""
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'metrics_{self.spider_name}_{timestamp}.json'
        
        summary = self.get_summary()
        
        os.makedirs('metrics', exist_ok=True)
        filepath = os.path.join('metrics', filename)
        
        with open(filepath, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Metrics saved to {filepath}")
        return filepath


class MetricsExtension:
    """Scrapy extension to automatically track metrics"""
    
    @classmethod
    def from_crawler(cls, crawler):
        ext = cls()
        ext.crawler = crawler
        ext.metrics = None  # Will be initialized in spider_opened
        
        # Connect signals
        crawler.signals.connect(ext.spider_opened, signal=scrapy.signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=scrapy.signals.spider_closed)
        crawler.signals.connect(ext.item_scraped, signal=scrapy.signals.item_scraped)
        crawler.signals.connect(ext.item_dropped, signal=scrapy.signals.item_dropped)
        crawler.signals.connect(ext.response_received, signal=scrapy.signals.response_received)
        crawler.signals.connect(ext.request_scheduled, signal=scrapy.signals.request_scheduled)
        
        return ext
    
    def spider_opened(self, spider):
        self.metrics = ScraperMetrics(spider.name)
        spider.logger.info("Metrics tracking started")
    
    def spider_closed(self, spider):
        # Log and save metrics
        if self.metrics:
            self.metrics.log_summary()
            self.metrics.save_to_file()
            self.metrics.save_to_database()
    
    def item_scraped(self, item, spider):
        if self.metrics:
            self.metrics.track_item(dict(item))
    
    def item_dropped(self, item, response, spider):
        if self.metrics:
            self.metrics.increment('items_dropped')
    
    def response_received(self, response, request, spider):
        if self.metrics:
            self.metrics.track_response(response)
    
    def request_scheduled(self, request, spider):
        if self.metrics:
            self.metrics.increment('requests_sent')


# SQL for creating metrics table
METRICS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scraper_metrics (
    id SERIAL PRIMARY KEY,
    spider_name VARCHAR(100) NOT NULL,
    run_date TIMESTAMP NOT NULL,
    elapsed_seconds FLOAT NOT NULL,
    items_scraped INTEGER NOT NULL,
    items_per_second FLOAT NOT NULL,
    success_rate FLOAT NOT NULL,
    active_percentage FLOAT NOT NULL,
    total_errors INTEGER NOT NULL,
    metrics_json JSON,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_scraper_metrics_spider ON scraper_metrics(spider_name);
CREATE INDEX idx_scraper_metrics_date ON scraper_metrics(run_date);
"""