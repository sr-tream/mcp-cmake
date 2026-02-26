# mcp_cmake/server.py
import argparse
import os
from typing import Optional

from fastmcp import Context, FastMCP

from . import core

# Initialize the FastMCP server
mcp = FastMCP(
    "MCP-CMake Server",
    description="A server for managing CMake projects.",
    version="0.2.0",
)

# --- Server State ---
WORKING_DIRECTORY: Optional[str] = None
IS_HEALTHY: bool = False


def update_state(healthy: bool, working_dir: Optional[str] = None):
    """Updates the server's health and working directory."""
    global IS_HEALTHY, WORKING_DIRECTORY
    IS_HEALTHY = healthy
    if working_dir:
        WORKING_DIRECTORY = working_dir


@mcp.tool
def health_check(ctx: Context, working_dir: Optional[str] = None) -> dict:
    """
    Checks the development environment's health, updates server state, and
    optionally sets a new working directory.
    """
    result = core.health_check(working_dir)
    update_state(result.get("is_healthy", False), result.get("working_directory"))
    return result


def tool_guard(func):
    """Decorator that resolves the working directory for a tool call.

    Resolution order:
    1. ``working_dir`` passed explicitly in the tool call.
    2. The global ``WORKING_DIRECTORY`` set via ``health_check`` or ``-w``.
    3. The current working directory (``os.getcwd()``).
    """

    def wrapper(*args, **kwargs):
        wd = kwargs.get("working_dir")
        if wd is None:
            wd = WORKING_DIRECTORY
        if wd is None:
            wd = os.getcwd()
        kwargs["working_dir"] = wd
        return func(*args, **kwargs)

    return wrapper


@mcp.tool
@tool_guard
def list_presets(ctx: Context, working_dir: Optional[str] = None) -> list[str]:
    """Lists available configure presets."""
    return core.list_presets(working_dir)


@mcp.tool
@tool_guard
def configure_project(ctx: Context, preset: str, working_dir: Optional[str] = None, cmake_defines: Optional[dict] = None) -> dict:
    """Configures the CMake project."""
    return core.configure_project(working_dir, preset, cmake_defines)


@mcp.tool
@tool_guard
def build_project(
    ctx: Context,
    preset: str,
    working_dir: Optional[str] = None,
    targets: Optional[list[str]] = None,
    verbose: bool = False,
    parallel_jobs: Optional[int] = None,
) -> dict:
    """Builds the project."""
    return core.build_project(working_dir, preset, targets, verbose, parallel_jobs)


@mcp.tool
@tool_guard
def test_project(
    ctx: Context,
    preset: str,
    working_dir: Optional[str] = None,
    test_filter: Optional[str] = None,
    verbose: bool = False,
    parallel_jobs: Optional[int] = None,
) -> dict:
    """Runs tests for the project."""
    return core.test_project(working_dir, preset, test_filter, verbose, parallel_jobs)


def main():
    """
    Initializes and starts the McpServer, handling command-line arguments.
    """
    parser = argparse.ArgumentParser(description="MCP-CMake Server")
    parser.add_argument(
        "-w",
        "--working-dir",
        type=str,
        help="Set the initial CMake project working directory.",
    )
    # Add arguments for transport, but let FastMCP handle them
    parser.add_argument("--stdio", action="store_true", help="Run with stdio transport (default).")
    parser.add_argument("--http", action="store_true", help="Run with HTTP transport.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host for HTTP transport.")
    parser.add_argument("--port", type=int, default=8000, help="Port for HTTP transport.")

    args = parser.parse_args()

    if args.working_dir:
        initial_dir = os.path.abspath(args.working_dir)
        print(f"Initializing with working directory: {initial_dir}")
        # Run initial health check
        result = core.health_check(initial_dir)
        update_state(result.get("is_healthy", False), result.get("working_directory"))
        print(f"Initial health check {'succeeded' if IS_HEALTHY else 'failed'}.")

    # FastMCP's run method can handle the transport arguments directly
    if args.http:
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
