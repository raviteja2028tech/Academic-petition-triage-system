"""Bounds on a run: LLM steps per agent, tool calls per run, wall-clock time (A1)."""
from __future__ import annotations

import time
from typing import Callable


class BudgetExhausted(Exception):
    def __init__(self, kind: str):
        super().__init__(f"budget exhausted: {kind}")
        self.kind = kind            # "steps" | "tool_calls" | "time"


class Budget:
    def __init__(self, max_steps: int, max_tool_calls: int, max_seconds: float,
                 clock: Callable[[], float] = time.monotonic):
        self.max_steps, self.max_tool_calls, self.max_seconds = max_steps, max_tool_calls, max_seconds
        self.clock = clock
        self.started = clock()
        self.steps: dict[str, int] = {}
        self.tool_calls = 0

    def remaining_seconds(self) -> float:
        return self.max_seconds - (self.clock() - self.started)

    def check_time(self) -> None:
        if self.remaining_seconds() <= 0:
            raise BudgetExhausted("time")

    def use_step(self, agent: str) -> None:
        self.check_time()
        if self.steps.get(agent, 0) >= self.max_steps:
            raise BudgetExhausted("steps")
        self.steps[agent] = self.steps.get(agent, 0) + 1

    def use_tool(self) -> None:
        self.check_time()
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExhausted("tool_calls")
        self.tool_calls += 1

    @property
    def tool_calls_left(self) -> int:
        return self.max_tool_calls - self.tool_calls
