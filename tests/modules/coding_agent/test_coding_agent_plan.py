"""
Unit tests for plan parsing and validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.modules.coding_agent.agent import CodingTaskDescriptor
from parika.modules.coding_agent.exceptions import (
    CodingPlanParsingError,
    CodingPlanValidationError,
)
from parika.modules.coding_agent.plan import parse_plan_response, validate_plan

KNOWN_CAPABILITIES = frozenset(
    {"coding.search", "filesystem.read", "filesystem.write", "shell.execute", "coding.execute_task"}
)


def _task(**overrides) -> CodingTaskDescriptor:
    defaults = dict(instruction="do something", workspace_root=Path("/workspace"))
    defaults.update(overrides)
    return CodingTaskDescriptor(**defaults)


def test_parse_plain_json() -> None:
    plan = parse_plan_response('{"steps": [{"capability_id": "coding.search", "inputs": {"query": "x"}}]}')
    assert len(plan.steps) == 1
    assert plan.steps[0].capability_id == "coding.search"
    assert plan.steps[0].id == "step_0"


def test_parse_json_wrapped_in_code_fence() -> None:
    text = '```json\n{"steps": [{"capability_id": "coding.search"}]}\n```'
    plan = parse_plan_response(text)
    assert plan.steps[0].capability_id == "coding.search"


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(CodingPlanParsingError):
        parse_plan_response("not json at all")


def test_parse_missing_steps_key_raises() -> None:
    with pytest.raises(CodingPlanParsingError):
        parse_plan_response('{"other": []}')


def test_parse_empty_steps_raises() -> None:
    with pytest.raises(CodingPlanParsingError):
        parse_plan_response('{"steps": []}')


def test_validate_rejects_disallowed_capability_prefix() -> None:
    plan = parse_plan_response('{"steps": [{"capability_id": "memory.remember"}]}')

    with pytest.raises(CodingPlanValidationError):
        validate_plan(plan, _task(), known_capability_ids=KNOWN_CAPABILITIES)


def test_validate_rejects_unknown_capability() -> None:
    plan = parse_plan_response('{"steps": [{"capability_id": "coding.unknown_op"}]}')

    with pytest.raises(CodingPlanValidationError):
        validate_plan(plan, _task(), known_capability_ids=KNOWN_CAPABILITIES)


def test_validate_rejects_write_outside_workspace_root() -> None:
    plan = parse_plan_response(
        '{"steps": [{"capability_id": "filesystem.write", '
        '"inputs": {"path": "/etc/passwd"}}]}'
    )

    with pytest.raises(CodingPlanValidationError):
        validate_plan(
            plan, _task(workspace_root=Path("/workspace")), known_capability_ids=KNOWN_CAPABILITIES
        )


def test_validate_accepts_write_inside_workspace_root(tmp_path: Path) -> None:
    target = tmp_path / "file.py"
    plan = parse_plan_response(
        f'{{"steps": [{{"capability_id": "filesystem.write", "inputs": {{"path": "{target}"}}}}]}}'
    )

    validate_plan(
        plan, _task(workspace_root=tmp_path), known_capability_ids=KNOWN_CAPABILITIES
    )


def test_validate_rejects_unknown_dependency() -> None:
    plan = parse_plan_response(
        '{"steps": [{"id": "a", "capability_id": "coding.search", "depends_on": ["missing"]}]}'
    )

    with pytest.raises(CodingPlanValidationError):
        validate_plan(plan, _task(), known_capability_ids=KNOWN_CAPABILITIES)


def test_validate_rejects_recursion_beyond_max_depth() -> None:
    plan = parse_plan_response('{"steps": [{"capability_id": "coding.execute_task"}]}')

    with pytest.raises(CodingPlanValidationError):
        validate_plan(
            plan,
            _task(depth=3, max_depth=3),
            known_capability_ids=KNOWN_CAPABILITIES,
        )


def test_validate_allows_recursion_within_max_depth() -> None:
    plan = parse_plan_response('{"steps": [{"capability_id": "coding.execute_task"}]}')

    validate_plan(
        plan,
        _task(depth=0, max_depth=3),
        known_capability_ids=KNOWN_CAPABILITIES,
    )


def test_validate_require_test_run_rejects_plan_without_test_step() -> None:
    plan = parse_plan_response('{"steps": [{"capability_id": "coding.search"}]}')

    with pytest.raises(CodingPlanValidationError):
        validate_plan(
            plan,
            _task(require_test_run=True),
            known_capability_ids=KNOWN_CAPABILITIES,
        )


def test_validate_require_test_run_accepts_plan_with_pytest_step() -> None:
    plan = parse_plan_response(
        '{"steps": [{"capability_id": "shell.execute", '
        '"inputs": {"command": ["pytest"]}}]}'
    )

    validate_plan(
        plan,
        _task(require_test_run=True),
        known_capability_ids=KNOWN_CAPABILITIES,
    )
