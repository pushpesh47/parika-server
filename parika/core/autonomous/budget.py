"""
PARIKA Autonomous Execution - Budget Enforcement

Enforces resource budgets for autonomous execution using ResourceManager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.resource_manager.models import ResourceSnapshot
from parika.core.logger.logger import Logger


@dataclass(frozen=True, slots=True, kw_only=True)
class BudgetLimit:
    """Resource budget limit configuration."""
    max_runtime_seconds: float | None = None
    max_retries: int | None = None
    max_children: int | None = None
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    max_cpu_percent: float | None = None
    max_memory_percent: float | None = None
    max_concurrent_workers: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BudgetUsage:
    """Current budget usage tracking."""
    runtime_seconds: float = 0.0
    retries: int = 0
    children_spawned: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    concurrent_workers: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class BudgetViolation:
    """Budget violation details."""
    limit_name: str
    limit_value: float
    current_value: float
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BudgetCheckResult:
    """Result of a budget check."""
    allowed: bool
    violations: tuple[BudgetViolation, ...] = ()
    usage: BudgetUsage = field(default_factory=BudgetUsage)
    remaining: MappingProxyType[str, Any] = MappingProxyType({})


class BudgetEnforcer:
    """
    Enforces resource budgets for autonomous execution.
    
    Integrates with ResourceManager for system-level resource monitoring
    and tracks execution-level budgets for autonomous tasks.
    """

    def __init__(
        self,
        *,
        resource_manager: ResourceManager,
        logger: Logger,
    ) -> None:
        self._resource_manager = resource_manager
        self._logger = logger.get_logger(__name__)
        
        # In-memory budget tracking per task
        self._budget_usage: dict[str, BudgetUsage] = {}
        self._budget_limits: dict[str, BudgetLimit] = {}
        self._task_start_times: dict[str, datetime] = {}

    def set_budget(self, task_id: str, budget: MappingProxyType[str, Any]) -> BudgetLimit:
        """Set budget limits for a task."""
        limit = BudgetLimit(
            max_runtime_seconds=budget.get("max_runtime_seconds"),
            max_retries=budget.get("max_retries"),
            max_children=budget.get("max_children"),
            max_tokens=budget.get("max_tokens"),
            max_cost_usd=budget.get("max_cost_usd"),
            max_cpu_percent=budget.get("max_cpu_percent"),
            max_memory_percent=budget.get("max_memory_percent"),
            max_concurrent_workers=budget.get("max_concurrent_workers"),
        )
        self._budget_limits[task_id] = limit
        self._budget_usage[task_id] = BudgetUsage()
        self._task_start_times[task_id] = datetime.now(UTC)
        return limit

    def start_tracking(self, task_id: str) -> None:
        """Start budget tracking for a task."""
        if task_id not in self._task_start_times:
            self._task_start_times[task_id] = datetime.now(UTC)
        if task_id not in self._budget_usage:
            self._budget_usage[task_id] = BudgetUsage()

    def check_budget(self, task_id: str) -> BudgetCheckResult:
        """Check if task is within budget limits."""
        limit = self._budget_limits.get(task_id)
        if limit is None:
            return BudgetCheckResult(allowed=True)

        usage = self._budget_usage.get(task_id, BudgetUsage())
        violations = []

        # Update runtime
        start_time = self._task_start_times.get(task_id)
        if start_time:
            runtime = (datetime.now(UTC) - start_time).total_seconds()
            usage = BudgetUsage(
                runtime_seconds=runtime,
                retries=usage.retries,
                children_spawned=usage.children_spawned,
                tokens_used=usage.tokens_used,
                cost_usd=usage.cost_usd,
                cpu_percent=usage.cpu_percent,
                memory_percent=usage.memory_percent,
                concurrent_workers=usage.concurrent_workers,
            )

        # Check runtime limit
        if limit.max_runtime_seconds is not None:
            if usage.runtime_seconds >= limit.max_runtime_seconds:
                violations.append(BudgetViolation(
                    limit_name="max_runtime_seconds",
                    limit_value=limit.max_runtime_seconds,
                    current_value=usage.runtime_seconds,
                    message=f"Task exceeded max runtime of {limit.max_runtime_seconds}s",
                ))

        # Check retry limit
        if limit.max_retries is not None:
            if usage.retries >= limit.max_retries:
                violations.append(BudgetViolation(
                    limit_name="max_retries",
                    limit_value=float(limit.max_retries),
                    current_value=float(usage.retries),
                    message=f"Task exceeded max retries of {limit.max_retries}",
                ))

        # Check children limit
        if limit.max_children is not None:
            if usage.children_spawned >= limit.max_children:
                violations.append(BudgetViolation(
                    limit_name="max_children",
                    limit_value=float(limit.max_children),
                    current_value=float(usage.children_spawned),
                    message=f"Task exceeded max children of {limit.max_children}",
                ))

        # Check token limit
        if limit.max_tokens is not None:
            if usage.tokens_used >= limit.max_tokens:
                violations.append(BudgetViolation(
                    limit_name="max_tokens",
                    limit_value=float(limit.max_tokens),
                    current_value=float(usage.tokens_used),
                    message=f"Task exceeded max tokens of {limit.max_tokens}",
                ))

        # Check cost limit
        if limit.max_cost_usd is not None:
            if usage.cost_usd >= limit.max_cost_usd:
                violations.append(BudgetViolation(
                    limit_name="max_cost_usd",
                    limit_value=limit.max_cost_usd,
                    current_value=usage.cost_usd,
                    message=f"Task exceeded max cost of ${limit.max_cost_usd}",
                ))

        # Check system resource limits
        if limit.max_cpu_percent is not None or limit.max_memory_percent is not None:
            snapshot = self._resource_manager.get_resource_snapshot()
            
            if limit.max_cpu_percent is not None:
                cpu_usage = snapshot.cpu.usage_percent
                if cpu_usage >= limit.max_cpu_percent:
                    violations.append(BudgetViolation(
                        limit_name="max_cpu_percent",
                        limit_value=limit.max_cpu_percent,
                        current_value=cpu_usage,
                        message=f"System CPU usage {cpu_usage}% exceeds limit {limit.max_cpu_percent}%",
                    ))
            
            if limit.max_memory_percent is not None:
                mem_usage = snapshot.memory.usage_percent
                if mem_usage >= limit.max_memory_percent:
                    violations.append(BudgetViolation(
                        limit_name="max_memory_percent",
                        limit_value=limit.max_memory_percent,
                        current_value=mem_usage,
                        message=f"System memory usage {mem_usage}% exceeds limit {limit.max_memory_percent}%",
                    ))

        # Check concurrent workers limit
        if limit.max_concurrent_workers is not None:
            if usage.concurrent_workers >= limit.max_concurrent_workers:
                violations.append(BudgetViolation(
                    limit_name="max_concurrent_workers",
                    limit_value=float(limit.max_concurrent_workers),
                    current_value=float(usage.concurrent_workers),
                    message=f"Task exceeded max concurrent workers of {limit.max_concurrent_workers}",
                ))

        # Calculate remaining budget
        remaining = {}
        if limit.max_runtime_seconds is not None:
            remaining["runtime_seconds"] = max(0, limit.max_runtime_seconds - usage.runtime_seconds)
        if limit.max_retries is not None:
            remaining["retries"] = max(0, limit.max_retries - usage.retries)
        if limit.max_children is not None:
            remaining["children"] = max(0, limit.max_children - usage.children_spawned)
        if limit.max_tokens is not None:
            remaining["tokens"] = max(0, limit.max_tokens - usage.tokens_used)
        if limit.max_cost_usd is not None:
            remaining["cost_usd"] = max(0.0, limit.max_cost_usd - usage.cost_usd)

        allowed = len(violations) == 0
        
        if not allowed:
            self._logger.warning(
                "Budget violation for task '%s': %s",
                task_id, "; ".join(v.message for v in violations)
            )

        return BudgetCheckResult(
            allowed=allowed,
            violations=tuple(violations),
            usage=usage,
            remaining=MappingProxyType(remaining),
        )

    def record_retry(self, task_id: str) -> BudgetCheckResult:
        """Record a retry attempt."""
        usage = self._budget_usage.get(task_id, BudgetUsage())
        usage = BudgetUsage(
            runtime_seconds=usage.runtime_seconds,
            retries=usage.retries + 1,
            children_spawned=usage.children_spawned,
            tokens_used=usage.tokens_used,
            cost_usd=usage.cost_usd,
            cpu_percent=usage.cpu_percent,
            memory_percent=usage.memory_percent,
            concurrent_workers=usage.concurrent_workers,
        )
        self._budget_usage[task_id] = usage
        return self.check_budget(task_id)

    def record_child_spawn(self, task_id: str) -> BudgetCheckResult:
        """Record a child task spawn."""
        usage = self._budget_usage.get(task_id, BudgetUsage())
        usage = BudgetUsage(
            runtime_seconds=usage.runtime_seconds,
            retries=usage.retries,
            children_spawned=usage.children_spawned + 1,
            tokens_used=usage.tokens_used,
            cost_usd=usage.cost_usd,
            cpu_percent=usage.cpu_percent,
            memory_percent=usage.memory_percent,
            concurrent_workers=usage.concurrent_workers,
        )
        self._budget_usage[task_id] = usage
        return self.check_budget(task_id)

    def record_tokens(self, task_id: str, tokens: int) -> BudgetCheckResult:
        """Record token usage."""
        usage = self._budget_usage.get(task_id, BudgetUsage())
        usage = BudgetUsage(
            runtime_seconds=usage.runtime_seconds,
            retries=usage.retries,
            children_spawned=usage.children_spawned,
            tokens_used=usage.tokens_used + tokens,
            cost_usd=usage.cost_usd,
            cpu_percent=usage.cpu_percent,
            memory_percent=usage.memory_percent,
            concurrent_workers=usage.concurrent_workers,
        )
        self._budget_usage[task_id] = usage
        return self.check_budget(task_id)

    def record_cost(self, task_id: str, cost_usd: float) -> BudgetCheckResult:
        """Record cost usage."""
        usage = self._budget_usage.get(task_id, BudgetUsage())
        usage = BudgetUsage(
            runtime_seconds=usage.runtime_seconds,
            retries=usage.retries,
            children_spawned=usage.children_spawned,
            tokens_used=usage.tokens_used,
            cost_usd=usage.cost_usd + cost_usd,
            cpu_percent=usage.cpu_percent,
            memory_percent=usage.memory_percent,
            concurrent_workers=usage.concurrent_workers,
        )
        self._budget_usage[task_id] = usage
        return self.check_budget(task_id)

    def record_worker_start(self, task_id: str) -> BudgetCheckResult:
        """Record a worker starting."""
        usage = self._budget_usage.get(task_id, BudgetUsage())
        usage = BudgetUsage(
            runtime_seconds=usage.runtime_seconds,
            retries=usage.retries,
            children_spawned=usage.children_spawned,
            tokens_used=usage.tokens_used,
            cost_usd=usage.cost_usd,
            cpu_percent=usage.cpu_percent,
            memory_percent=usage.memory_percent,
            concurrent_workers=usage.concurrent_workers + 1,
        )
        self._budget_usage[task_id] = usage
        return self.check_budget(task_id)

    def record_worker_end(self, task_id: str) -> BudgetCheckResult:
        """Record a worker ending."""
        usage = self._budget_usage.get(task_id, BudgetUsage())
        usage = BudgetUsage(
            runtime_seconds=usage.runtime_seconds,
            retries=usage.retries,
            children_spawned=usage.children_spawned,
            tokens_used=usage.tokens_used,
            cost_usd=usage.cost_usd,
            cpu_percent=usage.cpu_percent,
            memory_percent=usage.memory_percent,
            concurrent_workers=max(0, usage.concurrent_workers - 1),
        )
        self._budget_usage[task_id] = usage
        return self.check_budget(task_id)

    def get_usage(self, task_id: str) -> BudgetUsage | None:
        """Get current budget usage for a task."""
        return self._budget_usage.get(task_id)

    def get_limit(self, task_id: str) -> BudgetLimit | None:
        """Get budget limit for a task."""
        return self._budget_limits.get(task_id)

    def cleanup(self, task_id: str) -> None:
        """Clean up budget tracking for a completed task."""
        self._budget_usage.pop(task_id, None)
        self._budget_limits.pop(task_id, None)
        self._task_start_times.pop(task_id, None)

    def get_system_resources(self) -> ResourceSnapshot:
        """Get current system resource snapshot."""
        return self._resource_manager.get_resource_snapshot()