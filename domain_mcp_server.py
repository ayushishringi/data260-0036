"""STDIO MCP server for the three s0036_rel domain tools."""
import logging

from hw5_tools.domain import DomainStore, envelope

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("s0036_domain_mcp")
store = DomainStore.fixture()

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # keeps offline tests/imports usable before pip install mcp[cli]
    FastMCP = None

if FastMCP:
    mcp = FastMCP("s0036_rel")

    @mcp.tool()
    def search(query: str, limit: int = 5) -> dict:
        return store.search(query, limit)

    @mcp.tool()
    def detail(id: str | int) -> dict:
        return store.detail(id)

    @mcp.tool()
    def aggregate(severity: str | None = None) -> dict:
        return store.aggregate(severity)

    if __name__ == "__main__":
        mcp.run(transport="stdio")
