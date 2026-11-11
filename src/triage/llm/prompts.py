"""Versioned prompts stored as files in prompts/<name>_<version>.yaml. The id and sha256 are recorded per run."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

import yaml


class PromptError(Exception):
    pass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system: str
    user: str
    sha256: str

    @property
    def id(self) -> str:
        return f"{self.name}_{self.version}"

    def render_user(self, **vars: str) -> str:
        out = self.user
        for k, v in vars.items():
            out = out.replace("{{" + k + "}}", str(v))
        return out


def load_prompt(prompts_dir: str, name: str, version: str) -> Prompt:
    path = os.path.join(prompts_dir, f"{name}_{version}.yaml")
    if not os.path.isfile(path):
        raise PromptError(f"prompt file not found: {path}")
    raw = open(path, "rb").read()
    d = yaml.safe_load(raw)
    for k in ("name", "version", "system", "user"):
        if k not in d:
            raise PromptError(f"{path}: missing key '{k}'")
    if d["name"] != name or str(d["version"]) != version:
        raise PromptError(f"{path}: name/version in file do not match its filename")
    return Prompt(name, version, d["system"], d["user"], hashlib.sha256(raw).hexdigest())
