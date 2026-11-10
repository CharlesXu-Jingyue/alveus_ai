"""Image tools (mcp_servers/comfy.py): parameters land in the right nodes of the shipped workflows,
the result is fetched from a (fake) ComfyUI, input pictures are found, the GUI route serves them."""
import asyncio
import json
import os
from pathlib import Path

import httpx
import numpy as np
import pytest

from mcp_servers import comfy

ROOT = Path(__file__).resolve().parents[1] / "config" / "comfy"


def wf(name):
    return comfy.load_workflow(str(ROOT / name))


def test_text_to_image_fills_prompt_seed_size_and_previews():
    g, outs = comfy.prepare(wf("txt2img_z_image_turbo_demo.json"), prompt="a fox", seed=7, steps=6,
                            width=1344, height=768)
    assert g["27"]["inputs"]["text"] == "a fox"
    assert g["3"]["inputs"]["seed"] == 7 and g["3"]["inputs"]["steps"] == 6
    assert (g["13"]["inputs"]["width"], g["13"]["inputs"]["height"]) == (1344, 768)
    assert outs == ["9"] and g["9"]["class_type"] == "PreviewImage"   # not written to ComfyUI's output


def test_controlnet_edit_sets_image_and_strength_and_drops_the_edge_preview():
    g, outs = comfy.prepare(wf("img2img_z_image_turbo_fun_union_controlnet_demo.json"), prompt="watercolour",
                            seed=1, image="alveus/input.png", strength=0.5)
    assert g["45"]["inputs"]["text"] == "watercolour" and g["58"]["inputs"]["image"] == "alveus/input.png"
    assert g["60"]["inputs"]["strength"] == 0.5 and g["44"]["inputs"]["denoise"] == 1
    assert "56" not in g and outs == ["9"]


def test_other_exports_work_too_positive_prompt_only():
    g, _ = comfy.prepare(wf("txt2img_sdxl_base_refiner.json"), prompt="a bottle", seed=3)
    assert g["6"]["inputs"]["text"] == g["15"]["inputs"]["text"] == "a bottle"       # base and refiner
    assert g["7"]["inputs"]["text"] == "text, watermark"                           # negative untouched
    assert g["10"]["inputs"]["noise_seed"] == 3
    g, _ = comfy.prepare(wf("img2img_sdxl_demo.json"), prompt="a car", seed=3, strength=0.4)
    assert g["6"]["inputs"]["text"] == "a car"            # found through the unCLIP conditioning
    assert g["3"]["inputs"]["denoise"] == 1               # empty latent: strength is not a denoise there


def test_gui_export_is_refused(tmp_path):
    p = tmp_path / "gui.json"
    p.write_text(json.dumps({"nodes": [], "links": []}))
    with pytest.raises(ValueError, match="Export \\(API\\)"):
        comfy.load_workflow(str(p))


def test_sizes_and_names():
    assert comfy.fit(4000, 3000, 1024) == (1024, 768)
    assert comfy.fit(500, 333, 1024) == (1024, 688)
    assert comfy.slug("A Fox, in SNOW!") == "a-fox-in-snow" and comfy.slug("红狐狸") == ""
    assert comfy.out_name("红狐狸", "edit").endswith("_edit.png")


def test_input_pictures_are_found(tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(comfy, "IMAGES", tmp_path)
    with pytest.raises(FileNotFoundError, match="no pictures"):
        comfy.resolve_input("")
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    for i, p in enumerate((a, b)):
        Image.fromarray(np.zeros((30, 40, 3), np.uint8)).save(p)
        os.utime(p, (1000 + i, 1000 + i))
    assert comfy.resolve_input("last") == b and comfy.resolve_input("a.png") == a
    assert comfy.resolve_input(str(a)) == a
    with pytest.raises(FileNotFoundError):
        comfy.resolve_input("nope.png")
    png, w, h = comfy.input_png(a, 1024)
    assert (w, h) == (1024, 768) and png[:4] == b"\x89PNG"


def fake_comfy(fail=None):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/prompt":
            seen["prompt"] = json.loads(req.content)["prompt"]
            if fail == "nodes":
                return httpx.Response(400, json={"error": {"message": "Prompt outputs failed validation"},
                                                 "node_errors": {"28": {"class_type": "UNETLoader", "errors": [
                                                     {"message": "Value not in list", "details": "unet_name: 'x' not in []"}]}}})
            return httpx.Response(200, json={"prompt_id": "p1"})
        if req.url.path == "/history/p1":
            if fail == "run":
                return httpx.Response(200, json={"p1": {"status": {"status_str": "error", "completed": False, "messages": [
                    ["execution_error", {"exception_message": "CUDA out of memory"}]]}}})
            return httpx.Response(200, json={"p1": {"status": {"status_str": "success", "completed": True},
                                                    "outputs": {"9": {"images": [{"filename": "t.png", "subfolder": "", "type": "temp"}]}}}})
        if req.url.path == "/view":
            seen["view"] = dict(req.url.params)
            return httpx.Response(200, content=b"\x89PNG fake")
        return httpx.Response(404)
    return httpx.MockTransport(handler), seen


def test_run_workflow_fetches_the_preview_and_reports_errors():
    g, outs = comfy.prepare(wf("txt2img_z_image_turbo_demo.json"), prompt="x", seed=1)

    async def go(fail=None):
        transport, seen = fake_comfy(fail)
        async with httpx.AsyncClient(transport=transport, base_url="http://comfy") as c:
            return await comfy.run_workflow(c, g, outs), seen
    png, seen = asyncio.run(go())
    assert png.startswith(b"\x89PNG") and seen["view"]["type"] == "temp" and seen["prompt"]["27"]["inputs"]["text"] == "x"
    with pytest.raises(RuntimeError, match="Load Diffusion Model: unet_name"):
        asyncio.run(go("nodes"))
    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        asyncio.run(go("run"))


def test_gui_serves_only_pictures_in_the_folder(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from alveus import api
    from alveus.config import load_config
    (tmp_path / "x.png").write_bytes(b"\x89PNG fake")
    (tmp_path / "notes.txt").write_text("secret")
    cfg = load_config()
    cfg["tools"]["servers"]["images"]["env"]["ALVEUS_IMAGES_DIR"] = str(tmp_path)
    monkeypatch.setattr(api, "load_config", lambda: cfg)
    a = type("A", (), {})()
    a.cfg, a.agent, a.stt, a.tts = cfg, None, None, None
    c = TestClient(api.build_app(a))
    assert c.get("/images/file", params={"name": "x.png"}).content == b"\x89PNG fake"
    for bad in ("notes.txt", "../x.png", "missing.png", str(tmp_path / "x.png")):
        assert c.get("/images/file", params={"name": bad}).status_code == 404


def test_header_stop_interrupts_while_a_tool_runs():
    from fastapi.testclient import TestClient

    from alveus.api import build_app
    from alveus.config import load_config

    class Agent:
        tool_running = "images__generate_image"
        stopped = 0
        lock = asyncio.Lock()

        def interrupt(self):
            Agent.stopped += 1
    a = type("A", (), {})()
    a.cfg, a.agent, a.stt, a.tts = load_config(), Agent(), None, None
    c = TestClient(build_app(a))
    assert c.post("/stop").json() == {"interrupted": True} and Agent.stopped == 1
    Agent.tool_running = None                       # nothing running: Stop only cuts speech, as before
    assert c.post("/stop").json() == {"stopped": True} and Agent.stopped == 1
