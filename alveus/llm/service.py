"""Keep the local LLM server (systemd user unit ``alveus-llm``) in line with the active profile.

The assistant calls ``reconcile_local_server`` once when it starts, so the machine stays light no
matter how the profile was changed (settings form, YAML editor, hand edit + restart, reboot):

  profile without ``serve:`` (cloud API, external server)  -> stop alveus-llm if it runs (frees VRAM)
  profile with ``serve:``, unit stopped or failed          -> start it
  profile with ``serve:``, unit serves a different model   -> restart it with this profile's model

The chosen profile itself is persistent already: the GUI saves ``llm.profile`` in config/local.yaml,
which every start (and ``alveus llm serve`` in the unit) reads. Nothing happens when the unit is not
installed, when systemd is unavailable, with ``llm.manage_local_server: false``, or when the profile
is a one-off override (``alveus talk --profile`` / ``ALVEUS_LLM_PROFILE``), because the unit would
still serve the saved profile.
"""
from __future__ import annotations

import logging
import os
import subprocess

log = logging.getLogger(__name__)

UNIT = "alveus-llm.service"
RUNNING = ("active", "activating", "reloading")


def plan(managed: bool, unit_state: str | None, served: list[str] | None, model: str) -> str | None:
    """What to do with the unit: 'stop' | 'start' | 'restart' | None.

    managed     the profile has a ``serve:`` section (alveus-llm runs its model)
    unit_state  systemd ActiveState, or None when the unit is not installed
    served      model ids the server reports, or None when it does not answer (yet)
    """
    if unit_state is None:
        return None
    running = unit_state in RUNNING
    if not managed:
        return "stop" if running else None
    if not running:
        return "start"
    if served and model not in served:   # None/empty = still loading or unreachable: leave it
        return "restart"
    return None


def unit_state() -> str | None:
    try:
        out = subprocess.run(["systemctl", "--user", "show", UNIT, "-p", "LoadState", "-p", "ActiveState"],
                             capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if props.get("LoadState") != "loaded":
        return None
    return props.get("ActiveState") or "unknown"


def served_models(base_url: str | None) -> list[str] | None:
    if not base_url:
        return None
    import httpx
    try:
        r = httpx.get(f"{str(base_url).rstrip('/')}/models", timeout=2.0)
        if r.status_code != 200:
            return None   # llama-server answers 503 while it loads
        return [m["id"] for m in r.json().get("data", [])]
    except Exception:  # noqa: BLE001
        return None


def reconcile_local_server(cfg, prof) -> str | None:
    """Apply ``plan`` for the active profile; returns the action taken (for logs and tests)."""
    if not bool(cfg.llm.get("manage_local_server", True)):
        return None
    if os.environ.get("ALVEUS_LLM_PROFILE"):
        log.info("LLM profile %s is a one-off override; leaving %s as it is", prof.get("name"), UNIT)
        return None
    state = unit_state()
    managed = bool(prof.get("serve"))
    served = served_models(prof.get("base_url")) if managed and state in RUNNING else None
    action = plan(managed, state, served, str(prof.get("model", "")))
    if action is None:
        return None
    why = {"stop": f"profile {prof.get('name')} needs no local server; stopping it to free the GPU",
           "start": f"profile {prof.get('name')} runs on the local server; starting it",
           "restart": f"the local server serves {served}, profile {prof.get('name')} needs {prof.get('model')}; restarting it"}
    log.info("LLM server: %s", why[action])
    try:
        # --no-block: never wait on systemd from inside a unit that may be part of the same transaction
        subprocess.run(["systemctl", "--user", "--no-block", action, UNIT], timeout=10, check=False,
                       capture_output=True)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("could not %s %s: %s", action, UNIT, e)
        return None
    return action
