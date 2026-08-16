"""
PARIKA Coding Agent - Plan Parsing and Validation

Parses the model's structured decomposition response (a fixed JSON
schema, never free-form text) into an immutable `CodingPlan`, and
implements the deterministic "review before modification" validation
gate -- a real, enforced gate: a plan that fails validation is
rejected before any step executes. See
docs/development/Module_Guide.md sections
8.3.3, 8.6, and 8.7.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent import CodingTaskDescriptor
from .exceptions import CodingPlanParsingError, CodingPlanValidationError

_ALLOWED_CAPABILITY_PREFIXES: tuple[str, ...] = ("coding.", "filesystem.", "shell.")
_CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_PATH_ARGUMENT_KEYS: tuple[str, ...] = ("path", "cwd")


@dataclass(frozen=True, slots=True, kw_only=True)
class CodingPlanStep:
    id: str
    capability_id: str
    inputs: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class CodingPlan:
    steps: tuple[CodingPlanStep, ...]


def parse_plan_response(text: str) -> CodingPlan:
    """
    Parse a model response into a `CodingPlan`.

    Accepts a bare JSON object or one wrapped in a Markdown code
    fence (many models wrap JSON output in ```json ... ``` even when
    explicitly asked not to).

    Raises:
        CodingPlanParsingError:
            If `text` is not valid JSON, or does not match the fixed
            `{"steps": [...]}` schema.
    """

    candidate = text.strip()
    fence_match = _CODE_FENCE_PATTERN.search(candidate)

    if fence_match:
        candidate = fence_match.group(1).strip()

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as ex:
        raise CodingPlanParsingError(
            f"The model's response was not valid JSON: {ex}"
        ) from ex

    if not isinstance(data, dict) or "steps" not in data:
        raise CodingPlanParsingError(
            "The model's response must be a JSON object with a "
            "'steps' array."
        )

    raw_steps = data["steps"]

    if not isinstance(raw_steps, list) or not raw_steps:
        raise CodingPlanParsingError(
            "'steps' must be a non-empty JSON array."
        )

    steps: list[CodingPlanStep] = []

    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict) or "capability_id" not in raw_step:
            raise CodingPlanParsingError(
                f"Step {index} must be an object with a 'capability_id'."
            )

        steps.append(
            CodingPlanStep(
                id=str(raw_step.get("id", f"step_{index}")),
                capability_id=str(raw_step["capability_id"]),
                inputs=dict(raw_step.get("inputs", {}) or {}),
                depends_on=tuple(str(item) for item in raw_step.get("depends_on", ()) or ()),
            )
        )

    return CodingPlan(steps=tuple(steps))


def validate_plan(
    plan: CodingPlan,
    task: CodingTaskDescriptor,
    *,
    known_capability_ids: frozenset[str],
) -> None:
    """
    Validate `plan` before any step executes.

    Raises:
        CodingPlanValidationError:
            If any step names an unknown/disallowed capability, a
            `filesystem.write`/`shell.execute` step targets a path
            outside `task.workspace_root`/`task.allowed_write_roots`,
            a step depends on an unknown step id, or a nested
            `coding.execute_task` step would exceed `task.max_depth`.
    """

    step_ids = {step.id for step in plan.steps}
    authorized_roots = (task.workspace_root, *task.allowed_write_roots)

    for step in plan.steps:
        if not step.capability_id.startswith(_ALLOWED_CAPABILITY_PREFIXES):
            raise CodingPlanValidationError(
                f"Step '{step.id}' names capability '{step.capability_id}', "
                "which is outside the Coding Agent's allowed "
                f"{_ALLOWED_CAPABILITY_PREFIXES} prefixes."
            )

        if step.capability_id not in known_capability_ids:
            raise CodingPlanValidationError(
                f"Step '{step.id}' names capability "
                f"'{step.capability_id}', which is not a known, "
                "enabled Capability."
            )

        if step.capability_id == "coding.execute_task":
            if task.depth + 1 > task.max_depth:
                raise CodingPlanValidationError(
                    f"Step '{step.id}' would recurse into "
                    "'coding.execute_task' at depth "
                    f"{task.depth + 1}, exceeding max_depth="
                    f"{task.max_depth}."
                )

        for dependency_id in step.depends_on:
            if dependency_id not in step_ids:
                raise CodingPlanValidationError(
                    f"Step '{step.id}' depends on unknown step "
                    f"'{dependency_id}'."
                )

        _validate_step_paths(step, authorized_roots)

    if task.require_test_run and not _has_test_step(plan):
        raise CodingPlanValidationError(
            "[coding_agent].require_test_run is enabled, but this "
            "plan does not include a shell.execute step running a "
            "test command."
        )


def _validate_step_paths(step: CodingPlanStep, authorized_roots: tuple[Path, ...]) -> None:
    if not step.capability_id.startswith(("filesystem.write", "shell.execute", "coding.patch_generate")):
        return

    for key in _PATH_ARGUMENT_KEYS:
        raw_value = step.inputs.get(key)

        if raw_value is None:
            continue

        candidate = Path(str(raw_value)).resolve()

        if not any(
            candidate == root.resolve() or root.resolve() in candidate.parents
            for root in authorized_roots
        ):
            raise CodingPlanValidationError(
                f"Step '{step.id}' targets path '{candidate}', which "
                "is outside every authorized root "
                f"({[str(r) for r in authorized_roots]})."
            )


def _has_test_step(plan: CodingPlan) -> bool:
    test_markers = ("pytest", "test", "jest", "phpunit", "go test", "cargo test")

    for step in plan.steps:
        if step.capability_id != "shell.execute":
            continue

        command = step.inputs.get("command")

        if isinstance(command, list) and any(
            any(marker in str(part).lower() for marker in test_markers)
            for part in command
        ):
            return True

    return False
