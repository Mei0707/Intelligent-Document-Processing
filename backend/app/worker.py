"""python -m app.worker — bounded worker pool and durable-outbox dispatcher."""
import logging
import signal
import socket
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event
from prometheus_client import start_http_server
from redis.exceptions import RedisError, ResponseError
from . import jobs, models
from .config import settings
from .db import SessionLocal, init_db
from .monitoring import (JOB_SECONDS, JOB_OUTCOMES, QUEUE_WAIT, DOCUMENTS_PROCESSING,
                         DOCUMENT_PROCESSING_TOTAL_SECONDS, record_document_processing)
from .pipeline import process_document
from .services.llm import measure_usage
from .services.redis_client import redis_client
from .telemetry import configure_telemetry, span

log = logging.getLogger("idp.worker")


def execute_job(job_id):
    token = jobs.claim(job_id)
    if not token:
        return
    started = time.perf_counter()
    DOCUMENTS_PROCESSING.inc()
    outcome = "succeeded"
    try:
        with SessionLocal() as db:
            job = db.get(models.ProcessingJob, job_id)
            document_id, carrier = job.document_id, job.trace_context
            QUEUE_WAIT.observe((datetime.utcnow() - job.created_at).total_seconds())
        with span("job.process", carrier=carrier, job_id=job_id), jobs.heartbeat(job_id, token), measure_usage():
            process_document(document_id, job_id, token)
    except jobs.LeaseLost:
        outcome = "lease_lost"
    except Exception as error:
        log.warning("Job %s attempt failed: %s", job_id, type(error).__name__)
        outcome = jobs.fail(job_id, token, error)
        if outcome == "dead":
            record_document_processing("failed", None, type(error).__name__)
    finally:
        elapsed = time.perf_counter() - started
        JOB_SECONDS.observe(elapsed)
        DOCUMENT_PROCESSING_TOTAL_SECONDS.observe(elapsed)
        JOB_OUTCOMES.labels(outcome).inc()
        DOCUMENTS_PROCESSING.dec()


def run():
    logging.basicConfig(level=logging.INFO)
    init_db()
    provider = configure_telemetry("idp-worker")
    start_http_server(settings.worker_metrics_port)
    client = redis_client()
    consumer = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    futures = {}
    last_dispatch = 0
    try:
        with ThreadPoolExecutor(max_workers=settings.worker_concurrency) as pool:
            while not stop.is_set():
                try:
                    try:
                        client.xgroup_create(jobs.STREAM, jobs.GROUP, id="0", mkstream=True)
                    except ResponseError as error:
                        if "BUSYGROUP" not in str(error):
                            raise
                    # ACK only after durable completion/retry state. On infrastructure
                    # errors, leave pending for reclaim and SQL-outbox redelivery.
                    for future, message_id in list(futures.items()):
                        if future.done():
                            try:
                                future.result()
                            except Exception:
                                log.exception("Worker task infrastructure failure")
                            else:
                                client.xack(jobs.STREAM, jobs.GROUP, message_id)
                                client.xdel(jobs.STREAM, message_id)
                            del futures[future]
                    if time.monotonic() - last_dispatch > 2:
                        jobs.dispatch_due(client)
                        last_dispatch = time.monotonic()
                    capacity = settings.worker_concurrency - len(futures)
                    if capacity <= 0:
                        stop.wait(.1)
                        continue
                    claimed = client.xautoclaim(jobs.STREAM, jobs.GROUP, consumer,
                                                settings.job_lease_seconds * 1000, "0-0", count=capacity)
                    messages = claimed[1]
                    if not messages:
                        rows = client.xreadgroup(jobs.GROUP, consumer, {jobs.STREAM: ">"}, count=capacity, block=1000)
                        messages = rows[0][1] if rows else []
                    for message_id, fields in messages:
                        if "job_id" not in fields:
                            client.xack(jobs.STREAM, jobs.GROUP, message_id)
                            client.xdel(jobs.STREAM, message_id)
                            continue
                        futures[pool.submit(execute_job, fields["job_id"])] = message_id
                except RedisError:
                    log.warning("Redis unavailable; durable jobs remain in SQL outbox")
                    stop.wait(2)
    finally:
        provider.shutdown()


if __name__ == "__main__":
    run()
