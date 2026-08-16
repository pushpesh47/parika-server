"""
PARIKA Permission Manager - Workspace Permission Manager

Extends `PermissionManager` with workspace-scoped permission
delegation (Once/Session/Permanent/Deny), so that every present and
future component that touches a workspace (the Filesystem Tool today;
the Shell Tool, and any future Coding/Image/Video/Audio tool) asks this
one shared authority instead of implementing its own permission logic.

This is not a new Core component - see
`docs/architecture/Core_Component_Responsibilities.md` section 25 for
the full design this module implements. `WorkspacePermissionManager`
composes `PermissionManager`'s existing, unmodified public API
(`grant()`/`revoke()`/`contains()`/`check()`) rather than changing it.

A workspace is the directory containing the target path being
accessed, unless a different workspace resolution strategy is
introduced in the future. Workspace paths are never hardcoded here or
anywhere else in PARIKA; the trusted set always comes from
configuration (`[workspace].default_workspace`,
`[filesystem].trusted_workspaces`) or from a user's own interactive
"Always trust" decision at runtime.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event, RLock

from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .permission_manager import PermissionManager
from .workspace_events import (
    WorkspacePermissionEvaluatedEvent,
    WorkspaceTrustedEvent,
)
from .workspace_operation import WorkspaceOperation
from .workspace_permission_decision import WorkspacePermissionDecision
from .workspace_permission_prompt import WorkspacePermissionPrompt
from .workspace_permission_scope import WorkspacePermissionScope
from .workspace_trust_store import RuntimeTrustWriter

WORKSPACE_PERMISSION_EVALUATED_EVENT = "workspace_permission.evaluated"
WORKSPACE_TRUSTED_EVENT = "workspace_permission.trusted"

DEFAULT_WORKSPACE_CONFIG_KEY = "workspace.default_workspace"
TRUSTED_WORKSPACES_CONFIG_KEY = "filesystem.trusted_workspaces"
LEGACY_ALLOWED_ROOTS_CONFIG_KEY = "filesystem.allowed_roots"
DEFAULT_WORKSPACE_FALLBACK = "data"


class _PendingRequest:
    """
    Internal holder used to coalesce concurrent permission requests for
    the same `(workspace, operation)` pair (see
    `WorkspacePermissionManager.check()`).
    """

    __slots__ = ("event", "decision")

    def __init__(self) -> None:
        self.event = Event()
        self.decision: WorkspacePermissionDecision | None = None


class WorkspacePermissionManager:
    """
    Centralized authority for workspace-scoped filesystem and shell
    permissions.

    No component may implement its own permission logic; every Tool
    that touches a workspace must ask this shared authority instead.
    """

    def __init__(
        self,
        *,
        permission_manager: PermissionManager,
        configuration: Configuration,
        event_bus: EventBus,
        logger: Logger,
        prompt: WorkspacePermissionPrompt | None = None,
        trust_writer: RuntimeTrustWriter | None = None,
    ) -> None:
        """
        Initialize the WorkspacePermissionManager.

        Args:
            permission_manager:
                The Core `PermissionManager` instance to compose. Its
                public API is used exactly as-is; no method on it is
                overridden or bypassed.

            configuration:
                The Core `Configuration` component, used to read
                `[workspace].default_workspace` and
                `[filesystem].trusted_workspaces` (falling back to the
                deprecated `[filesystem].allowed_roots` alias when the
                former is absent from every configuration layer).

            event_bus:
                EventBus used to publish workspace permission events.

            logger:
                PARIKA Logger component.

            prompt:
                Optional `WorkspacePermissionPrompt` implementation
                (normally supplied by whichever Interface is active,
                e.g. the CLI). When `None`, every request outside a
                trusted workspace fails closed (`DENY`) rather than
                blocking indefinitely.

            trust_writer:
                Optional `RuntimeTrustWriter` used to persist `PERMANENT`
                decisions into `config/runtime.toml`. When `None`, a
                `PERMANENT` choice still takes effect for the remainder
                of the current process (via the same in-memory
                `PermissionManager.grant()` call `SESSION` uses) but is
                not persisted across a restart.
        """

        self._permission_manager = permission_manager
        self._configuration = configuration
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)
        self._prompt = prompt
        self._trust_writer = trust_writer

        self._lock = RLock()
        self._extra_trusted_workspaces: set[Path] = set()
        self._pending_requests: dict[tuple[str, str], _PendingRequest] = {}

    # ------------------------------------------------------------------
    # Trust
    # ------------------------------------------------------------------

    def trusted_workspaces(self) -> tuple[Path, ...]:
        """
        Return every workspace currently treated as trusted.

        Combines configuration (`[workspace].default_workspace`,
        `[filesystem].trusted_workspaces`/legacy `allowed_roots`) with
        any workspace granted `PERMANENT` trust during this process.
        """

        return self._compute_trusted_workspaces()

    def is_trusted(self, path: Path) -> bool:
        """
        Determine whether `path` falls inside a trusted workspace.

        Args:
            path:
                Any filesystem path (not necessarily an already-
                resolved workspace key).
        """

        return self._is_workspace_trusted(self._resolve_workspace_key(path))

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    def check(
        self,
        path: Path,
        operation: WorkspaceOperation,
        *,
        reason: str | None = None,
    ) -> WorkspacePermissionDecision:
        """
        Determine whether `operation` is authorized for the workspace
        containing `path`.

        This never raises for a denied request; it returns a decision
        with `authorized=False`, exactly like
        `PermissionManager.check()`. Callers (e.g. `PathSecurity`, a
        Shell Tool driver) are responsible for translating a denied
        decision into their own domain-specific exception.

        At most one interactive prompt is ever shown per
        `(workspace, operation)` pair at a time: concurrent callers for
        the same pair wait for, and receive, that one prompt's
        resulting decision instead of triggering a second prompt.

        Args:
            path:
                The path the caller wants to perform `operation` on.
                Resolved to its workspace key (see
                `Core_Component_Responsibilities.md` section 25) before
                any check is performed.

            operation:
                The workspace-scoped operation being requested.

            reason:
                Optional human-readable context surfaced to the
                interactive prompt, if one is shown.

        Returns:
            The resolved, immutable `WorkspacePermissionDecision`.
        """

        workspace = self._resolve_workspace_key(path)

        if operation is WorkspaceOperation.READ:
            # Reads are always allowed, unconditionally - never this
            # extension's concern (see Tool_Guide.md section 23.1).
            decision = WorkspacePermissionDecision(
                workspace=workspace,
                operation=operation,
                authorized=True,
                reason="Reads are always allowed.",
            )
            self._publish_evaluated(decision)
            return decision

        if self._is_workspace_trusted(workspace):
            decision = WorkspacePermissionDecision(
                workspace=workspace,
                operation=operation,
                authorized=True,
                reason="Workspace is trusted.",
            )
            self._publish_evaluated(decision)
            return decision

        subject_id = self._subject_id(workspace)
        operation_key = str(operation)

        if self._permission_manager.contains(subject_id, operation_key):
            existing = self._permission_manager.check(subject_id, operation_key)

            if existing.authorized:
                decision = WorkspacePermissionDecision(
                    workspace=workspace,
                    operation=operation,
                    authorized=True,
                    reason=existing.reason,
                )
                self._publish_evaluated(decision)
                return decision

        decision = self._check_with_coalescing(
            workspace, operation, subject_id, operation_key, reason
        )
        self._publish_evaluated(decision)
        return decision

    # ------------------------------------------------------------------
    # Internal - concurrent request coalescing
    # ------------------------------------------------------------------

    def _check_with_coalescing(
        self,
        workspace: Path,
        operation: WorkspaceOperation,
        subject_id: str,
        operation_key: str,
        reason: str | None,
    ) -> WorkspacePermissionDecision:
        coalesce_key = (subject_id, operation_key)

        with self._lock:
            pending = self._pending_requests.get(coalesce_key)

            if pending is not None:
                is_leader = False
            else:
                pending = _PendingRequest()
                self._pending_requests[coalesce_key] = pending
                is_leader = True

        if not is_leader:
            pending.event.wait()

            if pending.decision is not None:
                return pending.decision

            return WorkspacePermissionDecision(
                workspace=workspace,
                operation=operation,
                authorized=False,
                scope_applied=WorkspacePermissionScope.DENY,
                reason="Concurrent permission request could not be resolved.",
            )

        try:
            scope = self._request_scope(workspace, operation, reason)
            decision = self._apply_scope(
                workspace, operation, scope, subject_id, operation_key, reason
            )

        except Exception:
            self._logger.exception(
                "Error while resolving workspace permission for '%s'.",
                workspace,
            )
            decision = WorkspacePermissionDecision(
                workspace=workspace,
                operation=operation,
                authorized=False,
                scope_applied=WorkspacePermissionScope.DENY,
                reason=(
                    "An error occurred while requesting permission; "
                    "denying by default."
                ),
            )

        finally:
            pending.decision = decision

            with self._lock:
                self._pending_requests.pop(coalesce_key, None)

            pending.event.set()

        return decision

    def _request_scope(
        self,
        workspace: Path,
        operation: WorkspaceOperation,
        reason: str | None,
    ) -> WorkspacePermissionScope:
        if self._prompt is None:
            self._logger.warning(
                "No WorkspacePermissionPrompt is registered; denying "
                "'%s' access to workspace '%s' by default.",
                operation.value,
                workspace,
            )
            return WorkspacePermissionScope.DENY

        return self._prompt.request_decision(
            workspace=workspace,
            operation=operation,
            reason=reason,
        )

    def _apply_scope(
        self,
        workspace: Path,
        operation: WorkspaceOperation,
        scope: WorkspacePermissionScope,
        subject_id: str,
        operation_key: str,
        reason: str | None,
    ) -> WorkspacePermissionDecision:
        if scope is WorkspacePermissionScope.DENY:
            return WorkspacePermissionDecision(
                workspace=workspace,
                operation=operation,
                authorized=False,
                scope_applied=scope,
                reason=reason,
            )

        if scope is WorkspacePermissionScope.ONCE:
            return WorkspacePermissionDecision(
                workspace=workspace,
                operation=operation,
                authorized=True,
                scope_applied=scope,
                reason=reason,
            )

        if scope in (
            WorkspacePermissionScope.SESSION,
            WorkspacePermissionScope.PERMANENT,
        ):
            self._grant(subject_id, operation_key, reason)

            if scope is WorkspacePermissionScope.PERMANENT:
                self._mark_permanently_trusted(workspace)

            return WorkspacePermissionDecision(
                workspace=workspace,
                operation=operation,
                authorized=True,
                scope_applied=scope,
                reason=reason,
            )

        raise ValueError(f"Unknown WorkspacePermissionScope: {scope!r}")

    def _grant(
        self,
        subject_id: str,
        operation_key: str,
        reason: str | None,
    ) -> None:
        if self._permission_manager.contains(subject_id, operation_key):
            self._permission_manager.revoke(subject_id, operation_key)

        self._permission_manager.grant(subject_id, operation_key, reason=reason)

    def _mark_permanently_trusted(self, workspace: Path) -> None:
        with self._lock:
            self._extra_trusted_workspaces.add(workspace)

        if self._trust_writer is not None:
            try:
                self._trust_writer.add_trusted_workspace(workspace)

            except Exception:
                self._logger.exception(
                    "Failed to persist trusted workspace '%s' to "
                    "runtime.toml; it remains trusted for this process "
                    "only.",
                    workspace,
                )

        self._event_bus.publish(
            WORKSPACE_TRUSTED_EVENT,
            WorkspaceTrustedEvent(workspace=workspace),
        )

    # ------------------------------------------------------------------
    # Internal - trust computation
    # ------------------------------------------------------------------

    def _is_workspace_trusted(self, workspace: Path) -> bool:
        with self._lock:
            if workspace in self._extra_trusted_workspaces:
                return True

        for trusted in self._compute_trusted_workspaces():
            if workspace == trusted or trusted in workspace.parents:
                return True

        return False

    def _compute_trusted_workspaces(self) -> tuple[Path, ...]:
        project_root = self._configuration.get_project_root()

        raw_trusted = self._configuration.get(TRUSTED_WORKSPACES_CONFIG_KEY, None)

        if raw_trusted is None:
            raw_trusted = self._configuration.get(
                LEGACY_ALLOWED_ROOTS_CONFIG_KEY, []
            )

        roots: list[Path] = []

        if isinstance(raw_trusted, (list, tuple)):
            for raw_root in raw_trusted:
                resolved_root = self._resolve_configured_path(
                    str(raw_root), project_root
                )

                if resolved_root not in roots:
                    roots.append(resolved_root)

        raw_default_workspace = self._configuration.get(
            DEFAULT_WORKSPACE_CONFIG_KEY, DEFAULT_WORKSPACE_FALLBACK
        )

        if raw_default_workspace:
            default_workspace_path = self._resolve_configured_path(
                str(raw_default_workspace), project_root
            )

            if default_workspace_path not in roots:
                roots.append(default_workspace_path)

        with self._lock:
            for extra in self._extra_trusted_workspaces:
                if extra not in roots:
                    roots.append(extra)

        return tuple(roots)

    @staticmethod
    def _resolve_configured_path(raw_path: str, project_root: Path) -> Path:
        candidate = Path(raw_path)

        if not candidate.is_absolute():
            candidate = project_root / candidate

        return candidate.resolve()

    # ------------------------------------------------------------------
    # Internal - workspace/subject resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_workspace_key(path: Path) -> Path:
        """
        Resolve `path` to its workspace: the directory containing the
        target path being accessed, unless a different workspace
        resolution strategy is introduced in the future (see
        `Core_Component_Responsibilities.md` section 25).
        """

        resolved = Path(path).resolve()

        return resolved if resolved.is_dir() else resolved.parent

    @staticmethod
    def _subject_id(workspace: Path) -> str:
        """
        Namespace a workspace as a `PermissionManager` subject id, so
        it can never collide with any other kind of subject id (a
        Module id, a Tool id, ...) a future caller registers in the
        same shared registry.
        """

        return f"workspace:{workspace}"

    def _publish_evaluated(self, decision: WorkspacePermissionDecision) -> None:
        self._event_bus.publish(
            WORKSPACE_PERMISSION_EVALUATED_EVENT,
            WorkspacePermissionEvaluatedEvent(decision=decision),
        )

        self._logger.debug(
            "Workspace permission evaluated: workspace='%s' "
            "operation='%s' authorized=%s scope_applied=%s.",
            decision.workspace,
            decision.operation.value,
            decision.authorized,
            decision.scope_applied.value if decision.scope_applied else None,
        )
