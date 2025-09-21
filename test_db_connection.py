#!/usr/bin/env python3
"""
Test database connectivity via SSH tunnel
Mimics DBeaver connection setup
"""

import psycopg2
from sshtunnel import SSHTunnelForwarder
import os
from datetime import datetime, timedelta

# SSH Configuration (matching DBeaver)
SSH_HOST = "3.221.26.92"
SSH_PORT = 22
SSH_USER = "ubuntu"
SSH_KEY_PATH = "/home/cn/Desktop/HomeAiCode/id_rsa"  # Using the key from DBeaver config

# Database Configuration (from DBeaver)
DB_HOST = "webscraping-database.cluster-c9y2u088elix.us-east-1.rds.amazonaws.com"
DB_PORT = 5432
DB_NAME = "homeai_db"
DB_USER = "webscrapinguser"
DB_PASSWORD = "IXq3IC0Uw6StMkBhb4mb"

# Local port (DBeaver typically uses dynamic, but we'll use a fixed one)
LOCAL_PORT = 54320  # Using port typically used by DBeaver

def test_db_connection():
    """Test database connection via SSH tunnel"""

    print(f"[{datetime.now()}] Setting up SSH tunnel...")

    try:
        # Create SSH tunnel
        with SSHTunnelForwarder(
            (SSH_HOST, SSH_PORT),
            ssh_username=SSH_USER,
            ssh_pkey=SSH_KEY_PATH,
            remote_bind_address=(DB_HOST, DB_PORT),
            local_bind_address=('127.0.0.1', LOCAL_PORT)
        ) as tunnel:

            print(f"[{datetime.now()}] SSH tunnel established on localhost:{tunnel.local_bind_port}")

            # Connect to database through tunnel
            conn = psycopg2.connect(
                host='localhost',
                port=tunnel.local_bind_port,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )

            print(f"[{datetime.now()}] Connected to database successfully!")

            # Test queries
            with conn.cursor() as cur:
                # Check properties_romania table
                cur.execute("SELECT COUNT(*) FROM properties_romania")
                total_count = cur.fetchone()[0]
                print(f"Total properties in Romania table: {total_count}")

                # Check recent properties (last 24 hours)
                cur.execute("""
                    SELECT COUNT(*) FROM properties_romania
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """)
                recent_count = cur.fetchone()[0]
                print(f"Properties added in last 24 hours: {recent_count}")

                # Get sample of recent properties
                cur.execute("""
                    SELECT external_id, title, price_ron, price_eur, city, created_at
                    FROM properties_romania
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY created_at DESC
                    LIMIT 5
                """)

                recent_properties = cur.fetchall()
                if recent_properties:
                    print("\nRecent properties:")
                    for prop in recent_properties:
                        price = f"RON {prop[2]}" if prop[2] else f"EUR {prop[3]}" if prop[3] else "No price"
                        print(f"  - {prop[0]}: {prop[1][:50]}... | {price} | {prop[4]} | {prop[5]}")

                # Check for price changes (for the report)
                cur.execute("""
                    SELECT COUNT(DISTINCT external_id)
                    FROM properties_romania
                    WHERE created_at > NOW() - INTERVAL '2 months'
                """)
                two_month_properties = cur.fetchone()[0]
                print(f"\nProperties tracked in last 2 months: {two_month_properties}")

                # Test price decrease detection query
                cur.execute("""
                    WITH price_history AS (
                        SELECT
                            external_id,
                            title,
                            city,
                            price_ron,
                            price_eur,
                            created_at,
                            LAG(COALESCE(price_ron, price_eur * 5)) OVER (
                                PARTITION BY external_id
                                ORDER BY created_at
                            ) as previous_price,
                            COALESCE(price_ron, price_eur * 5) as current_price_ron
                        FROM properties_romania
                        WHERE created_at > NOW() - INTERVAL '2 months'
                    )
                    SELECT COUNT(*)
                    FROM price_history
                    WHERE previous_price > current_price_ron
                    AND previous_price IS NOT NULL
                """)
                price_decreases = cur.fetchone()[0]
                print(f"Properties with price decreases: {price_decreases}")

            conn.close()
            print(f"\n[{datetime.now()}] Database connection test completed successfully!")

            return True

    except Exception as e:
        print(f"\n[{datetime.now()}] ERROR: Failed to connect to database")
        print(f"Error details: {e}")
        return False

if __name__ == "__main__":
    # Check if SSH key exists
    if not os.path.exists(SSH_KEY_PATH):
        print(f"ERROR: SSH key not found at {SSH_KEY_PATH}")
        print("Please ensure the SSH key file exists")
        exit(1)

    # Test the connection
    success = test_db_connection()

    if success:
        print("\n✅ Database connectivity test PASSED")
    else:
        print("\n❌ Database connectivity test FAILED")
        exit(1)