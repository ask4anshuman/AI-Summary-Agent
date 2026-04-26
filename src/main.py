# Purpose : FastAPI application entry point. Creates the app instance and registers all API routes.
# Called by: uvicorn (production/dev server) via `uvicorn src.main:app`.
#            pytest TestClient in tests/conftest.py imports `app` directly for integration tests.

from fastapi import FastAPI

from src.api.routes import router

app = FastAPI(title="AI SQL Summary Agent", version="0.1.0")
app.include_router(router)
