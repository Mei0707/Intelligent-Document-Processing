"""SQL outbox + Redis Streams delivery with fenced leases and bounded retries.

At-least-once delivery is intentional. Only the current SQL lease holder may
commit outputs. Workers periodically publish unclaimed rows, so broker outages
and a crash between SQL commit and XADD never lose an accepted upload.
"""
import logging
import random
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import Event, Thread
from sqlalchemy import and_, or_, update, select, func
from . import models
from .config import settings
from .db import SessionLocal
from .monitoring import QUEUE_DEPTH
from .services.redis_client import redis_client
from .telemetry import trace_carrier

log = logging.getLogger("idp.jobs")
STREAM = "idp:jobs"
DEAD_STREAM = "idp:jobs:dead"
GROUP = "idp-workers"
ACTIVE = ("queued", "processing", "retrying")


class PermanentJobError(ValueError):
    pass


class LeaseLost(RuntimeError):
    pass


def create_job(db, doc, content_hash, idempotency_key=None):
    job = models.ProcessingJob(id=str(uuid.uuid4()), document_id=doc.id,
                               content_hash=content_hash, idempotency_key=idempotency_key,
                               trace_context=trace_carrier())
    db.add(job)
    return job


def runnable(now):
    return or_(and_(models.ProcessingJob.status.in_(("queued", "retrying")),
                    models.ProcessingJob.available_at <= now),
               and_(models.ProcessingJob.status == "processing", models.ProcessingJob.lease_until < now))


def dispatch_due(client=None):
    client = client or redis_client()
    now = datetime.utcnow()
    with SessionLocal() as db:
        # Recover workers killed on their final attempt into the durable DLQ.
        exhausted = db.scalars(select(models.ProcessingJob).where(
            runnable(now), models.ProcessingJob.attempts >= settings.job_max_attempts).limit(100)).all()
        for job in exhausted:
            changed = db.execute(update(models.ProcessingJob).where(
                models.ProcessingJob.id == job.id, runnable(now),
                models.ProcessingJob.attempts >= settings.job_max_attempts
            ).values(status="dead", stage="failed", error="Worker lease expired after final attempt",
                     lease_token=None, lease_until=None, updated_at=now)).rowcount
            if changed:
                db.execute(update(models.Document).where(models.Document.id == job.document_id).values(
                    status="failed", error="Worker lease expired after final attempt"))
        db.commit()
        due = db.scalars(select(models.ProcessingJob).where(
            runnable(now), models.ProcessingJob.attempts < settings.job_max_attempts,
            or_(models.ProcessingJob.published_at.is_(None),
                models.ProcessingJob.published_at < now - timedelta(seconds=15))
        ).order_by(models.ProcessingJob.available_at).limit(100)).all()
        for job in due:
            client.xadd(STREAM, {"job_id": job.id})
            job.published_at = now
        # SQL is the authoritative dead-letter ledger. Broker DLQ publication is
        # also an outbox; a publish/commit crash can duplicate a DLQ notification.
        dead = db.scalars(select(models.ProcessingJob).where(
            models.ProcessingJob.status == "dead", models.ProcessingJob.dead_lettered_at.is_(None)).limit(100)).all()
        for job in dead:
            client.xadd(DEAD_STREAM, {"job_id": job.id, "attempts": job.attempts,
                                     "error": job.error or "failed"}, maxlen=10000, approximate=True)
            job.dead_lettered_at = now
        db.commit()
        counts = dict(db.execute(select(models.ProcessingJob.status, func.count()).group_by(models.ProcessingJob.status)).all())
        for state in (*ACTIVE, "succeeded", "dead"):
            QUEUE_DEPTH.labels(state).set(counts.get(state, 0))


def claim(job_id):
    now = datetime.utcnow()
    token = str(uuid.uuid4())
    with SessionLocal() as db:
        result = db.execute(update(models.ProcessingJob).where(
            models.ProcessingJob.id == job_id, runnable(now),
            models.ProcessingJob.attempts < settings.job_max_attempts
        ).values(status="processing", attempts=models.ProcessingJob.attempts + 1,
                 lease_token=token, lease_until=now + timedelta(seconds=settings.job_lease_seconds),
                 updated_at=now, stage="starting", error=None))
        if not result.rowcount:
            return None
        job = db.get(models.ProcessingJob, job_id)
        db.execute(update(models.Document).where(models.Document.id == job.document_id).values(status="processing", error=None))
        db.commit()
        return token


def owned(job_id, token):
    return and_(models.ProcessingJob.id == job_id, models.ProcessingJob.status == "processing",
                models.ProcessingJob.lease_token == token, models.ProcessingJob.lease_until > datetime.utcnow())


def renew(job_id, token, stage=None):
    now = datetime.utcnow()
    values = dict(updated_at=now, lease_until=now + timedelta(seconds=settings.job_lease_seconds))
    if stage:
        values["stage"] = stage
    with SessionLocal() as db:
        result = db.execute(update(models.ProcessingJob).where(owned(job_id, token)).values(**values))
        db.commit()
        if not result.rowcount:
            raise LeaseLost("Job lease is no longer owned by this worker")


@contextmanager
def heartbeat(job_id, token):
    stop = Event()
    def beat():
        while not stop.wait(settings.job_lease_seconds / 3):
            try:
                renew(job_id, token)
            except Exception:
                log.exception("Job heartbeat failed for %s", job_id)
                return  # final commit still enforces the lease
    thread = Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)


def fail(job_id, token, error):
    from .services.llm import InferenceBusy
    now = datetime.utcnow()
    with SessionLocal() as db:
        job = db.get(models.ProcessingJob, job_id)
        if not job:
            return "lease_lost"
        busy = isinstance(error, InferenceBusy)
        permanent = isinstance(error, (PermanentJobError, FileNotFoundError))
        dead = not busy and (permanent or job.attempts >= settings.job_max_attempts)
        state = "dead" if dead else "retrying"
        delay = min(300, settings.retry_base_seconds * 2 ** max(0, job.attempts - 1)) + random.random()
        # Store error type only: provider exceptions may contain document content or credentials.
        message = None if busy else type(error).__name__
        if isinstance(error, PermanentJobError):
            message += ": " + str(error)
        if busy:
            delay = 1 + random.random()
        changed = db.execute(update(models.ProcessingJob).where(owned(job_id, token)).values(
            status=state, stage="waiting_capacity" if busy else "failed" if dead else "waiting_retry", error=message,
            attempts=max(0, job.attempts - 1) if busy else job.attempts,
            updated_at=now, available_at=now + timedelta(seconds=delay),
            published_at=None, lease_until=None, lease_token=None)).rowcount
        if not changed:
            return "lease_lost"
        db.execute(update(models.Document).where(models.Document.id == job.document_id).values(
            status="failed" if dead else "pending", error=message))
        db.commit()
        return state


def reset_job(db, job):
    """Manual replay uses the same ID; stale stream messages remain harmless."""
    if job.status in ACTIVE:
        return False
    changed = db.execute(update(models.ProcessingJob).where(
        models.ProcessingJob.id == job.id, models.ProcessingJob.status.notin_(ACTIVE)
    ).values(status="queued", stage="queued", attempts=0, error=None, lease_token=None,
             lease_until=None, available_at=datetime.utcnow(), updated_at=datetime.utcnow(),
             published_at=None, dead_lettered_at=None, trace_context=trace_carrier())).rowcount
    if changed:
        db.execute(update(models.Document).where(models.Document.id == job.document_id).values(status="pending", error=None))
    return bool(changed)
