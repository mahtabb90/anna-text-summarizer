"""Executa plugin for the my-first-anna-app Anna App.

Tools:
  * ping       - smoke-test method (kept from the starter project).
  * summarize  - summarizes text by asking the Anna host LLM through reverse
                 ``sampling/createMessage`` (Executa Protocol v2). No API keys.

Protocol notes (see https://anna.partners/developers/tools/executa-sampling):
  * ``initialize`` negotiates protocol 2.0 and advertises ``capabilities.sampling``.
  * ``describe`` declares ``host_capabilities: ["llm.sample"]``.
  * A single stdin reader thread routes frames: frames with a ``method`` are
    requests from the Agent, frames without one are responses to our own reverse
    RPCs. This keeps the process responsive while an invoke waits for sampling.
"""

import json
import queue
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

PROTOCOL_VERSION = "2.0"
PLUGIN_NAME = "tool-dev-my-first-anna-app"
PLUGIN_VERSION = "0.1.1"

# Input limits. Keep well below the host's per-invoke token cap (32 000 tokens).
MAX_TEXT_CHARS = 20000
SUMMARY_MAX_TOKENS = 600
# Must stay below the tool timeout declared in MANIFEST.
SAMPLING_WAIT_SECONDS = 70

SYSTEM_PROMPT = (
    "You are a concise summarization assistant. Summarize the user's text "
    "faithfully in the same language as the text. Keep it short, focus on the "
    "key points, add no new facts, and reply with the summary only."
)

MANIFEST = {
    "name": PLUGIN_NAME,
    "version": PLUGIN_VERSION,
    "description": "Summarizes text using the Anna-hosted LLM via reverse sampling.",
    # Required for reverse sampling; otherwise the host rejects it with -32008.
    "host_capabilities": ["llm.sample"],
    "tools": [
        {
            "name": "ping",
            "description": "Smoke-test method.",
            "parameters": [],
        },
        {
            "name": "summarize",
            "description": "Summarize the supplied text into a short summary using the Anna LLM.",
            "timeout": 80,
            "parameters": [
                {
                    "name": "text",
                    "type": "string",
                    "description": "The text to summarize.",
                    "required": True,
                }
            ],
        },
    ],
}

# Friendly messages for the documented sampling error codes.
SAMPLING_ERROR_MESSAGES = {
    -32001: "AI sampling is not enabled for this tool. Enable it for this Executa in your Anna settings and try again.",
    -32002: "Your Anna AI quota has been used up. Please try again later.",
    -32003: "The AI provider failed to respond. Please try again.",
    -32004: "The summarization request was rejected as invalid. Try shorter or different text.",
    -32005: "The AI took too long to respond. Try a shorter text.",
    -32006: "Too many AI calls were made in one request.",
    -32007: "The text is too large for a single summary. Try a shorter text.",
    -32008: "AI sampling was not negotiated with the host. Make sure llm.sample is declared and the host supports protocol 2.0.",
    -32009: "The AI request was denied.",
}

_stdout_lock = threading.Lock()
_pending_lock = threading.Lock()
_pending = {}  # reverse-RPC id -> queue.Queue
_requests = queue.Queue()  # Agent -> plugin requests


