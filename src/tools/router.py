import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from src.config import runtime_profile
from src.tools.market_data import market_data
from src.tools.models import (
    MarketDataRequest,
    MarketDataResponse,
    SearchResourcesRequest,
    SearchResourcesResponse,
)
from src.tools.search_resources import search_resources


async def _verify_tools_secret(
    x_pipeline_secret: Optional[str] = Header(None),
) -> None:
    shared_secret = os.getenv("PIPELINE_SHARED_SECRET")
    if not shared_secret:
        if (
            runtime_profile.FREE_HF_MODE
            or os.getenv("ENVIRONMENT") == "production"
            or os.getenv("ALLOW_DEV_AUTH_BYPASS") != "true"
        ):
            raise HTTPException(
                status_code=500,
                detail="PIPELINE_SHARED_SECRET must be configured",
            )
        return
    if x_pipeline_secret != shared_secret:
        raise HTTPException(status_code=401, detail="Invalid pipeline secret")


router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/search_resources", response_model=SearchResourcesResponse)
async def search_resources_endpoint(
    request: SearchResourcesRequest,
    _auth: None = Depends(_verify_tools_secret),
) -> SearchResourcesResponse:
    return await search_resources(request)


@router.post("/market_data", response_model=MarketDataResponse)
async def market_data_endpoint(
    request: MarketDataRequest,
    _auth: None = Depends(_verify_tools_secret),
) -> MarketDataResponse:
    return await market_data(request)
