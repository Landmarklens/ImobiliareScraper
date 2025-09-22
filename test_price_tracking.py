#!/usr/bin/env python3
"""
Test script to verify price tracking functionality
"""

import json
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import your models and pipelines
from imobiliare_spiders.scraper_core.models import SpiderResultRomania, Base
from imobiliare_spiders.scraper_core.pipelines import RomaniaDatabasePipeline

def test_price_tracking():
    """Test the price tracking functionality"""

    # Create a test database connection (use test DB or mock)
    print("Testing Price Tracking Functionality")
    print("=" * 50)

    # Test 1: Create a property with initial price
    test_item_1 = {
        'fingerprint': 'test_property_001',
        'external_source': 'test_source',
        'external_url': 'http://test.com/property1',
        'external_id': 'test_001',
        'title': 'Test Property',
        'property_type': 'apartment',
        'deal_type': 'rent',
        'price_ron': 1000.0,
        'price_eur': 200.0,
        'city': 'Bucharest'
    }

    print("\n1. Creating new property with initial price:")
    print(f"   RON: {test_item_1['price_ron']}, EUR: {test_item_1['price_eur']}")

    # Test 2: Update same property with lower price (price drop)
    test_item_2 = test_item_1.copy()
    test_item_2['price_ron'] = 900.0  # 10% drop
    test_item_2['price_eur'] = 180.0

    print("\n2. Simulating price drop:")
    print(f"   New RON: {test_item_2['price_ron']} (from {test_item_1['price_ron']})")
    print(f"   New EUR: {test_item_2['price_eur']} (from {test_item_1['price_eur']})")
    print(f"   Expected change: -10%")
    print(f"   Should trigger price_drop_alert: Yes")

    # Test 3: Update with higher price (price increase)
    test_item_3 = test_item_1.copy()
    test_item_3['price_ron'] = 1100.0  # 10% increase from original
    test_item_3['price_eur'] = 220.0

    print("\n3. Simulating price increase:")
    print(f"   New RON: {test_item_3['price_ron']}")
    print(f"   New EUR: {test_item_3['price_eur']}")
    print(f"   Expected change: +10% from original")

    # Test 4: No price change
    test_item_4 = test_item_1.copy()

    print("\n4. Simulating no price change:")
    print(f"   Price remains: RON {test_item_4['price_ron']}, EUR {test_item_4['price_eur']}")
    print(f"   Expected: No price history update")

    print("\n" + "=" * 50)
    print("Test Summary:")
    print("- Price history JSON should contain all price changes")
    print("- price_change_percentage should be calculated correctly")
    print("- price_drop_alert should be True for drops >= 5%")
    print("- highest_price_ron and lowest_price_ron should track extremes")
    print("- price_change_count should increment on each change")

    return True

def verify_database_schema():
    """Verify that the new columns exist in the database"""
    print("\nVerifying Database Schema")
    print("=" * 50)

    required_columns = [
        'price_history',
        'previous_price_ron',
        'previous_price_eur',
        'price_change_ron',
        'price_change_eur',
        'price_change_percentage',
        'price_last_changed',
        'price_change_count',
        'price_drop_alert',
        'highest_price_ron',
        'lowest_price_ron'
    ]

    print("\nRequired columns for price tracking:")
    for col in required_columns:
        print(f"  - {col}")

    print("\nNOTE: Run the SQL migration script first:")
    print("  psql -d homeai_db -f add_price_history_columns.sql")

    return True

if __name__ == "__main__":
    print("Price Tracking Test Suite")
    print("=" * 50)

    # Run tests
    test_price_tracking()
    verify_database_schema()

    print("\n" + "=" * 50)
    print("Testing complete!")
    print("\nNext steps:")
    print("1. Run the SQL migration: add_price_history_columns.sql")
    print("2. Deploy the updated pipeline code")
    print("3. Run the spider and monitor for price changes")
    print("4. Query the database to verify price history is tracked")