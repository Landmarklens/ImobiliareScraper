# -*- coding: utf-8 -*-
"""
Mixin for spiders that need geocoding functionality
"""
import os
import logging

logger = logging.getLogger(__name__)


class GeocodingMixin:
    """Mixin to add geocoding configuration to spiders"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Skip initialization in test mode
        if os.environ.get('PYTEST_CURRENT_TEST'):
            return
            
        # Set OpenCage API key
        api_key = None
        
        # Check if running on AWS (ECS)
        if os.environ.get('AWS_EXECUTION_ENV') or os.environ.get('ECS_CONTAINER_METADATA_URI'):
            # Running on AWS - try to get from parameter store
            try:
                import boto3
                ssm = boto3.client('ssm', region_name='us-east-1')
                
                # Get the API key from parameter store with timeout
                response = ssm.get_parameter(
                    Name='/HomeAiScrapper/OPEN_CAGE',
                    WithDecryption=True
                )
                api_key = response['Parameter']['Value']
                logger.info("OpenCage API key loaded from AWS Parameter Store")
            except Exception as e:
                logger.error(f"Failed to load OpenCage API key from Parameter Store: {e}")
        else:
            # Running locally - use hardcoded key for testing
            api_key = os.environ.get('OPENCAGE_API_KEY', '53e7e46a4d9f4774a1151682d1ffd91b')
            if api_key:
                logger.info("OpenCage API key loaded for local testing")
            else:
                logger.warning("No OpenCage API key found")
        
        # Set the API key in environment for geocoding utility
        if api_key:
            os.environ['OPENCAGE_API_KEY'] = api_key
        else:
            logger.warning("Geocoding will be disabled - no API key available")