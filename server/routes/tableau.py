"""
Tableau Dashboard API routes.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from middleware.auth import require_auth
from config.tableau_dashboards import get_tableau_dashboard_config, get_all_tableau_dashboard_configs

router = APIRouter(prefix="/tableau", tags=["tableau"])


class DashboardListResponse(BaseModel):
    dashboards: list


@router.get("/list")
async def list_dashboards(user_token: str = Depends(require_auth)):
    """List all available Tableau dashboards."""
    configs = get_all_tableau_dashboard_configs()
    return DashboardListResponse(
        dashboards=[
            {
                "id": config.id,
                "name": config.name,
                "description": config.description,
                "category": config.category,
                "dashboard_url": config.get_full_url(),
                "default_filters": config.default_filters,
                "toolbar": config.toolbar,
                "tabs": config.tabs
            }
            for config in configs
        ]
    )


@router.get("/config/{dashboard_id}")
async def get_dashboard_config(dashboard_id: str, user_token: str = Depends(require_auth)):
    """Get configuration for a specific Tableau dashboard."""
    try:
        config = get_tableau_dashboard_config(dashboard_id)
        return {
            "id": config.id,
            "name": config.name,
            "description": config.description,
            "dashboard_url": config.get_full_url(),
            "default_filters": config.default_filters,
            "toolbar": config.toolbar,
            "tabs": config.tabs,
            "device": config.device
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
