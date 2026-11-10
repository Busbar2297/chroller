"""Forward Hermes tool calls to the local Chroller companion."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_URL = "http://127.0.0.1:8765"


def extension_commands():
    """Command catalog owned by the extension. The bridge sends these names unchanged."""
    plugin_dir = Path(__file__).resolve().parent
    repo_catalog = plugin_dir.parent / "extension" / "commands.json"
    path = repo_catalog if repo_catalog.exists() else plugin_dir / "commands.json"
    return json.loads(path.read_text(encoding="utf-8"))


def set_companion_url(url):
    global _URL
    if url:
        _URL = str(url).rstrip("/")


def _base_url():
    url = os.environ.get("CHROLLER_URL") or _URL or "http://127.0.0.1:8765"
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "http" or host not in ("127.0.0.1", "localhost"):
        raise ValueError("Chroller companion URL must be http://127.0.0.1 or http://localhost.")
    return url.rstrip("/")


def _token():
    env = os.environ.get("CHROLLER_TOKEN")
    if env:
        return env.strip()
    override = os.environ.get("CHROLLER_TOKEN_FILE")
    path = Path(override) if override else Path.home() / ".chroller" / "token"
    if not path.exists():
        raise ValueError("Start the Chroller companion, then pair the extension with the token it prints.")
    return path.read_text(encoding="utf-8").strip()


def _normalize(args):
    if args is None:
        return {}
    if isinstance(args, str):
        parsed = json.loads(args or "{}")
        return parsed if isinstance(parsed, dict) else {}
    return dict(args)


def _missing(required, args):
    for key in required:
        value = args.get(key)
        if value in (None, "") or value == []:
            return key
    return ""


def call_companion(op, args):
    body = json.dumps({"op": op, "args": args}).encode("utf-8")
    request = urllib.request.Request(
        _base_url() + "/v1/command",
        data=body,
        headers={
            "Authorization": "Bearer " + _token(),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(detail)
            message = payload.get("error") or "Companion rejected the call."
        except json.JSONDecodeError:
            message = "Companion rejected the call."
        return {"ok": False, "error": message}
    except urllib.error.URLError:
        return {"ok": False, "error": "Chroller companion is not running on 127.0.0.1:8765."}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not payload.get("ok"):
        return {"ok": False, "error": payload.get("error") or "Chroller could not run that action."}
    return {"ok": True, "data": payload.get("data")}


def dispatch(op, args):
    try:
        catalog = {row["name"]: row for row in extension_commands()}
        spec = catalog.get(op)
        if spec is None:
            return json.dumps({"ok": False, "error": "Unknown command " + op + "."})
        parsed = _normalize(args)
        missing = _missing(spec.get("required") or [], parsed)
        if missing:
            return json.dumps({"ok": False, "error": missing + " is required."})
        if spec.get("default_method") and "method" not in parsed:
            parsed["method"] = spec["default_method"]
        return json.dumps(call_companion(op, parsed))
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def make_handler(op):
    def handle(args=None, **kwargs):
        return dispatch(op, args)
    handle.__name__ = op
    return handle
