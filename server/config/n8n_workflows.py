"""Configuration for N8N workflow widgets.

=== HOW TO ADD A NEW N8N WORKFLOW ===

1. Set up your N8N workflow with a webhook trigger
2. Copy the webhook URL from N8N
3. Add a new N8NWorkflowConfig to N8N_WORKFLOW_CONFIGS list below
4. Configure:
   - id: Unique identifier (lowercase, underscores)
   - name: Display name shown in UI
   - webhook_url: The webhook URL from N8N
   - description: What this workflow does
   - category: Widget category (e.g., "Automation", "Integration")
   - parameters: Optional list of parameter definitions for the workflow
5. Save and deploy - the workflow will automatically appear in the widget library!

=== CONFIGURATION ===
N8N workflows can be triggered directly from the frontend or proxied through the backend.
Set N8N_BASE_URL in app.yaml if you want to use relative webhook paths.
"""
import os
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

# Get N8N base URL from environment (optional)
N8N_BASE_URL = os.environ.get('N8N_BASE_URL', '')


class N8NParameterConfig(BaseModel):
    """Configuration for an N8N workflow parameter."""
    name: str  # Parameter name
    label: str  # Display label in UI
    type: str = "text"  # text, number, select, textarea
    default: Optional[Any] = None  # Default value
    required: bool = False  # Whether the parameter is required
    options: Optional[List[str]] = None  # For select type
    placeholder: Optional[str] = None  # Placeholder text


class N8NWorkflowConfig(BaseModel):
    """Configuration for an N8N workflow widget."""
    id: str  # Unique identifier for the frontend
    name: str  # Display name
    webhook_url: str  # Full webhook URL or path (if using N8N_BASE_URL)
    description: str  # Description for the UI
    category: str = "Automation"  # Widget category
    parameters: Optional[List[N8NParameterConfig]] = None  # Workflow parameters
    method: str = "POST"  # HTTP method (POST, GET)
    success_message: Optional[str] = None  # Custom success message
   
    def get_full_url(self) -> str:
        """Get the full webhook URL."""
        if self.webhook_url.startswith('http'):
            return self.webhook_url
        return f"{N8N_BASE_URL}{self.webhook_url}"


# Define all available N8N workflows here
N8N_WORKFLOW_CONFIGS: List[N8NWorkflowConfig] = [
    # Example workflow configuration
    # N8NWorkflowConfig(
    #     id="inventory_alert",
    #     name="Trigger Inventory Alert",
    #     webhook_url="https://your-n8n-instance.com/webhook/inventory-alert",
    #     description="Sends inventory alert notifications via email and Slack",
    #     category="Alerts",
    #     parameters=[
    #         N8NParameterConfig(
    #             name="product_id",
    #             label="Product ID",
    #             type="text",
    #             required=True,
    #             placeholder="Enter product ID"
    #         ),
    #         N8NParameterConfig(
    #             name="threshold",
    #             label="Alert Threshold",
    #             type="number",
    #             default=10,
    #             required=True
    #         ),
    #     ],
    #     success_message="Inventory alert workflow triggered successfully!"
    # ),
]


def get_n8n_workflow_config(workflow_id: str) -> N8NWorkflowConfig:
    """Get configuration for a specific N8N workflow by ID."""
    for config in N8N_WORKFLOW_CONFIGS:
        if config.id == workflow_id:
            return config
    raise ValueError(f"N8N workflow with id '{workflow_id}' not found")


def get_all_n8n_workflow_configs() -> List[N8NWorkflowConfig]:
    """Get all available N8N workflow configurations."""
    return N8N_WORKFLOW_CONFIGS
