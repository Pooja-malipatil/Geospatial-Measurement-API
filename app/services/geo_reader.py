import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely.geometry import mapping


class GeoFileError(Exception):
    """Raised when an uploaded geospatial file cannot be read or understood."""


def _clean_value(value):
    """Turn a property value into something JSON can handle."""
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):  # numpy number -> plain Python number
        value = value.item()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)  # dates and anything unusual become text


def _crs_to_string(crs):
    epsg = crs.to_epsg()
    return f"EPSG:{epsg}" if epsg else crs.to_string()


def _load_shapefile_zip(path: Path) -> gpd.GeoDataFrame:
    """Find every .shp inside the zip (even in sub-folders) and read it."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = [
                name
                for name in archive.namelist()
                if name.lower().endswith(".shp") and not name.startswith("__MACOSX")
            ]
    except zipfile.BadZipFile:
        raise GeoFileError("The uploaded file is not a valid zip archive.")

    if not members:
        raise GeoFileError("The zip does not contain a .shp file.")

    frames = []
    for member in members:
        frame = gpd.read_file(f"/vsizip/{path.as_posix()}/{member}")
        if frame.crs is None:
            raise GeoFileError(
                f"The Shapefile '{member}' has no coordinate system (.prj file is missing)."
            )
        frames.append(frame)

    # If the zip holds several Shapefiles in different CRSs, convert to the first one.
    target_crs = frames[0].crs
    frames = [f if f.crs == target_crs else f.to_crs(target_crs) for f in frames]
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=target_crs)


def _load_geodataframe(path: Path) -> gpd.GeoDataFrame:
    extension = path.suffix.lower()

    if extension == ".kml":
        # A KML can hold several layers (one per Folder), so read them all.
        layer_names = pyogrio.list_layers(str(path))[:, 0]
        frames = [gpd.read_file(str(path), layer=name) for name in layer_names]
        if not frames:
            raise GeoFileError("The KML file contains no layers.")
        gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")  # KML is always lon/lat WGS84
        return gdf

    if extension == ".zip":
        return _load_shapefile_zip(path)

    raise GeoFileError(f"Unsupported file type: {extension}")


def read_features(path: Path) -> dict:
    """Read a KML or zipped Shapefile and return its CRS and features."""
    try:
        gdf = _load_geodataframe(path)
    except GeoFileError:
        raise
    except Exception as exc:
        raise GeoFileError(f"Could not read the geospatial file: {exc}") from exc

    crs = _crs_to_string(gdf.crs)
    geometry_column = gdf.geometry.name

    features = []
    for index, row in gdf.iterrows():
        geometry = row.geometry
        properties = {
            key: _clean_value(value)
            for key, value in row.drop(geometry_column).items()
        }
        features.append(
            {
                "index": int(index),
                "geometry_type": geometry.geom_type if geometry is not None else None,
                "geometry": mapping(geometry) if geometry is not None else None,
                "crs": crs,
                "properties": properties,
            }
        )

    return {"crs": crs, "features": features}