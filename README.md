# MCP-CMake: A Tool for CMake Project Management

[日本語のドキュメントはこちら (View in Japanese)](./README_ja.md)

MCP-CMake provides a set of tools to manage CMake-based projects through the Model Context Protocol (MCP). It allows you to configure, build, and test your CMake projects programmatically.

## 🚀 Getting Started

### Server Setup

Start the MCP-CMake server. No arguments are required — the working directory can be supplied at startup or via individual tool calls.

```bash
# Start without a pre-configured project (working directory resolved per tool call)
python -m mcp_cmake.server

# Or pre-configure a project directory at startup (optional)
python -m mcp_cmake.server -w /path/to/your/cmake/project
```

#### Using uv / uvx

If you have [uv](https://docs.astral.sh/uv/) installed, you can run the server directly from the GitHub repository:

```bash
# Run via uvx directly from GitHub
uvx --from git+https://github.com/sr-tream/mcp-cmake mcp-cmake

# Pre-configure a project directory at startup
uvx --from git+https://github.com/sr-tream/mcp-cmake mcp-cmake -w /path/to/your/cmake/project
```

To avoid typing the full URL every time, install the tool once with `uv tool install`:

```bash
# Install from GitHub
uv tool install git+https://github.com/sr-tream/mcp-cmake

# Or install from a local clone (run from the repository root)
uv tool install .
```

After installation, run the server simply as:

```bash
mcp-cmake
mcp-cmake -w /path/to/your/cmake/project
```

Or, from inside the cloned repository using `uv run`:

```bash
# Run without a pre-configured project
uv run python -m mcp_cmake.server

# Pre-configure a project directory at startup
uv run python -m mcp_cmake.server -w /path/to/your/cmake/project
```

### Working Directory Resolution

Each tool resolves its working directory in the following order:

1. The `working_dir` argument passed directly in the tool call.
2. The global `WORKING_DIRECTORY` set via `check_environment` or the `-w` startup flag.
3. The server process's current working directory (`os.getcwd()`).

### Server State

The server maintains two internal states:
-   `WORKING_DIRECTORY`: The absolute path to the CMake project being managed (optional).
-   `IS_HEALTHY`: A boolean flag updated by `check_environment`. Tools no longer require this to be `true` — they resolve the working directory independently.

## 🛠️ Available Tools

### 1. `check_environment`

Verifies the development environment for a CMake project. Checks that `cmake` and `ctest` are available on `PATH` and that a `CMakePresets.json` file exists in the project directory. If `working_dir` is provided the global working directory is updated for subsequent tool calls.

Use this tool to validate a project directory before running `configure_project`, `build_project`, or `test_project`.

-   **Arguments:**
    -   `working_dir` (Optional[str]): Path to the CMake project directory. Updates the global working directory when supplied.
-   **Returns:** A dictionary with check results and an `is_healthy` flag.

**Example:**
```python
# Check the current working directory
client.call_tool("check_environment")

# Validate a specific project and make it the active directory
client.call_tool("check_environment", {"working_dir": "/path/to/project"})
```

### 2. `list_presets`

Lists the configure preset names defined in `CMakePresets.json`. Returns an empty list when the file is absent or contains no `configurePresets`. Use the returned names as the `preset` argument for `configure_project`, `build_project`, and `test_project`.

-   **Arguments:**
    -   `working_dir` (Optional[str]): Override the working directory for this call.
-   **Returns:** A list of preset name strings.

**Example:**
```python
presets = client.call_tool("list_presets")
# or with an explicit directory:
presets = client.call_tool("list_presets", {"working_dir": "/path/to/project"})
print(presets.text)
# Output: ['default', 'ninja-multi-config', 'windows-msvc']
```

### 3. `configure_project`

Configures a CMake project using the named configure preset. Automatically detects the active compiler (GCC, Clang, or MSVC) and injects the appropriate structured-diagnostics flag so that compiler errors returned by `build_project` are easier to parse. Extra CMake cache variables can be supplied via `cmake_defines`. Run this before `build_project` when a build directory does not yet exist.

-   **Arguments:**
    -   `preset` (str): The name of the configure preset to use.
    -   `working_dir` (Optional[str]): Override the working directory for this call.
    -   `cmake_defines` (Optional[dict]): A dictionary of CMake defines to pass with the `-D` flag (e.g., `{"MY_VAR": "VALUE"}`).
-   **Returns:** A success or failure response.

**Example:**
```python
client.call_tool("configure_project", {"preset": "default"})
# or with an explicit directory:
client.call_tool("configure_project", {"preset": "default", "working_dir": "/path/to/project"})
```

### 4. `build_project`

Builds the CMake project using the named build preset. On failure, returns a structured error report parsed from the compiler's diagnostic output (JSON for GCC/Clang, SARIF for MSVC, plain text otherwise) so that errors can be analysed programmatically.

-   **Arguments:**
    -   `preset` (str): The name of the build preset to use.
    -   `working_dir` (Optional[str]): Override the working directory for this call.
    -   `targets` (Optional[list[str]]): A list of specific targets to build.
    -   `verbose` (Optional[bool]): If `True`, enables verbose build output.
    -   `parallel_jobs` (Optional[int]): The number of parallel jobs to use for building.
-   **Returns:** A success or failure response with detailed error information.

**Example:**
```python
# Build the default target
client.call_tool("build_project", {"preset": "default"})

# Build a specific target with 4 parallel jobs
client.call_tool("build_project", {"preset": "default", "targets": ["my_executable"], "parallel_jobs": 4})

# Build using an explicit directory
client.call_tool("build_project", {"preset": "default", "working_dir": "/path/to/project"})
```

### 5. `test_project`

Runs the project's test suite via CTest using the named test preset. Optionally narrows the run to tests whose names match a regex with `test_filter`, enables verbose CTest output, or runs tests in parallel. The project must be built before tests can be run.

-   **Arguments:**
    -   `preset` (str): The name of the test preset to use.
    -   `working_dir` (Optional[str]): Override the working directory for this call.
    -   `test_filter` (Optional[str]): A regex to filter which tests to run.
    -   `verbose` (Optional[bool]): If `True`, enables verbose test output.
    -   `parallel_jobs` (Optional[int]): The number of parallel tests to run.
-   **Returns:** A success or failure response.

**Example:**
```python
# Run all tests
client.call_tool("test_project", {"preset": "default"})

# Run tests matching a specific name
client.call_tool("test_project", {"preset": "default", "test_filter": "MyTest*"})

# Run tests in a specific directory
client.call_tool("test_project", {"preset": "default", "working_dir": "/path/to/project"})
```
