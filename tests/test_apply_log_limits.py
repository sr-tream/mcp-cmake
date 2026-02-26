# tests/test_apply_log_limits.py

import os
from unittest.mock import MagicMock, patch

import pytest

from mcp_cmake.core import _apply_log_limits

MARKER_TAG = "build_output_striped"


def _make_log(n: int) -> str:
    """Return a log string with *n* numbered lines."""
    return "".join(f"line {i}\n" for i in range(1, n + 1))


# ---------------------------------------------------------------------------
# No-op cases
# ---------------------------------------------------------------------------


def test_no_limits_returns_log_unchanged():
    log = _make_log(10)
    assert _apply_log_limits(log, head=None, tail=None) == log


def test_head_larger_than_log_returns_log_unchanged():
    log = _make_log(5)
    assert _apply_log_limits(log, head=100, tail=None) == log


def test_tail_larger_than_log_returns_log_unchanged():
    log = _make_log(5)
    assert _apply_log_limits(log, head=None, tail=100) == log


def test_head_plus_tail_covers_all_lines_returns_log_unchanged():
    log = _make_log(10)
    # head=6 + tail=4 = 10 == total, nothing stripped
    assert _apply_log_limits(log, head=6, tail=4) == log


# ---------------------------------------------------------------------------
# head-only truncation
# ---------------------------------------------------------------------------


def test_head_only_keeps_first_n_lines():
    log = _make_log(10)
    result = _apply_log_limits(log, head=3, tail=None)
    lines = result.splitlines()
    assert lines[0] == "line 1"
    assert lines[1] == "line 2"
    assert lines[2] == "line 3"


def test_head_only_inserts_marker_after_head_lines():
    log = _make_log(10)
    result = _apply_log_limits(log, head=3, tail=None)
    assert MARKER_TAG in result
    assert "stripped 7 lines" in result


def test_head_only_marker_contains_tmp_path(tmp_path):
    log = _make_log(10)
    result = _apply_log_limits(log, head=3, tail=None)
    # The marker should embed an absolute path
    assert "<build_output_striped>" in result
    # Extract the path from the marker
    start = result.index("`") + 1
    end = result.index("`", start)
    tmp_file = result[start:end]
    assert os.path.isfile(tmp_file)
    with open(tmp_file) as fh:
        assert fh.read() == log
    os.unlink(tmp_file)


# ---------------------------------------------------------------------------
# tail-only truncation
# ---------------------------------------------------------------------------


def test_tail_only_keeps_last_n_lines():
    log = _make_log(10)
    result = _apply_log_limits(log, head=None, tail=3)
    lines = result.splitlines()
    assert lines[-1] == "line 10"
    assert lines[-2] == "line 9"
    assert lines[-3] == "line 8"


def test_tail_only_inserts_marker_before_tail_lines():
    log = _make_log(10)
    result = _apply_log_limits(log, head=None, tail=3)
    assert MARKER_TAG in result
    assert "stripped 7 lines" in result


def test_tail_only_marker_at_start_of_output():
    log = _make_log(10)
    result = _apply_log_limits(log, head=None, tail=3)
    assert result.startswith("<build_output_striped>")


# ---------------------------------------------------------------------------
# head + tail truncation
# ---------------------------------------------------------------------------


def test_head_and_tail_keeps_correct_lines():
    log = _make_log(10)
    result = _apply_log_limits(log, head=2, tail=2)
    lines = [l for l in result.splitlines() if not l.startswith("<build_output_striped>")]
    assert lines[0] == "line 1"
    assert lines[1] == "line 2"
    assert lines[-2] == "line 9"
    assert lines[-1] == "line 10"


def test_head_and_tail_stripped_count():
    log = _make_log(10)
    result = _apply_log_limits(log, head=2, tail=2)
    assert "stripped 6 lines" in result


def test_head_and_tail_marker_between_sections():
    log = _make_log(10)
    result = _apply_log_limits(log, head=2, tail=2)
    marker_pos = result.index(MARKER_TAG)
    # head lines should appear before the marker
    assert result.index("line 2") < marker_pos
    # tail lines should appear after the marker
    assert result.index("line 9") > marker_pos


# ---------------------------------------------------------------------------
# Temp file content
# ---------------------------------------------------------------------------


def test_full_log_written_to_tmp_file():
    log = _make_log(20)
    result = _apply_log_limits(log, head=5, tail=None)
    start = result.index("`") + 1
    end = result.index("`", start)
    tmp_file = result[start:end]
    try:
        with open(tmp_file) as fh:
            assert fh.read() == log
    finally:
        os.unlink(tmp_file)


# ---------------------------------------------------------------------------
# Custom tag parameter
# ---------------------------------------------------------------------------


def test_custom_tag_used_in_marker():
    log = _make_log(10)
    result = _apply_log_limits(log, head=3, tail=None, tag="configure_output_striped")
    assert "<configure_output_striped>" in result
    assert "</configure_output_striped>" in result
    assert "<build_output_striped>" not in result


def test_custom_tag_test_output_striped():
    log = _make_log(10)
    result = _apply_log_limits(log, head=3, tail=None, tag="test_output_striped")
    assert "<test_output_striped>" in result
    assert "</test_output_striped>" in result


