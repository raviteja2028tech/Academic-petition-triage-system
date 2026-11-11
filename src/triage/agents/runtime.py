"""Runs one petition through the agent graph and persists the outcome. Called by the RQ worker."""
from __future__ import annotations

from typing import Optional

from .. import db
from ..config import Settings
from ..llm.client import LLMClient, LLMNotConfigured
from ..llm.prompts import PromptError, load_prompt
from ..retrieval.search import Retriever
from .budget import Budget
from .context import AgentContext
from .graph import build_graph, exception_to_escalation
from .policy import DISCLAIMER
from .runtime_errors import RetrievalUnavailable
from .state import Escalation, EscalationReason

_retriever: Optional[Retriever] = None


def make_llm(s: Settings) -> LLMClient:
    """Primary (+ optional fallback) provider behind retry/backoff and a Redis circuit breaker."""
    from ..reliability.resilient_llm import build_resilient
    return build_resilient(s)


def make_retriever(s: Settings) -> Retriever:
    """One retriever (and embedding model) per worker process."""
    global _retriever
    if _retriever is None:
        try:
            _retriever = _build_retriever(s)
        except Exception as e:  # noqa: BLE001
            raise RetrievalUnavailable(f"cannot open the regulation index: {type(e).__name__}: {e}") from e
    return _retriever


def _build_retriever(s: Settings) -> Retriever:
    from ..retrieval.embed import SentenceTransformerEmbedder
    from ..retrieval.store import ChromaStore, make_client
    from ..reliability.cache import CachedEmbedder, CachedRetriever
    from ..reliability.deps import redis_for
    from ..reliability.metrics import get_metrics
    emb = SentenceTransformerEmbedder(s.embed_model, s.hf_home or None)
    if s.cache_enabled:
        conn, m = redis_for(s), get_metrics(s)
        emb = CachedEmbedder(emb, conn, m, s.cache_ttl_seconds)
    r = Retriever(ChromaStore(make_client(s.chroma_host, s.chroma_port), s.chroma_collection, emb.tag), emb)
    if s.cache_enabled:
        r = CachedRetriever(r, conn, m, s.db_path, s.cache_ttl_seconds)
    return r


def load_prompts(s: Settings) -> dict:
    return {"triage": load_prompt(s.prompts_dir, "triage", s.triage_prompt_version),
            "research": load_prompt(s.prompts_dir, "research", s.research_prompt_version),
            "verifier": load_prompt(s.prompts_dir, "verifier", s.verifier_prompt_version)}


def _early_escalation(s: Settings, run_id: str, esc: Escalation) -> None:
    result = {"mode": "agents", "evidence_used": False, "route": "refer-to-committee", "position": "NO_DETERMINATION",
              "basis": esc.detail, "citations": [], "escalation": esc.model_dump(mode="json"),
              "evidence_reviewed": [], "disclaimer": DISCLAIMER,
              "message": "No determination was made; escalated to a human. " + esc.detail}
    db.add_event(s.db_path, run_id, "escalation", {"reason": esc.reason.value, "detail": esc.detail})
    db.set_status(s.db_path, run_id, "escalated", result=result, detail={"reason": esc.reason.value})


def run_pipeline(s: Settings, run_id: str, llm: Optional[LLMClient] = None,
                 retriever: Optional[Retriever] = None, prompts: Optional[dict] = None) -> None:
    """llm / retriever / prompts may be injected (evaluation harness, tests); otherwise built from settings."""
    run = db.get_run(s.db_path, run_id)
    if run is None:
        raise RuntimeError(f"run {run_id} not found")
    if run["status"] != "queued":
        return
    db.set_mode(s.db_path, run_id, "agents")
    db.set_status(s.db_path, run_id, "running", detail={"worker": "agents"})
    try:
        prompts = prompts or load_prompts(s)
        llm = llm or make_llm(s)
        retriever = retriever or make_retriever(s)
    except (LLMNotConfigured, RetrievalUnavailable, PromptError) as e:
        esc = (exception_to_escalation(e) if not isinstance(e, PromptError)
               else Escalation(required=True, reason=EscalationReason.agent_error, detail=f"prompt error: {e}"))
        return _early_escalation(s, run_id, esc)
    except Exception as e:  # noqa: BLE001
        return _early_escalation(s, run_id, exception_to_escalation(e))

    budget = Budget(s.max_research_steps, s.max_tool_calls, s.max_run_seconds)
    ctx = AgentContext(settings=s, run_id=run_id, llm=llm, retriever=retriever, budget=budget, prompts=prompts)
    if hasattr(llm, "sink"):                       # resilient wrapper: surface retries / fallback / breaker in run_events
        llm.sink, llm.remaining = ctx.record, budget.remaining_seconds
    ctx.record("prompt_versions", **{k: {"id": p.id, "sha256": p.sha256[:12]} for k, p in prompts.items()})
    try:
        out = build_graph(ctx).invoke({"petition": run["petition"], "attempt": 1, "hint": ""},
                                      config={"recursion_limit": 40})
        final = out["final"]
    except Exception as e:  # noqa: BLE001  (graph machinery itself failed)
        db.set_status(s.db_path, run_id, "failed", error=f"{type(e).__name__}: {e}")
        raise
    db.set_status(s.db_path, run_id, final["status"], result=final["result"],
                  detail={"mode": "agents", "route": final["result"]["route"]})
