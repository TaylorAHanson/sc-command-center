
import os
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from databricks.sdk import WorkspaceClient
from typing import Optional, Dict, Any, List

from middleware.auth import get_db_client, get_db_client_for_jobs

# --- Configuration & Client Setup ---

router = APIRouter()

# --- Pydantic Models (API Contracts) ---

class JobTriggerRequest(BaseModel):
    """Request to trigger a Databricks job."""
    job_id: int
    parameters: Optional[Dict[str, str]] = None
    notebook_params: Optional[Dict[str, str]] = None
    jar_params: Optional[List[str]] = None
    python_params: Optional[List[str]] = None
    spark_submit_params: Optional[List[str]] = None

class JobTriggerResponse(BaseModel):
    """Response after triggering a job."""
    run_id: int
    job_id: int
    status: str
    message: str

class JobStatusResponse(BaseModel):
    """Response with job run status."""
    run_id: int
    job_id: int
    state: str
    life_cycle_state: str
    result_state: Optional[str] = None
    state_message: Optional[str] = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    run_duration: Optional[int] = None
    setup_duration: Optional[int] = None
    execution_duration: Optional[int] = None
    cleanup_duration: Optional[int] = None
    run_page_url: Optional[str] = None
    tasks: Optional[List[Dict[str, Any]]] = None

class JobOutputResponse(BaseModel):
    """Response with job run output."""
    run_id: int
    job_id: int
    notebook_output: Optional[Dict[str, Any]] = None
    logs: Optional[str] = None
    error: Optional[str] = None
    error_trace: Optional[str] = None

from middleware.auth import get_db_client
from fastapi import APIRouter, HTTPException, Depends

# --- API Endpoints ---

@router.post("/trigger", response_model=JobTriggerResponse, summary="Trigger a Databricks job")
async def trigger_job(
    request: JobTriggerRequest, 
    w: WorkspaceClient = Depends(get_db_client_for_jobs)
):
    """
    Triggers a Databricks job by job_id and returns the run_id.
    Uses centralized authentication (OBO or SP based on DEV_MODE).
    """
    try:
       
        # Build run parameters
        run_params = {}
        if request.parameters:
            run_params['job_parameters'] = request.parameters
        if request.notebook_params:
            run_params['notebook_params'] = request.notebook_params
        if request.jar_params:
            run_params['jar_params'] = request.jar_params
        if request.python_params:
            run_params['python_params'] = request.python_params
        if request.spark_submit_params:
            run_params['spark_submit_params'] = request.spark_submit_params
       
        # Trigger the job
        logging.info(f"Triggering job {request.job_id} with params: {run_params}")
        run = w.jobs.run_now(job_id=request.job_id, **run_params)
       
        return JobTriggerResponse(
            run_id=run.run_id,
            job_id=request.job_id,
            status="triggered",
            message=f"Job {request.job_id} triggered successfully. Run ID: {run.run_id}"
        )
   
    except Exception as e:
        logging.exception(f"Failed to trigger job {request.job_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger job: {str(e)}")

@router.get("/status/{run_id}", response_model=JobStatusResponse, summary="Get job run status")
async def get_job_status(
    run_id: int, 
    w: WorkspaceClient = Depends(get_db_client_for_jobs)
):
    """
    Gets the status of a job run by run_id.
    Uses centralized authentication.
    """
    try:
       
        # Get run details
        run = w.jobs.get_run(run_id=run_id)
       
        # Extract state information
        state = run.state
        life_cycle_state = state.life_cycle_state.value if state and state.life_cycle_state else "UNKNOWN"
        result_state = state.result_state.value if state and state.result_state else None
        state_message = state.state_message if state else None
       
        # Extract timing information
        start_time = run.start_time
        end_time = run.end_time
        run_duration = run.run_duration
        setup_duration = run.setup_duration
        execution_duration = run.execution_duration
        cleanup_duration = run.cleanup_duration
       
        # Get run page URL
        run_page_url = run.run_page_url
       
        # Extract task information if available
        tasks = None
        if run.tasks:
            tasks = []
            for task in run.tasks:
                task_info = {
                    "task_key": task.task_key,
                    "state": task.state.life_cycle_state.value if task.state and task.state.life_cycle_state else "UNKNOWN",
                    "result_state": task.state.result_state.value if task.state and task.state.result_state else None,
                    "start_time": task.start_time,
                    "end_time": task.end_time,
                    "run_page_url": task.run_page_url
                }
                tasks.append(task_info)
       
        return JobStatusResponse(
            run_id=run_id,
            job_id=run.job_id,
            state=life_cycle_state,
            life_cycle_state=life_cycle_state,
            result_state=result_state,
            state_message=state_message,
            start_time=start_time,
            end_time=end_time,
            run_duration=run_duration,
            setup_duration=setup_duration,
            execution_duration=execution_duration,
            cleanup_duration=cleanup_duration,
            run_page_url=run_page_url,
            tasks=tasks
        )
   
    except Exception as e:
        logging.exception(f"Failed to get status for run {run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")

