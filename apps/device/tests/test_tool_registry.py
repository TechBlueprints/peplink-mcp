"""MCP tool registry tests."""

from peplink_device_mcp.tool_registry import IMPLEMENTED_TOOLS, REGISTERED_TOOLS


def test_implemented_tools_registered():
    for name in IMPLEMENTED_TOOLS:
        assert name in REGISTERED_TOOLS
    assert REGISTERED_TOOLS["peplink_get_info_location"]["tier"] == "read_only"
