import shutil
from pathlib import Path

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from app.main import app
from app.routers import files
from app.services.measurements import measure_feature

SAMPLE_KML = Path(__file__).parent.parent / "sample" / "test_plot.kml"


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Save uploads in a temporary folder and start each test with an empty store.
    monkeypatch.setattr(files, "UPLOAD_DIR", tmp_path)
    files.files_db.clear()
    return TestClient(app)


def upload_sample_kml(client):
    with open(SAMPLE_KML, "rb") as f:
        return client.post("/api/files/", files={"file": ("test_plot.kml", f)})


def test_upload_kml_succeeds(client):
    response = upload_sample_kml(client)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["crs"] == "EPSG:4326"
    assert body["feature_count"] == 3


def test_rejects_unsupported_extension(client):
    response = client.post("/api/files/", files={"file": ("notes.txt", b"hello")})
    assert response.status_code == 400


def test_rejects_empty_file(client):
    response = client.post("/api/files/", files={"file": ("empty.kml", b"")})
    assert response.status_code == 400


def test_corrupt_kml_returns_422_not_crash(client):
    response = client.post("/api/files/", files={"file": ("broken.kml", b"not xml")})
    assert response.status_code == 422


def test_file_info(client):
    file_id = upload_sample_kml(client).json()["id"]
    response = client.get(f"/api/files/{file_id}/")
    assert response.status_code == 200
    assert response.json()["feature_count"] == 3


def test_unknown_file_returns_404(client):
    assert client.get("/api/files/doesnotexist/").status_code == 404
    assert client.get("/api/files/doesnotexist/measurements/").status_code == 404


def test_measurements_are_in_meters(client):
    file_id = upload_sample_kml(client).json()["id"]
    items = client.get(f"/api/files/{file_id}/measurements/").json()["measurements"]
    by_type = {item["geometry_type"]: item for item in items}

    polygon = by_type["Polygon"]
    assert polygon["projected_crs"] == "EPSG:32643"
    assert 11_900 < polygon["area_sq_m"] < 12_100  # about 108.5 m x 110.7 m

    line = by_type["LineString"]
    assert 150 < line["length_m"] < 160

    point = by_type["Point"]
    assert point["supported"] is False


def test_shapefile_zip_upload(client, tmp_path):
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    square = Polygon([(77.59, 12.97), (77.591, 12.97), (77.591, 12.971), (77.59, 12.971)])
    gpd.GeoDataFrame({"name": ["plot"]}, geometry=[square], crs="EPSG:4326").to_file(
        shp_dir / "plots.shp"
    )
    zip_path = shutil.make_archive(str(tmp_path / "plots"), "zip", root_dir=shp_dir)

    with open(zip_path, "rb") as f:
        response = client.post("/api/files/", files={"file": ("plots.zip", f)})
    assert response.status_code == 201
    assert response.json()["feature_count"] == 1


def test_unsupported_geometry_is_handled_gracefully():
    collection = {
        "type": "GeometryCollection",
        "geometries": [{"type": "Point", "coordinates": [77.59, 12.97]}],
    }
    result = measure_feature(collection, "EPSG:4326")
    assert result["supported"] is False
    assert "not supported" in result["note"]
    
    
def test_geojson_for_map(client):
    file_id = upload_sample_kml(client).json()["id"]
    body = client.get(f"/api/files/{file_id}/geojson/").json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 3
    
    
def test_shapefile_inside_subfolder_of_zip(client, tmp_path):
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    square = Polygon([(77.59, 12.97), (77.591, 12.97), (77.591, 12.971), (77.59, 12.971)])
    gpd.GeoDataFrame({"name": ["plot"]}, geometry=[square], crs="EPSG:4326").to_file(
        shp_dir / "plots.shp"
    )
    # root_dir is the parent, so files end up inside a "shp/" folder in the zip
    zip_path = shutil.make_archive(str(tmp_path / "nested"), "zip", root_dir=tmp_path, base_dir="shp")

    with open(zip_path, "rb") as f:
        response = client.post("/api/files/", files={"file": ("nested.zip", f)})
    assert response.status_code == 201
    assert response.json()["feature_count"] == 1


def test_zip_without_shapefile_gives_clear_error(client):
    import io, zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("readme.txt", "hello")
    response = client.post("/api/files/", files={"file": ("empty.zip", buffer.getvalue())})
    assert response.status_code == 422
    assert "does not contain a .shp" in response.json()["detail"]
    
def test_features_have_all_required_fields(client):
    file_id = upload_sample_kml(client).json()["id"]
    body = client.get(f"/api/files/{file_id}/features/").json()
    assert body["feature_count"] == 3
    for feature in body["features"]:
        assert set(feature) >= {"index", "geometry_type", "geometry", "crs", "properties"}