from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.jobs import router as jobs_router

app = FastAPI(title="Universal Video Content Extraction Platform")

app.include_router(auth_router)
app.include_router(jobs_router)


@app.get("/health")
def health():
    return {"status": "ok"}
