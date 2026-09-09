"""The phase `gate` key and the artifact-field `kind` key.

Both exist to be defaulted: every phase written before they existed must keep
behaving exactly as it did, which is what most of these tests pin.
"""

from __future__ import annotations

import pytest

from clive import prompts


def test_existing_phase_defaults_to_criteria_gate():
    phase = prompts.load_phase("algorithm_design")
    assert phase["gate"] == "criteria"


def test_existing_artifact_fields_default_to_text_kind():
    phase = prompts.load_phase("algorithm_design")
    assert phase["artifact_fields"]
    assert all(f["kind"] == "text" for f in phase["artifact_fields"])


def test_save_phase_rejects_an_unknown_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PHASES_DIR", tmp_path)
    with pytest.raises(prompts.ContentError, match="gate"):
        prompts.save_phase("scratch", {
            "gate": "vibes",
            "system_prompt": "s",
            "user_template": "u",
        })


def test_save_phase_rejects_an_unknown_field_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PHASES_DIR", tmp_path)
    with pytest.raises(prompts.ContentError, match="kind"):
        prompts.save_phase("scratch", {
            "artifact_fields": [{"id": "code", "kind": "hologram"}],
            "system_prompt": "s",
            "user_template": "u",
        })


def test_save_phase_round_trips_gate_and_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PHASES_DIR", tmp_path)
    saved = prompts.save_phase("scratch", {
        "gate": "tests",
        "artifact_fields": [{"id": "code", "label": "Code", "kind": "code", "language": "c"}],
        "system_prompt": "s",
        "user_template": "u",
    })
    assert saved["gate"] == "tests"
    assert saved["artifact_fields"][0]["kind"] == "code"
    assert saved["artifact_fields"][0]["language"] == "c"
