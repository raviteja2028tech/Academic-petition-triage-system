"""Locust load test. Each virtual user submits a synthetic petition and polls until the run is terminal, reporting:
  * the submit request itself            (name: POST /v1/petitions)
  * the polling requests                 (name: GET /v1/runs/[id])
  * END-TO-END latency, submit -> terminal status   (request_type "E2E", name "submit->terminal")
A run "fails" if it ends `failed`, or does not finish within E2E_TIMEOUT_S.

Env: E2E_TIMEOUT_S=120  POLL_INTERVAL_S=0.5  RATE_PER_USER=0 (0 = closed loop, no think time;
     >0 = at most this many petitions per second per user -> use for an offered nominal load)
Only valid with the LLM STUB behind the workers (see docs/LOAD_TEST.md); the API, queue, workers, embeddings and
retrieval are the real ones.
"""
import os
import random
import time

from locust import HttpUser, constant, constant_throughput, events, task

E2E_TIMEOUT = float(os.environ.get("E2E_TIMEOUT_S", "120"))
POLL = float(os.environ.get("POLL_INTERVAL_S", "0.5"))
RATE = float(os.environ.get("RATE_PER_USER", "0"))
TERMINAL = {"completed", "escalated", "failed"}
TEXTS = ["I was hospitalised for three weeks and request consideration of my attendance shortage.",
         "I suffered a prolonged illness during the semester and request that my attendance shortage be considered.",
         "A family medical emergency caused me to miss classes; I request condonation of the shortage."]


class PetitionUser(HttpUser):
    wait_time = constant_throughput(RATE) if RATE > 0 else constant(0)

    def payload(self) -> dict:
        held = 50
        attended = random.randint(38, 42)             # 76 % - 84 %: inside the 75-85 % band
        return {"student_ref": "SYN-%06d" % random.randint(1, 999999), "program": "Computer Science",
                "admission_batch": "2025-26", "petition_type": "attendance", "course_code": "CS101", "semester": 3,
                "classes_held": held, "classes_attended": attended,
                "attendance_percentage": round(100 * attended / held, 1), "reason_category": "medical",
                "medical_documentation": "certificate", "petition_text": random.choice(TEXTS)}

    @task
    def petition_end_to_end(self):
        t0 = time.time()
        with self.client.post("/v1/petitions", json=self.payload(), name="POST /v1/petitions", catch_response=True) as r:
            if r.status_code != 202:
                r.failure(f"HTTP {r.status_code}")
                return
            run_id = r.json()["run_id"]
        status, err = "queued", None
        while time.time() - t0 < E2E_TIMEOUT:
            time.sleep(POLL)
            with self.client.get(f"/v1/runs/{run_id}", name="GET /v1/runs/[id]", catch_response=True) as g:
                if g.status_code != 200:
                    g.failure(f"HTTP {g.status_code}")
                    continue
                status = g.json()["status"]
            if status in TERMINAL:
                break
        else:
            err = Exception(f"run not finished within {E2E_TIMEOUT}s (status={status})")
        if status == "failed":
            err = Exception("run ended in status failed")
        events.request.fire(request_type="E2E", name="submit->terminal", response_time=(time.time() - t0) * 1000,
                            response_length=0, exception=err, context={})
