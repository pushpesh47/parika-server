"""
Unit tests for the Filesystem Tool manifest.
"""

from __future__ import annotations

from parika.tools.filesystem.manifest import (
    FILESYSTEM_OPERATIONS,
    create_filesystem_tool,
)


class TestManifest:
    def test_thirteen_operations_are_defined(self) -> None:
        assert len(FILESYSTEM_OPERATIONS) == 13

    def test_every_operation_has_a_unique_capability_and_tool_id(self) -> None:
        capability_ids = [spec.capability_id for spec in FILESYSTEM_OPERATIONS]
        tool_ids = [spec.tool_id for spec in FILESYSTEM_OPERATIONS]

        assert len(capability_ids) == len(set(capability_ids))
        assert len(tool_ids) == len(set(tool_ids))

    def test_create_filesystem_tool_matches_spec(self) -> None:
        for spec in FILESYSTEM_OPERATIONS:
            tool = create_filesystem_tool(spec)

            assert tool.id == spec.tool_id
            assert tool.capabilities == (spec.capability_id,)
            assert tool.enabled
