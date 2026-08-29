"""Loading, rendering, and saving everything under prompts/, criteria/, and cases/.

This is the single reader/writer for CLive's authored content. The notebooks use
it so they stop hardcoding criteria; the Studio app uses it so an edit made in the
browser lands in the same YAML a human would hand-edit.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import jinja2
import yaml

from clive.config import (
    BASE_PROMPTS_DIR,
    CRITERIA_DIR,
    PHASES_DIR,
    PROBLEMS_DIR,
)
from clive.providers import get_provider

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")

#: A superseded file, kept beside the current one for the record: `<slug>.v<N>.yaml`.
ARCHIVE_RE = re.compile(r"\.v\d+$")


class ContentError(ValueError):
    """Authored content is missing or malformed. Carries a message meant for the user."""


def check_slug(value: str, what: str) -> str:
    """Validate an id used to build a file path.

    Ids arrive from URLs and from the browser, so this is the boundary that keeps
    `../` and absolute paths out of the filesystem calls below.
    """
    value = (value or "").strip()
    if not SLUG_RE.match(value):
        raise ContentError(
            f"{what} must be lowercase letters, digits, and underscores, "
            f"starting with a letter or digit - got {value!r}."
        )
    return value


def live_yaml_files(directory: Path) -> list[Path]:
    """The current version of every authored file in `directory`, sorted by filename.

    Superseded versions stay on disk as `<slug>.v<N>.yaml` so the history of a
    prompt is readable next to the prompt. They are not selectable content: an id
    resolves to `<slug>.yaml` (see `phase_path`), so listing an archive hands the
    caller an id whose file does not exist, and the load fails with `No such file`.
    """
    return sorted(p for p in directory.glob("*.yaml") if not ARCHIVE_RE.search(p.stem))


# --------------------------------------------------------------------------- io


class _BlockDumper(yaml.SafeDumper):
    """SafeDumper that writes multi-line strings as literal blocks.

    Without this, round-tripping a phase through the Studio would turn every
    system prompt into one enormous quoted line and make the diff unreadable.
    """


def _represent_str(dumper: yaml.SafeDumper, data: str):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_BlockDumper.add_representer(str, _represent_str)


def dump_yaml(data: Any) -> str:
    return yaml.dump(
        data,
        Dumper=_BlockDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )


def read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ContentError(f"No such file: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ContentError(f"{path.name} does not contain a YAML mapping.")
    return loaded


def read_header(path: Path) -> str:
    """The leading comment block of a file, if any.

    PyYAML drops comments on a round-trip, which would silently delete the
    explanation at the top of every authored file the first time it is saved from
    the Studio. Capturing and re-emitting the header keeps that documentation.
    """
    if not path.exists():
        return ""
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or (not line.strip() and lines):
            lines.append(line)
        else:
            break
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def write_yaml(path: Path, data: Any, header: str = "") -> None:
    """Write `data` to `path` atomically, so an interrupted save cannot truncate
    a file that was previously valid."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (header + "\n" if header else "") + dump_yaml(data)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ------------------------------------------------------------------------ phases


def phase_path(phase: str) -> Path:
    return PHASES_DIR / f"{check_slug(phase, 'phase id')}.yaml"


def list_phases() -> list[dict]:
    """Every phase, ordered by the `order` field then by filename."""
    phases = []
    for path in live_yaml_files(PHASES_DIR):
        try:
            data = read_yaml(path)
        except ContentError:
            continue
        slug = data.get("phase") or path.stem
        phases.append(
            {
                "phase": slug,
                "label": data.get("label") or slug.replace("_", " ").title(),
                "order": data.get("order", 999),
                "version": data.get("version", 1),
            }
        )
    return sorted(phases, key=lambda p: (p["order"], p["phase"]))


