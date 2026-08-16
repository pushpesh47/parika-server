"""
Unit tests for `parika.tools.runtime_info.manifest`.
"""

from __future__ import annotations

from parika.tools.runtime_info.manifest import (
    RUNTIME_INFO_CAPABILITY_ID,
    RUNTIME_INFO_TOOL_ID,
    create_runtime_info_tool,
)


class TestCreateRuntimeInfoTool:
    def test_builds_expected_tool(self) -> None:
        tool = create_runtime_info_tool()

        assert tool.id == RUNTIME_INFO_TOOL_ID
        assert tool.capabilities == (RUNTIME_INFO_CAPABILITY_ID,)
        assert tool.enabled is True
