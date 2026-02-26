import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from middleware.auth import AuthMiddleware
from services.databricks_service import db_service
from routes import widgets, actions, genie, sql_query, n8n, tableau
from routes import databricks_jobs as jobs_router
from database import init_db

# Support for running behind a proxy
class ProxyHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Handle X-Forwarded headers
        forwarded_proto = request.headers.get("x-forwarded-proto")
        forwarded_host = request.headers.get("x-forwarded-host")
        forwarded_prefix = request.headers.get("x-forwarded-prefix", "")
       
        # Update scope if behind proxy
        if forwarded_proto:
            request.scope["scheme"] = forwarded_proto
        if forwarded_host:
            request.scope["server"] = (forwarded_host, 80)
            
        response = await call_next(request)
        return response

app = FastAPI(
    title="Supply Chain Command Center",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

@app.on_event("startup")
async def startup_event():
    init_db()

# Add proxy headers middleware first
app.add_middleware(ProxyHeadersMiddleware)

# Add authentication middleware to extract user tokens
app.add_middleware(AuthMiddleware)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware to log all requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"\n=== Incoming Request ===")
    print(f"Method: {request.method}")
    print(f"Path: {request.url.path}")
    
    response = await call_next(request)
   
    print(f"Response status: {response.status_code}")
    print(f"=== End Request ===\n")
    return response

# Health check endpoints
@app.get("/health")
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "Supply Chain Command Center"}

# Debug endpoint
@app.get("/debug")
async def debug_info(request: Request):
    return {
        "path": request.url.path,
        "headers": dict(request.headers),
        "method": request.method
    }

# Metrics endpoint
@app.get("/metrics")
async def metrics():
    return Response(content="# No metrics yet\n", media_type="text/plain")

# Include routers
app.include_router(widgets.router) # Prefix /api/widgets in widgets.py
app.include_router(actions.router) # Prefix /api/actions in actions.py
app.include_router(genie.router, prefix="/api/genie", tags=["genie"])
app.include_router(sql_query.router, prefix="/api/sql", tags=["sql"])
app.include_router(jobs_router.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(n8n.router, prefix="/api", tags=["n8n"])
app.include_router(tableau.router, prefix="/api", tags=["tableau"])

from routes import custom_widgets
from routes import agent_studio
app.include_router(custom_widgets.router, prefix="/api/widgets", tags=["custom_widgets"])
app.include_router(agent_studio.router, prefix="/api/agent/widget", tags=["agent_studio"])


# Serve Frontend
base_dir = Path(__file__).resolve().parent.parent
client_dist_path = base_dir / "dist"

# Mount static files for assets
if client_dist_path.exists():
    assets_path = client_dist_path / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

# Catch-all route for SPA - must be last
@app.get("/{full_path:path}")
async def serve_spa(full_path: str, request: Request):
    # Don't serve files for API routes
    if full_path.startswith("api/"):
        return JSONResponse({"error": "Not found"}, status_code=404)
   
    if not client_dist_path.exists():
        return JSONResponse({
            "message": "Frontend not built. Please run `npm run build` and restart.",
            "expected_path": str(client_dist_path)
        }, status_code=503)
   
    # Try to serve the specific file if it exists
    if full_path:
        file_path = client_dist_path / full_path
        if file_path.is_file():
            return FileResponse(file_path)
   
    # Otherwise serve index.html for SPA routing
    index_path = client_dist_path / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    else:
        return JSONResponse({"error": "Frontend not found"}, status_code=404)


