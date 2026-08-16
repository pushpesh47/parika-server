"""
PARIKA Ollama Provider - Health Checking

A small, stateless health-check helper kept separate from
`driver.py` so the driver itself stays focused on orchestration (see
`PARIKA_Core_Coding_Standards.md` - File Size Guidelines).
"""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any

from parika.core.provider_manager.provider_health import ProviderHealth

from .exceptions import OllamaProviderError

RequestJsonFn = Callable[..., dict[str, Any]]


def check_ollama_health(
    *,
    request_json: RequestJsonFn,
    version_path: str,
    timeout: float,
) -> ProviderHealth:
    """
    Check whether an Ollama server is reachable.

    Connectivity failures are captured into
    `ProviderHealth(available=False, ...)` rather than raised, since
    that is exactly what `ProviderHealth` is for and it keeps callers
    (a CLI `/status` command, or `ProviderManager.refresh_health()`)
    resilient to "Ollama is not installed" or "the server is
    offline" without needing their own try/except.

    Args:
        request_json:
            Callable performing a non-streaming JSON request, with
            the same signature as
            `OllamaProviderDriver._request_json()`.

        version_path:
            Path of the version endpoint to call (e.g. `/api/version`).

        timeout:
            Timeout, in seconds, applied to the health check.

    Returns:
        The observed ProviderHealth.
    """

    started_at = perf_counter()

    try:
        payload = request_json(
            "GET",
            version_path,
            payload=None,
            timeout=timeout,
        )

    except OllamaProviderError as ex:
        return ProviderHealth(available=False, message=str(ex))

    latency_ms = (perf_counter() - started_at) * 1000

    version = payload.get("version")
    message = f"Ollama {version}" if version else "Ollama reachable"

    return ProviderHealth(
        available=True,
        latency_ms=latency_ms,
        message=message,
    )
