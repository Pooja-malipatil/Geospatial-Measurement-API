from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import files

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Geospatial File Measurement API")
app.include_router(files.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(STATIC_DIR / "index.html")