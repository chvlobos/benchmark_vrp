"""Geography: the urban polygon and point sampling inside it.

The packaged ``data/santiago_urban.geojson`` is a hand-digitised envelope of the
consolidated urban area of Greater Santiago (about 790 km²), traced along the
2017 census urban limit: it keeps Quilicura, Huechuraba, La Dehesa, Las Condes,
Peñalolén, La Florida, Puente Alto, San Bernardo, Maipú and Pudahuel, and leaves
out the airport, the Andean foothills and the rural fringe. It is an
approximation for synthetic instances, not an official boundary.
"""

from __future__ import annotations

import json
import math
from importlib import resources
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon, box
from shapely.prepared import prep

KM_PER_DEG_LAT = 110.57


def km_per_deg_lon(lat: float) -> float:
    return 111.32 * math.cos(math.radians(lat))


def load_polygon(name_or_path: str = "santiago_urban.geojson") -> Polygon:
    """Load a polygon from the package data or from a path (first feature of a collection)."""
    p = Path(name_or_path)
    if p.exists():
        text = p.read_text(encoding="utf-8")
    else:
        text = (
            resources.files("cvrptw_bench.data").joinpath(name_or_path).read_text(encoding="utf-8")
        )
    gj = json.loads(text)
    geom = gj["features"][0]["geometry"] if gj.get("type") == "FeatureCollection" else gj
    if geom["type"] != "Polygon":
        raise ValueError("only Polygon geometries are supported")
    poly = Polygon(geom["coordinates"][0], geom["coordinates"][1:])
    if not poly.is_valid:
        raise ValueError("invalid polygon")
    return poly


def bbox_polygon(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> Polygon:
    return box(min_lon, min_lat, max_lon, max_lat)


class Region:
    """Sampling helper around a polygon (lon/lat, WGS84)."""

    def __init__(self, polygon: Polygon):
        self.polygon = polygon
        self._prep = prep(polygon)
        self.min_lon, self.min_lat, self.max_lon, self.max_lat = polygon.bounds
        self.centroid_lat = polygon.centroid.y

    def contains(self, lon: float, lat: float) -> bool:
        return self._prep.contains(Point(lon, lat))

    def sample_uniform(self, rng: np.random.Generator, k: int) -> np.ndarray:
        """k points uniform in the polygon, shape (k, 2) as (lon, lat). Rejection sampling."""
        out = np.empty((k, 2))
        filled = 0
        while filled < k:
            m = max(64, 2 * (k - filled))
            lon = rng.uniform(self.min_lon, self.max_lon, m)
            lat = rng.uniform(self.min_lat, self.max_lat, m)
            for x, y in zip(lon, lat, strict=True):
                if self._prep.contains(Point(x, y)):
                    out[filled] = (x, y)
                    filled += 1
                    if filled == k:
                        break
        return out

    def sample_gaussian(
        self, rng: np.random.Generator, center: tuple[float, float], sigma_km: float, k: int
    ) -> np.ndarray:
        """k points ~ N(center, sigma_km) in the plane, re-drawn until inside the polygon."""
        clon, clat = center
        s_lat = sigma_km / KM_PER_DEG_LAT
        s_lon = sigma_km / km_per_deg_lon(clat)
        out = np.empty((k, 2))
        filled = 0
        while filled < k:
            m = max(32, 2 * (k - filled))
            lon = rng.normal(clon, s_lon, m)
            lat = rng.normal(clat, s_lat, m)
            for x, y in zip(lon, lat, strict=True):
                if self._prep.contains(Point(x, y)):
                    out[filled] = (x, y)
                    filled += 1
                    if filled == k:
                        break
        return out
