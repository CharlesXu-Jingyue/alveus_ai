"""API keys for cloud LLM providers.

Keys are looked up by variable name (e.g. ANTHROPIC_API_KEY): first in the process environment,
then in ``~/.config/alveus/secrets.env`` (``ALVEUS_SECRETS`` overrides the path), a ``NAME=value``
file kept outside the repository with mode 600. The GUI writes that file through ``PUT /secrets``
and only ever reads back whether a key is set, never its value.

Keys found in the file are deliberately NOT exported to ``os.environ``: tool servers (the shell
tool among them) inherit the assistant's environment, and the model must not be able to print them.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def secrets_path() -> Path:
    return Path(os.environ.get("ALVEUS_SECRETS") or "~/.config/alveus/secrets.env").expanduser()


def _read() -> dict[str, str]:
    p = secrets_path()
    try:
        text = p.read_text()
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if NAME_RE.match(k) and v:
            out[k] = v
    return out


def get(name: str | None) -> str | None:
    """The key's value, or None when it is not set anywhere."""
    if not name:
        return None
    return os.environ.get(name) or _read().get(name)


def source(name: str) -> str | None:
    """'env' (process environment), 'file' (secrets.env) or None."""
    if os.environ.get(name):
        return "env"
    return "file" if name in _read() else None


def set_secret(name: str, value: str | None) -> None:
    """Store (or with an empty value remove) a key in secrets.env, keeping the file private."""
    if not NAME_RE.match(name):
        raise ValueError(f"invalid key name {name!r}: use capitals, digits and _ (e.g. ANTHROPIC_API_KEY)")
    value = (value or "").strip()
    if any(c in value for c in "\r\n"):
        raise ValueError("the key must be a single line")
    data = _read()
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    p = secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    body = "# Alveus API keys (written by the GUI; keep private). NAME=value per line.\n" + "".join(
        f"{k}={v}\n" for k, v in sorted(data.items()))
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(body)
    os.replace(tmp, p)
    os.chmod(p, 0o600)


def api_key_for(profile) -> str | None:
    """Key for a resolved LLM profile: a literal ``api_key`` wins, else the ``api_key_env`` variable."""
    literal = profile.get("api_key")
    if literal:
        return str(literal)
    return get(profile.get("api_key_env"))