def load_phase(phase: str) -> dict:
    data = read_yaml(phase_path(phase))
    data.setdefault("phase", phase)
    data.setdefault("label", phase.replace("_", " ").title())
    data.setdefault("artifact_fields", [])
    data.setdefault("task_description", "")
    model = data.setdefault("model", {})
    model.setdefault("id", get_provider().default_model)
    model.setdefault("effort", "medium")
    model.setdefault("max_output_tokens", 4000)
    return data


def save_phase(phase: str, data: dict) -> dict:
    """Persist a phase, preserving the key order a hand-written file uses."""
    phase = check_slug(phase, "phase id")
    existing = read_yaml(phase_path(phase)) if phase_path(phase).exists() else {}

    merged = dict(existing)
    merged.update(data)
    merged["phase"] = phase
    merged["created"] = _as_date(merged.get("created"))

    # An empty changelog box means "I did not write one", not "delete the history".
    # A Studio save once blanked this field and took the v3 and v2 rationale with it;
    # clearing it deliberately is a file edit, which is rare enough to be worth the
    # inconvenience against losing the record by accident.
    if not str(merged.get("changelog", "")).strip() and str(existing.get("changelog", "")).strip():
        merged["changelog"] = existing["changelog"]

    for field in merged.get("artifact_fields") or []:
        check_slug(field.get("id", ""), "artifact field id")

    if not str(merged.get("system_prompt", "")).strip():
        raise ContentError("system_prompt cannot be empty.")
    if not str(merged.get("user_template", "")).strip():
        raise ContentError("user_template cannot be empty.")

    # Fail before writing rather than leaving a phase whose template cannot render.
    try:
        jinja_env().from_string(merged["user_template"])
    except jinja2.TemplateSyntaxError as exc:
        raise ContentError(
            f"user_template has a Jinja syntax error on line {exc.lineno}: {exc.message}"
        ) from None

    key_order = [
        "id",
        "version",
        "phase",
        "label",
        "order",
        "created",
        "changelog",
        "model",
        "task_description",
        "artifact_fields",
        "system_prompt",
        "user_template",
        "examples",
    ]
    ordered = {k: merged[k] for k in key_order if k in merged}
    ordered.update({k: v for k, v in merged.items() if k not in ordered})

    path = phase_path(phase)
    write_yaml(path, ordered, read_header(path))
    return load_phase(phase)


def _as_date(value: Any) -> Any:
    """Restore a YYYY-MM-DD string to a date.

    Dates survive the trip out to the browser as ISO strings (JSON has no date
    type); without this they would come back as quoted strings and the YAML would
    gain a pair of quotes on every save.
    """
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return value
    return value


# ---------------------------------------------------------------------- criteria


def criteria_path(phase: str) -> Path:
    return CRITERIA_DIR / f"{check_slug(phase, 'phase id')}.yaml"


def load_criteria(phase: str) -> dict:
    path = criteria_path(phase)
    if not path.exists():
        return {"id": f"criteria.{phase}", "phase": phase, "version": 1, "criteria": []}
    data = read_yaml(path)
    data.setdefault("criteria", [])
    return data


def save_criteria(phase: str, data: dict) -> dict:
    phase = check_slug(phase, "phase id")
    criteria = data.get("criteria") or []

    seen: set[str] = set()
    cleaned = []
    for item in criteria:
        cid = check_slug(item.get("id", ""), "criterion id")
        if cid in seen:
            raise ContentError(f"Duplicate criterion id {cid!r}.")
        seen.add(cid)
        if not str(item.get("text", "")).strip():
            raise ContentError(f"Criterion {cid!r} has no text.")
        cleaned.append(
            {
                "id": cid,
                "text": str(item["text"]).strip(),
                "guidance": _as_block(item.get("guidance", "")),
            }
        )

    ordered = {
        "id": data.get("id") or f"criteria.{phase}",
        "phase": phase,
        "version": int(data.get("version") or 1),
        "criteria": cleaned,
    }
    path = criteria_path(phase)
    write_yaml(path, ordered, read_header(path))
    return load_criteria(phase)


