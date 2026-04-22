from fastapi import FastAPI

from src.api.routes import router

app = FastAPI(title="AI SQL Summary Agent", version="0.1.0")
app.include_router(router)
