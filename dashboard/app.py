#!/usr/bin/env python3
"""
Imobiliare.ro Scraper Dashboard
Password-protected monitoring interface for scraper runs
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_basicauth import BasicAuth
import psycopg2
from psycopg2.extras import RealDictCursor
from sshtunnel import SSHTunnelForwarder
import os
from datetime import datetime, timedelta
import boto3
import json
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'imobiliare-dashboard-secret-2024')

# Basic Authentication
app.config['BASIC_AUTH_USERNAME'] = os.environ.get('DASHBOARD_USERNAME', 'homeai')
app.config['BASIC_AUTH_PASSWORD'] = os.environ.get('DASHBOARD_PASSWORD', 'Imobiliare2024!')
app.config['BASIC_AUTH_FORCE'] = True
basic_auth = BasicAuth(app)

# Database configuration
DB_CONFIG = {
    'ssh_host': os.environ.get('SSH_HOST', '3.221.26.92'),
    'ssh_port': 22,
    'ssh_user': 'ubuntu',
    'ssh_key': os.environ.get('SSH_PRIVATE_KEY'),  # Will use the key content directly
    'ssh_key_path': os.environ.get('SSH_KEY_PATH', '/home/cn/Desktop/HomeAiCode/id_rsa'),
    'db_host': 'webscraping-database.cluster-c9y2u088elix.us-east-1.rds.amazonaws.com',
    'db_port': 5432,
    'db_name': 'homeai_db',
    'db_user': 'webscrapinguser',
    'db_password': 'IXq3IC0Uw6StMkBhb4mb'
}

# AWS clients
ecs_client = boto3.client('ecs', region_name='us-east-1')
logs_client = boto3.client('logs', region_name='us-east-1')

def get_db_connection():
    """Create database connection via SSH tunnel"""
    import tempfile

    # Handle SSH key from environment variable or file
    ssh_key_path = DB_CONFIG.get('ssh_key_path')
    ssh_key_content = DB_CONFIG.get('ssh_key')

    if ssh_key_content:
        # Write SSH key content to temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.pem') as f:
            f.write(ssh_key_content)
            ssh_key_path = f.name
            os.chmod(ssh_key_path, 0o600)

    tunnel = SSHTunnelForwarder(
        (DB_CONFIG['ssh_host'], DB_CONFIG['ssh_port']),
        ssh_username=DB_CONFIG['ssh_user'],
        ssh_pkey=ssh_key_path,
        remote_bind_address=(DB_CONFIG['db_host'], DB_CONFIG['db_port']),
        local_bind_address=('127.0.0.1', 54321)
    )
    tunnel.start()

    conn = psycopg2.connect(
        host='localhost',
        port=tunnel.local_bind_port,
        database=DB_CONFIG['db_name'],
        user=DB_CONFIG['db_user'],
        password=DB_CONFIG['db_password'],
        cursor_factory=RealDictCursor
    )

    return conn, tunnel

@app.route('/')
@basic_auth.required
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/api/scraper-runs')
@basic_auth.required
def scraper_runs():
    """Get recent scraper run information from ECS"""
    try:
        # Get recent tasks
        tasks = ecs_client.list_tasks(
            cluster='homeai-ecs-cluster',
            family='imobiliare-scraper-task',
            maxResults=20
        )

        runs = []
        if tasks.get('taskArns'):
            task_details = ecs_client.describe_tasks(
                cluster='homeai-ecs-cluster',
                tasks=tasks['taskArns']
            )

            for task in task_details.get('tasks', []):
                run = {
                    'task_id': task['taskArn'].split('/')[-1],
                    'status': task.get('lastStatus', 'Unknown'),
                    'started_at': task.get('startedAt', '').isoformat() if task.get('startedAt') else None,
                    'stopped_at': task.get('stoppedAt', '').isoformat() if task.get('stoppedAt') else None,
                    'stopped_reason': task.get('stoppedReason', '')
                }
                runs.append(run)

        return jsonify(runs)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs/<task_id>')
@basic_auth.required
def get_logs(task_id):
    """Get logs for a specific task"""
    try:
        log_stream = f'ecs/Imobiliarescraper/{task_id}'

        response = logs_client.get_log_events(
            logGroupName='/ecs/imobiliare-scraper',
            logStreamName=log_stream,
            limit=500
        )

        logs = [event['message'] for event in response.get('events', [])]
        return jsonify({'logs': logs})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/scraped-properties')
@basic_auth.required
def scraped_properties():
    """Get scraped properties statistics"""
    try:
        conn, tunnel = get_db_connection()
        cur = conn.cursor()

        # Get total count
        cur.execute("SELECT COUNT(*) as count FROM properties_romania")
        total = cur.fetchone()['count']

        # Get count by day for last 7 days
        cur.execute("""
            SELECT
                DATE(created_at) as date,
                COUNT(*) as count
            FROM properties_romania
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """)
        daily_counts = cur.fetchall()

        # Get count by city
        cur.execute("""
            SELECT
                city,
                COUNT(*) as count
            FROM properties_romania
            GROUP BY city
            ORDER BY count DESC
            LIMIT 10
        """)
        city_counts = cur.fetchall()

        cur.close()
        conn.close()
        tunnel.stop()

        return jsonify({
            'total': total,
            'daily_counts': daily_counts,
            'city_counts': city_counts
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/price-decreases')
@basic_auth.required
def price_decreases():
    """Get properties with price drops using new price history fields"""
    try:
        conn, tunnel = get_db_connection()
        cur = conn.cursor()

        # First try using new price history columns if they exist
        try:
            cur.execute("""
                SELECT
                    fingerprint,
                    external_id,
                    title,
                    city,
                    address,
                    external_url,
                    property_type,
                    square_meters,
                    room_count,
                    price_ron as current_price,
                    previous_price_ron as original_price,
                    price_change_ron as price_decrease,
                    price_change_percentage as decrease_percentage,
                    currency,
                    price_last_changed as latest_date,
                    price_change_count,
                    price_drop_alert
                FROM properties_romania
                WHERE price_change_percentage < 0
                AND price_last_changed > NOW() - INTERVAL '30 days'
                AND status = 'ad_active'
                ORDER BY price_change_percentage ASC
                LIMIT 100
            """)
            results = cur.fetchall()

            # If no results or columns don't exist, fall back to old query
            if not results:
                raise Exception("No results with new columns")

        except:
            # Fallback to original query if new columns don't exist
            cur.execute("""
                WITH price_changes AS (
                    SELECT DISTINCT ON (external_id)
                        p1.external_id,
                        p1.title,
                        p1.city,
                        p1.address,
                        p1.external_url,
                        p1.property_type,
                        p1.square_meters,
                        p1.room_count,
                        COALESCE(p1.price_ron, p1.price_eur * 5) as current_price,
                        p1.currency,
                        p1.created_at as latest_date,
                        (
                            SELECT COALESCE(p2.price_ron, p2.price_eur * 5)
                            FROM properties_romania p2
                            WHERE p2.external_id = p1.external_id
                            AND p2.created_at < p1.created_at
                            AND p2.created_at > NOW() - INTERVAL '2 months'
                            ORDER BY p2.created_at ASC
                            LIMIT 1
                        ) as original_price
                    FROM properties_romania p1
                    WHERE p1.created_at > NOW() - INTERVAL '2 months'
                    ORDER BY p1.external_id, p1.created_at DESC
                )
                SELECT
                    external_id,
                    title,
                    city,
                    address,
                    external_url,
                    property_type,
                    square_meters,
                    room_count,
                    current_price,
                    original_price,
                    currency,
                    latest_date,
                    (original_price - current_price) as price_decrease,
                    ROUND(((original_price - current_price) / NULLIF(original_price, 0) * 100)::numeric, 2) as decrease_percentage
                FROM price_changes
                WHERE original_price > current_price
                AND original_price IS NOT NULL
                ORDER BY price_decrease DESC
                LIMIT 100
        """)

        properties = cur.fetchall()

        cur.close()
        conn.close()
        tunnel.stop()

        return jsonify(properties)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/recent-properties')
@basic_auth.required
def recent_properties():
    """Get recently scraped properties"""
    try:
        conn, tunnel = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                external_id,
                title,
                city,
                address,
                external_url,
                property_type,
                square_meters,
                room_count,
                COALESCE(price_ron, price_eur * 5) as price,
                currency,
                created_at
            FROM properties_romania
            ORDER BY created_at DESC
            LIMIT 50
        """)

        properties = cur.fetchall()

        cur.close()
        conn.close()
        tunnel.stop()

        return jsonify(properties)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/price-history/<fingerprint>')
