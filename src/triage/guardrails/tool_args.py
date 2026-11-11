"""Allow-list + argument validation for the Research agent's tools. Anything not matching is rejected BEFORE it runs.

The model chooses tools, but it cannot widen them: unknown tools, unknown arguments, oversized strings or malformed
clause ids are refused and reported back to the model as an error (and recorded in run_events).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..retrieval.chunk import TOPIC_RULES

CLAUSE_RX = r"^[A-Za-z0-9][A-Za-z0-9.()\- ]{0,39}$"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchArgs(_Args):
    query: str = Field(min_length=2, max_length=300)
    k: int = Field(default=5, ge=1, le=8)


class SemanticArgs(SearchArgs):
    topic: Optional[str] = None

    @field_validator("topic")
    @classmethod
    def _topic(cls, v):
        if v is not None and v not in TOPIC_RULES:
            raise ValueError(f"topic must be one of {sorted(TOPIC_RULES)}")
        return v


class ClauseArgs(_Args):
    clause_id: str = Field(pattern=CLAUSE_RX)


class NoArgs(_Args):
    pass


SCHEMAS: dict[str, type[_Args]] = {
    "search_semantic": SemanticArgs, "search_keyword": SearchArgs, "search_hybrid": SemanticArgs, "get_clause": ClauseArgs,
    "get_neighbouring_clauses": ClauseArgs, "get_petition_fields": NoArgs, "finish": NoArgs,
}
ALLOWED_TOOLS = tuple(SCHEMAS)


class ToolArgError(ValueError):
    pass


def validate_tool_args(tool: str, args: dict) -> dict:
    """Returns the cleaned argument dict or raises ToolArgError."""
    schema = SCHEMAS.get(tool)
    if schema is None:
        raise ToolArgError(f"tool '{tool}' is not on the allow-list {list(ALLOWED_TOOLS)}")
    if not isinstance(args, dict):
        raise ToolArgError("arguments must be a JSON object")
    try:
        return schema.model_validate(args).model_dump(exclude_none=True)
    except ValidationError as e:
        first = e.errors()[0]
        raise ToolArgError(f"invalid argument '{'.'.join(str(x) for x in first['loc'])}': {first['msg']}") from e
