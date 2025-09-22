#!/usr/bin/env python3
"""
Test script for the enhanced proxy replacement system
"""

import os
import sys
import time
import logging
from datetime import datetime

# Add project path
sys.path.insert(0, '/home/cn/Desktop/HomeAiCode/ImobiliareScraper')

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)

def test_proxy_middleware():
    """Test the proxy middleware functionality"""

    # Import after path setup
    from imobiliare_spiders.scraper_core.middlewares import WebshareProxyMiddleware
    import boto3

    logger = logging.getLogger(__name__)

    # Get API key from SSM
    try:
        ssm = boto3.client('ssm', region_name='us-east-1')
        api_key = ssm.get_parameter(
            Name='/HomeAiScrapper/WEBSHARE_API_KEY',
            WithDecryption=True
        )['Parameter']['Value']
    except Exception as e:
        logger.error(f"Failed to get API key: {e}")
        return

    # Initialize middleware
    middleware = WebshareProxyMiddleware(
        api_key=api_key,
        api_url="https://proxy.webshare.io/api/v2/proxy/list/",
        refresh_hours=3.0
    )

    # Test 1: Fetch initial proxies
    logger.info("=" * 60)
    logger.info("TEST 1: Fetching initial proxy list")
    middleware.fetch_proxies()

    active_count = len(middleware.proxy_pools['active'])
    logger.info(f"✓ Loaded {active_count} active proxies")

    if active_count == 0:
        logger.error("No proxies loaded! Check API key.")
        return

    # Test 2: Check quota
    logger.info("=" * 60)
    logger.info("TEST 2: Checking replacement quota")
    middleware.check_replacement_quota()

    remaining = middleware.replacement_quota['limit'] - middleware.replacement_quota['used']
    logger.info(f"✓ Replacement quota: {remaining}/{middleware.replacement_quota['limit']}")

    # Test 3: Get best proxy
    logger.info("=" * 60)
    logger.info("TEST 3: Getting best proxy")

    best_proxy = middleware.get_best_proxy()
    if best_proxy:
        logger.info(f"✓ Got proxy: {best_proxy['address']}")
    else:
        logger.error("Failed to get proxy!")
        return

    # Test 4: Simulate proxy failure (403 block)
    logger.info("=" * 60)
    logger.info("TEST 4: Simulating 403 block")

    test_proxy_addr = best_proxy['address']
    logger.info(f"Marking {test_proxy_addr} as failed (403)")

    middleware.mark_proxy_failure(test_proxy_addr, 403)

    # Check pools
    active_after = len(middleware.proxy_pools['active'])
    quarantine_count = len(middleware.proxy_pools['quarantine'])
    blacklist_count = len(middleware.proxy_pools['blacklist'])

    logger.info(f"✓ Active: {active_after}, Quarantine: {quarantine_count}, Blacklist: {blacklist_count}")

    # Test 5: Quarantine recovery
    logger.info("=" * 60)
    logger.info("TEST 5: Testing quarantine recovery")

    if quarantine_count > 0:
        quarantined = list(middleware.proxy_pools['quarantine'].keys())[0]
        until = middleware.proxy_pools['quarantine'][quarantined]['until']
        logger.info(f"Proxy {quarantined} quarantined until {until.strftime('%H:%M:%S')}")

        # Force recovery check
        middleware._check_quarantine_recovery()
        logger.info("✓ Recovery check completed")

    # Test 6: Emergency recovery
    logger.info("=" * 60)
    logger.info("TEST 6: Testing emergency recovery")

    # Temporarily clear active pool
    original_active = middleware.proxy_pools['active'].copy()
    middleware.proxy_pools['active'] = []

    emergency_proxy = middleware._emergency_proxy_recovery()
    if emergency_proxy:
        logger.info(f"✓ Emergency recovery successful: {emergency_proxy['address']}")
    else:
        logger.warning("Emergency recovery returned no proxy")

    # Restore
    if not middleware.proxy_pools['active']:
        middleware.proxy_pools['active'] = original_active

    # Test 7: Performance metrics
    logger.info("=" * 60)
    logger.info("TEST 7: Checking performance metrics")

    # Simulate some success/failure
    for proxy_addr in list(middleware.proxy_metrics.keys())[:3]:
        metrics = middleware.proxy_metrics[proxy_addr]
        metrics['success'] = 10
        metrics['failures'] = 2
        metrics['response_times'] = [0.5, 0.8, 1.2]

    # Get best proxy based on metrics
    best_by_metrics = middleware.get_best_proxy()
    if best_by_metrics:
        addr = best_by_metrics['address']
        m = middleware.proxy_metrics[addr]
        if m['success'] + m['failures'] > 0:
            success_rate = m['success'] / (m['success'] + m['failures']) * 100
            logger.info(f"✓ Best proxy by metrics: {addr} ({success_rate:.1f}% success)")
        else:
            logger.info(f"✓ Selected unused proxy: {addr}")

    # Summary
    logger.info("=" * 60)
    logger.info("TEST SUMMARY")
    logger.info(f"Active proxies: {len(middleware.proxy_pools['active'])}")
    logger.info(f"Quarantined: {len(middleware.proxy_pools['quarantine'])}")
    logger.info(f"Blacklisted: {len(middleware.proxy_pools['blacklist'])}")
    logger.info(f"Replacement quota remaining: {remaining}")
    logger.info("✓ All tests completed successfully!")


if __name__ == "__main__":
    test_proxy_middleware()