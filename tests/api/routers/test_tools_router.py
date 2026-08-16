"""
Tests for `GET /api/v1/tools`.
"""

from __future__ import annotations


def test_list_tools_returns_registered_tools(client) -> None:
    response = client.get("/api/v1/tools")

    assert response.status_code == 200

    body = response.json()
    tool_ids = {tool["id"] for tool in body["tools"]}

    # Filesystem module registers tool.filesystem_read (capability
    # filesystem.read) as one of its Tools.
    assert "tool.filesystem_read" in tool_ids

    filesystem_read = next(
        tool for tool in body["tools"] if tool["id"] == "tool.filesystem_read"
    )
    assert "filesystem.read" in filesystem_read["capabilities"]
