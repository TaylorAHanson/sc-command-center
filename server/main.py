import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from services.databricks_service import db_service
from routes import widgets, actions
from database import init_db

app = FastAPI(title="Supply Chain Command Center")

@app.on_event("startup")
async def startup_event():
    init_db()

app.include_router(widgets.router)
app.include_router(actions.router)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routes
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "Supply Chain Command Center"}

@app.post("/api/jobs/trigger/{job_id}")
async def trigger_job(job_id: int):
    return db_service.trigger_job(job_id)

# Serve Frontend - expects client/dist to exist (built by Vite)
# In development, we might not have dist yet, so we wrap in try/except or check existence
client_dist_path = os.path.join(os.path.dirname(__file__), "../client/dist")

if os.path.exists(client_dist_path):
    app.mount("/", StaticFiles(directory=client_dist_path, html=True), name="static")
else:
    @app.get("/")
    def root():
        return {"message": "Frontend not built. Please run `npm run build` in /client and restart."}

