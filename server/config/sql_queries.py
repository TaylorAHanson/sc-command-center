"""Configuration for SQL query widgets.

=== HOW TO ADD A NEW SQL QUERY WIDGET ===

1. Write your SQL query (can use parameters with {param_name} syntax)
2. Add a new SqlQueryConfig to SQL_QUERY_CONFIGS list below
3. Configure:
   - id: Unique identifier (lowercase, underscores)
   - name: Display name shown in UI
   - sql: Your SQL query (can be multi-line)
   - warehouse_id: Leave as None to use default from app.yaml, or specify a different one
   - description: What this query shows
   - category: Widget category (e.g., "Analytics", "Monitoring")
   - refresh_interval: Optional auto-refresh in seconds
   - parameters: Optional list of parameter definitions for dynamic queries
4. Save and deploy - the widget will automatically appear in the widget library!

The query results will be available to both table and chart widgets.

=== CONFIGURATION ===
Set SQL_WAREHOUSE_ID in app.yaml to configure the default warehouse for all queries.
"""
import os
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

# Get default warehouse ID from environment
DEFAULT_WAREHOUSE_ID = os.environ.get('SQL_WAREHOUSE_ID', '')


class SqlParameterConfig(BaseModel):
    """Configuration for a SQL query parameter."""
    name: str  # Parameter name (used in SQL as {param_name})
    label: str  # Display label in UI
    type: str = "text"  # text, number, date, select
    default: Optional[Any] = None  # Default value
    options: Optional[List[str]] = None  # For select type


class SqlQueryConfig(BaseModel):
    """Configuration for a SQL query widget."""
    id: str  # Unique identifier for the frontend
    name: str  # Display name
    sql: str  # SQL query to execute
    warehouse_id: Optional[str] = None  # Databricks SQL Warehouse ID (uses default if None)
    description: str  # Description for the UI
    category: str = "Analytics"  # Widget category
    refresh_interval: Optional[int] = None  # Auto-refresh interval in seconds
    parameters: Optional[List[SqlParameterConfig]] = None  # Query parameters
    chart_config: Optional[Dict[str, Any]] = None  # Optional chart configuration hints
   
    def get_warehouse_id(self) -> str:
        """Get the warehouse ID, using default if not specified."""
        return self.warehouse_id or DEFAULT_WAREHOUSE_ID


# Define all available SQL queries here
# NOTE: Set SQL_WAREHOUSE_ID in app.yaml to configure the default warehouse
# Individual queries can override by setting warehouse_id explicitly
SQL_QUERY_CONFIGS: List[SqlQueryConfig] = [
    # Simple test query using samples catalog (available in most workspaces)
    SqlQueryConfig(
        id="test_query",
        name="Test Query - NYC Taxi Data",
        sql="""
            SELECT
                pickup_zip,
                COUNT(*) as trip_count,
                AVG(fare_amount) as avg_fare,
                AVG(trip_distance) as avg_distance
            FROM samples.nyctaxi.trips
            WHERE pickup_zip IS NOT NULL
            GROUP BY pickup_zip
            ORDER BY trip_count DESC
            LIMIT 20
        """,
        warehouse_id=None,  # Uses default from app.yaml
        description="Test query using NYC taxi sample data",
        category="Analytics",
        refresh_interval=None,
    ),
   
    SqlQueryConfig(
        id="supplier_performance",
        name="Supplier Performance Metrics",
        sql="""
            SELECT
                supplier_name,
                on_time_delivery_pct,
                quality_score,
                cost_rating,
                status,
                total_orders,
                region,
                last_order_date
            FROM supply_chain.supplier_performance
            ORDER BY on_time_delivery_pct DESC
            LIMIT 100
        """,
        warehouse_id=None,  # Uses default from app.yaml
        description="Real-time supplier performance metrics and ratings",
        category="Analytics",
        refresh_interval=300,  # Refresh every 5 minutes
    ),
   
    SqlQueryConfig(
        id="inventory_trends",
        name="Inventory Trends",
        sql="""
            SELECT
                date,
                product_name,
                inventory_level,
                region
            FROM supply_chain.inventory_daily
            WHERE date >= CURRENT_DATE - INTERVAL 30 DAYS
            ORDER BY date, product_name
        """,
        warehouse_id=None,  # Uses default from app.yaml
        description="30-day inventory level trends by product and region",
        category="Analytics",
        refresh_interval=600,  # Refresh every 10 minutes
        chart_config={
            "type": "line",
            "x_axis": "date",
            "y_axis": "inventory_level",
            "series_by": "product_name"
        }
    ),
   
    SqlQueryConfig(
        id="shipment_status",
        name="Shipment Status Overview",
        sql="""
            SELECT
                shipment_id,
                origin,
                destination,
                status,
                expected_delivery,
                actual_delivery,
                carrier,
                tracking_number
            FROM supply_chain.shipments
            WHERE status IN ('In Transit', 'Delayed', 'Pending')
            ORDER BY expected_delivery
        """,
        warehouse_id=None,  # Uses default from app.yaml
        description="Current status of active shipments",
        category="Logistics",
        refresh_interval=180,  # Refresh every 3 minutes
    ),
   
    # Example with parameters
    SqlQueryConfig(
        id="regional_sales",
        name="Regional Sales Analysis",
        sql="""
            SELECT
                region,
                product_category,
                SUM(sales_amount) as total_sales,
                COUNT(DISTINCT order_id) as order_count,
                AVG(sales_amount) as avg_order_value
            FROM supply_chain.sales
            WHERE date >= '{start_date}'
              AND date <= '{end_date}'
              AND region = '{region}'
            GROUP BY region, product_category
            ORDER BY total_sales DESC
        """,
        warehouse_id=None,  # Uses default from app.yaml
        description="Sales analysis by region and product category",
        category="Analytics",
        parameters=[
            SqlParameterConfig(
                name="start_date",
                label="Start Date",
                type="date",
                default="2024-01-01"
            ),
            SqlParameterConfig(
                name="end_date",
                label="End Date",
                type="date",
                default="2024-12-31"
            ),
            SqlParameterConfig(
                name="region",
                label="Region",
                type="select",
                options=["North America", "Europe", "Asia-Pacific", "Latin America"],
                default="North America"
            )
        ]
    ),
]


def get_sql_query_config(query_id: str) -> SqlQueryConfig:
    """Get configuration for a specific SQL query by ID."""
    for config in SQL_QUERY_CONFIGS:
        if config.id == query_id:
            return config
    raise ValueError(f"SQL query with id '{query_id}' not found")


def get_all_sql_query_configs() -> List[SqlQueryConfig]:
    """Get all available SQL query configurations."""
    # Only return queries if we have a valid warehouse ID configured
    if not DEFAULT_WAREHOUSE_ID:
        return []
   
    return [
        config for config in SQL_QUERY_CONFIGS
        if config.get_warehouse_id()  # Has a valid warehouse ID
    ]