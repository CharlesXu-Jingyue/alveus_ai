"""Instructions and personalities: the two halves of the system prompt.

``instructions`` (``assistant.instructions_file``, default ``config/instructions.md``) hold the
directions and boundaries: identity, how spoken replies are shaped, the private-system rules,
tools and confirmations. A *personality* only shapes how the assistant sounds (tone, word
choice, humour); the active one (``assistant.personality``) is inserted where the instructions
say ``{personality}``, or appended when they do not.

A personality is a Markdown file with a short YAML header::

    ---
    label: Calm
    description: Warm, steady and unhurried
    ---
    You are calm, warm and unhurried, ...

Shipped personalities live in ``config/personalities/`` and are never written to. The owner's
own ones, and edited copies of shipped ones (same id, so the copy wins), live in
``assistant.personalities_dir`` (default ``<repo>/personalities``, git-ignored). Deleting such a
copy restores the shipped original.
"""
from __future__ import annotations

import datetime as dt
import logging
import platform
import re
import socket
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from .config import REPO_ROOT

log = logging.getLogger(__name__)

SHIPPED_DIR = REPO_ROOT / "config" / "personalities"
DEFAULT = "calm"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
FIELDS = ("name", "other_name", "voice_gender", "user_name", "date", "hostname", "os")
FALLBACK_INSTRUCTIONS = "You are {name}, a helpful local voice assistant.\n\n{personality}"


@dataclass
class Personality:
    id: str
    label: str
    description: str
    text: str
    shipped: bool         # one that comes with Alveus
    edited: bool          # the owner's copy overrides the shipped one
    path: str
    order: float = 100

    def as_dict(self) -> dict:
        return asdict(self)


def own_dir(cfg) -> Path:
    d = cfg.assistant.get("personalities_dir") if cfg is not None else None
    return Path(d).expanduser() if d else REPO_ROOT / "personalities"


def parse(raw: str) -> tuple[dict, str]:
    """Split a personality file into its header and its text."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", raw, re.S)
    if not m:
        return {}, raw.strip()
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), raw[m.end():].strip()


def render(meta: dict, text: str) -> str:
    head = yaml.safe_dump({k: v for k, v in meta.items() if v not in (None, "")}, sort_keys=False,
                          allow_unicode=True, width=1000).strip()
    return f"---\n{head}\n---\n{text.strip()}\n"


def _read(path: Path, shipped: bool, edited: bool) -> Personality:
    meta, text = parse(path.read_text(errors="replace"))
    return Personality(id=path.stem, label=str(meta.get("label") or path.stem.replace("_", " ").title()),
                       description=str(meta.get("description") or ""), text=text, shipped=shipped,
                       edited=edited, path=str(path), order=float(meta.get("order", 100)))


def load_all(cfg) -> dict[str, Personality]:
    """Every personality by id: the shipped ones first (in their order), then the owner's own."""
    shipped = {p.stem: p for p in sorted(SHIPPED_DIR.glob("*.md")) if ID_RE.match(p.stem)}
    own_d = own_dir(cfg)
    own = {p.stem: p for p in sorted(own_d.glob("*.md")) if ID_RE.match(p.stem)} if own_d.is_dir() else {}
    out: dict[str, Personality] = {}
    for pid, path in shipped.items():
        try:
            out[pid] = _read(own.get(pid, path), shipped=True, edited=pid in own)
        except OSError as e:
            log.warning("personality %s unreadable: %s", pid, e)
    extra = []
    for pid, path in own.items():
        if pid not in shipped:
            try:
                extra.append(_read(path, shipped=False, edited=False))
            except OSError as e:
                log.warning("personality %s unreadable: %s", pid, e)
    ordered = sorted(out.values(), key=lambda p: (p.order, p.label.lower()))
    ordered += sorted(extra, key=lambda p: p.label.lower())
    return {p.id: p for p in ordered}


def active(cfg) -> Personality | None:
    """The chosen personality; the default one when the choice no longer exists."""
    allp = load_all(cfg)
    want = str(cfg.assistant.get("personality") or DEFAULT)
    if want in allp:
        return allp[want]
    if want != DEFAULT:
        log.warning("personality %r not found; using %r", want, DEFAULT)
    return allp.get(DEFAULT) or next(iter(allp.values()), None)


def slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40].strip("-")
    return s or "personality"


def save(cfg, pid: str, label: str, description: str, text: str) -> Personality:
    """Write a personality into the owner's folder (for a shipped id: an edited copy)."""
    if not ID_RE.match(pid):
        raise ValueError("a personality id uses lowercase letters, digits, - and _ (at most 40)")
    if not text.strip():
        raise ValueError("the personality text is empty")
    d = own_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    shipped = SHIPPED_DIR / f"{pid}.md"
    order = parse(shipped.read_text())[0].get("order") if shipped.exists() else None
    (d / f"{pid}.md").write_text(render({"label": label.strip() or pid, "description": description.strip(),
                                         "order": order}, text))
    return load_all(cfg)[pid]


def remove(cfg, pid: str) -> str:
    """Delete the owner's file: 'deleted' for their own, 'restored' for an edited shipped one."""
    if not ID_RE.match(pid):
        raise ValueError("unknown personality")
    f = own_dir(cfg) / f"{pid}.md"
    if not f.exists():
        raise FileNotFoundError("only your own personalities and edited copies can be removed")
    f.unlink()
    return "restored" if (SHIPPED_DIR / f"{pid}.md").exists() else "deleted"


def instructions_path(cfg) -> Path:
    a = cfg.assistant
    p = a.get("instructions_file") or a.get("persona_file")   # persona_file: the name before 2026-11-07
    return Path(p).expanduser() if p else REPO_ROOT / "config" / "instructions.md"


def fill(template: str, values: dict[str, str]) -> str:
    """Replace the known {placeholders} only, so other braces in hand-written text are kept."""
    return re.sub(r"\{(" + "|".join(map(re.escape, values)) + r")\}", lambda m: values[m.group(1)], template)


def system_prompt(cfg, name: str, other_name: str, female: bool) -> str:
    """Instructions with the active personality, placeholders filled in."""
    p = instructions_path(cfg)
    try:
        instructions = p.read_text()
    except OSError:
        log.warning("instructions file %s not readable; using a one-line fallback", p)
        instructions = FALLBACK_INSTRUCTIONS
    pers = active(cfg)
    values = {
        "name": name, "other_name": other_name, "voice_gender": "female" if female else "male",
        "user_name": str(cfg.assistant.get("user_name") or "the user"),
        "date": dt.date.today().strftime("%A, %B %d, %Y"), "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
    }
    body = fill(pers.text, values) if pers else ""
    text = fill(instructions, values)
    if "{personality}" in text:
        text = text.replace("{personality}", body)
    elif body:
        text = text.rstrip() + "\n\n" + body
    return re.sub(r"\n{3,}", "\n\n", text).strip()
