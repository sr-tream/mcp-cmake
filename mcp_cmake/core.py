# mcp_cmake/core.py

import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

from .helpers import format_error_for_llm_analysis
from .models import ErrorDetail, FailureResponse, SuccessResponse


def check_environment(working_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Verifies the development environment for a CMake project.
    """
    if not working_dir or not os.path.isdir(working_dir):
        return {
            "working_directory": working_dir,
            "is_healthy": False,
            "error": "Working directory not set or does not exist.",
        }

    working_dir = os.path.abspath(working_dir)

    def find_executable(name):
        path = shutil.which(name)
        return {"found": bool(path), "path": path}

    cmakepresets_path = os.path.join(working_dir, "CMakePresets.json")

    checks = {
        "cmake_executable": find_executable("cmake"),
        "ctest_executable": find_executable("ctest"),
        "cmakepresets_file": {
            "found": os.path.isfile(cmakepresets_path),
            "path": cmakepresets_path,
        },
        "preset_consistency": {"passed": False, "details": "Check not implemented."},
    }

    all_checks_passed = all(check["found"] for name, check in checks.items() if name != "preset_consistency")

    # For now, preset_consistency is not a blocking check.
    # This can be implemented later.
    if all_checks_passed:
        checks["preset_consistency"]["passed"] = True
        checks["preset_consistency"]["details"] = "Consistency check passed (placeholder)."

    return {
        "working_directory": working_dir,
        "is_healthy": all_checks_passed,
        "checks": checks,
    }


def list_presets(working_dir: str) -> Dict[str, List[str]]:
    """
    Lists all available presets (configure, build, test, workflow) by invoking
    ``cmake --list-presets={type}``.  Presets from both ``CMakePresets.json``
    and ``CMakeUserPresets.json`` are included automatically.
    """
    result: Dict[str, List[str]] = {}
    for preset_type in ["configure", "build", "test", "workflow"]:
        try:
            proc = subprocess.run(
                ["cmake", f"--list-presets={preset_type}"],
                cwd=working_dir,
                capture_output=True,
                text=True,
            )
            names: List[str] = []
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    stripped = line.strip()
                    parts = stripped.split('"')
                    if stripped.startswith('"') and len(parts) >= 2:
                        # Lines are: "name" or "name" - description
                        names.append(parts[1])
            result[preset_type] = names
        except FileNotFoundError:
            result[preset_type] = []
    return result


def _apply_log_limits(log: str, head: Optional[int], tail: Optional[int], tag: str = "build_output_striped") -> str:
    """Return *log* optionally trimmed to *head* first and/or *tail* last lines.

    When any lines are omitted a ``<{tag}>`` marker is inserted at the cut
    point and the full log is preserved in a temporary file whose path is
    embedded in the marker.
    """
    if head is None and tail is None:
        return log

    lines = log.splitlines(keepends=True)
    total = len(lines)

    # How many lines would actually be stripped?
    if head is not None and tail is not None:
        stripped_count = max(0, total - head - tail)
    elif head is not None:
        stripped_count = max(0, total - head)
    else:  # tail only
        stripped_count = max(0, total - tail)

    if stripped_count == 0:
        # No lines need to be removed; return the log unchanged.
        return log

    # Persist the full log to a temp file so the caller can inspect it.
    fd, tmp_path = tempfile.mkstemp(suffix=".log", prefix="mcp_cmake_build_")
    with os.fdopen(fd, "w") as fh:
        fh.write(log)

    marker = (
        f"<{tag}>Here stripped {stripped_count} lines, "
        f"due to head/tail output limits. "
        f"You can find full log in file `{tmp_path}`</{tag}>"
    )

    if head is not None and tail is not None:
        head_lines = lines[:head]
        tail_lines = lines[-tail:] if tail > 0 else []
        parts = head_lines + [marker + "\n"] + tail_lines
    elif head is not None:
        parts = lines[:head] + [marker]
    else:  # tail only
        parts = ([marker + "\n"] + lines[-tail:]) if tail > 0 else [marker]

    return "".join(parts)


def configure_preset(
    working_dir: str,
    preset: str,
    cmake_defines: Optional[Dict[str, str]] = None,
    head: Optional[int] = None,
    tail: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Configures the CMake project using a named preset.
    """
    try:
        # 1. Initial configure to determine compiler
        build_dir = os.path.join(working_dir, "build", preset)
        if not os.path.exists(build_dir):
            os.makedirs(build_dir)

        initial_cmd = ["cmake", "-S", working_dir, "-B", build_dir, f"--preset={preset}"]
        initial_result = subprocess.run(initial_cmd, check=True, cwd=working_dir, capture_output=True, text=True)
        initial_log = initial_result.stdout + initial_result.stderr

        # 2. Read compiler IDs and existing flag values from CMakeCache.txt.
        # _INIT variables only take effect when the cache is first created, so we
        # read the already-cached CMAKE_C_FLAGS / CMAKE_CXX_FLAGS and append the
        # diagnostic flag to them on the second configure pass.
        # Cache format: KEY:TYPE=VALUE — parse key exactly to avoid matching
        # entries like CMAKE_CXX_COMPILER_ID-ADVANCED which share the same prefix.
        cache_file = os.path.join(build_dir, "CMakeCache.txt")
        c_compiler_id = None
        cxx_compiler_id = None
        c_flags = ""
        cxx_flags = ""
        with open(cache_file, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith(("#", "//")) or "=" not in stripped:
                    continue
                key_and_type, value_part = stripped.split("=", 1)
                if ":" not in key_and_type:
                    continue
                key, _ = key_and_type.split(":", 1)
                val = value_part.strip()
                if key == "CMAKE_CXX_COMPILER_ID" and not cxx_compiler_id:
                    cxx_compiler_id = val if val else None
                elif key == "CMAKE_C_COMPILER_ID" and not c_compiler_id:
                    c_compiler_id = val if val else None
                elif key == "CMAKE_CXX_FLAGS":
                    cxx_flags = val
                elif key == "CMAKE_C_FLAGS":
                    c_flags = val

        # 3. Compute diagnostic flags per language independently so that mixed
        # toolchains (e.g. MSVC for C++, GNU for C) get the correct flag for each.
        def _diag_flags_for(compiler: Optional[str]) -> str:
            if compiler in ["GNU", "Clang"]:
                return "-fdiagnostics-format=json"
            if compiler == "MSVC":
                return "/diagnostics:sarif"
            return ""

        cxx_diag_flags = _diag_flags_for(cxx_compiler_id)
        c_diag_flags = _diag_flags_for(c_compiler_id)

        # 4. Final configure with diagnostic flags appended to any existing flags.
        # Use CMAKE_C_FLAGS / CMAKE_CXX_FLAGS (not _INIT) so they take effect even
        # when the cache already exists (e.g. toolchain-based presets).
        # Note: check=True is intentionally omitted here so that a non-zero
        # returncode can be returned with configure_log included in the response.
        final_cmd = ["cmake", "-S", working_dir, "-B", build_dir, f"--preset={preset}"]
        if cxx_diag_flags and cxx_compiler_id:
            combined = f"{cxx_flags} {cxx_diag_flags}".strip()
            final_cmd.append(f"-DCMAKE_CXX_FLAGS={combined}")
        if c_diag_flags and c_compiler_id:
            combined = f"{c_flags} {c_diag_flags}".strip()
            final_cmd.append(f"-DCMAKE_C_FLAGS={combined}")

        if cmake_defines:
            for key, value in cmake_defines.items():
                final_cmd.append(f"-D{key}={value}")

        result = subprocess.run(final_cmd, cwd=working_dir, capture_output=True, text=True)

        configure_log = _apply_log_limits(
            initial_log + result.stdout + result.stderr, head, tail, tag="configure_output_striped"
        )

        if result.returncode == 0:
            response = SuccessResponse().dict()
            response["configure_log"] = configure_log
            return response
        else:
            response = FailureResponse(
                summary="CMake configuration failed.", errors=[ErrorDetail(message=result.stderr, severity="error")]
            ).dict()
            response["configure_log"] = configure_log
            return response

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        error_message = e.stderr if isinstance(e, subprocess.CalledProcessError) else str(e)
        return FailureResponse(
            summary="CMake configuration failed.", errors=[ErrorDetail(message=error_message, severity="error")]
        ).dict()


def build_preset(
    working_dir: str,
    preset: str,
    targets: Optional[List[str]] = None,
    verbose: bool = False,
    parallel_jobs: Optional[int] = None,
    head: Optional[int] = None,
    tail: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Builds the project using a named preset.
    """
    try:
        build_dir = os.path.join(working_dir, "build", preset)
        cmd = ["cmake", "--build", build_dir, f"--preset={preset}"]
        if targets:
            cmd.extend(["--target", *targets])
        if verbose:
            cmd.append("--verbose")
        if parallel_jobs:
            cmd.extend(["--parallel", str(parallel_jobs)])

        result = subprocess.run(cmd, cwd=working_dir, capture_output=True, text=True)

        build_log = _apply_log_limits(result.stdout + result.stderr, head, tail, tag="build_output_striped")

        if result.returncode == 0:
            response = SuccessResponse().dict()
            response["build_log"] = build_log
            return response
        else:
            # Determine compiler to know the error format.
            # Prefer CMAKE_CXX_COMPILER_ID; fall back to CMAKE_C_COMPILER_ID for
            # C-only and toolchain-based projects.
            # Use exact key matching to avoid matching keys like CMAKE_CXX_COMPILER_ID-ADVANCED.
            cache_file = os.path.join(build_dir, "CMakeCache.txt")
            compiler_id = "Unknown"
            with open(cache_file, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith(("#", "//")) or "=" not in stripped:
                        continue
                    key_and_type, value_part = stripped.split("=", 1)
                    if ":" not in key_and_type:
                        continue
                    key, _ = key_and_type.split(":", 1)
                    val = value_part.strip()
                    if key == "CMAKE_CXX_COMPILER_ID" and val:
                        compiler_id = val
                        break  # CXX takes precedence; stop scanning
                    elif key == "CMAKE_C_COMPILER_ID" and val and compiler_id == "Unknown":
                        compiler_id = val
                        # Don't break — keep scanning for CMAKE_CXX_COMPILER_ID

            error_format = "raw"
            if compiler_id in ["GNU", "Clang"]:
                error_format = "json"
            elif compiler_id == "MSVC":
                error_format = "sarif"

            formatted_error = format_error_for_llm_analysis(result.stderr, error_format)
            response = FailureResponse(**formatted_error).dict()
            response["build_log"] = build_log
            return response

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        error_message = e.stderr if isinstance(e, subprocess.CalledProcessError) else str(e)
        return FailureResponse(summary="Build failed.", errors=[ErrorDetail(message=error_message, severity="error")]).dict()


def test_preset(
    working_dir: str,
    preset: str,
    test_filter: Optional[str] = None,
    verbose: bool = False,
    parallel_jobs: Optional[int] = None,
    head: Optional[int] = None,
    tail: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Runs tests for the project using a named preset.
    """
    try:
        build_dir = os.path.join(working_dir, "build", preset)
        cmd = ["ctest", f"--preset={preset}"]
        if test_filter:
            cmd.extend(["-R", test_filter])
        if verbose:
            cmd.append("--verbose")
        if parallel_jobs:
            cmd.extend(["-j", str(parallel_jobs)])

        result = subprocess.run(cmd, cwd=build_dir, capture_output=True, text=True)

        test_log = _apply_log_limits(result.stdout + result.stderr, head, tail, tag="test_output_striped")

        if result.returncode == 0:
            response = SuccessResponse(message="All tests passed.").dict()
            response["test_log"] = test_log
            return response
        else:
            # CTest output is not structured, so we treat it as raw text.
            response = FailureResponse(
                summary="Tests failed.", errors=[ErrorDetail(message=result.stdout + result.stderr, severity="error")]
            ).dict()
            response["test_log"] = test_log
            return response

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        error_message = e.stderr if isinstance(e, subprocess.CalledProcessError) else str(e)
        return FailureResponse(
            summary="Test execution failed.", errors=[ErrorDetail(message=error_message, severity="error")]
        ).dict()


def _read_compiler_ids_from_cache(cache_file: str):
    """Read compiler IDs and existing flag values from a CMakeCache.txt file.

    Returns a tuple: (c_compiler_id, cxx_compiler_id, c_flags, cxx_flags).
    """
    c_compiler_id = None
    cxx_compiler_id = None
    c_flags = ""
    cxx_flags = ""
    with open(cache_file, "r") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith(("#", "//")) or "=" not in stripped:
                continue
            key_and_type, value_part = stripped.split("=", 1)
            if ":" not in key_and_type:
                continue
            key, _ = key_and_type.split(":", 1)
            val = value_part.strip()
            if key == "CMAKE_CXX_COMPILER_ID" and not cxx_compiler_id:
                cxx_compiler_id = val if val else None
            elif key == "CMAKE_C_COMPILER_ID" and not c_compiler_id:
                c_compiler_id = val if val else None
            elif key == "CMAKE_CXX_FLAGS":
                cxx_flags = val
            elif key == "CMAKE_C_FLAGS":
                c_flags = val
    return c_compiler_id, cxx_compiler_id, c_flags, cxx_flags


def configure(
    working_dir: str,
    build_dir: Optional[str] = None,
    generator: Optional[str] = None,
    cmake_defines: Optional[Dict[str, str]] = None,
    head: Optional[int] = None,
    tail: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Configures a CMake project without using a preset.

    ``working_dir`` is used as the source directory (``-S``).  ``build_dir``
    defaults to ``<working_dir>/build`` when not supplied.  An optional CMake
    generator can be requested via ``generator`` (e.g. ``"Ninja"``).
    """
    try:
        if build_dir is None:
            build_dir = os.path.join(working_dir, "build")
        if not os.path.exists(build_dir):
            os.makedirs(build_dir)

        def _diag_flags_for(compiler: Optional[str]) -> str:
            if compiler in ["GNU", "Clang"]:
                return "-fdiagnostics-format=json"
            if compiler == "MSVC":
                return "/diagnostics:sarif"
            return ""

        # 1. Initial configure to determine compiler
        initial_cmd = ["cmake", "-S", working_dir, "-B", build_dir]
        if generator:
            initial_cmd.extend(["-G", generator])
        initial_result = subprocess.run(initial_cmd, check=True, cwd=working_dir, capture_output=True, text=True)
        initial_log = initial_result.stdout + initial_result.stderr

        # 2. Read compiler IDs and existing flag values from CMakeCache.txt.
        cache_file = os.path.join(build_dir, "CMakeCache.txt")
        c_compiler_id, cxx_compiler_id, c_flags, cxx_flags = _read_compiler_ids_from_cache(cache_file)

        # 3. Final configure with diagnostic flags appended to any existing flags.
        # Note: check=True is intentionally omitted here so that a non-zero
        # returncode can be returned with configure_log included in the response.
        final_cmd = ["cmake", "-S", working_dir, "-B", build_dir]
        if generator:
            final_cmd.extend(["-G", generator])
        cxx_diag_flags = _diag_flags_for(cxx_compiler_id)
        c_diag_flags = _diag_flags_for(c_compiler_id)
        if cxx_diag_flags and cxx_compiler_id:
            combined = f"{cxx_flags} {cxx_diag_flags}".strip()
            final_cmd.append(f"-DCMAKE_CXX_FLAGS={combined}")
        if c_diag_flags and c_compiler_id:
            combined = f"{c_flags} {c_diag_flags}".strip()
            final_cmd.append(f"-DCMAKE_C_FLAGS={combined}")
        if cmake_defines:
            for key, value in cmake_defines.items():
                final_cmd.append(f"-D{key}={value}")

        result = subprocess.run(final_cmd, cwd=working_dir, capture_output=True, text=True)

        configure_log = _apply_log_limits(
            initial_log + result.stdout + result.stderr, head, tail, tag="configure_output_striped"
        )

        if result.returncode == 0:
            response = SuccessResponse().dict()
            response["configure_log"] = configure_log
            return response
        else:
            response = FailureResponse(
                summary="CMake configuration failed.", errors=[ErrorDetail(message=result.stderr, severity="error")]
            ).dict()
            response["configure_log"] = configure_log
            return response

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        error_message = e.stderr if isinstance(e, subprocess.CalledProcessError) else str(e)
        return FailureResponse(
            summary="CMake configuration failed.", errors=[ErrorDetail(message=error_message, severity="error")]
        ).dict()


def build(
    working_dir: str,
    build_dir: Optional[str] = None,
    targets: Optional[List[str]] = None,
    verbose: bool = False,
    parallel_jobs: Optional[int] = None,
    head: Optional[int] = None,
    tail: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Builds a CMake project without using a preset.

    ``build_dir`` defaults to ``<working_dir>/build`` when not supplied.
    """
    try:
        if build_dir is None:
            build_dir = os.path.join(working_dir, "build")

        cmd = ["cmake", "--build", build_dir]
        if targets:
            cmd.extend(["--target", *targets])
        if verbose:
            cmd.append("--verbose")
        if parallel_jobs:
            cmd.extend(["--parallel", str(parallel_jobs)])

        result = subprocess.run(cmd, cwd=working_dir, capture_output=True, text=True)

        build_log = _apply_log_limits(result.stdout + result.stderr, head, tail, tag="build_output_striped")

        if result.returncode == 0:
            response = SuccessResponse().dict()
            response["build_log"] = build_log
            return response
        else:
            # Determine compiler to know the error format.
            cache_file = os.path.join(build_dir, "CMakeCache.txt")
            compiler_id = "Unknown"
            try:
                c_id, cxx_id, _, _ = _read_compiler_ids_from_cache(cache_file)
                if cxx_id:
                    compiler_id = cxx_id
                elif c_id:
                    compiler_id = c_id
            except (FileNotFoundError, OSError):
                pass

            error_format = "raw"
            if compiler_id in ["GNU", "Clang"]:
                error_format = "json"
            elif compiler_id == "MSVC":
                error_format = "sarif"

            formatted_error = format_error_for_llm_analysis(result.stderr, error_format)
            response = FailureResponse(**formatted_error).dict()
            response["build_log"] = build_log
            return response

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        error_message = e.stderr if isinstance(e, subprocess.CalledProcessError) else str(e)
        return FailureResponse(summary="Build failed.", errors=[ErrorDetail(message=error_message, severity="error")]).dict()
