"""Image MCP server: makes and redraws pictures by running exported ComfyUI workflows.

Two workflows, each an API-format export from the ComfyUI GUI (Workflow -> Export (API)):
  ALVEUS_COMFY_GENERATE  text to image (default: Z-Image Turbo)
  ALVEUS_COMFY_EDIT      image to image (default: Z-Image Turbo with the Fun ControlNet Union, Canny)
The parameters are put into the graph by what the nodes are, not by their ids, so another export
(SDXL, Qwen-Image ...) works as long as it uses the usual nodes: the prompt goes into the text
encoder feeding the sampler's positive input, the seed and steps into the sampler, the size into
the empty latent, the picture into LoadImage, the strength into the ControlNet (or the sampler's
denoise when there is none). Save nodes become preview nodes, so ComfyUI's own output folder only
holds what its GUI made; the result is copied into ALVEUS_IMAGES_DIR.

Other settings: ALVEUS_COMFY_URL (http://127.0.0.1:8188) and ALVEUS_COMFY_UNLOAD_AFTER_S: ComfyUI
unloads its models after that many idle seconds (default 120), so the GPU is free again for speech
and the language model while a series of edits stays fast; 0 = right after each picture, -1 = never.
"""
from __future__ import annotations

import asyncio
import atexit
import copy
import datetime as dt
import io
import json
import logging
import os
import random
import re
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .common import FastMCP, annot, j

mcp = FastMCP("images")
logging.getLogger("httpx").setLevel(logging.WARNING)      # not one line per poll in the journal
HOME = os.environ.get("ALVEUS_HOME", str(Path(__file__).resolve().parents[1]))
URL = os.environ.get("ALVEUS_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
IMAGES = Path(os.path.expanduser(os.environ.get("ALVEUS_IMAGES_DIR", "~/local/data/alveus-ai/images")))
GENERATE = os.environ.get("ALVEUS_COMFY_GENERATE", f"{HOME}/config/comfy/txt2img_z_image_turbo_demo.json")
EDIT = os.environ.get("ALVEUS_COMFY_EDIT",
                      f"{HOME}/config/comfy/img2img_z_image_turbo_fun_union_controlnet_demo.json")
UNLOAD_AFTER_S = float(os.environ.get("ALVEUS_COMFY_UNLOAD_AFTER_S", "120") or -1)
TIMEOUT_S = float(os.environ.get("ALVEUS_COMFY_TIMEOUT_S", "540"))
EXTS = (".png", ".jpg", ".jpeg", ".webp")

SAMPLERS = ("KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced")
CONTROL = ("QwenImageDiffsynthControlnet", "ControlNetApply", "ControlNetApplyAdvanced", "ControlNetApplySD3")


# ------------------------------------------------------------------ the graph
def load_workflow(path: str) -> dict[str, Any]:
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = Path(HOME) / p
    wf = json.loads(p.read_text())
    if "nodes" in wf and "links" in wf:
        raise ValueError(f"{p.name} is a GUI workflow; export it with Workflow -> Export (API)")
    return wf


def _of(wf: dict[str, Any], classes: tuple[str, ...]) -> list[str]:
    return [k for k, n in wf.items() if n.get("class_type") in classes]


def _is_link(v: Any) -> bool:
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)


def prompt_nodes(wf: dict[str, Any]) -> list[str]:
    """Text encoders that feed a sampler's positive input (followed through ControlNet nodes)."""
    found: list[str] = []
    for s in _of(wf, SAMPLERS):
        todo = [wf[s]["inputs"].get("positive")]
        seen = set()
        while todo:
            link = todo.pop()
            if not _is_link(link) or link[0] in seen or link[0] not in wf:
                continue
            seen.add(link[0])
            ins = wf[link[0]]["inputs"]
            if "text" in ins:
                found.append(link[0])
            else:
                todo += [ins.get(k) for k in ("positive", "conditioning", "conditioning_to", "conditioning_1")]
    return list(dict.fromkeys(found))


