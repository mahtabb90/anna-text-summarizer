#!/usr/bin/env python3
"""Protocol smoke test for a packaged Executa archive.

    python scripts/smoke_test.py dist/<archive>.tar.gz|.zip

Extracts the archive exactly as shipped, checks its layout against executa.json,
launches the entrypoint and drives it over stdio JSON-RPC:
initialize, describe, health, ping, and a summarize call with empty input (which is
rejected locally, so no Anna host / reverse Sampling is needed). Then closes stdin
and requires a clean exit. Every stdout line must be a JSON-RPC frame.
"""

import json
import os
import queue
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path

EXECUTA_DIR = Path(__file__).resolve().parent.parent
TIMEOUT = 15  # generous vs. the Agent's ~5 s describe budget; describe latency is asserted separately
DESCRIBE_BUDGET = 5.0


def fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def extract(archive, dest):
    """Extract with path-traversal protection and return the member names."""
    root = Path(dest).resolve()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            for name in names:
                if not (root / name).resolve().is_relative_to(root):
                    fail(f"unsafe path in archive: {name}")
            zf.extractall(root)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            names = tf.getnames()
            for member in tf.getmembers():
                if not (root / member.name).resolve().is_relative_to(root) or not (member.isfile() or member.isdir()):
                    fail(f"unsafe member in archive: {member.name}")
            tf.extractall(root)
    return names


class Executa:
    def __init__(self, exe):
        self.proc = subprocess.Popen(
            [str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=exe.parent
        )
        self.lines = queue.Queue()
        self.stderr = []
        threading.Thread(target=self._pump_out, daemon=True).start()
        threading.Thread(target=self._pump_err, daemon=True).start()

    def _pump_out(self):
        for raw in self.proc.stdout:
            self.lines.put(raw)
        self.lines.put(None)

    def _pump_err(self):
        for raw in self.proc.stderr:
            self.stderr.append(raw.decode("utf-8", "replace"))

    def call(self, req_id, method, params=None):
        frame = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            frame["params"] = params
        self.proc.stdin.write((json.dumps(frame) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        start = time.monotonic()
        try:
            raw = self.lines.get(timeout=TIMEOUT)
        except queue.Empty:
            fail(f"{method}: no response within {TIMEOUT}s")
        if raw is None:
            fail(f"{method}: process closed stdout / exited early (rc={self.proc.poll()})")
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            fail(f"{method}: non-JSON line on stdout: {raw[:200]!r}")
        if msg.get("jsonrpc") != "2.0" or msg.get("id") != req_id:
            fail(f"{method}: bad envelope/id correlation: {msg}")
        if "error" in msg:
            fail(f"{method}: JSON-RPC error: {msg['error']}")
        if self.proc.poll() is not None:
            fail(f"{method}: process exited between requests (rc={self.proc.returncode})")
        return msg["result"], time.monotonic() - start


def main():
    if len(sys.argv) != 2:
        fail("usage: smoke_test.py <archive>")
    archive = Path(sys.argv[1]).resolve()
    if not archive.is_file():
        fail(f"archive not found: {archive}")

    cfg = json.loads((EXECUTA_DIR / "executa.json").read_text(encoding="utf-8"))
    artifacts = cfg["distribution"]["profiles"]["binary"]["binary_artifacts"]
    expected = [a["entrypoint"] for a in artifacts.values() if Path(a["path"].format(version=cfg["version"])).name == archive.name]
    if len(expected) != 1:
        fail(f"{archive.name} does not match any binary_artifacts path in executa.json")
    entrypoint = expected[0]

    with tempfile.TemporaryDirectory(prefix="executa-smoke-") as tmp:
        names = extract(archive, tmp)
        print("archive contents:", sorted(names))
        if sorted(names) != sorted([entrypoint, "manifest.json"]):
            fail(f"unexpected archive layout; want exactly [{entrypoint}, manifest.json]")
        manifest = json.loads((Path(tmp) / "manifest.json").read_text(encoding="utf-8"))
        if manifest["version"] != cfg["version"]:
            fail("archive manifest version != executa.json version")
        entry_map = manifest["runtime"]["binary"]["entrypoint"]
        if entrypoint not in (entry_map["default"], entry_map["windows-x86_64"]):
            fail("archive manifest entrypoint does not match executa.json entrypoint")
        exe = Path(tmp) / entrypoint
        if os.name != "nt" and not os.access(exe, os.X_OK):
            fail("entrypoint is not executable after extraction")

        ex = Executa(exe)
        try:
            # First call includes the onefile cold start (self-extraction + interpreter boot).
            init, cold = ex.call(1, "initialize", {"protocolVersion": "2.0", "capabilities": {"sampling": {}}})
            if init.get("protocolVersion") != "2.0" or "sampling" not in init.get("capabilities", {}):
                fail(f"initialize: unexpected result {init}")
            print(f"cold start to first response: {cold:.2f}s")
            if cold > DESCRIBE_BUDGET:
                fail(f"cold start took {cold:.1f}s (> {DESCRIBE_BUDGET}s Agent budget)")

            desc, took = ex.call(2, "describe")
            tools = {t["name"] for t in desc.get("tools", [])}
            if not {"ping", "summarize"} <= tools or "llm.sample" not in desc.get("host_capabilities", []):
                fail(f"describe: unexpected manifest {desc}")
            print(f"describe latency: {took:.2f}s")

            health, _ = ex.call(3, "health")
            if health.get("status") != "ready":
                fail(f"health: unexpected result {health}")

            pong, _ = ex.call(4, "invoke", {"tool": "ping", "arguments": {}, "context": {}})
            if pong != {"success": True, "data": {"pong": True}}:
                fail(f"ping: unexpected result {pong}")

            empty, _ = ex.call(5, "invoke", {"tool": "summarize", "arguments": {"text": "  "}, "context": {}})
            if empty.get("success") is not False or not empty.get("error"):
                fail(f"summarize(empty): expected local validation error, got {empty}")

            ex.call(6, "shutdown")
            ex.proc.stdin.close()  # EOF: the process must now exit on its own
            try:
                rc = ex.proc.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                ex.proc.kill()
                fail("process did not exit after stdin EOF")
            if rc != 0:
                fail(f"non-zero exit code after EOF: {rc}")
            extra = ex.lines.get(timeout=2)
            if extra is not None:
                fail(f"unexpected extra stdout after final response: {extra[:200]!r}")
        finally:
            if ex.proc.poll() is None:
                ex.proc.kill()
    print(f"OK: {archive.name}")


if __name__ == "__main__":
    main()
