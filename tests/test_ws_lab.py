"""Offline tests for the standalone Narwal WebSocket laboratory."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "tools" / "narwal_ws_lab.py"
SPEC = importlib.util.spec_from_file_location("narwal_ws_lab", SCRIPT)
assert SPEC and SPEC.loader
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def test_catalog_classifies_queries_and_dangerous_commands() -> None:
    rows = {row["name"]: row for row in lab.topic_catalog()}
    assert rows["TOPIC_CMD_GET_BASE_STATUS"]["risk"] == "read-only"
    assert rows["TOPIC_CMD_REBOOT"]["risk"] == "high"
    assert rows["TOPIC_CMD_PLAN_START"]["risk"] == "state-changing"


def test_confirmation_is_exact_and_high_risk_is_blocked() -> None:
    lab.require_confirmation("locate", "SEND locate", "state-changing", False)
    with pytest.raises(SystemExit, match="Exact confirmation"):
        lab.require_confirmation("locate", "send locate", "state-changing", False)
    with pytest.raises(SystemExit, match="High-risk"):
        lab.require_confirmation("stop-task", "SEND stop-task", "high", False)
    lab.require_confirmation(
        "raw:developer/ping",
        "SEND raw:developer/ping",
        "high",
        True,
    )


def test_transcript_annotation_and_markdown_report(tmp_path: Path) -> None:
    capture = tmp_path / "capture.jsonl"
    transcript = lab.Transcript(capture, "session-1")
    transcript.write("session", host="192.0.2.1", port=9002)
    transcript.write("command_send", recipe="base-status", topic="status/get_device_base_status")
    transcript.write("command_response", result_code=0)
    lab.append_annotation(capture, "Robot remained docked.")

    events = [json.loads(line) for line in capture.read_text().splitlines()]
    assert events[-1]["kind"] == "operator_observation"
    assert events[-1]["text"] == "Robot remained docked."

    report = tmp_path / "report.md"
    lab.render_report([capture], report)
    text = report.read_text()
    assert "base-status" in text
    assert "Robot remained docked." in text
