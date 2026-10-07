from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "MultiLineString"}


def _utm_epsg(lon: float, lat: float) -> int:
    """Pick the UTM zone that covers this longitude/latitude."""
    zone = min(max(int((lon + 180) // 6) + 1, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone


def measure_feature(geometry_dict: dict | None, source_crs: str) -> dict:
    result = {
        "supported": False,
        "projected_crs": None,
        "area_sq_m": None,
        "length_m": None,
        "note": None,
    }

    if not geometry_dict:
        result["note"] = "Feature has no geometry."
        return result

    geom = shape(geometry_dict)
    if geom.is_empty:
        result["note"] = "Feature geometry is empty."
        return result

    if geom.geom_type in ("Point", "MultiPoint"):
        result["note"] = "No measurement required for points."
        return result

    if geom.geom_type not in AREA_TYPES | LENGTH_TYPES:
        result["note"] = f"Measurement not supported for {geom.geom_type}."
        return result

    # 1. Find where the shape is on Earth (lon/lat) to choose the UTM zone.
    to_lonlat = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    centroid = geom.centroid
    lon, lat = to_lonlat.transform(centroid.x, centroid.y)
    utm_crs = f"EPSG:{_utm_epsg(lon, lat)}"

    # 2. Reproject the shape into that metric CRS.
    to_utm = Transformer.from_crs(source_crs, utm_crs, always_xy=True)
    projected = transform(to_utm.transform, geom)

    # 3. Measure in meters.
    result["supported"] = True
    result["projected_crs"] = utm_crs
    if geom.geom_type in AREA_TYPES:
        result["area_sq_m"] = round(projected.area, 3)
    else:
        result["length_m"] = round(projected.length, 3)
    return result

def geometry_to_wgs84(geometry_dict: dict | None, source_crs: str) -> dict | None:
    """Convert a stored geometry to lon/lat so a web map can draw it."""
    if not geometry_dict:
        return None
    if source_crs == "EPSG:4326":
        return geometry_dict
    to_lonlat = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    return mapping(transform(to_lonlat.transform, shape(geometry_dict)))