# ---------------------------------------------------------------------------
# configure_project log output (via mocked subprocess)
# ---------------------------------------------------------------------------


def _make_mock_run(stdout="", stderr="", returncode=0):
    mock = MagicMock()
    mock.stdout = stdout
    mock.stderr = stderr
    mock.returncode = returncode
    return mock


def _patch_subprocess_and_cache(initial_stdout="init\n", final_stdout="final\n", final_returncode=0):
    """Return a context manager that stubs out subprocess.run and open(CMakeCache.txt)."""
    import io

    initial_mock = _make_mock_run(stdout=initial_stdout, stderr="")
    final_mock = _make_mock_run(stdout=final_stdout, stderr="", returncode=final_returncode)
    # subprocess.run is called twice: initial configure then final configure
    run_side_effects = [initial_mock, final_mock]

    # Minimal CMakeCache.txt content – no compilers detected keeps diag flags empty
    cache_content = "# CMake cache\n"
    fake_open = patch("builtins.open", lambda path, *a, **kw: io.StringIO(cache_content))
    fake_makedirs = patch("os.makedirs")
    fake_exists = patch("os.path.exists", return_value=True)
    fake_run = patch("subprocess.run", side_effect=run_side_effects)
    return fake_makedirs, fake_exists, fake_run, fake_open


def test_configure_project_success_includes_configure_log():
    from mcp_cmake.core import configure_project

    initial_mock = _make_mock_run(stdout="-- Configuring pass 1\n", stderr="")
    final_mock = _make_mock_run(stdout="-- Configuring pass 2\n", stderr="", returncode=0)

    import io

    cache_content = "# empty cache\n"
    with (
        patch("subprocess.run", side_effect=[initial_mock, final_mock]),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", lambda path, *a, **kw: io.StringIO(cache_content)),
    ):
        resp = configure_project("/fake/dir", "debug")

    assert resp["success"] is True
    assert "configure_log" in resp
    assert "-- Configuring pass 1" in resp["configure_log"]
    assert "-- Configuring pass 2" in resp["configure_log"]


def test_configure_project_failure_includes_configure_log():
    from mcp_cmake.core import configure_project

    initial_mock = _make_mock_run(stdout="-- Configuring pass 1\n", stderr="")
    final_mock = _make_mock_run(stdout="", stderr="CMake Error: something went wrong\n", returncode=1)

    import io

    cache_content = "# empty cache\n"
    with (
        patch("subprocess.run", side_effect=[initial_mock, final_mock]),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", lambda path, *a, **kw: io.StringIO(cache_content)),
    ):
        resp = configure_project("/fake/dir", "debug")

    assert resp["success"] is False
    assert "configure_log" in resp
    assert "CMake Error" in resp["configure_log"]


def test_configure_project_head_limit_applies_configure_tag():
    from mcp_cmake.core import configure_project

    many_lines = "".join(f"line {i}\n" for i in range(1, 21))
    initial_mock = _make_mock_run(stdout=many_lines, stderr="")
    final_mock = _make_mock_run(stdout=many_lines, stderr="", returncode=0)

    import io

    cache_content = "# empty cache\n"
    with (
        patch("subprocess.run", side_effect=[initial_mock, final_mock]),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", lambda path, *a, **kw: io.StringIO(cache_content)),
    ):
        resp = configure_project("/fake/dir", "debug", head=5)

    assert "<configure_output_striped>" in resp["configure_log"]


# ---------------------------------------------------------------------------
# test_project log output (via mocked subprocess)
# ---------------------------------------------------------------------------


def test_test_project_success_includes_test_log():
    from mcp_cmake.core import test_project

    mock_result = _make_mock_run(stdout="100% tests passed\n", stderr="", returncode=0)
    with patch("subprocess.run", return_value=mock_result):
        resp = test_project("/fake/dir", "debug")

    assert resp["success"] is True
    assert "test_log" in resp
    assert "100% tests passed" in resp["test_log"]


def test_test_project_failure_includes_test_log():
    from mcp_cmake.core import test_project

    mock_result = _make_mock_run(stdout="1/3 tests failed\n", stderr="", returncode=8)
    with patch("subprocess.run", return_value=mock_result):
        resp = test_project("/fake/dir", "debug")

    assert resp["success"] is False
    assert "test_log" in resp
    assert "1/3 tests failed" in resp["test_log"]


def test_test_project_tail_limit_applies_test_tag():
    from mcp_cmake.core import test_project

    many_lines = "".join(f"test {i}\n" for i in range(1, 21))
    mock_result = _make_mock_run(stdout=many_lines, stderr="", returncode=0)
    with patch("subprocess.run", return_value=mock_result):
        resp = test_project("/fake/dir", "debug", tail=5)

    assert "<test_output_striped>" in resp["test_log"]
    # Full log saved to a temp file — clean it up
    log = resp["test_log"]
    start = log.index("`") + 1
    end = log.index("`", start)
    tmp_file = log[start:end]
    if os.path.isfile(tmp_file):
        os.unlink(tmp_file)
