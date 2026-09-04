"""System status & control MCP server (CPU/GPU/memory/disk, processes, services, power)."""
from __future__ import annotations

import datetime as dt
import os
import platform
import socket
import time

import psutil

from .common import FastMCP, annot, j, run

mcp = FastMCP("system")


def _gpus() -> list[dict]:
    try:
        import pynvml as nv

        nv.nvmlInit()
        out = []
        for i in range(nv.nvmlDeviceGetCount()):
            h = nv.nvmlDeviceGetHandleByIndex(i)
            mem = nv.nvmlDeviceGetMemoryInfo(h)
            util = nv.nvmlDeviceGetUtilizationRates(h)
            name = nv.nvmlDeviceGetName(h)
            name = name.decode() if isinstance(name, bytes) else name
            out.append({
                "index": i, "name": name,
                "temperature_c": nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU),
                "utilization_pct": util.gpu, "memory_used_mb": mem.used // 2**20, "memory_total_mb": mem.total // 2**20,
                "power_w": round(nv.nvmlDeviceGetPowerUsage(h) / 1000, 1),
            })
        nv.nvmlShutdown()
        return out
    except Exception as e:  # noqa: BLE001
        return [{"error": f"no NVIDIA GPU info: {e}"}]


@mcp.tool(annotations=annot(read_only=True))
def system_status() -> str:
    """Overall machine status: CPU, memory, disk, GPU, uptime, load."""
    vm, du = psutil.virtual_memory(), psutil.disk_usage("/")
    return j({
        "hostname": socket.gethostname(), "os": f"{platform.system()} {platform.release()}",
        "time": dt.datetime.now().isoformat(timespec="seconds"),
        "uptime_h": round((time.time() - psutil.boot_time()) / 3600, 1),
        "cpu_pct": psutil.cpu_percent(interval=0.3), "load_avg": os.getloadavg(),
        "cpu_temp_c": _cpu_temp(),
        "memory": {"used_gb": round(vm.used / 2**30, 1), "total_gb": round(vm.total / 2**30, 1), "pct": vm.percent},
        "disk_root": {"used_gb": round(du.used / 2**30), "total_gb": round(du.total / 2**30), "pct": du.percent},
        "gpus": _gpus(),
        "battery": _battery(),
    })


def _cpu_temp():
    try:
        temps = psutil.sensors_temperatures()
        for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            if temps.get(key):
                return round(max(t.current for t in temps[key]), 1)
    except Exception:  # noqa: BLE001
        pass
    return None


def _battery():
    try:
        b = psutil.sensors_battery()
        return None if b is None else {"pct": b.percent, "plugged": b.power_plugged}
    except Exception:  # noqa: BLE001
        return None


@mcp.tool(annotations=annot(read_only=True))
def gpu_status() -> str:
    """GPU name, temperature, utilization, memory and power."""
    return j(_gpus())


@mcp.tool(annotations=annot(read_only=True))
def top_processes(sort_by: str = "cpu", limit: int = 10) -> str:
    """List the heaviest processes by 'cpu' or 'memory'."""
    procs = []
    for p in psutil.process_iter(["pid", "name", "username", "memory_info"]):
        try:
            procs.append(p)
            p.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    time.sleep(0.4)
    rows = []
    for p in procs:
        try:
            rows.append({"pid": p.pid, "name": p.info["name"], "user": p.info["username"],
                         "cpu_pct": p.cpu_percent(None), "mem_mb": round(p.info["memory_info"].rss / 2**20)})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    key = "cpu_pct" if sort_by == "cpu" else "mem_mb"
    rows.sort(key=lambda r: r[key], reverse=True)
    return j(rows[:limit])


@mcp.tool(annotations=annot(read_only=True))
def find_process(name: str) -> str:
    """Find running processes whose name or command line contains `name`."""
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
            if name.lower() in (p.info["name"] or "").lower() or name.lower() in cl.lower():
                out.append({"pid": p.pid, "name": p.info["name"], "cmdline": cl[:160]})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return j(out[:50])


@mcp.tool(annotations=annot(destructive=True))
def kill_process(pid: int, force: bool = False) -> str:
    """Terminate a process by PID (SIGTERM, or SIGKILL if force)."""
    try:
        p = psutil.Process(pid)
        name = p.name()
        (p.kill if force else p.terminate)()
        return j({"killed": pid, "name": name})
    except Exception as e:  # noqa: BLE001
        return j({"error": str(e)})


@mcp.tool(annotations=annot(read_only=True))
def list_services(scope: str = "user", state: str = "running") -> str:
    """List systemd services. scope: 'user' or 'system'; state: running|failed|all."""
    cmd = ["systemctl"] + (["--user"] if scope == "user" else []) + ["list-units", "--type=service", "--no-pager", "--plain", "--no-legend"]
    if state != "all":
        cmd.append(f"--state={state}")
    return j(run(cmd))


@mcp.tool(annotations=annot(destructive=True))
def control_service(name: str, action: str, scope: str = "user") -> str:
    """start | stop | restart | enable | disable a systemd service (user scope by default)."""
    if action not in ("start", "stop", "restart", "enable", "disable", "status"):
        return j({"error": "bad action"})
    cmd = ["systemctl"] + (["--user"] if scope == "user" else []) + [action, name, "--no-pager"]
    return j(run(cmd))


@mcp.tool(annotations=annot(read_only=True))
def network_info() -> str:
    """IP addresses, default interface and basic connectivity check."""
    addrs = {}
    for iface, lst in psutil.net_if_addrs().items():
        v4 = [a.address for a in lst if a.family == socket.AF_INET and not a.address.startswith("127.")]
        if v4:
            addrs[iface] = v4
    ping = run(["ping", "-c", "1", "-W", "2", "1.1.1.1"], timeout=5)
    return j({"interfaces": addrs, "internet": ping.get("exit_code") == 0})


@mcp.tool(annotations=annot(destructive=True))
def power(action: str) -> str:
    """Power action: suspend | hibernate | reboot | poweroff | lock. Always confirmed with the user first."""
    if action == "lock":
        return j(run(["loginctl", "lock-session"]))
    if action not in ("suspend", "hibernate", "reboot", "poweroff"):
        return j({"error": "bad action"})
    return j(run(["systemctl", action]))


if __name__ == "__main__":
    mcp.run()
