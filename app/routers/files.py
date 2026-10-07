import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from app.services.geo_reader import GeoFileError, read_features
from app.services.measurements import measure_feature
from app.services.measurements import geometry_to_wgs84, measure_feature

router = APIRouter(prefix="/api/files", tags=["files"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".kml", ".zip"}

# Temporary in-memory store. We'll improve this in a later step.
files_db: dict[str, dict] = {}


@router.post("/", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Upload a .kml or a .zip (Shapefile).",
        )

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    
    
    file_id = uuid.uuid4().hex
    saved_path = UPLOAD_DIR / f"{file_id}{extension}"
    saved_path.write_bytes(contents)

    record = {
        "id": file_id,
        "filename": file.filename,
        "path": str(saved_path),
        "status": "PROCESSING",
        "crs": None,
        "feature_count": 0,
        "features": [],
        "error": None,
    }
    files_db[file_id] = record

    try:
        result = read_features(saved_path)
    except GeoFileError as exc:
        record["status"] = "FAILED"
        record["error"] = str(exc)
        raise HTTPException(status_code=422, detail=str(exc))

    record["crs"] = result["crs"]
    record["features"] = result["features"]
    record["feature_count"] = len(result["features"])
    record["status"] = "COMPLETED"

    return {
        "id": file_id,
        "filename": file.filename,
        "status": record["status"],
        "crs": record["crs"],
        "feature_count": record["feature_count"],
    }


def _get_record_or_404(file_id: str) -> dict:
    record = files_db.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return record


@router.get("/{file_id}/")
def get_file_info(file_id: str):
    record = _get_record_or_404(file_id)
    return {
        "id": record["id"],
        "filename": record["filename"],
        "feature_count": record["feature_count"],
        "crs": record["crs"],
        "status": record["status"],
        "error": record["error"],
    }


@router.get("/{file_id}/measurements/")
def get_measurements(file_id: str):
    record = _get_record_or_404(file_id)
    if record["status"] != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"File is not ready. Current status: {record['status']}.",
        )

    measurements = []
    for feature in record["features"]:
        try:
            measured = measure_feature(feature["geometry"], feature["crs"])
        except Exception as exc:
            measured = {
                "supported": False,
                "projected_crs": None,
                "area_sq_m": None,
                "length_m": None,
                "note": f"Measurement failed: {exc}",
            }
        measurements.append(
            {
                "index": feature["index"],
                "geometry_type": feature["geometry_type"],
                "properties": feature["properties"],
                **measured,
            }
        )

    return {"id": record["id"], "crs": record["crs"], "measurements": measurements}



@router.get("/{file_id}/geojson/")
def get_geojson(file_id: str):
    record = _get_record_or_404(file_id)
    if record["status"] != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"File is not ready. Current status: {record['status']}.",
        )

    features = []
    for feature in record["features"]:
        try:
            geometry = geometry_to_wgs84(feature["geometry"], feature["crs"])
        except Exception:
            geometry = None
        if geometry is None:
            continue  # skip shapes we can't draw instead of failing the request
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {"feature_index": feature["index"], **feature["properties"]},
            }
        )
    return {"type": "FeatureCollection", "features": features}

@router.get("/{file_id}/features/")
def get_features(file_id: str):
    record = _get_record_or_404(file_id)
    if record["status"] != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"File is not ready. Current status: {record['status']}.",
        )
    return {
        "id": record["id"],
        "feature_count": record["feature_count"],
        "features": record["features"],
    }
    