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
from urllib.parse import parse_qs, urlparse

from clive import hint as hinting
from clive import judge as judging
from clive import nudge as nudging
from clive import prompts
from clive import simulate as simulating
from clive.config import EFFORT_CHOICES
from clive.providers import get_provider
from clive.studio import student as studenting

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

    if parts == ["api", "hint"] and method == "POST":
        return run_hint(body)

    if parts == ["api", "nudge"] and method == "POST":
        return run_nudge(body)

    if parts == ["api", "promote"] and method == "POST":
        return promote(body)

    # The student API. Separate from the routes above rather than sharing them: those
    # answer an author who may see everything, these answer a student who may not.
    if parts == ["api", "student", "boot"] and method == "GET":
        return studenting.boot()

    if len(parts) == 4 and parts[:3] == ["api", "student", "problem"] and method == "GET":
        return studenting.problem(parts[3])

    if parts == ["api", "student", "submit"] and method == "POST":
        return run_student_submit(body)

    if parts == ["api", "student", "hint"] and method == "POST":
        return run_student_hint(body)

    if parts == ["api", "personas"] and method == "GET":
        doc = prompts.load_personas()
        return {
            "personas": [
                {
                    "id": p["id"], "name": p["name"], "blurb": p.get("blurb", ""),
                    "behaviour": p.get("behaviour", ""),
                    "help_seeking": p.get("help_seeking", "never"),
                }
                for p in doc.get("personas") or []
            ],
            "system_prompt": doc.get("system_prompt", ""),
            "model": doc.get("model", {}),
            "version": doc.get("version", 1),
            "max_attempts_cap": simulating.MAX_ATTEMPTS_CAP,
        }

    if parts == ["api", "persona-preview"] and method == "POST":
        return persona_preview(body)

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


def run_hint(body: dict) -> dict:
    """One hint for the artifact in `body`, from the same resolved context the judge
    uses — so a Sandbox session hints against its scratch criteria, not the saved ones.

    No judge run is required first. A hint reads the artifact, not the verdicts, which
    is what lets a student ask for one while still staring at an empty form.
    """
    phase, problem, criteria = resolve_context(body)
    try:
        return hinting.hint(
            phase,
            problem,
            body.get("artifact") or {},
            criteria,
            int(body.get("attempt", 1)),
            body.get("prior_artifacts") or [],
            body.get("history") or [],
        )
    except hinting.JudgeError as exc:
        raise ApiError(str(exc), 502) from None


def run_nudge(body: dict) -> dict:
    """One nudge for the judged submission in `body`, from the same resolved context the
    judge used — so a Sandbox session nudges against its scratch criteria, not the saved
    ones, and the gates named back to the student are the ones they were actually judged on.

    Unlike a hint, this requires `verdicts`: the nudge speaks about failures, and without
    a judge run there are none. The browser posts back the verdict list it just received
    rather than the server re-judging, which would cost a second call and could disagree
    with the result already on screen.
    """
    phase, problem, criteria = resolve_context(body)
    try:
        return nudging.nudge(
            phase,
            problem,
            body.get("artifact") or {},
            criteria,
            body.get("verdicts") or [],
            int(body.get("attempt", 1)),
            body.get("prior_artifacts") or [],
            body.get("history") or [],
        )
    except nudging.JudgeError as exc:
        raise ApiError(str(exc), 502) from None