@router.get("/output/{run_id}", response_model=JobOutputResponse, summary="Get job run output")
async def get_job_output(
    run_id: int, 
    w: WorkspaceClient = Depends(get_db_client_for_jobs)
):
    """
    Gets the output of a completed job run by run_id.
    Uses centralized authentication.
    """
    try:
       
        # Get run output
        run_output = w.jobs.get_run_output(run_id=run_id)
       
        # Extract output information
        notebook_output = None
        logs = None
        error = None
        error_trace = None
       
        if run_output.notebook_output:
            notebook_output = {
                "result": run_output.notebook_output.result,
                "truncated": run_output.notebook_output.truncated
            }
       
        if run_output.logs:
            logs = run_output.logs
       
        if run_output.error:
            error = run_output.error
       
        if run_output.error_trace:
            error_trace = run_output.error_trace
       
        # Get the run to extract job_id
        run = w.jobs.get_run(run_id=run_id)
       
        return JobOutputResponse(
            run_id=run_id,
            job_id=run.job_id,
            notebook_output=notebook_output,
            logs=logs,
            error=error,
            error_trace=error_trace
        )
   
    except Exception as e:
        logging.exception(f"Failed to get output for run {run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get job output: {str(e)}")

@router.delete("/cancel/{run_id}", summary="Cancel a running job")
async def cancel_job(
    run_id: int, 
    w: WorkspaceClient = Depends(get_db_client_for_jobs)
):
    """
    Cancels a running job by run_id.
    Uses centralized authentication.
    """
    try:
       
        # Cancel the run
        w.jobs.cancel_run(run_id=run_id)
       
        return {
            "run_id": run_id,
            "status": "cancelled",
            "message": f"Job run {run_id} cancelled successfully"
        }
   
    except Exception as e:
        logging.exception(f"Failed to cancel run {run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")

@router.get("/job/{job_id}", summary="Get job details")
async def get_job_details(
    job_id: int,
    w: WorkspaceClient = Depends(get_db_client_for_jobs)
):
    """
    Get details about a specific job including its name and settings.
    """
    try:
        job = w.jobs.get(job_id=job_id)
        
        return {
            "job_id": job_id,
            "name": job.settings.name if job.settings else None,
            "description": job.settings.description if job.settings else None,
            "creator_user_name": job.creator_user_name,
            "created_time": job.created_time
        }
    
    except Exception as e:
        logging.exception(f"Failed to get job details for job {job_id}: {str(e)}")
        raise HTTPException(status_code=404, detail=f"Job not found: {str(e)}")

class ExecuteNotebookRequest(BaseModel):
    """Request to execute a notebook."""
    notebook_path: str
    parameters: Optional[Dict[str, str]] = None

@router.post("/execute-notebook", summary="Execute a Databricks notebook")
async def execute_notebook(
    request: ExecuteNotebookRequest,
    w: WorkspaceClient = Depends(get_db_client_for_jobs)
):
    """
    Executes a notebook using a one-time job.
    Uses centralized authentication (OBO or SP based on DEV_MODE).
    """
    try:
        # Submit a one-time notebook job
        from databricks.sdk.service.jobs import SubmitTask, NotebookTask, Source
        
        task = SubmitTask(
            task_key="notebook_task",
            notebook_task=NotebookTask(
                notebook_path=request.notebook_path,
                source=Source.WORKSPACE,
                base_parameters=request.parameters or {}
            )
        )
        
        logging.info(f"Submitting one-time job for notebook {request.notebook_path}")
        run = w.jobs.submit(tasks=[task], run_name=f"Execute Notebook: {request.notebook_path.split('/')[-1]}")
        
        return {
            "run_id": run.run_id,
            "status": "triggered",
            "message": f"Notebook execution started. Run ID: {run.run_id}"
        }
    
    except Exception as e:
        logging.exception(f"Failed to execute notebook {request.notebook_path}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to execute notebook: {str(e)}")

@router.get("/notebooks", summary="List Databricks notebooks")
async def list_notebooks(
    path: str = "/Users",
    w: WorkspaceClient = Depends(get_db_client_for_jobs)
):
    """
    Lists notebooks in a given workspace path.
    Uses centralized authentication (OBO or SP based on DEV_MODE).
    """
    try:
        notebooks = []
        
        # List objects in the path
        for obj in w.workspace.list(path):
            if obj.object_type and obj.object_type.value == "NOTEBOOK":
                notebooks.append({
                    "path": obj.path,
                    "name": obj.path.split("/")[-1] if obj.path else "Unknown",
                    "language": obj.language.value if obj.language else None
                })
        
        return {"notebooks": notebooks}
    
    except Exception as e:
        logging.exception(f"Failed to list notebooks in path {path}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list notebooks: {str(e)}")
