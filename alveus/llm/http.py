"""Plain-httpx helpers shared by the OpenAI-protocol adapters (no vendor SDK: see troubleshooting,
the openai SDK + httpx2 streaming misbehaves at close)."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from .base import LLMError

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))


def error_text(body: str) -> str:
    """The human part of an error body ({"error": {"message": ...}} and similar)."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body.strip()[:300]
    err = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(err, dict):
        return str(err.get("message") or err.get("msg") or err)[:300]
    return str(err)[:300]


def http_error(label: str, status: int, body: str) -> LLMError:
    detail = error_text(body)
    what = {401: "rejected the API key", 403: "refused access (check the key's permissions)",
            402: "says the account has no credit left", 404: "does not know this model or address",
            429: "is rate limiting us or the quota is used up"}.get(status, f"returned HTTP {status}")
    return LLMError(f"{label} {what}" + (f": {detail}" if detail else ""))


def _delay(resp: httpx.Response | None, attempt: int) -> float:
    if resp is not None:
        ra = resp.headers.get("retry-after")
        try:
            if ra is not None:
                return min(float(ra), 20.0)
        except ValueError:
            pass
    return min(1.0 * 2 ** attempt, 8.0)


@asynccontextmanager
async def open_stream(client: httpx.AsyncClient, url: str, body: dict[str, Any], headers: dict[str, str],
                      label: str, retries: int = 2):
    """POST and yield the streaming response; retries connection failures and 429/5xx before any
    output arrived, and turns HTTP errors into a short LLMError."""
    attempt = 0
    while True:
        try:
            resp = await client.send(client.build_request("POST", url, json=body, headers=headers), stream=True)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError, httpx.ReadError) as e:
            if attempt < retries:
                await asyncio.sleep(_delay(None, attempt))
                attempt += 1
                continue
            raise LLMError(f"cannot reach {label} at {url.rsplit('/', 1)[0]} ({type(e).__name__})") from e
        if resp.status_code >= 400:
            text = (await resp.aread()).decode(errors="replace")
            await resp.aclose()
            if resp.status_code in RETRY_STATUS and attempt < retries:
                log.info("%s HTTP %s, retrying", label, resp.status_code)
                await asyncio.sleep(_delay(resp, attempt))
                attempt += 1
                continue
            log.warning("%s HTTP %s: %s", label, resp.status_code, text[:800])
            raise http_error(label, resp.status_code, text)
        try:
            yield resp
        finally:
            await resp.aclose()
        return


async def iter_sse(resp: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """JSON objects from the ``data:`` lines of a server-sent-events stream."""
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            log.debug("bad SSE chunk: %r", data[:200])


def normalize_args(s: str) -> str:
    """Tool-call arguments as a valid JSON string (best-effort repair of truncated JSON)."""
    s = (s or "").strip()
    if not s:
        return "{}"
    try:
        json.loads(s)
        return s
    except json.JSONDecodeError:
        for suffix in ('"}', "}", '"]}', "]}"):
            try:
                json.loads(s + suffix)
                return s + suffix
            except json.JSONDecodeError:
                continue
        log.warning("Unparseable tool arguments: %r", s[:200])
        return json.dumps({"_raw": s})


def auth_headers(key: str | None, extra: dict[str, Any] | None = None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {key}"} if key else {}
    h.update({str(k): str(v) for k, v in (extra or {}).items()})
    return h