def persona_preview(body: dict) -> dict:
    """The exact prompt a persona would be sent, rendered without spending a token.

    Same idea as the Prompt tab's preview: an author should be able to read what the
    model will actually be told rather than infer it from the template. `stage` picks
    which shape to show — the first attempt, or the retry where the feedback and help
    blocks appear, which are the parts a template reader cannot easily picture.
    """
    doc = prompts.load_personas()
    persona = prompts.find_persona(doc, body.get("persona") or "")
    phase = prompts.load_phase(body["phase_id"])
    problem = prompts.load_problem(body["problem_id"])
    stage = body.get("stage") or "first"

    feedback = help_text = None
    attempt = 1
    if stage == "retry":
        attempt = 2
        criteria = prompts.load_criteria(phase["phase"])["criteria"]
        gating = [c for c in criteria if c.get("gate", prompts.DEFAULT_GATE) != "advisory"]
        # A stand-in verdict so the block renders with real criterion text. Marked as a
        # sample in the response so nobody reads it as a run that happened.
        first = gating[0] if gating else {"text": "(a gating criterion)"}
        feedback = {
            "failed": [{"text": first.get("text", ""), "evidence": "(what the judge quoted)"}],
            "nudge": {"summary": "(the summary naming every failing gate)",
                      "nudge": "(the nudge for the one to fix first)"},
            "previous": [{"label": f.get("label") or f["id"], "value": "(what they wrote last time)"}
                         for f in phase.get("artifact_fields") or []],
        }
    if stage == "retry" or persona.get("help_seeking") == "eager":
        help_text = {"diagnosis": "(one sentence on why they look stuck)",
                     "hint": "(the nudge toward some optional depth)"}

    return {
        "system_prompt": doc.get("system_prompt", ""),
        "user_prompt": prompts.render_persona_prompt(
            doc, persona, phase, problem, attempt, None, feedback, help_text),
        "stage": stage,
        "sampled": stage == "retry" or help_text is not None,
        "model": doc.get("model", {}),
    }


def run_student_submit(body: dict) -> dict:
    """A student submission: judged, then nudged in the same call if a gate failed.

    `student.submit` handles a failed nudge itself and still returns the verdicts, so
    the only thing that reaches here is the judge call giving up entirely — which is
    the one case where there is nothing to show.
    """
    try:
        return studenting.submit(body)
    except judging.JudgeError as exc:
        raise ApiError(str(exc), 502) from None


def run_student_hint(body: dict) -> dict:
    try:
        return studenting.hint(body)
    except hinting.JudgeError as exc:
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
        url = urlparse(self.path)
        # Simulation is the one response that is not a single JSON body: it is a run that
        # takes minutes, and the point of watching it is seeing each step as it lands.
        if url.path == "/api/simulate":
            self._stream_simulation(parse_qs(url.query))
        elif url.path.startswith("/api/"):
            self._handle("GET", url.path, {})
        else:
            self._serve_static(url.path)

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

    def _stream_simulation(self, qs: dict[str, list[str]]):
        """Stream a persona's run as Server-Sent Events.

        SSE rather than a websocket because this is one-way and the stdlib already does
        it: a long-lived response, one `data:` line per event. `ThreadingHTTPServer` gives
        each run its own thread, so a simulation does not block the Studio behind it.

        Every event is flushed as it is produced. Buffering the run and sending it at the
        end would answer the same JSON several minutes later, which is the thing this
        endpoint exists not to do.
        """
        one = lambda k, d="": (qs.get(k) or [d])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        # Close, not keep-alive. There is no Content-Length and no chunked encoding on a
        # stream of unknown length, so end-of-body *is* end-of-connection — announcing
        # keep-alive leaves the client waiting after the last event for a body that is
        # already complete.
        self.send_header("Connection", "close")
        self.close_connection = True
        # Named proxies buffer event streams by default and would hold the whole run.
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def emit(event: dict) -> None:
            payload = json.dumps(event, ensure_ascii=False, default=str)
            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()

        try:
            events = simulating.run(
                one("persona"),
                one("problem"),
                int(one("attempts", "3") or 3),
                [p for p in (one("phases") or "").split(",") if p] or None,
            )
            for event in events:
                emit(event)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # The browser navigated away or pressed Stop. Nothing was written that the
            # user still wants; ending the generator is the whole of the cleanup.
            return
        except (ApiError, prompts.ContentError) as exc:
            self._try_emit(emit, {"type": "error", "fatal": True, "message": str(exc)})
        except Exception as exc:  # a stream cannot answer with a status code
            self._try_emit(emit, {"type": "error", "fatal": True,
                                  "message": f"{type(exc).__name__}: {exc}"})

    @staticmethod
    def _try_emit(emit, event: dict) -> None:
        """Report a failure down a stream that may itself already be gone."""
        try:
            emit(event)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, ValueError):
            pass

    def _serve_static(self, path: str):
        if path in ("/", ""):
            name = "index.html"
        elif path.rstrip("/") == "/student":
            name = "student.html"
        else:
            name = path.lstrip("/")
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
    print(f"  student:  {url}student")
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
