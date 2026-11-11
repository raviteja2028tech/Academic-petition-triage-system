"""Thin HTTP client for the FastAPI backend. The UI has no business logic and no database access."""
from __future__ import annotations

from typing import Any, Optional

import httpx


class ApiError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status, self.body = status, body


class ApiClient:
    def __init__(self, base_url: str = "", client: Optional[httpx.Client] = None):
        self._client = client or httpx.Client(base_url=base_url, timeout=10)

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            return self._client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise ApiError(f"API unreachable: {type(e).__name__}") from e

    def submit(self, payload: dict) -> dict:
        r = self._req("POST", "/v1/petitions", json=payload)
        if r.status_code == 202:
            return r.json()
        if r.status_code == 422:
            raise ApiError("validation failed", 422, r.json())
        raise ApiError(f"submission failed (HTTP {r.status_code})", r.status_code, _safe(r))

    def run(self, run_id: str) -> dict:
        r = self._req("GET", f"/v1/runs/{run_id}")
        if r.status_code == 404:
            raise ApiError("run not found", 404)
        if r.status_code != 200:
            raise ApiError(f"HTTP {r.status_code}", r.status_code)
        return r.json()

    def runs(self, limit: int = 20) -> dict:
        return self._get_json("/v1/runs", params={"limit": limit})

    def corpus(self) -> dict:
        return self._get_json("/v1/corpus")

    def ready(self) -> dict:
        r = self._req("GET", "/readyz")
        return r.json()

    def trace(self, run_id: str) -> dict:
        return self._get_json(f"/v1/runs/{run_id}/trace")

    def stats(self) -> dict:
        return self._get_json("/v1/stats")

    def feedback(self) -> dict:
        return self._get_json("/v1/feedback")

    def evaluation(self) -> dict:
        return self._get_json("/v1/evaluation")

    def send_feedback(self, run_id: str, rating: int, agrees, comment: str) -> None:
        body = {"rating": rating}
        if agrees is not None:
            body["agrees_with_recommendation"] = agrees
        if comment:
            body["comment"] = comment
        r = self._req("POST", f"/v1/runs/{run_id}/feedback", json=body)
        if r.status_code != 200:
            raise ApiError(f"feedback not stored (HTTP {r.status_code})", r.status_code, _safe(r))

    def upload_document(self, run_id: str, filename: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
        r = self._req("POST", f"/v1/runs/{run_id}/documents", files={"file": (filename, data, content_type)})
        if r.status_code != 201:
            body = _safe(r)
            detail = body.get("detail") if isinstance(body, dict) else body
            raise ApiError(f"{detail or 'upload failed'} (HTTP {r.status_code})", r.status_code, body)
        return r.json()

    def download_document(self, run_id: str, doc_id: int) -> bytes:
        r = self._req("GET", f"/v1/runs/{run_id}/documents/{doc_id}")
        if r.status_code != 200:
            raise ApiError(f"document not available (HTTP {r.status_code})", r.status_code)
        return r.content

    def examiner_decision(self, run_id: str, decision: str, note: str, examiner_label: str) -> dict:
        r = self._req("POST", f"/v1/runs/{run_id}/examiner-decision",
                      json={"decision": decision, "note": note, "examiner_label": examiner_label})
        if r.status_code != 201:
            body = _safe(r)
            detail = body.get("detail") if isinstance(body, dict) else body
            raise ApiError(f"decision not stored: {detail if isinstance(detail, str) else 'invalid input'} (HTTP {r.status_code})",
                           r.status_code, body)
        return r.json()

    def _get_json(self, path: str, **kw) -> dict:
        r = self._req("GET", path, **kw)
        if r.status_code != 200:
            raise ApiError(f"HTTP {r.status_code}", r.status_code)
        return r.json()


def _safe(r: httpx.Response) -> Any:
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return r.text[:200]
