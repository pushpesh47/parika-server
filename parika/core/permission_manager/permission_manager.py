"""
PARIKA Permission Manager

Provides the core component responsible for determining whether an
operation is authorized.

PermissionManager maintains the authoritative runtime registry of
static PermissionGrant records and evaluates authorization checks
against that registry, including whether an operation requires
explicit user confirmation before it may proceed.

PermissionManager does not define policies. Conditional,
context-dependent behavior belongs to PolicyEngine. PermissionManager
also does not execute the operations it authorizes; enforcement and
execution remain the responsibility of the caller.
"""

from __future__ import annotations

from threading import RLock

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .decision import PermissionDecision
from .events import (
    PermissionDeniedEvent,
    PermissionGrantedEvent,
    PermissionRevokedEvent,
)
from .exceptions import (
    PermissionAlreadyGrantedError,
    PermissionNotFoundError,
)
from .permission_grant import PermissionGrant

PERMISSION_GRANTED_EVENT = "permission.granted"
PERMISSION_REVOKED_EVENT = "permission.revoked"
PERMISSION_DENIED_EVENT = "permission.denied"


class PermissionManager:
    """
    Determines whether an operation is authorized.

    PermissionManager owns the authoritative runtime registry of
    static PermissionGrant records, keyed by subject and operation.
    It evaluates authorization checks against that registry and
    reports whether an operation additionally requires explicit user
    confirmation.

    PermissionManager intentionally does not:

    - Define policies. Conditional, context-dependent behavior belongs
      to PolicyEngine.
    - Execute operations. Enforcement and execution remain the
      responsibility of the caller.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize the PermissionManager.

        Args:
            event_bus:
                EventBus used to publish permission events.

            logger:
                PARIKA Logger component.
        """

        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = RLock()
        self._grants: dict[tuple[str, str], PermissionGrant] = {}

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def grant(
        self,
        subject_id: str,
        operation: str,
        *,
        requires_confirmation: bool = False,
        reason: str | None = None,
    ) -> PermissionGrant:
        """
        Grant a subject permission to perform an operation.

        Args:
            subject_id:
                Identifier of the subject being authorized.

            operation:
                Identifier of the operation being authorized.

            requires_confirmation:
                Whether every check of this grant requires explicit
                user confirmation.

            reason:
                Optional human-readable explanation of the grant.

        Returns:
            The newly created PermissionGrant.

        Raises:
            PermissionAlreadyGrantedError:
                If a grant already exists for this subject and
                operation.
        """

        key = (subject_id, operation)

        with self._lock:
            if key in self._grants:
                raise PermissionAlreadyGrantedError(
                    f"Permission for subject '{subject_id}' to "
                    f"perform '{operation}' is already granted."
                )

            new_grant = PermissionGrant(
                subject_id=subject_id,
                operation=operation,
                requires_confirmation=requires_confirmation,
                reason=reason,
            )

            self._grants[key] = new_grant

            event = PermissionGrantedEvent(grant=new_grant)

        self._event_bus.publish(PERMISSION_GRANTED_EVENT, event)

        self._logger.debug(
            "Granted subject '%s' permission to perform '%s'.",
            subject_id,
            operation,
        )

        return new_grant

    def revoke(self, subject_id: str, operation: str) -> None:
        """
        Revoke a subject's permission to perform an operation.

        Raises:
            PermissionNotFoundError:
                If no grant exists for this subject and operation.
        """

        key = (subject_id, operation)

        with self._lock:
            if key not in self._grants:
                raise PermissionNotFoundError(
                    f"No permission grant exists for subject "
                    f"'{subject_id}' and operation '{operation}'."
                )

            del self._grants[key]

            event = PermissionRevokedEvent(
                subject_id=subject_id,
                operation=operation,
            )

        self._event_bus.publish(PERMISSION_REVOKED_EVENT, event)

        self._logger.debug(
            "Revoked subject '%s' permission to perform '%s'.",
            subject_id,
            operation,
        )

    def get(self, subject_id: str, operation: str) -> PermissionGrant:
        """
        Retrieve a registered PermissionGrant.

        Raises:
            PermissionNotFoundError:
                If no grant exists for this subject and operation.
        """

        with self._lock:
            return self._require_grant(subject_id, operation)

    def contains(self, subject_id: str, operation: str) -> bool:
        """
        Determine whether a grant exists for this subject and
        operation.
        """

        with self._lock:
            return (subject_id, operation) in self._grants

    def get_all(self) -> tuple[PermissionGrant, ...]:
        """
        Return every registered PermissionGrant.
        """

        with self._lock:
            return tuple(self._grants.values())

    def count(self) -> int:
        """
        Return the number of registered PermissionGrant records.
        """

        with self._lock:
            return len(self._grants)

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    def check(
        self,
        subject_id: str,
        operation: str,
        *,
        confirmed: bool = False,
    ) -> PermissionDecision:
        """
        Determine whether a subject is authorized to perform an
        operation.

        Args:
            subject_id:
                Identifier of the subject requesting authorization.

            operation:
                Identifier of the operation being requested.

            confirmed:
                Whether the caller has already obtained explicit user
                confirmation for this specific request. Ignored when
                the matching grant does not require confirmation.

        Returns:
            The resolved PermissionDecision. This never raises for an
            unknown subject/operation pair; an unknown pair simply
            resolves to a denied decision.
        """

        with self._lock:
            existing_grant = self._grants.get((subject_id, operation))

        if existing_grant is None:
            decision = PermissionDecision(
                subject_id=subject_id,
                operation=operation,
                authorized=False,
                requires_confirmation=False,
                reason="No permission has been granted.",
            )

        elif existing_grant.requires_confirmation and not confirmed:
            decision = PermissionDecision(
                subject_id=subject_id,
                operation=operation,
                authorized=False,
                requires_confirmation=True,
                reason=existing_grant.reason,
            )

        else:
            decision = PermissionDecision(
                subject_id=subject_id,
                operation=operation,
                authorized=True,
                requires_confirmation=False,
                reason=existing_grant.reason,
            )

        if not decision.authorized:
            self._event_bus.publish(
                PERMISSION_DENIED_EVENT,
                PermissionDeniedEvent(
                    subject_id=subject_id,
                    operation=operation,
                    reason=decision.reason,
                ),
            )

            self._logger.debug(
                "Denied subject '%s' for operation '%s' "
                "(requires_confirmation=%s).",
                subject_id,
                operation,
                decision.requires_confirmation,
            )

        return decision

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _require_grant(
        self,
        subject_id: str,
        operation: str,
    ) -> PermissionGrant:
        """
        Retrieve a registered PermissionGrant.

        Raises:
            PermissionNotFoundError:
                If no grant exists for this subject and operation.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        try:
            return self._grants[(subject_id, operation)]

        except KeyError as ex:
            raise PermissionNotFoundError(
                f"No permission grant exists for subject "
                f"'{subject_id}' and operation '{operation}'."
            ) from ex