def prepare(wf: dict[str, Any], *, prompt: str, seed: int, steps: int | None = None,
            width: int | None = None, height: int | None = None, image: str | None = None,
            strength: float | None = None) -> tuple[dict[str, Any], list[str]]:
    """A copy of the workflow with the parameters filled in, and the ids of the nodes whose pictures
    are the result."""
    wf = copy.deepcopy(wf)
    texts = prompt_nodes(wf)
    if not texts:
        raise ValueError("the workflow has no text prompt feeding a sampler")
    for t in texts:
        wf[t]["inputs"]["text"] = prompt
    samplers = _of(wf, SAMPLERS)
    for s in samplers:
        ins = wf[s]["inputs"]
        for k in ("seed", "noise_seed"):
            if k in ins and not _is_link(ins[k]):
                ins[k] = seed
        if steps and wf[s]["class_type"] == "KSampler" and not _is_link(ins.get("steps")):
            ins["steps"] = steps
    for n in wf.values():
        ins = n["inputs"]
        if n["class_type"].startswith("Empty") and "Latent" in n["class_type"]:
            if width and isinstance(ins.get("width"), int):
                ins["width"] = width
            if height and isinstance(ins.get("height"), int):
                ins["height"] = height
    if image is not None:
        loads = _of(wf, ("LoadImage",))
        if not loads:
            raise ValueError("the editing workflow has no Load Image node")
        for k in loads:
            wf[k]["inputs"]["image"] = image
    if strength is not None:
        control = _of(wf, CONTROL)
        for k in control:
            wf[k]["inputs"]["strength"] = strength
        if not control:   # plain image-to-image (latent from VAEEncode): strength = how much is redrawn
            for s in samplers:
                lat = wf[s]["inputs"].get("latent_image")
                if "denoise" in wf[s]["inputs"] and _is_link(lat) and \
                        wf.get(lat[0], {}).get("class_type", "").startswith("VAEEncode"):
                    wf[s]["inputs"]["denoise"] = strength
    # the result comes back as a preview (ComfyUI's temp folder), other previews are dropped
    for k in _of(wf, ("PreviewImage",)):
        del wf[k]
    outs = _of(wf, ("SaveImage",))
    for k in outs:
        wf[k] = {"class_type": "PreviewImage", "inputs": {"images": wf[k]["inputs"]["images"]},
                 "_meta": {"title": "Alveus result"}}
    if not outs:
        raise ValueError("the workflow has no Save Image node")
    return wf, outs


# ------------------------------------------------------------------ files
def slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n].rstrip("-")


def out_name(prompt: str, kind: str = "") -> str:
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    parts = [stamp, kind, slug(prompt)]
    return "_".join(p for p in parts if p) + ".png"


