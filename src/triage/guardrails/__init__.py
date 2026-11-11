"""Guardrails (Phase 5): injection detection, lightweight toxicity baseline, tool-argument validation, numeric-claim check.

These are HEURISTICS. They reduce risk and make failures visible; they do not prove that an input is safe and they
cannot stop every attack (see docs/guardrails.md for the documented limits). The hard guarantees in this system come
from structure instead: petition text is passed as delimited data, tools are allow-listed, citations are verified
against the index, outputs are schema-validated, and every doubtful path ends in a human-decision escalation.
"""
from .injection import detect_injection
from .numeric import unsupported_numbers
from .toxicity import toxicity_findings
from .tool_args import ToolArgError, validate_tool_args

__all__ = ["detect_injection", "toxicity_findings", "validate_tool_args", "ToolArgError", "unsupported_numbers",
           "check_input", "check_output"]


def check_input(petition_text: str) -> list[dict]:
    """Findings on untrusted petition text. Empty list = nothing flagged (NOT a guarantee of safety)."""
    return ([{"check": "prompt_injection", "pattern": p} for p in detect_injection(petition_text)] +
            [{"check": "toxicity", "pattern": p} for p in toxicity_findings(petition_text)])


def check_output(*texts: str) -> list[dict]:
    """Findings on model-produced text before it reaches a user: toxicity and leaked-instruction markers."""
    out: list[dict] = []
    for t in texts:
        out += [{"check": "toxicity", "pattern": p} for p in toxicity_findings(t)]
        out += [{"check": "instruction_leak", "pattern": p} for p in detect_injection(t, output_mode=True)]
    return out
