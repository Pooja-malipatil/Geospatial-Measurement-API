# Geospatial File Measurement API

A FastAPI service that takes a KML file or a zipped Shapefile, reads the features inside it, and returns the area of polygons and the length of lines in meters.

## Setup

You need Python 3.10 or newer (I used 3.14).

```bash
git clone https://github.com/<Pooja-Malipatil>/Geospatial-Measurement-API.git
cd geo-measurement-api

python -m venv venv
venv\Scripts\activate          # on macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

- API docs (you can try the endpoints here): http://127.0.0.1:8000/docs
- Map viewer: http://127.0.0.1:8000/

Run the tests with `pytest -v`. The first run takes about 30 seconds because the geo libraries are slow to load.

Sample files to try are in the `sample/` folder.

## API

| Method | Path | What it does |
|---|---|---|
| POST | `/api/files/` | Upload a `.kml` or a `.zip` containing a Shapefile |
| GET | `/api/files/{id}/` | Info about the uploaded file |
| GET | `/api/files/{id}/measurements/` | Area or length for each feature |
| GET | `/api/files/{id}/features/` | Index, geometry type, geometry, CRS and properties of each feature |
| GET | `/api/files/{id}/geojson/` | Shapes as GeoJSON in EPSG:4326 (used by the map viewer) |

### Upload

```bash
curl -F "file=@sample/test_plot.kml" http://127.0.0.1:8000/api/files/
```

```json
{
  "id": "cd49c6e86f9a4b7ba43dbfd36d17399b",
  "filename": "test_plot.kml",
  "status": "COMPLETED",
  "crs": "EPSG:4326",
  "feature_count": 3
}
```

### File information

`GET /api/files/cd49c6e86f9a4b7ba43dbfd36d17399b/`

```json
{
  "id": "cd49c6e86f9a4b7ba43dbfd36d17399b",
  "filename": "test_plot.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error": null
}
```

### Measurements

`GET /api/files/cd49c6e86f9a4b7ba43dbfd36d17399b/measurements/`

KML files also carry some default fields (tessellate, extrude, etc.), which I left out of `properties` below to keep it short.

```json
{
  "id": "cd49c6e86f9a4b7ba43dbfd36d17399b",
  "crs": "EPSG:4326",
  "measurements": [
    {
      "index": 0,
      "geometry_type": "Polygon",
      "properties": { "Name": "Test Plot" },
      "supported": true,
      "projected_crs": "EPSG:32643",
      "area_sq_m": 12016.97,
      "length_m": null,
      "note": null
    },
    {
      "index": 1,
      "geometry_type": "LineString",
      "properties": { "Name": "Test Road" },
      "supported": true,
      "projected_crs": "EPSG:32643",
      "area_sq_m": null,
      "length_m": 155.044,
      "note": null
    },
    {
      "index": 2,
      "geometry_type": "Point",
      "properties": { "Name": "Test Point" },
      "supported": false,
      "projected_crs": null,
      "area_sq_m": null,
      "length_m": null,
      "note": "No measurement required for points."
    }
  ]
}
```

### Errors

Errors come back as `{"detail": "message"}`.

| Code | When |
|---|---|
| 400 | Wrong file type, or the file is empty |
| 404 | File id not found |
| 409 | Measurements asked for a file that is not `COMPLETED` |
| 422 | The file could not be read (broken KML, invalid zip, no `.shp` in the zip, Shapefile without a `.prj`) |

## Architecture

### Application structure

```
app/
  main.py                   creates the app and registers the routes
  routers/files.py          the API endpoints
  services/geo_reader.py    reads KML / zipped Shapefile into features
  services/measurements.py  picks the projected CRS and calculates area / length
  static/index.html         map viewer
tests/test_api.py           tests
sample/                     example files to upload
```

The router only handles the HTTP side (checks, status codes, responses). The geospatial work is in `services/`, so it does not depend on FastAPI.

### File-processing flow

1. The file is checked: only `.kml` or `.zip` is allowed, and it must not be empty.
2. It is saved with a generated id as its name (not the original filename).
3. It is read with GeoPandas. For a KML, every layer (Folder) is read and combined. For a zip, the `.shp` file is found inside the archive, even in a sub-folder.
4. For each feature we keep the index, geometry type, geometry, CRS and properties.
5. The result is stored with status `COMPLETED`. If reading fails, the status is `FAILED` and the API returns a 422 with the reason.

### Measurement flow

When `/measurements/` is called, each feature is handled on its own:

1. Points, empty geometries and unsupported types are not measured. They get `supported: false` and a note.
2. For polygons and lines, the geometry is converted to a projected CRS (see below).
3. Polygons get `area_sq_m` and lines get `length_m`, calculated in the projected CRS.

If one feature fails, only that feature gets a note. The rest of the response is not affected.

### CRS handling

Latitude and longitude are in degrees, and a degree is not a fixed distance, so area or length calculated on them is wrong. Before measuring, I convert each geometry to the UTM zone where it is located.

The zone is chosen from the centre point (centroid) of the feature:

```python
zone = min(max(int((lon + 180) // 6) + 1, 1), 60)
epsg = (32600 if lat >= 0 else 32700) + zone   # 326xx north, 327xx south
```

The conversion is done with `pyproj`, using `always_xy=True` so the coordinates always stay in (longitude, latitude) order. The area and length are then taken from the converted shape. The zone that was used is returned as `projected_crs`. This works for files in any CRS, not only EPSG:4326.

## Design decisions

- **FastAPI instead of Django.** It is quicker to set up for a small API, and it gives automatic validation and the `/docs` page.
- **UTM zone per feature.** It is accurate for small and medium areas and easy to explain. I also considered one equal-area CRS for everything (for example EPSG:6933) and a geodesic calculation with `pyproj.Geod`. Both are options for later, but UTM was the simplest good choice.
- **GeoPandas for reading files.** One library reads both KML and Shapefile and gives the CRS.
- **Shapefile without a `.prj` is rejected.** Without a CRS the result would be a guess, and a wrong number is worse than an error message.
- **All KML layers are read.** Files from Google Earth put features in Folders, and reading only the first layer would lose data.
- **Uploads are saved under a generated id.** This avoids name clashes and unsafe filenames.
- **Files are processed during the upload request, and records are kept in memory.** This keeps the project simple. The downside is covered in future scope.
- **Unsupported geometries return a note instead of an error,** so one odd feature does not break the whole file.

## Extra: map viewer

Open http://127.0.0.1:8000/ to upload a file and see the shapes on a map (Leaflet) with a table of measurements. Clicking a row zooms to that shape. It is one static HTML file served by FastAPI, so nothing extra needs to be installed.

![Viewer](docs/screenshot.png)

## Learning and future scope

### What I learned

- Why you cannot measure area or distance in degrees, and how projected systems like UTM fix that.
- How UTM zones are numbered, and the latitude/longitude axis-order problem in `pyproj`.
- How KML and Shapefiles are structured: Folders become layers, and a Shapefile is really several files in a zip.
- Building an API with FastAPI: routers, status codes, and keeping the logic in a separate service layer.
- Writing tests for edge cases, such as a Shapefile inside a sub-folder of the zip, an empty file, and a zip with no Shapefile.

### Future scope

- Store the records in a database (PostgreSQL with PostGIS) instead of memory.
- Process big files in a background job, and add a file size limit.
- Measure shapes that cross several UTM zones more accurately, for example with a geodesic calculation.
- Measure the parts of mixed geometries (a KML placemark with a point and a line together is currently reported as unsupported).
- Support more formats such as KMZ and GeoJSON.