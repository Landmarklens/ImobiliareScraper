import os
import sys
import boto3
from dotenv import load_dotenv

load_dotenv()

# Use modern asyncio reactor for better performance (Python 3.7+)
if sys.version_info >= (3, 7):
    TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor'
    print("[SETTINGS] Using AsyncioSelectorReactor for better performance")
else:
    print("[SETTINGS] Using default reactor (Python version < 3.7)")


def get_parameter(param_name, default=None):
    """Get parameter from AWS Parameter Store or environment"""
    # Check if running in production
    if os.getenv('ENVIRONMENT') == 'production':
        try:
            ssm = boto3.client('ssm', region_name='us-east-1')
            response = ssm.get_parameter(Name=param_name, WithDecryption=True)
            return response['Parameter']['Value']
        except Exception as e:
            print(f"[SETTINGS] Failed to get parameter {param_name} from SSM: {e}")

    # Fall back to environment variable
    env_key = param_name.split('/')[-1]
    return os.getenv(env_key, default)


# Scrapy settings for imobiliare_spiders project
BOT_NAME = "imobiliare_spiders"

SPIDER_MODULES = ["scraper_core.spiders.romania"]
NEWSPIDER_MODULE = "scraper_core.spiders.romania"

# Environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DEV_MODE = os.getenv("DEV_MODE", "True").lower() == "true"

# Database configuration - using same DB as Swiss scraper
DB_CONNECTION_STRING = get_parameter(
    "/HomeAiScrapper/DB_CONNECTION_STRING",
    "postgresql://localhost:5432/homeai_db"
)

# AWS S3 Configuration (even though we don't store images, keeping for consistency)
S3_ACCESS_KEY = get_parameter("/HomeAiScrapper/S3_ACCESS_KEY", "your_access_key")
S3_SECRET_KEY = get_parameter("/HomeAiScrapper/S3_SECRET_KEY", "your_secret_key")
S3_BUCKET_NAME = get_parameter("/HomeAiScrapper/S3_BUCKET_NAME", "homeai-scraped-data")

# Geocoding services
OPEN_CAGE_API_KEY = get_parameter("/HomeAiScrapper/OPEN_CAGE", "")
GOOGLE_MAPS_API_KEY = get_parameter("/homeai/prod/GOOGLE_MAPS_API_KEY", "")

# Proxy configuration (if needed for Romanian sites)
WEBSHARE_API_KEY = get_parameter("/HomeAiScrapper/WEBSHARE_API_KEY", "")
WEBSHARE_API_URL = get_parameter(
    "/HomeAiScrapper/WEBSHARE_API_URL",
    "https://proxy.webshare.io/api/v2/proxy/list/"
)
PROXY_ENABLED = get_parameter("/HomeAiScrapper/PROXY_ENABLED", "true").lower() == "true"
PROXY_REFRESH_HOURS = 3.0  # Fixed refresh interval

# Monitoring (optional)
SCRAPEOPS_API_KEY = ""  # Not currently used
SLACK_WEBHOOK_URL = ""  # Not currently used

# Romania specific settings
IMOBILIARE_API_KEY = get_parameter("/homeai/prod/imobiliare/API_KEY", "")
IMOBILIARE_RATE_LIMIT = float(get_parameter("/homeai/prod/imobiliare/RATE_LIMIT", "1.0"))
IMOBILIARE_USER_AGENT = get_parameter(
    "/homeai/prod/imobiliare/USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
)

# Obey robots.txt rules
ROBOTSTXT_OBEY = True

# Configure maximum concurrent requests performed by Scrapy
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 4

# Configure a delay for requests for the same website
DOWNLOAD_DELAY = IMOBILIARE_RATE_LIMIT
RANDOMIZE_DOWNLOAD_DELAY = True

# The download delay setting will honor only one of:
CONCURRENT_REQUESTS_PER_DOMAIN = 4
CONCURRENT_ITEMS = 100

# Disable cookies (enabled by default)
COOKIES_ENABLED = True

# Disable Telnet Console (enabled by default)
TELNETCONSOLE_ENABLED = False

# Override the default request headers:
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
}

# User agent
USER_AGENT = IMOBILIARE_USER_AGENT

# Enable or disable spider middlewares
SPIDER_MIDDLEWARES = {
    'scraper_core.middlewares.StartUrlValidationMiddleware': 300,
}

# Enable or disable downloader middlewares
DOWNLOADER_MIDDLEWARES = {
    'scraper_core.selenium_middleware.UndetectedChromeMiddleware': 300,  # Process before proxy
    'scraper_core.middlewares.CustomUserAgentMiddleware': 400,
    'scraper_core.middlewares.WebshareProxyMiddleware': 350 if PROXY_ENABLED else None,
    'scraper_core.middlewares.RetryMiddleware': 500,
    'scraper_core.middlewares.HeadersMiddleware': 550,
}

# Remove None values from middlewares
DOWNLOADER_MIDDLEWARES = {k: v for k, v in DOWNLOADER_MIDDLEWARES.items() if v is not None}

# Enable or disable extensions
EXTENSIONS = {
    'scrapy.extensions.telnet.TelnetConsole': None,
}

# Configure item pipelines
ITEM_PIPELINES = {
    'scraper_core.pipelines.ValidationPipeline': 100,
    'scraper_core.pipelines.RomaniaDatabasePipeline': 300,
    # No ImagePipeline since we don't store images for Romania
    'scraper_core.pipelines.MetricsPipeline': 900,
}

# Selenium configuration for Cloudflare bypass
SELENIUM_HEADLESS = True  # Run Chrome in headless mode
SELENIUM_PROXY_ENABLED = False  # Proxies don't work well with Selenium/Cloudflare
CHROME_DRIVER_PATH = None  # Auto-detect

# AutoThrottle configuration
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 4.0
AUTOTHROTTLE_DEBUG = False

# Enable and configure HTTP caching
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 3600
HTTPCACHE_DIR = "httpcache"
HTTPCACHE_IGNORE_HTTP_CODES = [500, 503, 504, 400, 403, 404]
HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

# Memory usage monitoring
MEMUSAGE_ENABLED = True
MEMUSAGE_LIMIT_MB = 2048
MEMUSAGE_WARNING_MB = 1536

# Request fingerprinting
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"

# Reactor
REACTOR_THREADPOOL_MAXSIZE = 20

# DNS
DNSCACHE_ENABLED = True
DNSCACHE_SIZE = 10000
DNS_RESOLVER = 'scrapy.resolver.CachingThreadedResolver'

# Retry configuration
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# Logging
LOG_LEVEL = 'INFO' if not DEV_MODE else 'DEBUG'
LOG_FORMAT = '%(levelname)s: %(message)s'

# Stats collection
STATS_CLASS = 'scrapy.statscollectors.MemoryStatsCollector'

# CloudWatch Log Group (different from Swiss scraper)
CLOUDWATCH_LOG_GROUP = "/ecs/imobiliare-scraper"
CLOUDWATCH_LOG_STREAM_PREFIX = "ecs"

# Set settings whose default value is deprecated to a future-proof value
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"