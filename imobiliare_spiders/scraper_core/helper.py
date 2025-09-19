import re
from datetime import datetime
from math import ceil

import requests
from io import StringIO
from html.parser import HTMLParser
import jsonpath_ng.ext as jp
import jmespath
import json
import os

def jp_all_ctx(data, path):
    return jp.parse(path).find(data)


def jp_all(data, path, as_string=False, return_type=None):
    result = [
        match.value if not as_string else str(match.value)
        for match in jp_all_ctx(data, path)
    ]
    if return_type:
        return return_type(result)
    return result


def jp_first(data, path, default=None, allow_none=True):
    matches = jp_all(data, path)
    if len(matches) > 0:
        ret = matches[0]
        if ret is None and not allow_none:
            return default
        return ret
    return default


def jp_update(data, path, value):
    jp.parse(path).update_or_create(data, value)


def jm_all(data, path: str, as_string=False, return_type=None):
    path = path.removeprefix("$").removeprefix(".")
    result = jmespath.search(path, data)
    if not isinstance(result, list):
        result = [result]
    if as_string:
        result = [str(r) for r in result]
    if return_type:
        return return_type(result)
    if result is None:
        return []
    return result


def jm_first(data, path: str, default=None, allow_none=True):
    result = jm_all(data, path)
    if result and len(result) > 0:
        ret = result[0]
        if ret is None and not allow_none:
            return default
        return ret
    return default


# ---------------------------------------------------------------------------
# ID cache functions removed - now using database as source of truth
# ---------------------------------------------------------------------------
# The ID cache functionality has been moved to the pipeline where it
# loads existing IDs directly from the database on spider startup.
# This ensures consistency across deployments and eliminates the need
# for file-based caching.


def calculate_bedrooms_from_rooms(rooms):
    """
    Convert Swiss room count to bedrooms.
    In Switzerland, room count includes living room, so:
    - 1 room = studio (0 bedrooms)
    - 2 rooms = 1 bedroom + living room
    - 3.5 rooms = 2 bedrooms + living room + small room/kitchen
    """
    if rooms is None:
        return None
    
    try:
        room_count = float(rooms)
        if room_count <= 1:
            return 0  # Studio
        else:
            # Subtract 1 for living room, floor to get bedrooms
            return max(0, int(room_count) - 1)
    except (ValueError, TypeError):
        return None


def safe_int(value, default=None):
    """Safely convert value to int, return default if conversion fails."""
    if value is None:
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def safe_float(value, default=None):
    """Safely convert value to float, return default if conversion fails."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_bool(value, default=None):
    """Safely convert value to bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', 'yes', '1', 'oui', 'ja')
    return bool(value)

