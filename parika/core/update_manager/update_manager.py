"""
PARIKA Update Manager

Provides the core component responsible for coordinating updates
throughout the PARIKA ecosystem.

UpdateManager maintains the authoritative runtime registry of update
targets (Core, Modules, Providers, and Tools), coordinates checking
for and applying updates by delegating to callables supplied by each
target, orchestrates configuration migrations, and publishes update
lifecycle events through the EventBus.

UpdateManager does not install arbitrary software itself. The check
and apply callables supplied when registering a target are treated as
opaque logic owned by that target. UpdateManager also does not decide
whether an update is permitted to run; that decision belongs to
PolicyEngine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from threading import RLock
from types import MappingProxyType

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .events import (
    MigrationAppliedEvent,
    TargetRegisteredEvent,
    TargetUnregisteredEvent,
    UpdateAppliedEvent,
    UpdateAvailableEvent,
    UpdateFailedEvent,
    UpdateUpToDateEvent,
)
from .exceptions import (
    InvalidUpdateTargetError,
    MigrationAlreadyRegisteredError,
    MigrationError,
    TargetAlreadyRegisteredError,
    TargetNotFoundError,
    UpdateApplyError,
    UpdateNotAvailableError,
)
from .update_info import UpdateInfo
from .update_record import UpdateRecord
from .update_status import UpdateStatus

TARGET_REGISTERED_EVENT = "update.target.registered"
TARGET_UNREGISTERED_EVENT = "update.target.unregistered"
UPDATE_AVAILABLE_EVENT = "update.available"
UPDATE_UP_TO_DATE_EVENT = "update.up_to_date"
UPDATE_APPLIED_EVENT = "update.applied"
UPDATE_FAILED_EVENT = "update.failed"
MIGRATION_APPLIED_EVENT = "update.migration.applied"

CheckCallable = Callable[[], UpdateInfo | None]
ApplyCallable = Callable[[UpdateInfo], None]
MigrationCallable = Callable[[], None]


class UpdateManager:
    """
    Coordinates updates throughout the PARIKA ecosystem.

    UpdateManager owns the authoritative runtime registry of update
    targets. It orchestrates checking for and applying updates by
    delegating to callables supplied by each registered target, and
    orchestrates the ordered execution of configuration migrations.

    UpdateManager intentionally does not:

    - Install arbitrary software. Check and apply callables are
      opaque logic owned by the registering target.
    - Execute update policies. Whether an update is permitted to run
      is decided by PolicyEngine.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize the UpdateManager.

        Args:
            event_bus:
                EventBus used to publish update lifecycle events.

            logger:
                PARIKA Logger component.
        """

        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = RLock()

        self._targets: dict[str, UpdateRecord] = {}
        self._checks: dict[str, CheckCallable] = {}
        self._appliers: dict[str, ApplyCallable] = {}

        self._migrations: dict[str, MigrationCallable] = {}
        self._applied_migrations: set[str] = set()

    # ------------------------------------------------------------------
    # Target Registry
    # ------------------------------------------------------------------

    def register_target(
        self,
        target_id: str,
        *,
        check: CheckCallable,
        apply: ApplyCallable,
        current_version: str | None = None,
    ) -> None:
        """
        Register an update target.

        Args:
            target_id:
                Identifier of the target (e.g. "core",
                "module:web_search", "provider:ollama",
                "tool:web_search").

            check:
                Callable that returns an UpdateInfo describing an
                available update, or None if the target is up to
                date.

            apply:
                Callable that performs the actual update described by
                an UpdateInfo.

            current_version:
                Optional version currently installed for this target.

        Raises:
            TargetAlreadyRegisteredError:
                If the target is already registered.

            InvalidUpdateTargetError:
                If `check` or `apply` is not callable.
        """

        if not callable(check) or not callable(apply):
            raise InvalidUpdateTargetError(
                "check and apply must be callable."
            )

        with self._lock:
            if target_id in self._targets:
                raise TargetAlreadyRegisteredError(
                    f"Target '{target_id}' is already registered."
                )

            self._targets[target_id] = UpdateRecord(
                target_id=target_id,
                current_version=current_version,
            )
            self._checks[target_id] = check
            self._appliers[target_id] = apply

            event = TargetRegisteredEvent(target_id=target_id)

        self._event_bus.publish(TARGET_REGISTERED_EVENT, event)

        self._logger.debug(
            "Registered update target '%s'.",
            target_id,
        )

    def unregister_target(self, target_id: str) -> None:
        """
        Unregister an update target.

        Raises:
            TargetNotFoundError:
                If the target is not registered.
        """

        with self._lock:
            self._require_target(target_id)

            del self._targets[target_id]
            self._checks.pop(target_id, None)
            self._appliers.pop(target_id, None)

            event = TargetUnregisteredEvent(target_id=target_id)

        self._event_bus.publish(TARGET_UNREGISTERED_EVENT, event)

        self._logger.debug(
            "Unregistered update target '%s'.",
            target_id,
        )

    def get(self, target_id: str) -> UpdateRecord:
        """
        Retrieve the UpdateRecord for a registered target.

        Raises:
            TargetNotFoundError:
                If the target is not registered.
        """

        with self._lock:
            return self._require_target(target_id)

    def contains(self, target_id: str) -> bool:
        """
        Determine whether a target is registered.
        """

        with self._lock:
            return target_id in self._targets

    def get_all(self) -> Mapping[str, UpdateRecord]:
        """
        Return the UpdateRecord for every registered target.
        """

        with self._lock:
            return MappingProxyType(dict(self._targets))

    def count(self) -> int:
        """
        Return the number of registered targets.
        """

        with self._lock:
            return len(self._targets)

    # ------------------------------------------------------------------
    # Update Checking and Application
    # ------------------------------------------------------------------

    def check(self, target_id: str) -> UpdateRecord:
        """
        Check a target for an available update.

        A check callable that raises an exception is logged and
        results in a FAILED status; it does not propagate.

        Args:
            target_id:
                Identifier of the target to check.

        Returns:
            The updated UpdateRecord.

        Raises:
            TargetNotFoundError:
                If the target is not registered.
        """

        with self._lock:
            record = self._require_target(target_id)
            check_callable = self._checks[target_id]

        try:
            info = check_callable()

        except Exception as ex:
            self._logger.exception(
                "Update check for target '%s' raised an exception.",
                target_id,
            )

            with self._lock:
                record.status = UpdateStatus.FAILED
                record.failure = ex
                record.last_checked_at = datetime.now(UTC)

            self._event_bus.publish(
                UPDATE_FAILED_EVENT,
                UpdateFailedEvent(target_id=target_id, reason=str(ex)),
            )

            return record

        with self._lock:
            record.last_checked_at = datetime.now(UTC)

            if info is None:
                record.status = UpdateStatus.UP_TO_DATE
                record.pending_update = None

            else:
                record.status = UpdateStatus.UPDATE_AVAILABLE
                record.pending_update = info

        if info is None:
            self._event_bus.publish(
                UPDATE_UP_TO_DATE_EVENT,
                UpdateUpToDateEvent(target_id=target_id),
            )

        else:
            self._event_bus.publish(
                UPDATE_AVAILABLE_EVENT,
                UpdateAvailableEvent(target_id=target_id, info=info),
            )

        self._logger.debug(
            "Checked update target '%s': status='%s'.",
            target_id,
            record.status.value,
        )

        return record

    def check_all(self) -> Mapping[str, UpdateRecord]:
        """
        Check every registered target for an available update.

        Returns:
            The UpdateRecord for every registered target after
            checking.
        """

        with self._lock:
            target_ids = list(self._targets)

        for target_id in target_ids:
            self.check(target_id)

        return self.get_all()

    def apply(self, target_id: str) -> UpdateRecord:
        """
        Apply the pending update for a target.

        Args:
            target_id:
                Identifier of the target to update.

        Returns:
            The updated UpdateRecord.

        Raises:
            TargetNotFoundError:
                If the target is not registered.

            UpdateNotAvailableError:
                If the target has no pending update.

            UpdateApplyError:
                If the apply callable raises an exception.
        """

        with self._lock:
            record = self._require_target(target_id)

            if (
                record.status is not UpdateStatus.UPDATE_AVAILABLE
                or record.pending_update is None
            ):
                raise UpdateNotAvailableError(
                    f"Target '{target_id}' has no pending update."
                )

            info = record.pending_update
            apply_callable = self._appliers[target_id]

            record.status = UpdateStatus.UPDATING

        try:
            apply_callable(info)

        except Exception as ex:
            with self._lock:
                record.status = UpdateStatus.FAILED
                record.failure = ex

            self._event_bus.publish(
                UPDATE_FAILED_EVENT,
                UpdateFailedEvent(target_id=target_id, reason=str(ex)),
            )

            self._logger.exception(
                "Applying update for target '%s' failed.",
                target_id,
            )

            raise UpdateApplyError(
                f"Applying update for target '{target_id}' failed."
            ) from ex

        with self._lock:
            record.status = UpdateStatus.UPDATED
            record.current_version = info.available_version
            record.pending_update = None
            record.last_updated_at = datetime.now(UTC)

        self._event_bus.publish(
            UPDATE_APPLIED_EVENT,
            UpdateAppliedEvent(target_id=target_id, info=info),
        )

        self._logger.info(
            "Applied update for target '%s' (now '%s').",
            target_id,
            info.available_version,
        )

        return record

    # ------------------------------------------------------------------
    # Configuration Migrations
    # ------------------------------------------------------------------

    def register_migration(
        self,
        version: str,
        migration: MigrationCallable,
    ) -> None:
        """
        Register a configuration migration.

        Migrations run in registration order when run_migrations() is
        called.

        Args:
            version:
                Version identifier associated with this migration.

            migration:
                Zero-argument callable that performs the migration.

        Raises:
            MigrationAlreadyRegisteredError:
                If a migration is already registered for this
                version.
        """

        with self._lock:
            if version in self._migrations:
                raise MigrationAlreadyRegisteredError(
                    f"Migration for version '{version}' is already "
                    "registered."
                )

            self._migrations[version] = migration

    def run_migrations(self) -> tuple[str, ...]:
        """
        Run every registered migration that has not yet been applied,
        in registration order.

        Execution stops at the first migration that raises an
        exception; migrations registered afterward are not attempted.

        Returns:
            The versions of every migration successfully applied
            during this call.

        Raises:
            MigrationError:
                If a migration callable raises an exception.
        """

        with self._lock:
            pending_versions = [
                version
                for version in self._migrations
                if version not in self._applied_migrations
            ]

        applied: list[str] = []

        for version in pending_versions:

            with self._lock:
                migration = self._migrations[version]

            try:
                migration()

            except Exception as ex:
                self._logger.exception(
                    "Configuration migration '%s' failed.",
                    version,
                )

                raise MigrationError(
                    f"Configuration migration '{version}' failed."
                ) from ex

            with self._lock:
                self._applied_migrations.add(version)

            self._event_bus.publish(
                MIGRATION_APPLIED_EVENT,
                MigrationAppliedEvent(version=version),
            )

            self._logger.info(
                "Applied configuration migration '%s'.",
                version,
            )

            applied.append(version)

        return tuple(applied)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _require_target(self, target_id: str) -> UpdateRecord:
        """
        Retrieve a registered UpdateRecord.

        Raises:
            TargetNotFoundError:
                If the target is not registered.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        try:
            return self._targets[target_id]

        except KeyError as ex:
            raise TargetNotFoundError(
                f"Target '{target_id}' is not registered."
            ) from ex