def _as_block(text: str) -> str:
    """Normalise a multi-line field so it dumps as a literal block, not a folded one."""
    text = str(text or "").replace("\r\n", "\n").strip()
    return text + "\n" if "\n" in text else text


# ---------------------------------------------------------------------- problems


def problem_path(problem_id: str) -> Path:
    return PROBLEMS_DIR / f"{check_slug(problem_id, 'problem id')}.yaml"


def list_problems() -> list[dict]:
    problems = []
    for path in live_yaml_files(PROBLEMS_DIR):
        try:
            data = read_yaml(path)
        except ContentError:
            continue
        problems.append(
            {
                "slug": path.stem,
                "id": data.get("id") or f"problem.{path.stem}",
                "title": data.get("title") or path.stem,
                "difficulty": data.get("difficulty", ""),
            }
        )
    return problems


def load_problem(problem_id: str) -> dict:
    data = read_yaml(problem_path(problem_id))
    data.setdefault("public_test_cases", [])
    data["slug"] = problem_id
    return data


def save_problem(problem_id: str, data: dict) -> dict:
    problem_id = check_slug(problem_id, "problem id")
    if not str(data.get("statement", "")).strip():
        raise ContentError("A problem needs a statement.")

    cases = []
    for case in data.get("public_test_cases") or []:
        # A row with neither half filled in is one the user left behind.
        if not str(case.get("input", "")).strip() and not str(case.get("output", "")).strip():
            continue
        cases.append(
            {
                "input": str(case.get("input", "")).replace("\r\n", "\n"),
                "output": str(case.get("output", "")).replace("\r\n", "\n"),
            }
        )

    topics = data.get("topics") or []
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split(",") if t.strip()]

    ordered = {
        "id": data.get("id") or f"problem.{problem_id}",
        "title": str(data.get("title") or problem_id).strip(),
        "difficulty": str(data.get("difficulty") or "").strip(),
        "topics": topics,
        "statement": _as_block(data["statement"]),
        "public_test_cases": cases,
    }
    path = problem_path(problem_id)
    write_yaml(path, ordered, read_header(path))
    return load_problem(problem_id)


def delete_problem(problem_id: str) -> None:
    path = problem_path(problem_id)
    if not path.exists():
        raise ContentError(f"No problem named {problem_id!r}.")
    if len(list_problems()) <= 1:
        raise ContentError("Refusing to delete the last remaining problem.")
    path.unlink()


# --------------------------------------------------------------------- rendering


def jinja_env() -> jinja2.Environment:
    env = jinja2.Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.Undefined,
        autoescape=False,
    )
    env.filters.setdefault("tojson", json.dumps)
    return env


def render_user_prompt(
    phase: dict,
    problem: dict,
    artifact: dict,
    criteria: list[dict],
    attempt: int = 1,
    prior_artifacts: list[dict] | None = None,
) -> str:
    """Render a phase's user_template. `artifact` is the student's submission.

    `prior_artifacts` carries what the same student wrote in earlier phases, as
    `[{"label": ..., "fields": [{"label": ..., "value": ...}]}]`. It is optional and
    empty by default: the templates guard the EARLIER PHASES block with
    `{% if prior_artifacts %}`, so a caller that omits it — the notebook, the Run
    tab, a Sandbox session with carry-forward off — renders the same prompt as before
    the argument existed.
    """
    template = jinja_env().from_string(phase["user_template"])
    return template.render(
        problem=problem,
        artifact=artifact or {},
        artifact_fields=phase.get("artifact_fields") or [],
        criteria_to_judge=criteria,
        attempt=attempt,
        prior_artifacts=prior_artifacts or [],
    )


def load_output_schema(phase: dict) -> dict:
    """The JSON schema a phase pins for its response format."""
    rel = phase.get("model", {}).get("schema", "base/output_schema.json")
    path = (BASE_PROMPTS_DIR.parent / rel).resolve()
    if not path.is_file():
        raise ContentError(f"Output schema not found: {rel}")
    return json.loads(path.read_text(encoding="utf-8"))
