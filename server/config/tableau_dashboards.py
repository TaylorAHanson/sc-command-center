"""Configuration for Tableau dashboard widgets.

=== HOW TO ADD A NEW TABLEAU DASHBOARD ===

1. Publish your dashboard to Tableau Cloud
2. Get the dashboard URL or embed code
3. Add a new TableauDashboardConfig to TABLEAU_DASHBOARD_CONFIGS list below
4. Configure:
   - id: Unique identifier (lowercase, underscores)
   - name: Display name shown in UI
   - dashboard_url: The Tableau Cloud dashboard URL
   - description: What this dashboard shows
   - category: Widget category (e.g., "Analytics", "Monitoring")
   - default_filters: Optional default filters to apply
5. Save and deploy - the dashboard will automatically appear in the widget library!

=== CONFIGURATION ===
Set TABLEAU_SERVER_URL in app.yaml for your Tableau Cloud instance.
Example: https://10ax.online.tableau.com
"""
import os
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

# Get Tableau server URL from environment
TABLEAU_SERVER_URL = os.environ.get('TABLEAU_SERVER_URL', '')


class TableauDashboardConfig(BaseModel):
    """Configuration for a Tableau dashboard widget."""
    id: str  # Unique identifier for the frontend
    name: str  # Display name
    dashboard_url: str  # Full dashboard URL or path (relative to TABLEAU_SERVER_URL)
    description: str  # Description for the UI
    category: str = "Analytics"  # Widget category
    workbook_name: Optional[str] = None  # Workbook name for API access
    view_name: Optional[str] = None  # View/dashboard name for API access
    default_filters: Optional[Dict[str, str]] = None  # Default filters to apply
    toolbar: bool = True  # Show Tableau toolbar
    tabs: bool = True  # Show dashboard tabs
    device: str = "default"  # Device layout: default, desktop, tablet, phone
   
    def get_full_url(self) -> str:
        """Get the full dashboard URL."""
        if self.dashboard_url.startswith('http'):
            return self.dashboard_url
        # Remove leading slash if present
        path = self.dashboard_url.lstrip('/')
        return f"{TABLEAU_SERVER_URL}/{path}"


# Define all available Tableau dashboards here
TABLEAU_DASHBOARD_CONFIGS: List[TableauDashboardConfig] = [
    # Example dashboard configuration
    # TableauDashboardConfig(
    #     id="supply_chain_overview",
    #     name="Supply Chain Overview",
    #     dashboard_url="/views/SupplyChain/Overview",
    #     workbook_name="SupplyChain",
    #     view_name="Overview",
    #     description="High-level supply chain metrics and KPIs",
    #     category="Analytics",
    #     default_filters={
    #         "Region": "North America",
    #         "Year": "2024"
    #     },
    #     toolbar=True,
    #     tabs=False
    # ),
]


def get_tableau_dashboard_config(dashboard_id: str) -> TableauDashboardConfig:
    """Get configuration for a specific Tableau dashboard by ID."""
    for config in TABLEAU_DASHBOARD_CONFIGS:
        if config.id == dashboard_id:
            return config
    raise ValueError(f"Tableau dashboard with id '{dashboard_id}' not found")


def get_all_tableau_dashboard_configs() -> List[TableauDashboardConfig]:
    """Get all available Tableau dashboard configurations."""
    return TABLEAU_DASHBOARD_CONFIGS
