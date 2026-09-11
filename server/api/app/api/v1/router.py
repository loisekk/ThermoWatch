from fastapi import APIRouter

from app.api.v1 import events, history, ingest, ml_inference, model, predict, response

api_router = APIRouter()
api_router.include_router(events.router, tags=["events"])
api_router.include_router(ingest.router, tags=["ingest"])
api_router.include_router(predict.router, tags=["ml"])
api_router.include_router(ml_inference.router, tags=["ml"])
api_router.include_router(model.router, tags=["model"])
api_router.include_router(history.router, tags=["history"])
api_router.include_router(response.router, tags=["response"])