@basic_auth.required
def price_history(fingerprint):
    """Get price history for a specific property"""
    try:
        conn, tunnel = get_db_connection()
        cur = conn.cursor()

        # Try to get price history from new column
        try:
            cur.execute("""
                SELECT
                    fingerprint,
                    title,
                    external_url,
                    price_ron as current_price_ron,
                    price_eur as current_price_eur,
                    previous_price_ron,
                    previous_price_eur,
                    price_change_percentage,
                    price_last_changed,
                    price_change_count,
                    highest_price_ron,
                    lowest_price_ron,
                    price_history::text as history_json
                FROM properties_romania
                WHERE fingerprint = %s
            """, (fingerprint,))

            property_data = cur.fetchone()

            if property_data and property_data.get('history_json'):
                import json
                try:
                    property_data['price_history'] = json.loads(property_data['history_json'])
                except:
                    property_data['price_history'] = []
                del property_data['history_json']

        except:
            property_data = None

        cur.close()
        conn.close()
        tunnel.stop()

        if property_data:
            return jsonify(property_data)
        else:
            return jsonify({'error': 'Property not found'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/price-alerts')
@basic_auth.required
def price_alerts():
    """Get properties with active price drop alerts"""
    try:
        conn, tunnel = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                fingerprint,
                external_id,
                title,
                city,
                external_url,
                property_type,
                room_count,
                square_meters,
                price_ron,
                previous_price_ron,
                price_change_percentage,
                price_last_changed
            FROM properties_romania
            WHERE price_drop_alert = TRUE
            AND status = 'ad_active'
            ORDER BY price_last_changed DESC
            LIMIT 50
        """)

        alerts = cur.fetchall()

        cur.close()
        conn.close()
        tunnel.stop()

        return jsonify(alerts)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)