from fastapi import APIRouter

from src.tools.market_data import market_data
from src.tools.models import (
    MarketDataRequest,
    MarketDataResponse,
    SearchResourcesRequest,
    SearchResourcesResponse,
)
from src.tools.search_resources import search_resources


router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/search_resources", response_model=SearchResourcesResponse)
async def search_resources_endpoint(
    request: SearchResourcesRequest,
) -> SearchResourcesResponse:
    return await search_resources(request)


@router.post("/market_data", response_model=MarketDataResponse)
async def market_data_endpoint(request: MarketDataRequest) -> MarketDataResponse:
    return await market_data(request)
