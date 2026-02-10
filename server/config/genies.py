from typing import List, Optional
from pydantic import BaseModel

class GenieConfig(BaseModel):
    """Configuration for a single Genie space."""
    id: str # Unique identifier for the frontend
    name: str # Display name
    space_id: str # Databricks Genie Space ID
    description: str # Description for the UI
    icon: str = "bot" # Icon name (lucide-react icon)
    category: str = "AI & Automation" # Widget category

# Define all available genies here - just add new entries!
# To find your Space ID: Open your Genie space in Databricks and copy the ID from the URL
GENIE_CONFIGS: List[GenieConfig] = [
    GenieConfig(
        id="supply_chain_genie",
        name="Supply Chain Genie",
        space_id="01f106b447c7129b8f1dc466a177d9d7",
        description="AI assistant for supply chain analytics and insights",
        icon="bot",
        category="AI & Automation"
    ),
    # Add more genies here - just copy the block above and change the values:
    # GenieConfig(
    #     id="inventory_genie",
    #     name="Inventory Genie",
    #     space_id="your-space-id-here",
    #     description="Specialized assistant for inventory management",
    #     icon="package",
    #     category="AI & Automation"
    # ),
]

def get_genie_config(genie_id: str) -> GenieConfig:
    """Get configuration for a specific genie by ID."""
    for config in GENIE_CONFIGS:
        if config.id == genie_id:
            return config
    raise ValueError(f"Genie with id '{genie_id}' not found")

def get_all_genie_configs() -> List[GenieConfig]:
    """Get all available genie configurations."""
    # Filter out genies with empty space_id
    return [config for config in GENIE_CONFIGS if config.space_id]
