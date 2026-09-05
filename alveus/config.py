"""Configuration loading for Alveus.

Layers (later wins):
  1. config/alveus.yaml   (defaults, in repo)
  2. config/local.yaml    (machine-specific, git-ignored; written by install.sh)
  3. $ALVEUS_CONFIG       (optional extra file)
  4. environment overrides: ALVEUS_LLM_PROFILE, ALVEUS_STT_BACKEND, ALVEUS_TTS_BACKEND

Every string value is expanded: ``~`` and ``${VAR}``. The variables ALVEUS_HOME
(repo root) and ALVEUS_MODELS (model directory) are always defined; a YAML top-level
``env:`` mapping can define further defaults (used for llama-server path etc.).
"""
from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class DotDict(dict):
    """dict with attribute access and dotted-path ``get``."""

    def __getattr__(self, item: str) -> Any:
        try:
            v = self[item]
        except KeyError as e:
            raise AttributeError(item) from e
        return DotDict(v) if isinstance(v, dict) and not isinstance(v, DotDict) else v

    def path(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return DotDict(cur) if isinstance(cur, dict) else cur


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _expand(value: Any, env: dict[str, str]) -> Any:
    if isinstance(value, str):
        def sub(m: re.Match) -> str:
            return env.get(m.group(1), os.environ.get(m.group(1), m.group(0)))
        s = _VAR_RE.sub(sub, value)
        if s.startswith("~"):
            s = os.path.expanduser(s)
        return s
    if isinstance(value, list):
        return [_expand(v, env) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v, env) for k, v in value.items()}
    return value


def _load_yaml(p: Path) -> dict:
    if not p.exists():
        return {}
    with p.open() as f:
        return yaml.safe_load(f) or {}


def load_config(extra: str | os.PathLike | None = None) -> DotDict:
    cfg_dir = REPO_ROOT / "config"
    merged: dict = {}
    for p in (cfg_dir / "alveus.yaml", cfg_dir / "local.yaml"):
        merged = _deep_merge(merged, _load_yaml(p))
    extra = extra or os.environ.get("ALVEUS_CONFIG")
    if extra:
        merged = _deep_merge(merged, _load_yaml(Path(extra).expanduser()))

    # Variable environment: defaults from yaml `env:`, real environment wins.
    env: dict[str, str] = {
        "ALVEUS_HOME": str(REPO_ROOT),
        "ALVEUS_MODELS": str(REPO_ROOT / "models"),
        "ALVEUS_LLAMA_SERVER": "llama-server",
    }
    for k, v in (merged.pop("env", None) or {}).items():
        env[k] = os.path.expanduser(str(v))
    for k in list(env):
        if k in os.environ:
            env[k] = os.environ[k]
    # ${VAR} inside env values themselves
    for k, v in env.items():
        env[k] = _expand(v, env)

    merged = _expand(merged, env)
    merged["_env"] = env

    # Simple env overrides for the most common swaps.
    if os.environ.get("ALVEUS_LLM_PROFILE"):
        merged.setdefault("llm", {})["profile"] = os.environ["ALVEUS_LLM_PROFILE"]
    if os.environ.get("ALVEUS_STT_BACKEND"):
        merged.setdefault("stt", {})["backend"] = os.environ["ALVEUS_STT_BACKEND"]
    if os.environ.get("ALVEUS_TTS_BACKEND"):
        merged.setdefault("tts", {})["backend"] = os.environ["ALVEUS_TTS_BACKEND"]
    return DotDict(merged)


def llm_profile(cfg: DotDict, name: str | None = None) -> DotDict:
    """Return the active LLM profile merged with llm-level defaults."""
    llm = cfg.llm
    name = name or llm.get("profile")
    profiles = llm.get("profiles") or {}
    if name not in profiles:
        raise KeyError(f"LLM profile '{name}' not found; available: {sorted(profiles)}")
    prof = dict(profiles[name])
    for k in ("temperature", "top_p", "max_tokens", "max_tool_rounds"):
        prof.setdefault(k, llm.get(k))
    prof["name"] = name
    return DotDict(prof)


# ----------------------------------------------------------------------------- editing
LOCAL_YAML = REPO_ROOT / "config" / "local.yaml"


def read_local_yaml() -> str:
    return LOCAL_YAML.read_text() if LOCAL_YAML.exists() else ""


def write_local_yaml(text: str) -> dict:
    """Validate and write config/local.yaml verbatim. Returns the parsed mapping."""
    data = yaml.safe_load(text) if text.strip() else {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("local.yaml must be a mapping at the top level")
    LOCAL_YAML.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_YAML.write_text(text if text.endswith("\n") or not text else text + "\n")
    return data


def patch_local_yaml(patch: dict) -> dict:
    """Deep-merge ``patch`` into config/local.yaml (a ``None`` leaf removes the override)."""
    current = yaml.safe_load(read_local_yaml()) or {}
    merged = _merge_patch(current, patch)
    LOCAL_YAML.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_YAML.write_text("# Machine-specific overrides (git-ignored). Defaults are in alveus.yaml.\n"
                          + yaml.safe_dump(merged, sort_keys=False, allow_unicode=True))
    return merged


def _merge_patch(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        elif isinstance(v, dict):
            sub = out.get(k) if isinstance(out.get(k), dict) else {}
            merged = _merge_patch(sub, v)
            if merged:
                out[k] = merged
            else:
                out.pop(k, None)
        else:
            out[k] = copy.deepcopy(v)
    return out


def set_path(d: dict, dotted: str, value: Any) -> dict:
    """Build a nested patch dict from a dotted path."""
    cur = d
    parts = dotted.split(".")
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value
    return d