class SamplingFailure(Exception):
    """A sampling reverse RPC failed; ``message`` is safe to show to the user."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _send(obj):
    line = json.dumps(obj)
    with _stdout_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def _log(message):
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _reader():
    """Single stdin reader: route Agent requests and host responses by shape."""
    try:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                _log("ignoring non-JSON line on stdin")
                continue
            if not isinstance(msg, dict):
                continue
            if "method" in msg:
                _requests.put(msg)
            else:
                with _pending_lock:
                    waiter = _pending.pop(msg.get("id"), None)
                if waiter is not None:
                    waiter.put(msg)
    finally:
        # stdin closed: unblock any in-flight sampling waits, then stop the main loop.
        with _pending_lock:
            waiters = list(_pending.values())
            _pending.clear()
        for waiter in waiters:
            waiter.put({"error": {"code": -32603, "message": "host connection closed"}})
        _requests.put(None)


def _sample(prompt, invoke_id):
    """Ask the host LLM for a completion via reverse ``sampling/createMessage``."""
    rid = str(uuid.uuid4())
    waiter = queue.Queue(maxsize=1)
    with _pending_lock:
        _pending[rid] = waiter

    params = {
        "messages": [{"role": "user", "content": {"type": "text", "text": prompt}}],
        "systemPrompt": SYSTEM_PROMPT,
        "maxTokens": SUMMARY_MAX_TOKENS,
        "temperature": 0.3,
        "includeContext": "none",
    }
    if invoke_id:
        params["metadata"] = {"executa_invoke_id": invoke_id}

    _send({"jsonrpc": "2.0", "id": rid, "method": "sampling/createMessage", "params": params})

    try:
        resp = waiter.get(timeout=SAMPLING_WAIT_SECONDS)
    except queue.Empty:
        with _pending_lock:
            _pending.pop(rid, None)
        raise SamplingFailure(SAMPLING_ERROR_MESSAGES[-32005])

    error = resp.get("error")
    if error:
        code = error.get("code")
        data = error.get("data") or {}
        _log(f"sampling error: code={code} name={data.get('errorCode')} message={error.get('message')}")
        raise SamplingFailure(
            SAMPLING_ERROR_MESSAGES.get(code) or f"The AI request failed: {error.get('message', 'unknown error')}"
        )

    content = (resp.get("result") or {}).get("content")
    if isinstance(content, dict):
        text = content.get("text")
    elif isinstance(content, list):
        text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    else:
        text = None
    if not isinstance(text, str) or not text.strip():
        raise SamplingFailure("The AI returned an empty summary. Please try again.")
    return text.strip()


def _summarize(arguments, context):
    text = (arguments or {}).get("text")
    if not isinstance(text, str) or not text.strip():
        return {"success": False, "error": "Please provide some text to summarize."}
    text = text.strip()
    if len(text) > MAX_TEXT_CHARS:
        return {
            "success": False,
            "error": f"The text is too long ({len(text)} characters). The limit is {MAX_TEXT_CHARS}.",
        }
    invoke_id = (context or {}).get("invoke_id")
    try:
        summary = _sample(f"Summarize the following text:\n\n{text}", invoke_id)
    except SamplingFailure as exc:
        return {"success": False, "error": exc.message}
    return {"success": True, "data": {"summary": summary}}


def invoke(tool, arguments, context):
    # Tool methods MUST return the dispatcher contract envelope:
    #   {"success": True,  "data":  <payload-dict>}
    #   {"success": False, "error": "<reason>"}
    if tool == "ping":
        return {"success": True, "data": {"pong": True}}
    if tool == "summarize":
        return _summarize(arguments, context)
    return {"success": False, "error": f"unknown method: {tool}"}


def _handle(req):
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}
    try:
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": PLUGIN_NAME, "version": PLUGIN_VERSION},
                "server_info": {"name": PLUGIN_NAME, "version": PLUGIN_VERSION},
                "capabilities": {"sampling": {}},
            }
        elif method == "describe":
            result = MANIFEST
        elif method == "health":
            result = {"status": "ready", "message": "", "details": {}}
        elif method == "invoke":
            result = invoke(params.get("tool"), params.get("arguments") or {}, params.get("context") or {})
        elif method == "shutdown":
            result = {}
        else:
            if req_id is not None:
                _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"unknown rpc: {method}"}})
            return
    except Exception as exc:  # noqa: BLE001
        _log(f"internal error handling {method}: {exc!r}")
        if req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(exc)}})
        return
    if req_id is not None:
        _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def main():
    # Frames are exchanged as UTF-8 regardless of the Windows console code page.
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    threading.Thread(target=_reader, daemon=True).start()
    # Requests run on worker threads so the loop keeps draining stdin while an
    # invoke waits for its sampling response. Never exit after one response.
    with ThreadPoolExecutor(max_workers=4) as pool:
        while True:
            req = _requests.get()
            if req is None:
                break
            pool.submit(_handle, req)


if __name__ == "__main__":
    main()
