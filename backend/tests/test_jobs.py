import hashlib
import os
from redis import Redis
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import fakeredis
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker
from app import jobs, models
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.pipeline import process_document
from app.worker import execute_job
from app.services.retrieval import Corpus


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine = create_engine(f"sqlite:///{self.root / 'test.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        redis_url = os.environ.get("TEST_REDIS_URL")
        if redis_url:
            if not redis_url.endswith("/15"):
                raise ValueError("Use a disposable Redis database 15 for integration tests")
            self.client = Redis.from_url(redis_url, decode_responses=True)
            self.client.flushdb()
        else:
            self.client = fakeredis.FakeRedis(decode_responses=True)
        self.patches = [patch("app.jobs.SessionLocal", self.sessions), patch("app.pipeline.SessionLocal", self.sessions),
                        patch("app.worker.SessionLocal", self.sessions), patch.object(settings, "upload_dir", str(self.root / "uploads"))]
        for p in self.patches:
            p.start()
        def override_db():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = override_db
        # Deliberately omit lifespan: API tests use only an isolated database.
        self.api = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        for p in reversed(self.patches):
            p.stop()
        self.engine.dispose()
        self.tmp.cleanup()

    def upload(self, key="request-1", text="Invoice total 42 USD"):
        return self.api.post("/api/documents", files={"file": ("invoice.txt", text, "text/plain")},
                             headers={"Idempotency-Key": key})

    def get_job(self, job_id):
        with self.sessions() as db:
            return db.get(models.ProcessingJob, job_id)

    def expire(self, job_id):
        with self.sessions() as db:
            db.execute(update(models.ProcessingJob).where(models.ProcessingJob.id == job_id).values(
                lease_until=datetime.utcnow() - timedelta(seconds=1), available_at=datetime.utcnow() - timedelta(seconds=1)))
            db.commit()

    def test_upload_persists_outbox_without_redis_and_is_idempotent(self):
        with patch("app.services.redis_client.redis_client", side_effect=AssertionError("HTTP must not use broker")):
            response = self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        doc = response.json()
        self.assertEqual(doc["status"], "pending")
        self.assertTrue(doc["job_id"])
        self.assertEqual(self.upload().json()["id"], doc["id"])
        self.assertEqual(self.upload(text="different content").status_code, 409)
        self.assertEqual(self.api.get(f"/api/jobs/{doc['job_id']}").json()["status"], "queued")
        self.assertEqual(self.api.delete(f"/api/documents/{doc['id']}").status_code, 409)

    def test_broker_outage_recovery_and_duplicate_claim(self):
        doc = self.upload().json()
        from redis.exceptions import ConnectionError
        with patch.object(self.client, "xadd", side_effect=ConnectionError("offline")):
            with self.assertRaises(ConnectionError):
                jobs.dispatch_due(self.client)
        self.assertIsNone(self.get_job(doc["job_id"]).published_at)
        jobs.dispatch_due(self.client)
        self.assertEqual(self.client.xlen(jobs.STREAM), 1)
        self.assertIsNotNone(jobs.claim(doc["job_id"]))
        self.assertIsNone(jobs.claim(doc["job_id"]))

    def test_retry_backoff_dead_letter_and_replay(self):
        doc = self.upload().json()
        for attempt in range(settings.job_max_attempts):
            token = jobs.claim(doc["job_id"])
            self.assertIsNotNone(token)
            status = jobs.fail(doc["job_id"], token, RuntimeError("temporary"))
            if attempt < settings.job_max_attempts - 1:
                self.assertEqual(status, "retrying")
                self.assertIsNone(jobs.claim(doc["job_id"]))
                self.expire(doc["job_id"])
        self.assertEqual(status, "dead")
        jobs.dispatch_due(self.client)
        self.assertEqual(self.client.xlen(jobs.DEAD_STREAM), 1)
        jobs.dispatch_due(self.client)
        self.assertEqual(self.client.xlen(jobs.DEAD_STREAM), 1)
        replay = self.api.post(f"/api/jobs/{doc['job_id']}/retry")
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["attempts"], 0)
        self.assertIsNotNone(jobs.claim(doc["job_id"]))

    def test_inference_capacity_does_not_exhaust_failure_retries(self):
        from app.services.llm import InferenceBusy
        doc = self.upload().json()
        for _ in range(settings.job_max_attempts + 1):
            token = jobs.claim(doc["job_id"])
            self.assertIsNotNone(token)
            self.assertEqual(jobs.fail(doc["job_id"], token, InferenceBusy()), "retrying")
            job = self.get_job(doc["job_id"])
            self.assertEqual(job.attempts, 0)
            self.assertEqual(job.stage, "waiting_capacity")
            self.expire(doc["job_id"])

    def test_expired_worker_is_fenced_from_updates_and_final_commit(self):
        doc = self.upload().json()
        first = jobs.claim(doc["job_id"])
        self.expire(doc["job_id"])
        second = jobs.claim(doc["job_id"])
        self.assertNotEqual(first, second)
        with self.assertRaises(jobs.LeaseLost):
            jobs.renew(doc["job_id"], first)
        self.assertEqual(jobs.fail(doc["job_id"], first, RuntimeError()), "lease_lost")
        with patch("app.pipeline.renew"), self.pipeline_fakes():
            with self.assertRaises(jobs.LeaseLost):
                process_document(doc["id"], doc["job_id"], first)
        self.assertEqual(self.get_job(doc["job_id"]).lease_token, second)
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(models.Chunk)).all()), 0)

    def pipeline_fakes(self):
        from contextlib import ExitStack
        stack = ExitStack()
        for name, value in (("classifier.classify", {"category": "Invoice", "confidence": .9}),
                            ("extractor.extract_fields", {"total_amount": 42}), ("summarizer.summarize", "Invoice for 42 USD"),
                            ("embeddings.embed_chunks", [[1., 0.]])):
            stack.enter_context(patch("app.pipeline." + name, return_value=value))
        return stack

    def test_worker_commits_once_and_retrieval_sees_output_without_rehydrating(self):
        doc = self.upload().json()
        with self.pipeline_fakes():
            execute_job(doc["job_id"])
            execute_job(doc["job_id"])  # duplicate delivery
        self.assertEqual(self.get_job(doc["job_id"]).status, "succeeded")
        with self.sessions() as db:
            self.assertEqual(len(Corpus.from_db(db).entries), 1)
            chunk = db.scalars(select(models.Chunk)).one()
            self.assertEqual(chunk.text, "Invoice total 42 USD")
        hits = self.api.get("/api/search", params={"q": "invoice", "strategy": "bm25"})
        self.assertEqual(hits.status_code, 200, hits.text)
        self.assertEqual(len(hits.json()["hits"]), 1)
        self.assertEqual(self.api.get(f"/api/documents/{doc['id']}/chunks/{chunk.id}?digest=old").status_code, 410)
        self.assertEqual(self.api.delete(f"/api/documents/{doc['id']}").status_code, 204)

    def test_document_budget_stops_processing_before_any_inference(self):
        doc = self.upload().json()
        with patch.object(settings, "max_document_tokens", 1), patch("app.pipeline.classifier.classify") as classify:
            execute_job(doc["job_id"])
        self.assertEqual(self.get_job(doc["job_id"]).status, "dead")
        self.assertIn("MAX_DOCUMENT_TOKENS", self.get_job(doc["job_id"]).error)
        classify.assert_not_called()

    def test_final_attempt_crash_becomes_dead_letter(self):
        doc = self.upload().json()
        for _ in range(settings.job_max_attempts):
            jobs.claim(doc["job_id"])
            self.expire(doc["job_id"])
        jobs.dispatch_due(self.client)
        self.assertEqual(self.get_job(doc["job_id"]).status, "dead")
        self.assertEqual(self.client.xlen(jobs.DEAD_STREAM), 1)

    @unittest.skipUnless(os.environ.get("TEST_REDIS_URL"), "Requires disposable real Redis")
    def test_separate_worker_process_consumes_stream_and_publishes_results(self):
        """Exercise the actual broker loop, worker threads, SDK and SQL connection."""
        import json
        import socket
        import subprocess
        import sys
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        from urllib.request import urlopen

        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path.endswith("embeddings"):
                    result = {"object": "list", "model": "test", "usage": {"prompt_tokens": 5, "total_tokens": 5},
                              "data": [{"object": "embedding", "index": i, "embedding": [1., 0.]}
                                       for i, _ in enumerate(request["input"])]}
                else:
                    system = request["messages"][0]["content"]
                    content = (json.dumps({"category": "Invoice", "confidence": .99}) if "document classifier" in system
                               else json.dumps({"total_amount": 42}) if "Extract the following" in system
                               else "Invoice for 42 USD")
                    result = {"id": "test-completion", "object": "chat.completion", "created": 1,
                              "model": "gpt-4o-mini", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                              "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}
                body = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            metrics_port = port_socket.getsockname()[1]
        env = {**os.environ, "DATABASE_URL": f"sqlite:///{self.root / 'test.db'}",
               "REDIS_URL": os.environ["TEST_REDIS_URL"], "OPENAI_API_KEY": "test-key",
               "OPENAI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
               "WORKER_METRICS_PORT": str(metrics_port), "OTEL_EXPORTER_OTLP_ENDPOINT": ""}
        doc = self.upload().json()
        second_doc = self.upload(key="request-2").json()
        log_path = self.root / "worker.log"
        worker = None
        try:
            with log_path.open("w") as output:
                worker = subprocess.Popen([sys.executable, "-m", "app.worker"], env=env, stdout=output, stderr=output)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if all(self.get_job(d["job_id"]).status == "succeeded" for d in (doc, second_doc)):
                        break
                    if worker.poll() is not None:
                        self.fail(log_path.read_text())
                    time.sleep(.1)
                for d in (doc, second_doc):
                    self.assertEqual(self.get_job(d["job_id"]).status, "succeeded", log_path.read_text())
                metrics = urlopen(f"http://127.0.0.1:{metrics_port}/metrics").read().decode()
                self.assertIn('idp_job_attempts_total{outcome="succeeded"} 2.0', metrics)
                with self.sessions() as db:
                    self.assertEqual(len(Corpus.from_db(db).entries), 2)
        finally:
            if worker:
                worker.terminate()
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait()
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
