"""The two problem keys the Implement phase adds.

Both are optional: the nine problems in the corpus predate them, and a save must
not invent content for a file that has neither.
"""

from __future__ import annotations

from clive import prompts


def test_existing_problem_defaults_both_keys():
    problem = prompts.load_problem("grade_average")
    assert problem["starter_code"] == ""
    assert problem["hidden_test_cases"] == []


def test_save_round_trips_both_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PROBLEMS_DIR", tmp_path)
    prompts.save_problem("scratch", {
        "title": "Scratch",
        "statement": "Do a thing.\n",
        "public_test_cases": [{"input": "1", "output": "2"}],
        "hidden_test_cases": [{"input": "9", "output": "10"}],
        "starter_code": "#include <stdio.h>\n",
    })
    loaded = prompts.load_problem("scratch")
    assert loaded["hidden_test_cases"] == [{"input": "9", "output": "10"}]
    assert loaded["starter_code"] == "#include <stdio.h>\n"


def test_save_drops_blank_hidden_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PROBLEMS_DIR", tmp_path)
    prompts.save_problem("scratch", {
        "statement": "s\n",
        "hidden_test_cases": [{"input": "", "output": ""}, {"input": "a", "output": "b"}],
    })
    assert prompts.load_problem("scratch")["hidden_test_cases"] == [{"input": "a", "output": "b"}]


def test_save_omits_the_keys_when_empty(tmp_path, monkeypatch):
    """A problem with neither key must not gain two noise keys on every save."""
    monkeypatch.setattr(prompts, "PROBLEMS_DIR", tmp_path)
    prompts.save_problem("scratch", {"statement": "s\n"})
    text = (tmp_path / "scratch.yaml").read_text()
    assert "hidden_test_cases" not in text
    assert "starter_code" not in text
