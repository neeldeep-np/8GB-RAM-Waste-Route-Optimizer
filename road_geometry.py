"""
Road-following geometry for the MAP ONLY.

    OR-Tools  ->  road_distance_matrix.csv  ->  optimized route ORDER
    Map       ->  OSRM road geometry        ->  how that route is DRAWN

Nothing in this file is used by the optimizer or the simulation, so it can
never change the results.  It only turns an ordered list of stops
(lat, lon) into the polyline of the roads between them.

Geometry comes from an OSRM server:
    * default: the public demo server (needs internet)
    * your own server: set the OSRM_URL environment variable
      e.g.  OSRM_URL=http://localhost:5000

Every route that is fetched successfully is saved in
`road_geometry_cache.json`, so the demo also works offline afterwards.

If the server cannot be reached, get_route_path() says so
(road_following=False) and the frontend draws a dashed straight connector
and labels it clearly - it never pretends a straight line is a road.
"""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests


# ============================================================
# SETTINGS
# ============================================================

OSRM_BASE_URL = os.environ.get(
    "OSRM_URL",
    "https://router.project-osrm.org"
).rstrip("/")

OSRM_PROFILE = "driving"

REQUEST_TIMEOUT_SECONDS = 12

CACHE_FILE = (
    Path(__file__).resolve().parent
    / "road_geometry_cache.json"
)

# Depot coordinates are NOT part of locations.csv or the distance matrix.
# Fill this in as (latitude, longitude) - or type it into the sidebar of the
# app - to draw the depot and the first/last leg of every truck route.
DEPOT_LATLON = None


# ============================================================
# CACHE (memory + disk)
# ============================================================

_lock = threading.Lock()

_cache = None                 # loaded lazily: key -> [[lat, lon], ...]

_unavailable_until = 0.0      # skip the network briefly after a failure


def _load_cache():

    global _cache

    if _cache is None:

        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except (OSError, ValueError):
            _cache = {}

    return _cache


def _save_cache():

    try:
        tmp = CACHE_FILE.with_suffix(".tmp")

        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cache, f)

        os.replace(tmp, CACHE_FILE)

    except OSError:
        pass        # cache is a convenience, never a requirement


def _key(points):

    return "|".join(
        f"{lat:.6f},{lon:.6f}"
        for lat, lon in points
    )


# ============================================================
# OSRM REQUEST
# ============================================================

def _fetch_from_osrm(points):
    """Ask OSRM for the road path through `points`. None on failure."""

    global _unavailable_until

    if time.time() < _unavailable_until:
        return None

    coordinates = ";".join(
        f"{lon:.6f},{lat:.6f}"
        for lat, lon in points
    )

    url = (
        f"{OSRM_BASE_URL}/route/v1/{OSRM_PROFILE}/{coordinates}"
        "?overview=full&geometries=geojson"
        "&steps=false&continue_straight=false"
    )

    for attempt in range(2):

        try:

            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT_SECONDS
            )

            if response.status_code in (429, 502, 503, 504):
                time.sleep(1.5)
                continue

            response.raise_for_status()

            payload = response.json()

            if payload.get("code") != "Ok":
                return None

            line = payload["routes"][0]["geometry"]["coordinates"]

            # GeoJSON is [lon, lat]; folium wants [lat, lon]
            return [[lat, lon] for lon, lat in line]

        except (requests.RequestException, ValueError, KeyError, IndexError):
            _unavailable_until = time.time() + 30
            return None

    return None


# ============================================================
# PUBLIC API
# ============================================================

def get_route_path(points):
    """
    Road-following path through an ordered list of (lat, lon) points.

    Returns {"path": [[lat, lon], ...], "road_following": bool}
    road_following=False means the server was unreachable and `path`
    is just the straight connector between the stops.
    """

    points = [(float(lat), float(lon)) for lat, lon in points]

    if len(points) < 2:
        return {"path": [list(p) for p in points], "road_following": True}

    key = _key(points)

    with _lock:
        cached = _load_cache().get(key)

    if cached:
        return {"path": cached, "road_following": True}

    path = _fetch_from_osrm(points)

    if path:

        with _lock:
            _load_cache()[key] = path
            _save_cache()

        return {"path": path, "road_following": True}

    return {
        "path": [list(p) for p in points],
        "road_following": False
    }


def prefetch_routes(point_lists, max_workers=3, on_progress=None):
    """
    Fetch (and cache) geometry for many routes in parallel.

    Returns the number of routes that ended up road-following.
    """

    unique = {}

    for points in point_lists:
        unique[_key(points)] = points

    total = len(unique)

    done = 0
    road_following = 0

    if total == 0:
        return 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:

        for result in pool.map(get_route_path, unique.values()):

            done += 1
            road_following += bool(result["road_following"])

            if on_progress is not None:
                on_progress(done, total)

    return road_following


def parse_depot(text):
    """Parse 'lat, lon' typed by the user. Returns (lat, lon) or None."""

    if not text or not text.strip():
        return None

    try:

        lat_text, lon_text = text.replace(";", ",").split(",")

        lat, lon = float(lat_text), float(lon_text)

    except ValueError:
        return None

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    return (lat, lon)
