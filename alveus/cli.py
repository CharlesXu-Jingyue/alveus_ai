"""Alveus command-line interface."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .config import REPO_ROOT, llm_profile, load_config

app = typer.Typer(help="Alveus - local voice AI assistant", no_args_is_help=True, add_completion=False)
llm_app = typer.Typer(help="LLM server & profiles")
tts_app = typer.Typer(help="Text-to-speech utilities")
stt_app = typer.Typer(help="Speech-to-text utilities")
app.add_typer(llm_app, name="llm")
app.add_typer(tts_app, name="tts")
app.add_typer(stt_app, name="stt")
console = Console()


def _setup_logging(cfg, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else getattr(logging, str(cfg.logging.get("level", "INFO")).upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s", datefmt="[%X]",
                        handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=False)])
    for noisy in ("httpx", "httpcore", "openai", "urllib3", "numba", "faster_whisper", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    log_dir = cfg.logging.get("dir")
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(Path(log_dir) / "alveus.log")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(fh)


# ------------------------------------------------------------------------------ talk
@app.command()
def talk(verbose: bool = typer.Option(False, "-v", "--verbose"), no_api: bool = False,
         profile: str = typer.Option(None, help="LLM profile override")):
    """Run the full voice assistant (wake word / hotkey -> listen -> answer)."""
    if profile:
        os.environ["ALVEUS_LLM_PROFILE"] = profile
    cfg = load_config()
    _setup_logging(cfg, verbose)
    from .api import EventBus
    from .voice import VoiceAssistant

    bus = EventBus()

    def on_state(s):
        console.print(f"[dim]{time.strftime('%H:%M:%S')}[/dim] [bold cyan]{s.value}[/bold cyan]")
        bus.publish("state", state=s.value)

    def on_transcript(who, text):
        color = "green" if who == "user" else "magenta"
        console.print(f"[{color}]{who}:[/{color}] {text}")
        bus.publish("transcript", who=who, text=text, source="voice")

    va = VoiceAssistant(cfg, on_state=on_state, on_transcript=on_transcript)

    async def main():
        tasks = [asyncio.create_task(va.run_forever())]
        if cfg.api.get("enabled", True) and not no_api:
            from .api import build_app, serve
            host, port = cfg.api.get("host", "127.0.0.1"), int(cfg.api.get("port", 8765))
            console.print(f"[dim]GUI + API at http://{host}:{port}/[/dim]")
            tasks.append(asyncio.create_task(serve(build_app(va, bus), host, port)))
        try:
            await asyncio.gather(*tasks)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await va.close()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[dim]bye[/dim]")


# ------------------------------------------------------------------------------ chat (text)
@app.command()
def chat(verbose: bool = typer.Option(False, "-v", "--verbose"), no_tools: bool = False,
         speak: bool = typer.Option(False, help="Also speak replies"),
         profile: str = typer.Option(None, help="LLM profile override"),
         show_thinking: bool = typer.Option(False, help="Print the model's reasoning stream")):
    """Text REPL with the same agent and tools (no microphone)."""
    if profile:
        os.environ["ALVEUS_LLM_PROFILE"] = profile
    cfg = load_config()
    _setup_logging(cfg, verbose)
    from .api import HeadlessAssistant

    async def confirm(desc: str) -> bool:
        return typer.confirm(f"Alveus wants to {desc}. Allow?", default=False)

    async def main():
        ha = HeadlessAssistant(cfg, load_speech=speak)
        if no_tools:
            ha.cfg["tools"]["servers"] = {}
        await ha.start(confirm=confirm)
        if ha.hub and ha.hub.errors:
            for k, v in ha.hub.errors.items():
                console.print(f"[yellow]tool server '{k}' failed:[/yellow] {v}")
        ok, msg = await ha.llm.health()
        console.print(f"[bold]{cfg.assistant.name}[/bold] · LLM {'[green]ok[/green]' if ok else '[red]DOWN[/red]'} ({msg}) · "
                      f"{len(ha.hub.tools) if ha.hub else 0} tools. Type /reset, /tools or /quit.")
        if speak:
            from .audio import make_audio_out
            out = make_audio_out(cfg)
        while True:
            try:
                text = console.input("[green]you>[/green] ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                continue
            if text in ("/quit", "/exit"):
                break
            if text == "/reset":
                ha.agent.reset()
                console.print("[dim]history cleared[/dim]")
                continue
            if text == "/tools":
                for t in ha.hub.tools.values():
                    console.print(f"  [cyan]{t.full_name}[/cyan]{' [red]![/red]' if t.destructive else ''} - {t.description.splitlines()[0][:90]}")
                continue
            reply_parts = []
            t0 = time.time()
            console.print("[magenta]alveus>[/magenta] ", end="")
            async for ev in ha.agent.run(text):
                if ev.kind == "content":
                    reply_parts.append(ev.text)
                    console.print(ev.text, end="", highlight=False, markup=False)
                elif ev.kind == "reasoning" and show_thinking:
                    console.print(f"[dim]{ev.text}[/dim]", end="", highlight=False, markup=False)
                elif ev.kind == "tool_result":
                    console.print(f"\n  [dim]⚙ {ev.tool} → {ev.text[:140].replace(chr(10), ' ')}[/dim]", highlight=False, markup=False)
                elif ev.kind == "error":
                    console.print(f"\n[red]{ev.text}[/red]")
            console.print(f"\n[dim]({time.time() - t0:.1f}s)[/dim]")
            if speak and reply_parts:
                from .agent.sentences import speakable
                out.play(ha.tts.synthesize(speakable("".join(reply_parts))), ha.tts.sample_rate)
        await ha.close()

    asyncio.run(main())


# ------------------------------------------------------------------------------ api
@app.command()
def api(verbose: bool = typer.Option(False, "-v", "--verbose")):
    """Run only the HTTP API (chat / transcribe / speak) without the microphone loop."""
    cfg = load_config()
    _setup_logging(cfg, verbose)
    from .api import HeadlessAssistant, build_app, serve

    async def main():
        ha = HeadlessAssistant(cfg)
        await ha.start()
        console.print(f"GUI + API at http://{cfg.api.get('host')}:{cfg.api.get('port')}/  (API docs at /docs)")
        await serve(build_app(ha), cfg.api.get("host", "127.0.0.1"), int(cfg.api.get("port", 8765)))

    asyncio.run(main())


@app.command()
def trigger(port: int = None):
    """Tell a running `alveus talk` to start listening (bind this to a desktop shortcut)."""
    import httpx

    cfg = load_config()
    port = port or int(cfg.api.get("port", 8765))
    try:
        httpx.post(f"http://127.0.0.1:{port}/trigger", timeout=2)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]alveus is not running ({e})[/red]")
        raise typer.Exit(1)


@app.command()
def ui(port: int = None):
    """Open the browser GUI of the running assistant (or tell you how to start it)."""
    import webbrowser

    import httpx

    cfg = load_config()
    url = f"http://{cfg.api.get('host', '127.0.0.1')}:{port or int(cfg.api.get('port', 8765))}/"
    try:
        httpx.get(url + "health", timeout=2)
    except Exception:  # noqa: BLE001
        console.print(f"[yellow]Nothing is listening at {url}[/yellow]. Start the assistant first:\n"
                      "  systemctl --user start alveus     (voice + GUI)\n"
                      "  alveus talk                       (voice + GUI, foreground)\n"
                      "  alveus api                        (GUI only, no microphone)")
        raise typer.Exit(1)
    console.print(f"opening {url}")
    webbrowser.open(url)


@app.command()
def handbook(rebuild: bool = typer.Option(False, help="regenerate docs/handbook.html from docs/*.md first")):
    """Open the offline documentation (docs/handbook.html) in the browser."""
    import webbrowser

    path = REPO_ROOT / "docs" / "handbook.html"
    if rebuild or not path.exists():
        subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build_handbook.py")], check=True)
    console.print(f"opening {path}")
    webbrowser.open(path.as_uri())


@app.command()
def say(text: str, play: bool = True):
    """Speak text through a running `alveus talk` instance (or synthesize locally if none)."""
    import httpx

    cfg = load_config()
    try:
        httpx.post(f"http://127.0.0.1:{int(cfg.api.get('port', 8765))}/speak", json={"text": text, "play": play}, timeout=60)
    except Exception:  # noqa: BLE001
        tts_say(text)


# ------------------------------------------------------------------------------ tools / devices / doctor
@app.command()
def tools():
    """List tools exposed by all configured MCP servers."""
    cfg = load_config()
    _setup_logging(cfg)
    from .agent import ToolHub, hub_env

    async def main():
        async with ToolHub(cfg.tools.get("servers") or {}, cfg._env["ALVEUS_HOME"], env_extra=hub_env(cfg)) as hub:
            t = Table(title=f"{len(hub.tools)} tools")
            t.add_column("tool", style="cyan")
            t.add_column("destructive")
            t.add_column("description")
            for info in hub.tools.values():
                t.add_row(info.full_name, "yes" if info.destructive else "", info.description.splitlines()[0][:80])
            console.print(t)
            for k, v in hub.errors.items():
                console.print(f"[red]server '{k}' failed:[/red] {v}")

    asyncio.run(main())


@app.command()
def devices():
    """Show audio devices for the active audio backend."""
    from .audio import list_devices

    console.print(list_devices(load_config()))


@app.command()
def doctor(warm: bool = typer.Option(False, help="Also load STT/TTS/wake-word models")):
    """Check hardware, servers, models and dependencies."""
    cfg = load_config()
    env = cfg._env
    rows: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        rows.append((name, bool(ok), detail))

    # GPU
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,driver_version",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=10).stdout.strip()
        check("GPU", bool(out), out)
    except Exception as e:  # noqa: BLE001
        check("GPU", False, str(e))
    try:
        import torch
        check("torch CUDA", torch.cuda.is_available(), f"torch {torch.__version__}")
    except Exception as e:  # noqa: BLE001
        check("torch CUDA", False, str(e))
    # audio
    from .audio.backend import pick_backend
    b = pick_backend(cfg.audio.get("backend"))
    check("audio backend", b == "sounddevice" or (shutil.which("pw-record") is not None), b)
    # LLM
    try:
        prof = llm_profile(cfg)
        serve = prof.get("serve") or {}
        mp = serve.get("model_path")
        check(f"LLM weights ({prof.name})", mp and Path(mp).exists(), mp or "no serve.model_path")
        cmd = serve.get("command") or "llama-server"
        check("llama-server binary", Path(os.path.expanduser(cmd)).exists() or shutil.which(cmd) is not None, cmd)
        from .llm import make_llm
        ok, msg = asyncio.run(make_llm(prof).health())
        check("LLM endpoint", ok, msg)
    except Exception as e:  # noqa: BLE001
        check("LLM profile", False, str(e))
    for name, mod in (("faster-whisper", "faster_whisper"), ("kokoro", "kokoro"), ("openwakeword", "openwakeword"),
                      ("silero-vad", "silero_vad"), ("mcp", "mcp"), ("parakeet (onnx-asr)", "onnx_asr"), ("chatterbox", "chatterbox")):
        try:
            __import__(mod)
            check(name, True, "installed")
        except Exception as e:  # noqa: BLE001
            check(name, False, f"not installed ({type(e).__name__})")
    for binname in ("opencode", "xdotool", "wmctrl", "xclip", "notify-send", "wpctl", "playerctl"):
        check(f"bin: {binname}", shutil.which(binname) is not None, shutil.which(binname) or "missing (optional)")
    if warm:
        from .stt import make_stt
        from .tts import make_tts
        for label, maker in (("STT load", make_stt), ("TTS load", make_tts)):
            try:
                t0 = time.time()
                obj = maker(cfg)
                obj.load()
                check(label, True, f"{obj.name} in {time.time() - t0:.1f}s")
            except Exception as e:  # noqa: BLE001
                check(label, False, f"{type(e).__name__}: {e}")
        try:
            from .audio.wakeword import WakeWord
            WakeWord(cfg.activation.wake_word.get("model", "hey_jarvis"), models_dir=f"{env['ALVEUS_MODELS']}/wakeword")
            check("wake word", True, cfg.activation.wake_word.get("model"))
        except Exception as e:  # noqa: BLE001
            check("wake word", False, str(e))

    t = Table(title="alveus doctor")
    t.add_column("check")
    t.add_column("status")
    t.add_column("detail")
    for name, ok, detail in rows:
        t.add_row(name, "[green]OK[/green]" if ok else "[red]FAIL[/red]", str(detail)[:100])
    console.print(t)
    console.print(f"[dim]ALVEUS_HOME={env['ALVEUS_HOME']}  ALVEUS_MODELS={env['ALVEUS_MODELS']}[/dim]")


# ------------------------------------------------------------------------------ llm
@llm_app.command("profiles")
def llm_profiles():
    """List LLM profiles."""
    cfg = load_config()
    t = Table(title=f"LLM profiles (default: {cfg.llm.profile})")
    for c in ("profile", "backend", "model", "base_url", "weights"):
        t.add_column(c)
    for name, p in (cfg.llm.get("profiles") or {}).items():
        mp = (p.get("serve") or {}).get("model_path", "")
        mark = "[green]✓[/green]" if mp and Path(mp).exists() else ("[red]missing[/red]" if mp else "-")
        t.add_row(name, p.get("backend"), p.get("model"), p.get("base_url"), f"{mark} {mp}")
    console.print(t)


@llm_app.command("serve")
def llm_serve(profile: str = typer.Option(None), host: str = "127.0.0.1", port: int = 8080,
              extra: str = typer.Option("", help="extra llama-server args")):
    """Launch the inference server for a profile (used by the systemd unit)."""
    cfg = load_config()
    prof = llm_profile(cfg, profile)
    serve = prof.get("serve")
    if not serve:
        console.print(f"profile {prof.name} has no 'serve' section (remote/external server?)")
        raise typer.Exit(1)
    cmd = [os.path.expanduser(serve["command"]), "-m", serve["model_path"], "--host", host, "--port", str(port),
           "--alias", prof["model"], *serve.get("args", []), *(extra.split() if extra else [])]
    console.print("[dim]" + " ".join(cmd) + "[/dim]")
    os.execvp(cmd[0], cmd)


@llm_app.command("test")
def llm_test(prompt: str = "Say hello in one sentence.", profile: str = typer.Option(None)):
    """Send a quick prompt to the active LLM."""
    cfg = load_config()
    prof = llm_profile(cfg, profile)
    from .llm import make_llm

    async def main():
        llm = make_llm(prof)
        t0 = time.time()
        n = 0
        async for ev in llm.stream([{"role": "user", "content": prompt}]):
            if ev.kind == "content":
                console.print(ev.text, end="", markup=False)
                n += 1
            elif ev.kind == "done":
                console.print(f"\n[dim]{ev.usage.get('completion_tokens', n)} tokens in {time.time() - t0:.1f}s[/dim]")

    asyncio.run(main())


# ------------------------------------------------------------------------------ tts / stt
@tts_app.command("say")
def tts_say(text: str, out: str = typer.Option(None, help="write wav instead of playing")):
    """Synthesize and play text with the configured TTS backend."""
    cfg = load_config()
    from .agent.sentences import speakable
    from .tts import make_tts

    tts = make_tts(cfg)
    tts.load()
    t0 = time.time()
    audio = tts.synthesize(speakable(text))
    console.print(f"[dim]{tts.name}: {len(audio) / tts.sample_rate:.1f}s audio in {time.time() - t0:.2f}s[/dim]")
    if out:
        import soundfile as sf
        sf.write(out, audio, tts.sample_rate)
        console.print(f"wrote {out}")
    else:
        from .audio import make_audio_out
        make_audio_out(cfg).play_blocking(audio, tts.sample_rate)


@tts_app.command("voices")
def tts_voices():
    cfg = load_config()
    from .tts import make_tts
    console.print("\n".join(make_tts(cfg).voices()))


@stt_app.command("test")
def stt_test(seconds: float = 5.0, file: str = typer.Option(None, help="transcribe a wav instead of recording")):
    """Record from the mic for N seconds (or read a wav) and print the transcript."""
    import numpy as np

    cfg = load_config()
    from .stt import make_stt

    stt = make_stt(cfg)
    stt.load()
    if file:
        import soundfile as sf
        audio, sr = sf.read(file, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
    else:
        from .audio import make_audio_in
        mic = make_audio_in(cfg)
        mic.start()
        console.print(f"[green]recording {seconds}s... speak now[/green]")
        frames = []
        t0 = time.time()
        while time.time() - t0 < seconds:
            f = mic.read(1.0)
            if f is not None:
                frames.append(f)
        mic.stop()
        audio, sr = np.concatenate(frames), 16000
        console.print(f"[dim]level rms={float(np.sqrt((audio**2).mean())):.4f}[/dim]")
    t0 = time.time()
    text = stt.transcribe(audio, sr)
    console.print(f"[bold]{text}[/bold]  [dim]({stt.name}, {time.time() - t0:.2f}s)[/dim]")


@app.command()
def wakeword_test(seconds: float = 15.0):
    """Listen and print wake-word scores so you can tune the threshold."""
    cfg = load_config()
    from .audio import make_audio_in
    from .audio.wakeword import WakeWord

    ww = WakeWord(cfg.activation.wake_word.get("model", "hey_jarvis"), models_dir=f"{cfg._env['ALVEUS_MODELS']}/wakeword")
    mic = make_audio_in(cfg)
    mic.start()
    console.print(f"say '{ww.model_name.replace('_', ' ')}' ... ({seconds}s)")
    t0 = time.time()
    while time.time() - t0 < seconds:
        f = mic.read(1.0)
        if f is None:
            continue
        s = ww.feed(f)
        if s > 0.1:
            console.print(f"score {s:.2f}" + ("  [green]DETECTED[/green]" if s >= ww.threshold else ""))
    mic.stop()


@app.command()
def version():
    from . import __version__
    console.print(f"alveus {__version__}  ({REPO_ROOT})")


if __name__ == "__main__":
    app()
