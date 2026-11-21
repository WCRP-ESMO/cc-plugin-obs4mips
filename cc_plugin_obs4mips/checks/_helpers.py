"""
Pure helpers shared by the checks: URL/UUID tests, grid geometry, nominal_resolution.

Nothing here depends on the CVs or on an ODS version. The nominal_resolution tables come
from the CMIP6 global attributes document (Appendix 2), not from an ODS release; if a
future ODS changes them, move them to class attributes of that version's check class.
"""

import re
from bisect import bisect_right
from urllib.parse import urlsplit
from uuid import UUID

import numpy as np
from compliance_checker.cf import util as cfutil

EARTH_RADIUS_KM = 6371.0
NOMINAL_RESOLUTION_UPPER_BOUNDS_KM = (0.72, 1.6, 3.6, 7.2, 16, 36, 72, 160, 360, 720, 1600, 3600, 7200)
NOMINAL_RESOLUTION_LABELS_KM = (0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
NOMINAL_RESOLUTION_BOUNDARY_TOLERANCE = 0.03
STANDARD_GRID_NOMINAL_RESOLUTIONS = ("1x1 degree", "100 km")


def _is_url(value):
    parsed = urlsplit(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _is_uuid(value):
    try:
        UUID(value.rsplit("/", 1)[-1])
    except ValueError:
        return False
    return True


def _regular_latlon(ds):
    """Names of the 1-D latitude and longitude coordinates of a regular grid, else None."""
    lats = [n for n in cfutil.get_latitude_variables(ds) if ds.variables[n].ndim == 1]
    lons = [n for n in cfutil.get_longitude_variables(ds) if ds.variables[n].ndim == 1]
    return (lats[0], lons[0]) if lats and lons else None


def _cell_edges(ds, name):
    """
    Cell edges (ascending) of a 1-D coordinate: from its contiguous bounds if it has
    them, else halfway between the cell centers. None when there is a single cell.
    """
    var = ds.variables[name]
    centers = np.sort(np.ma.filled(var[:], np.nan).astype(float))
    bounds = ds.variables.get(getattr(var, "bounds", ""))
    if bounds is not None and bounds.ndim == 2 and bounds.shape[0] == len(centers):
        edges = np.unique(np.ma.filled(bounds[:], np.nan).astype(float))
        if len(edges) == len(centers) + 1:
            return edges
    if len(centers) < 2:
        return None
    middle = (centers[:-1] + centers[1:]) / 2
    return np.concatenate(
        ([2 * centers[0] - middle[0]], middle, [2 * centers[-1] - middle[-1]])
    )


def mean_resolution_km(lat_edges, lon_edges):
    """
    Mean over all cells of the largest distance between two cell vertices, weighted by
    cell area (CMIP6 global attributes document, Appendix 2), for a lat/lon grid.
    """
    lat = np.radians(np.clip(lat_edges, -90, 90))
    lon = np.radians(lon_edges)

    def distance(lon1, lat1, lon2, lat2):  # great-circle (haversine), km
        a = np.sin((lat2 - lat1) / 2) ** 2
        a = a + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
        return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))

    west, east, width = lon[:-1], lon[1:], np.diff(lon)
    weighted = total = 0.0
    for south, north in zip(lat[:-1], lat[1:]):
        # the largest of the six vertex-to-vertex distances (a diagonal or a long side)
        dmax = np.max(
            [
                distance(west, south, east, south),
                distance(west, north, east, north),
                distance(west, south, west, north),
                distance(west, south, east, north),
                distance(west, north, east, south),
            ],
            axis=0,
        )
        area = EARTH_RADIUS_KM**2 * width * abs(np.sin(north) - np.sin(south))
        weighted += np.sum(area * dmax)
        total += np.sum(area)
    return weighted / total


def nominal_resolutions_km(mean_km):
    """Labels (in km) a mean resolution may take; both sides if it is near a bound."""
    bounds, labels = NOMINAL_RESOLUTION_UPPER_BOUNDS_KM, NOMINAL_RESOLUTION_LABELS_KM
    i = bisect_right(bounds, mean_km)
    tolerance = NOMINAL_RESOLUTION_BOUNDARY_TOLERANCE
    accepted = {labels[i]}
    if i > 0 and mean_km < bounds[i - 1] * (1 + tolerance):
        accepted.add(labels[i - 1])
    if i < len(bounds) and mean_km > bounds[i] * (1 - tolerance):
        accepted.add(labels[i + 1])
    return accepted


def _nominal_resolution_km(value):
    """'100 km' -> 100.0 and '500-m' -> 0.5; None for anything else."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(?: km|-m)", value.strip())
    if match is None:
        return None
    return float(match[1]) / (1000 if value.strip().endswith("-m") else 1)


def _is_standard_grid(lat_edges, lon_edges):
    """The WIP standard grid: 1x1 degree, 360 x 180 cells, a longitude centered at 0.5E."""
    return (
        len(lat_edges) == 181
        and len(lon_edges) == 361
        and np.allclose(np.diff(lat_edges), 1)
        and np.allclose(np.diff(lon_edges), 1)
        and np.isclose(lat_edges[0], -90)
        and np.isclose(lon_edges[0], round(lon_edges[0]))  # centers at x.5, e.g. 0.5E
    )


