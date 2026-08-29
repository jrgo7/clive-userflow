"""CLive Studio - a local editor for the phases, criteria, problems, and prompts.

Stdlib HTTP server, no new dependencies. It serves one HTML page and a small JSON
API over the YAML files in the repo; every save writes the same files a human
would hand-edit, so the Studio and the notebooks never diverge.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from clive import judge as judging
from clive import prompts
from clive.config import EFFORT_CHOICES
from clive.providers import get_provider

STATIC_DIR = Path(__file__).resolve().parent / "static"

MAX_BODY_BYTES = 4 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ------------------------------------------------------------------------ routes


def route(method: str, path: str, body: dict) -> dict:
    parts = [p for p in path.strip("/").split("/") if p]

    if parts == ["api", "bootstrap"] and method == "GET":
        provider = get_provider()
        return {
            "phases": prompts.list_phases(),
            "problems": prompts.list_problems(),
            "models": provider.model_choices,
            "efforts": EFFORT_CHOICES,
            "provider": provider.name,
            "has_api_key": provider.has_api_key(),
        }

    if len(parts) == 3 and parts[0] == "api" and parts[1] == "phase":
        phase = parts[2]
        if method == "GET":
            return {
                "phase": prompts.load_phase(phase),
                "criteria": prompts.load_criteria(phase),
            }
        if method == "PUT":
            return {"phase": prompts.save_phase(phase, body)}

    if len(parts) == 3 and parts[0] == "api" and parts[1] == "criteria":
        phase = parts[2]
        if method == "PUT":
            return {"criteria": prompts.save_criteria(phase, body)}

    if parts == ["api", "problems"] and method == "GET":
        return {"problems": prompts.list_problems()}

    if parts == ["api", "rubric"] and method == "GET":
        return {"rubric": rubric()}

    if len(parts) == 3 and parts[0] == "api" and parts[1] == "problem":
        slug = parts[2]
        if method == "GET":
            return {"problem": prompts.load_problem(slug)}
        if method == "PUT":
            return {
                "problem": prompts.save_problem(slug, body),
                "problems": prompts.list_problems(),
            }
        if method == "DELETE":
            prompts.delete_problem(slug)
            return {"problems": prompts.list_problems()}

    if parts == ["api", "preview"] and method == "POST":
        return preview(body)

    if parts == ["api", "judge"] and method == "POST":
        return run_judge(body)

    if parts == ["api", "promote"] and method == "POST":
        return promote(body)

    raise ApiError(f"No route for {method} /{'/'.join(parts)}", 404)


def rubric() -> list[dict]:
    """Every phase with its criteria, in one response.

    The Rubric view's header counter recomputes on every render, so the browser
    caches this rather than re-fetching; one route beats a round-trip per phase.
    A phase with no criteria file yields an empty list rather than an error —
    `load_criteria` already returns an empty rubric for a missing file.
    """
    out = []
    for meta in prompts.list_phases():
        doc = prompts.load_criteria(meta["phase"])
        out.append(
            {
                "phase": meta["phase"],
                "label": meta["label"],
                "order": meta["order"],
                "criteria_version": doc.get("version", 1),
                "criteria": doc.get("criteria", []),
            }
        )
    return out


def resolve_context(body: dict) -> tuple[dict, dict, list[dict]]:
    """Work out which phase, problem, and criteria a request is about.

    Each of the three may arrive inline as an object or as an id to load from disk.
    That is what lets Sandbox mode work: the browser posts its unsaved scratch copy
    and the judge runs against it, with no file written and no separate code path.
    Omitting a part falls back to the saved file, which is what the Run tab does.
    """
    phase = body.get("phase") or prompts.load_phase(body["phase_id"])

    problem = body.get("problem")
    if not isinstance(problem, dict):
        problem = prompts.load_problem(problem or body["problem_id"])

    criteria = body.get("criteria")
    if criteria is None:
        criteria = prompts.load_criteria(phase["phase"])["criteria"]

    return phase, problem, criteria


def render_for(body: dict, phase: dict, problem: dict, criteria: list[dict]) -> str:
    """Render the user prompt, turning a bad template into a 400 rather than a 500."""
    try:
        return prompts.render_user_prompt(
            phase,
            problem,
            body.get("artifact") or {},
            criteria,
            int(body.get("attempt", 1)),
            body.get("prior_artifacts") or [],
        )
    except Exception as exc:
        # In Sandbox the template being broken is the normal case, not an outage.
        raise ApiError(f"Template failed to render: {exc}") from None


def preview(body: dict) -> dict:
    """Render the user prompt exactly as the judge call would, without spending a token."""
    phase, problem, criteria = resolve_context(body)
    return {
        "system_prompt": phase.get("system_prompt", ""),
        "user_prompt": render_for(body, phase, problem, criteria),
    }


def run_judge(body: dict) -> dict:
    phase, problem, criteria = resolve_context(body)
    render_for(body, phase, problem, criteria)  # fail fast on a bad template
    try:
        return judging.judge(
            phase,
            problem,
            body.get("artifact") or {},
            criteria,
            int(body.get("attempt", 1)),
            body.get("prior_artifacts") or [],
        )
    except judging.JudgeError as exc:
        raise ApiError(str(exc), 502) from None


def promote(body: dict) -> dict:
    """Write parts of a Sandbox scratch copy back to the real files.

    `parts` names what to write, so a rubric experiment can be kept without also
    committing the prompt edit sitting next to it. Validation is whatever
    save_phase / save_criteria / save_problem already enforce.
    """
    parts = body.get("parts") or []
    if not parts:
        raise ApiError("Nothing selected to promote.")

    written = []
    if "phase" in parts:
        phase = body.get("phase") or {}
        prompts.save_phase(phase.get("phase") or body["phase_id"], phase)
        written.append(f"prompts/phases/{phase.get('phase') or body['phase_id']}.yaml")
    if "criteria" in parts:
        criteria = body.get("criteria_doc") or {}
        slug = criteria.get("phase") or body["phase_id"]
        prompts.save_criteria(slug, criteria)
        written.append(f"criteria/{slug}.yaml")
    if "problem" in parts:
        problem = body.get("problem") or {}
        slug = problem.get("slug") or body["problem_id"]
        prompts.save_problem(slug, problem)
        written.append(f"cases/problems/{slug}.yaml")

    return {
        "written": written,
        "phases": prompts.list_phases(),
        "problems": prompts.list_problems(),
    }


# ----------------------------------------------------------------------- handler


class Handler(BaseHTTPRequestHandler):
    server_version = "CLiveStudio"

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self._handle("GET", path, {})
        else:
            self._serve_static(path)

    def do_POST(self):
        self._handle("POST", urlparse(self.path).path)

    def do_PUT(self):
        self._handle("PUT", urlparse(self.path).path)

    def do_DELETE(self):
        self._handle("DELETE", urlparse(self.path).path, {})

    # -- internals

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ApiError("Request body too large.", 413)
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError("Request body is not valid JSON.") from None
        return parsed if isinstance(parsed, dict) else {}

    def _handle(self, method: str, path: str, body: dict | None = None):
        try:
            # Read inside the try so a malformed body answers with JSON too.
            self._send_json(200, route(method, path, self._read_body() if body is None else body))
        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message})
        except prompts.ContentError as exc:
            self._send_json(400, {"error": str(exc)})
        except KeyError as exc:
            self._send_json(400, {"error": f"Missing field: {exc}"})
        except Exception as exc:  # never let the browser hang on an unhandled error
            self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _serve_static(self, path: str):
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / name).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            self.send_error(404)
            return
        payload = target.read_bytes()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, payload: dict):
        # `default=str` covers YAML dates, which parse to datetime.date and
        # would otherwise fail serialisation. save_phase converts them back.
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # One line per request, without the noisy default timestamp banner.
        print(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"

    provider = get_provider()
    print(f"CLive Studio  {url}")
    print(f"  provider: {provider.name}")
    print(f"  phases:   {', '.join(p['label'] for p in prompts.list_phases())}")
    print(f"  problems: {len(prompts.list_problems())}")
    if not provider.has_api_key():
        print(f"  note:     no {provider.api_key_env} set - editing works, Run will not.")
    print("  Ctrl-C to stop.\n")

    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
