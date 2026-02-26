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

### Working Directory Resolution

Each tool resolves its working directory in the following order:

1. The `working_dir` argument passed directly in the tool call.
2. The global `WORKING_DIRECTORY` set via `health_check` or the `-w` startup flag.
3. The server process's current working directory (`os.getcwd()`).

### Server State

The server maintains two internal states:
-   `WORKING_DIRECTORY`: The absolute path to the CMake project being managed (optional).
-   `IS_HEALTHY`: A boolean flag updated by `health_check`. Tools no longer require this to be `true` — they resolve the working directory independently.

## 🛠️ Available Tools

### 1. `health_check`

Verifies the development environment and sets the server to a `Healthy` state if successful. This tool can also be used to switch the working directory to a new project.

-   **Arguments:**
    -   `working_dir` (Optional[str]): The absolute path to a CMake project directory. If provided, the server will switch to this directory.
-   **Returns:** A dictionary containing the check results.

**Example:**
```python
# Run a health check on the current working directory
client.call_tool("health_check")

# Switch to a new project and check its health
client.call_tool("health_check", {"working_dir": "/path/to/another/project"})
```

### 2. `list_presets`

Lists the available `configurePresets` from the `CMakePresets.json` file in the working directory.

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

Configures the CMake project using a specified preset. This tool automatically detects the compiler and enables structured diagnostic logging (JSON for GCC/Clang, SARIF for MSVC).

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

Builds the project using a specified build preset. If the build fails, it returns a structured error report parsed from the compiler's output.

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

Runs tests for the project using a specified test preset.

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
