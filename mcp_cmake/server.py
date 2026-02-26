# mcp_cmake/server.py
import argparse
import functools
import os
from typing import Optional

from fastmcp import Context, FastMCP

from . import core

# Initialize the FastMCP server
mcp = FastMCP("MCP-CMake Server")

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
def check_environment(ctx: Context, working_dir: Optional[str] = None) -> dict:
    """
    Verifies the development environment for a CMake project.

    Checks that the ``cmake`` and ``ctest`` executables are available on PATH and
    that a ``CMakePresets.json`` file exists in the project directory.  If
    ``working_dir`` is provided the global working directory is updated so that
    subsequent tool calls use it by default.

    Use this tool to validate a project directory before running
    ``configure_project``, ``build_project``, or ``test_project``.
    """
    result = core.check_environment(working_dir)
    update_state(result.get("is_healthy", False), result.get("working_directory"))
    return result


def tool_guard(func):
    """Decorator that resolves the working directory for a tool call.

    Resolution order:
    1. ``working_dir`` passed explicitly in the tool call.
    2. The global ``WORKING_DIRECTORY`` set via ``check_environment`` or ``-w``.
    3. The current working directory (``os.getcwd()``).
    """

    @functools.wraps(func)
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
def list_presets(ctx: Context, working_dir: Optional[str] = None) -> dict:
    """
    Lists all available preset names grouped by type (configure, build, test,
    workflow) by delegating to ``cmake --list-presets``.

    Presets from both ``CMakePresets.json`` and ``CMakeUserPresets.json`` are
    included automatically.  Returns a dict whose keys are preset types and
    whose values are lists of preset names, e.g.
    ``{"configure": ["debug", "release"], "build": ["debug"], ...}``.
    """
    return core.list_presets(working_dir)


@mcp.tool
@tool_guard
def configure_project(
    ctx: Context,
    preset: str,
    working_dir: Optional[str] = None,
    cmake_defines: Optional[dict] = None,
    head: Optional[int] = None,
    tail: Optional[int] = None,
) -> dict:
    """
    Configures a CMake project using the named configure preset.

    Automatically detects the active compiler (GCC, Clang, or MSVC) and injects
    the appropriate structured-diagnostics flag so that compiler errors returned
    by ``build_project`` are easier to parse.  Extra CMake cache variables can be
    supplied via ``cmake_defines`` (e.g. ``{"BUILD_TESTS": "ON"}``).

    The full configure log (stdout + stderr from both configure passes) is
    always included in the ``configure_log`` field of the response.

    Use ``head`` and/or ``tail`` to limit the number of log lines returned.
    When a limit causes lines to be omitted, the complete log is saved to a
    temporary file and a ``<configure_output_striped>`` marker is inserted at
    the cut point indicating how many lines were stripped and the path to the
    file.

    Run this before ``build_project`` when a build directory does not yet exist.
    """
    return core.configure_project(working_dir, preset, cmake_defines, head, tail)


@mcp.tool
@tool_guard
def build_project(
    ctx: Context,
    preset: str,
    working_dir: Optional[str] = None,
    targets: Optional[list[str]] = None,
    verbose: bool = False,
    parallel_jobs: Optional[int] = None,
    head: Optional[int] = None,
    tail: Optional[int] = None,
) -> dict:
    """
    Builds the CMake project using the named build preset.

    On failure, returns a structured error report parsed from the compiler's
    diagnostic output (JSON for GCC/Clang, SARIF for MSVC, plain text
    otherwise) so that errors can be analysed programmatically.

    The full build log (stdout + stderr) is always included in the
    ``build_log`` field of the response.

    Optionally restrict the build to specific ``targets``, enable verbose
    compiler output with ``verbose``, or speed up the build with
    ``parallel_jobs``.

    Use ``head`` and/or ``tail`` to limit the number of log lines returned.
    When a limit causes lines to be omitted, the complete log is saved to a
    temporary file and a ``<build_output_striped>`` marker is inserted at the
    cut point indicating how many lines were stripped and the path to the file.
    """
    return core.build_project(working_dir, preset, targets, verbose, parallel_jobs, head, tail)


@mcp.tool
@tool_guard
def test_project(
    ctx: Context,
    preset: str,
    working_dir: Optional[str] = None,
    test_filter: Optional[str] = None,
    verbose: bool = False,
    parallel_jobs: Optional[int] = None,
    head: Optional[int] = None,
    tail: Optional[int] = None,
) -> dict:
    """
    Runs the project's test suite via CTest using the named test preset.

    The full test log (stdout + stderr) is always included in the ``test_log``
    field of the response.

    Optionally narrow the run to tests whose names match a regex with
    ``test_filter``, enable verbose CTest output with ``verbose``, or run tests
    in parallel with ``parallel_jobs``.  The project must be built before tests
    can be run.

    Use ``head`` and/or ``tail`` to limit the number of log lines returned.
    When a limit causes lines to be omitted, the complete log is saved to a
    temporary file and a ``<test_output_striped>`` marker is inserted at the
    cut point indicating how many lines were stripped and the path to the file.
    """
    return core.test_project(working_dir, preset, test_filter, verbose, parallel_jobs, head, tail)


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
        # Run initial environment check
        result = core.check_environment(initial_dir)
        update_state(result.get("is_healthy", False), result.get("working_directory"))
        print(f"Initial environment check {'succeeded' if IS_HEALTHY else 'failed'}.")

    # FastMCP's run method can handle the transport arguments directly
    if args.http:
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
