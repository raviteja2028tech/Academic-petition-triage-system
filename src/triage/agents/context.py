"""Shared run context: LLM access with timeout + event recording + validated JSON output, budget, retriever."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from .. import cost, db
from ..observability.tracing import set_attrs, span
from ..config import Settings
from ..llm.client import LLMClient, LLMError, extract_json
from ..llm.prompts import Prompt
from ..retrieval.search import Retriever
from .budget import Budget

T = TypeVar("T", bound=BaseModel)


class InvalidAgentOutput(Exception):
    pass


class EvidenceRegistry:
    """Everything any tool returned in this run. Citations may only resolve to passages registered here."""

    def __init__(self) -> None:
        self.by_id: dict[str, dict] = {}
        self._chunk_to_eid: dict[str, str] = {}

    def add(self, chunk_id: str, text: str, meta: dict, strategy: str, query: str, score: float) -> str:
        if chunk_id in self._chunk_to_eid:
            return self._chunk_to_eid[chunk_id]
        eid = f"E{len(self.by_id) + 1}"
        self.by_id[eid] = {"evidence_id": eid, "chunk_id": chunk_id, "doc_name": meta["doc_name"],
                           "chapter": meta["chapter"], "clause_id": meta["clause_id"],
                           "page_start": meta["page_start"], "page_end": meta["page_end"], "text": text,
                           "strategy": strategy, "query": query, "score": score}
        self._chunk_to_eid[chunk_id] = eid
        return eid


@dataclass
class AgentContext:
    settings: Settings
    run_id: str
    llm: LLMClient
    retriever: Retriever
    budget: Budget
    prompts: dict[str, Prompt]
    registry: EvidenceRegistry = field(default_factory=EvidenceRegistry)
    usage: dict[str, dict] = field(default_factory=dict)
    models: set = field(default_factory=set)         # model names that actually answered (shown to the reader)

    def record(self, event: str, **detail) -> None:
        db.add_event(self.settings.db_path, self.run_id, event, detail)

    def call_json(self, agent: str, model: Type[T], **vars: str) -> T:
        """One LLM call (with one repair retry on invalid output). Raises LLMError / InvalidAgentOutput /
        BudgetExhausted."""
        prompt = self.prompts[agent]
        user = prompt.render_user(**vars)
        error = ""
        for attempt in (1, 2):
            self.budget.check_time()
            timeout = max(1.0, min(self.settings.llm_timeout_seconds, self.budget.remaining_seconds()))
            msg = user if not error else (
                user + f"\n\nYour previous reply was invalid ({error}). Reply again with ONE valid JSON object only.")
            try:
                with span("llm.call", agent=agent, prompt=prompt.id, attempt=attempt) as sp:
                    r = self.llm.complete(agent, prompt.system, msg, timeout)
                    set_attrs(sp, model=r.model, provider=getattr(r, "provider", ""), prompt_tokens=r.prompt_tokens,
                              completion_tokens=r.completion_tokens)
            except LLMError as e:
                self.record("llm_call", agent=agent, prompt=prompt.id, prompt_sha256=prompt.sha256[:12],
                            attempt=attempt, ok=False, error=str(e), kind=getattr(e, "kind", None),
                            provider=getattr(e, "provider", None))
                raise
            self.models.add(r.model or "unknown")
            u = self.usage.setdefault(agent, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0,
                                              "estimated_calls": 0})
            estimated = r.prompt_tokens is None or r.completion_tokens is None
            ptok = r.prompt_tokens if r.prompt_tokens is not None else cost.estimate_tokens(prompt.system + msg)
            ctok = r.completion_tokens if r.completion_tokens is not None else cost.estimate_tokens(r.text)
            u["calls"] += 1
            u["estimated_calls"] += int(estimated)
            u["prompt_tokens"] += ptok
            u["completion_tokens"] += ctok
            call_usd = cost.call_cost(ptok, ctok, self.settings)
            try:
                out = model.model_validate(extract_json(r.text))
                self.record("llm_call", agent=agent, prompt=prompt.id, prompt_sha256=prompt.sha256[:12],
                            attempt=attempt, ok=True, latency_s=round(r.latency_s, 3), model=r.model,
                            prompt_tokens=ptok, completion_tokens=ctok,
                            token_source="estimated" if estimated else "reported",
                            cost_usd=round(call_usd, 6) if call_usd is not None else None,
                            provider=getattr(r, "provider", ""))
                return out
            except (ValueError, ValidationError) as e:
                error = str(e).replace("\n", " ")[:200]
                self.record("llm_call", agent=agent, prompt=prompt.id, attempt=attempt, ok=False,
                            error=f"invalid output: {error}", latency_s=round(r.latency_s, 3))
        raise InvalidAgentOutput(f"{agent}: model output failed validation twice ({error})")


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False, default=str)
