# tests/test_apply_log_limits.py

import os

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