def recent(limit: int = 10) -> list[Path]:
    if not IMAGES.is_dir():
        return []
    files = [p for p in IMAGES.iterdir() if p.suffix.lower() in EXTS and p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def resolve_input(image: str) -> Path:
    """'' / 'last' -> the newest picture in the image folder; a bare name -> that file in the folder;
    otherwise a path."""
    s = (image or "").strip()
    if s.lower() in ("", "last", "latest", "newest", "previous"):
        r = recent(1)
        if not r:
            raise FileNotFoundError(f"no pictures in {IMAGES} yet; name a file to edit")
        return r[0]
    p = Path(os.path.expanduser(s))
    if not p.is_absolute() and not p.exists():
        p = IMAGES / s
    if not p.is_file():
        raise FileNotFoundError(f"no such picture: {s}")
    return p


def fit(w: int, h: int, side: int) -> tuple[int, int]:
    """Scale so the long side is ``side``, both sides multiples of 16."""
    k = side / max(w, h)
    return max(16, round(w * k / 16) * 16), max(16, round(h * k / 16) * 16)


def input_png(path: Path, side: int) -> tuple[bytes, int, int]:
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = fit(*im.size, side)
        im = im.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
    return buf.getvalue(), w, h


def url_for(name: str) -> str:
    return f"/images/file?name={name}"


# ------------------------------------------------------------------ ComfyUI
def _node_errors(body: dict[str, Any], wf: dict[str, Any]) -> str:
    msgs = []
    for nid, e in (body.get("node_errors") or {}).items():
        title = (wf.get(nid, {}).get("_meta") or {}).get("title") or e.get("class_type") or nid
        for x in e.get("errors") or []:
            msgs.append(f"{title}: {x.get('details') or x.get('message')}")
    err = body.get("error") or {}
    return "; ".join(msgs)[:1200] or (err.get("message") if isinstance(err, dict) else str(err)) or str(body)[:600]


async def run_workflow(c: httpx.AsyncClient, wf: dict[str, Any], outs: list[str]) -> bytes:
    r = await c.post("/prompt", json={"prompt": wf, "client_id": f"alveus-{uuid.uuid4().hex[:8]}"})
    if r.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected the workflow: {_node_errors(r.json(), wf)}")
    pid = r.json()["prompt_id"]
    deadline = time.monotonic() + TIMEOUT_S
    while True:
        h = (await c.get(f"/history/{pid}")).json().get(pid)
        if h:
            st = h.get("status") or {}
            if st.get("status_str") == "error":
                why = [m[1].get("exception_message", "") for m in st.get("messages", []) if m[0] == "execution_error"]
                raise RuntimeError(f"ComfyUI failed: {'; '.join(w.strip() for w in why) or 'see its log'}")
            if st.get("completed", True):
                break
        if time.monotonic() > deadline:
            await c.post("/interrupt")
            raise TimeoutError(f"no picture after {TIMEOUT_S:.0f} s; the job was stopped")
        await asyncio.sleep(0.4)
    for k in outs:
        for img in (h.get("outputs", {}).get(k) or {}).get("images", []):
            v = await c.get("/view", params={"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                                             "type": img.get("type", "temp")})
            v.raise_for_status()
            return v.content
    raise RuntimeError("ComfyUI finished without a picture")


async def render(wf: dict[str, Any], outs: list[str], name: str, upload: bytes | None = None,
                 upload_name: str = "") -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(base_url=URL, timeout=60) as c:
            if upload is not None:
                r = await c.post("/upload/image", files={"image": (upload_name, upload, "image/png")},
                                 data={"type": "input", "subfolder": "alveus", "overwrite": "true"})
                r.raise_for_status()
            _cancel_unload()
            try:
                png = await run_workflow(c, wf, outs)
            finally:
                _schedule_unload()
    except httpx.ConnectError:
        raise RuntimeError(f"ComfyUI is not running at {URL} (start it: systemctl --user start comfyui)") from None
    IMAGES.mkdir(parents=True, exist_ok=True)
    path = IMAGES / name
    path.write_bytes(png)
    return {"image": str(path), "image_url": url_for(name), "seconds": round(time.monotonic() - t0, 1),
            "shown": "The picture is on screen in the chat window. Say what you made in a few words; "
                     "do not read out the file name."}


_unload_task: asyncio.Task | None = None
_unload_pending = False         # models loaded by us and not unloaded yet (the task dies with the loop)


def _cancel_unload() -> None:
    if _unload_task and not _unload_task.done():
        _unload_task.cancel()


async def _unload(delay: float) -> None:
    global _unload_pending
    await asyncio.sleep(delay)
    try:
        async with httpx.AsyncClient(base_url=URL, timeout=10) as c:
            await c.post("/free", json={"unload_models": True, "free_memory": True})
        _unload_pending = False
    except httpx.HTTPError:
        pass


def _schedule_unload() -> None:
    global _unload_task, _unload_pending
    _cancel_unload()
    if UNLOAD_AFTER_S >= 0:
        _unload_pending = True
        _unload_task = asyncio.get_running_loop().create_task(_unload(UNLOAD_AFTER_S))


@atexit.register
def _unload_on_exit() -> None:
    """Alveus stopped before the idle delay ran out: unload now rather than leave ComfyUI holding memory."""
    global _unload_pending
    if _unload_pending:
        _unload_pending = False
        try:
            httpx.post(f"{URL}/free", json={"unload_models": True, "free_memory": True}, timeout=5)
        except httpx.HTTPError:
            pass


def _seed(seed: int) -> int:
    return seed if seed is not None and seed >= 0 else random.randrange(2**50)


# ------------------------------------------------------------------ tools
@mcp.tool()
async def generate_image(prompt: str, width: int = 1024, height: int = 1024, seed: int = -1,
                         steps: int = 0) -> str:
    """Make a new picture from a description and save it (it shows in the chat window).
    prompt: a detailed description in English or Chinese: subject, setting, style, lighting,
      composition; write out any text that should appear in the picture in quotes.
    width, height: pixels, multiples of 16; 1024x1024 square, 1344x768 landscape, 768x1344 portrait.
    seed: -1 = random; reuse a returned seed to make the same picture again with small changes.
    steps: 0 = the workflow's own (8)."""
    wf = load_workflow(GENERATE)
    w, h = fit(width, height, max(256, min(2048, max(width, height))))
    s = _seed(seed)
    wf, outs = prepare(wf, prompt=prompt, seed=s, steps=steps or None, width=w, height=h)
    res = await render(wf, outs, out_name(prompt))
    return j({**res, "width": w, "height": h, "seed": s, "prompt": prompt})


@mcp.tool()
async def edit_image(prompt: str, image: str = "", strength: float = 0.75, size: int = 1024,
                     seed: int = -1) -> str:
    """Redraw an existing picture: it keeps the outlines (composition, shapes, poses, edges) and
    repaints everything else from the prompt, e.g. another style, colours, materials, season,
    lighting or a different person in the same pose. It cannot erase or add single objects.
    prompt: describe the whole result, not the change ("watercolour painting of a red fox in snow").
    image: a file path, a picture's name in the image folder, or "" for the newest picture made.
    strength: how closely the outlines are followed, 0.3 loose .. 1.0 strict.
    size: long side of the result in pixels."""
    src = resolve_input(image)
    png, w, h = input_png(src, max(256, min(2048, size)))
    s = _seed(seed)
    upload = "input.png"          # overwritten each time; ComfyUI notices the new contents
    wf, outs = prepare(load_workflow(EDIT), prompt=prompt, seed=s, image=f"alveus/{upload}",
                       strength=max(0.0, min(1.0, strength)))
    res = await render(wf, outs, out_name(prompt, "edit"), upload=png, upload_name=upload)
    return j({**res, "source": str(src), "width": w, "height": h, "seed": s, "prompt": prompt})


@mcp.tool(annotations=annot(read_only=True))
def recent_images(limit: int = 10) -> str:
    """The newest pictures in the image folder (name, path, when made), newest first."""
    rows = [{"name": p.name, "path": str(p), "image_url": url_for(p.name),
             "made": dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")}
            for p in recent(max(1, min(50, limit)))]
    return j({"folder": str(IMAGES), "images": rows})


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))       # so the unload above still runs
    mcp.run()
