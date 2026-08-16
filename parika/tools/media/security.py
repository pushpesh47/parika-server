"""
PARIKA Media Tool - Local Path Security

Confines `media.play`'s local-file resolution to a trusted,
explicitly configured allowlist of root directories -
`[media].allowed_local_roots` in `config/defaults.toml`, empty by
default (local media resolution disabled by default; deny-by-default,
never "read anything").

This is a deliberately *narrower* posture than
`parika/tools/filesystem/security.py`'s `PathSecurity`, which
permits unconditional reads of any host path for its own read
operations (`enforce_roots=False`). Media local-path resolution has
no equivalent "any path is fine" case: the resolved `MediaSource`
(including its raw `path`) is returned to the caller/model and
potentially surfaced to a Web Client, so an unconstrained resolver
would let a caller probe for the existence of arbitrary filesystem
paths merely by asking to "play" them. Confining every local
resolution to `allowed_local_roots` closes that gap; see
`docs/architecture/adr/0004-media-capability.md`'s "Local files"
decision.

This is the single choke point `resolution.py` passes every local
path through before ever constructing a local `MediaSource`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .exceptions import MediaPathNotAllowedError, MediaValidationError


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalMediaPathSecurityConfig:
    """Immutable configuration for `LocalMediaPathSecurity`."""

    allowed_roots: tuple[Path, ...] = field(default_factory=tuple)
    """
    Every directory local media resolution may touch, and any path
    beneath it (after resolving symlinks and `..` segments). Empty by
    default - local media resolution is disabled until an operator
    explicitly opts in.
    """


class LocalMediaPathSecurity:
    """
    Resolves and validates a caller-supplied local media path against
    a configured allowlist of root directories.
    """

    def __init__(self, config: LocalMediaPathSecurityConfig) -> None:
        self._roots = tuple(root.resolve() for root in config.allowed_roots)

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        """Every resolved root directory this boundary confines resolution to."""

        return self._roots

    def resolve(self, raw_path: str) -> Path:
        """
        Resolve and validate a caller-supplied local media path.

        Args:
            raw_path:
                The raw path string, e.g. from a "play the song in
                ..." request.

        Returns:
            The fully resolved, absolute `Path`. Existence is not
            checked here - see `resolution.py`, which reports a
            not-found source distinctly from a not-allowed one.

        Raises:
            MediaValidationError:
                If `raw_path` is not a non-empty string.

            MediaPathNotAllowedError:
                If local media resolution is disabled (no
                `allowed_roots` configured), or the resolved path
                falls outside every configured root.
        """

        if not isinstance(raw_path, str) or not raw_path.strip():
            raise MediaValidationError("A local media path must be a non-empty string.")

        if not self._roots:
            raise MediaPathNotAllowedError(
                "Local media playback is disabled: no "
                "`[media].allowed_local_roots` are configured."
            )

        candidate = Path(raw_path)

        if not candidate.is_absolute():
            candidate = self._roots[0] / candidate

        resolved = candidate.resolve()

        for root in self._roots:
            if resolved == root or root in resolved.parents:
                return resolved

        raise MediaPathNotAllowedError(
            f"Path '{raw_path}' resolves to '{resolved}', which is outside "
            "every configured `[media].allowed_local_roots` entry "
            f"({', '.join(str(root) for root in self._roots)})."
        )
