from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .. import jobs, models, schemas
from ..db import get_db

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=schemas.JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(models.ProcessingJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/{job_id}/retry", response_model=schemas.JobResponse)
def retry_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(models.ProcessingJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "dead":
        raise HTTPException(409, "Only dead-letter jobs can be replayed")
    jobs.reset_job(db, job)
    db.commit()
    db.refresh(job)
    return job
