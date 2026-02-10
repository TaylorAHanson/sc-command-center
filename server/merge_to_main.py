import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .services.databricks_service import db_service
from .middleware.auth import AuthMiddleware
from .routers import genie, sql_query
from .routers import databricks_jobs as jobs_router

# Support for running behind a proxy
class ProxyHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Log the original request
        print(f"Original request path: {request.url.path}")
        print(f"Original request URL: {request.url}")
       
        # Handle X-Forwarded headers
        forwarded_proto = request.headers.get("x-forwarded-proto")
        forwarded_host = request.headers.get("x-forwarded-host")
        forwarded_prefix = request.headers.get("x-forwarded-prefix", "")
       
        print(f"X-Forwarded-Proto: {forwarded_proto}")
        print(f"X-Forwarded-Host: {forwarded_host}")
        print(f"X-Forwarded-Prefix: {forwarded_prefix}")
       
        response = await call_next(request)
        return response

app = FastAPI(
    title="Supply Chain Command Center",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

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

# Serve Frontend - expects client/dist to exist (built by Vite)
# Get the absolute path to the client dist directory
base_dir = Path(__file__).resolve().parent.parent
client_dist_path = base_dir / "client" / "dist"

print(f"Looking for client dist at: {client_dist_path}")
print(f"Client dist exists: {client_dist_path.exists()}")

if client_dist_path.exists():
    print(f"Contents of dist: {list(client_dist_path.iterdir())}")
else:
    print(f"Client dist does not exist at: {client_dist_path}")

# Middleware to log all requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"\n=== Incoming Request ===")
    print(f"Method: {request.method}")
    print(f"Path: {request.url.path}")
    print(f"Full URL: {request.url}")
    print(f"Client: {request.client}")
    print(f"Headers: {dict(request.headers)}")
   
    response = await call_next(request)
   
    print(f"Response status: {response.status_code}")
    print(f"=== End Request ===\n")
    return response

# Health check endpoint for Databricks
@app.get("/health")
async def root_health_check():
    return {"status": "healthy", "service": "Supply Chain Command Center"}

# Debug endpoint to see what's happening
@app.get("/debug")
async def debug_info(request: Request):
    return {
        "path": request.url.path,
        "full_url": str(request.url),
        "headers": dict(request.headers),
        "client": str(request.client),
        "method": request.method
    }

# Metrics endpoint for Databricks monitoring
@app.get("/metrics")
async def metrics():
    # Return plain text for Prometheus-style metrics
    return Response(content="# No metrics yet\n", media_type="text/plain")

# Include routers
app.include_router(genie.router, prefix="/api/genie", tags=["genie"])
app.include_router(sql_query.router, prefix="/api/sql", tags=["sql"])
app.include_router(jobs_router.router, prefix="/api/jobs", tags=["jobs"])

# API Routes
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "Supply Chain Command Center"}

@app.post("/api/jobs/trigger/{job_id}")
async def trigger_job(job_id: int):
    return db_service.trigger_job(job_id)

# Mount static files for assets
if client_dist_path.exists():
    assets_path = client_dist_path / "assets"
    if assets_path.exists():
        print(f"Mounting assets from: {assets_path}")
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

# Catch-all route for SPA - must be last
@app.get("/{full_path:path}")
async def serve_spa(full_path: str, request: Request):
    print(f"Catch-all serving path: '{full_path}'")
   
    # Don't serve files for API routes (they should have been handled above)
    if full_path.startswith("api/"):
        return JSONResponse({"error": "Not found"}, status_code=404)
   
    if not client_dist_path.exists():
        return JSONResponse({
            "message": "Frontend not built. Please run `npm run build` in /client and restart.",
            "expected_path": str(client_dist_path)
        }, status_code=503)
   
    # Try to serve the specific file if it exists
    if full_path:
        file_path = client_dist_path / full_path
        if file_path.is_file():
            print(f"Serving file: {file_path}")
            return FileResponse(file_path)
   
    # Otherwise serve index.html for SPA routing
    index_path = client_dist_path / "index.html"
    if index_path.exists():
        print(f"Serving index.html for path: '{full_path}'")
        return FileResponse(index_path)
    else:
        return JSONResponse({"error": "Frontend not found", "path": str(index_path)}, status_code=404)