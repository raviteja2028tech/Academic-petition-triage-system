"""OpenTelemetry tracing (exported to Jaeger via OTLP/HTTP). A no-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set or an
exporter is injected (tests). Span attributes are restricted to short primitives: no petition text, no credentials.
Trace context crosses the queue as a W3C `traceparent` string passed to the job."""
from __future__ import annotations

import contextlib
import os
from typing import Any, Iterator, Optional

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_provider: Optional[TracerProvider] = None
_prop = TraceContextTextMapPropagator()
_FORBIDDEN = ("petition_text", "api_key", "authorization", "password", "secret", "token_value")


def setup_tracing(service: str, endpoint: Optional[str] = None, exporter=None, simple: bool = False) -> bool:
    """Returns True if tracing is active."""
    global _provider
    endpoint = endpoint if endpoint is not None else os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if exporter is None and not endpoint:
        return False
    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        exporter = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces", timeout=3)
    _provider = TracerProvider(resource=Resource.create({"service.name": service}))
    _provider.add_span_processor(SimpleSpanProcessor(exporter) if simple else BatchSpanProcessor(exporter))
    return True


_pid: Optional[int] = None


def ensure_tracing(service: str) -> bool:
    """RQ runs every job in a forked 'work horse' process, and the batch exporter's thread does not survive a fork.
    Call this at the start of a job: it (re)creates the provider when the process id changed."""
    global _pid
    if _pid == os.getpid() and _provider is not None:
        return True
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    _pid = os.getpid()
    return setup_tracing(service)


_flush_failures = 0


def flush_tracing() -> None:
    """End-of-job flush. In the long-lived `simple` worker the batch processor already exports in the background, so a job must
    NEVER wait for the collector (measured: an unreachable Jaeger added ~1.5-3 s to every job). In fork mode the work horse exits
    after the job, so it flushes, with a short timeout after the collector has failed once."""
    global _flush_failures
    if _provider is None or os.environ.get("WORKER_MODE", "simple").lower() == "simple":
        return
    try:
        ok = _provider.force_flush(3000 if _flush_failures == 0 else 300)
    except Exception:  # noqa: BLE001
        ok = False
    _flush_failures = 0 if ok else min(_flush_failures + 1, 5)


def shutdown_tracing() -> None:
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None


def _clean(attrs: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in attrs.items():
        if v is None or any(f in k.lower() for f in _FORBIDDEN):
            continue
        out[k] = v if isinstance(v, (bool, int, float)) else str(v)[:200]
    return out


@contextlib.contextmanager
def span(name: str, **attrs) -> Iterator[Optional[trace.Span]]:
    """Context manager; yields the span (or None when tracing is off). Exceptions are recorded then re-raised."""
    if _provider is None:
        yield None
        return
    tracer = _provider.get_tracer("triage")
    with tracer.start_as_current_span(name, attributes=_clean(attrs)) as sp:
        try:
            yield sp
        except Exception as e:  # noqa: BLE001
            sp.set_status(trace.Status(trace.StatusCode.ERROR, type(e).__name__))
            sp.record_exception(e)
            raise


def set_attrs(sp: Optional[trace.Span], **attrs) -> None:
    if sp is not None:
        for k, v in _clean(attrs).items():
            sp.set_attribute(k, v)


def current_traceparent() -> Optional[str]:
    if _provider is None:
        return None
    carrier: dict[str, str] = {}
    _prop.inject(carrier)
    return carrier.get("traceparent")


@contextlib.contextmanager
def use_parent(traceparent: Optional[str]) -> Iterator[None]:
    """Make a remote span (from the API) the parent of spans created in this block."""
    if not traceparent or _provider is None:
        yield
        return
    token = otel_context.attach(_prop.extract({"traceparent": traceparent}))
    try:
        yield
    finally:
        otel_context.detach(token)
