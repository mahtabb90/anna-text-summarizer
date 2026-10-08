#!/usr/bin/env python3
"""Build the Executa as a self-contained PyInstaller --onefile binary and package it.

Run on the platform you are building for (PyInstaller does not cross-compile):

    python scripts/build_binary.py            # build + archive + sha256
    python scripts/build_binary.py --clean    # remove build/ and dist/ only

All names, the version and the archive format come from ``executa.json``
(``distribution.profiles.binary.binary_artifacts``), so they are defined once.
Output (relative to the Executa directory):

    dist/<archive>             .tar.gz (macOS/Linux) or .zip (Windows)
    dist/<archive>.sha256      "<sha256>  <archive>"

Inside the archive: the executable at the archive root and a generated
``manifest.json`` (the archive manifest, unrelated to the App's manifest.json).
"""

import argparse
import hashlib
import io
import json
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

EXECUTA_DIR = Path(__file__).resolve().parent.parent
SOURCE = EXECUTA_DIR / "my_first_anna_app_plugin.py"
BUILD_DIR = EXECUTA_DIR / "build"
DIST_DIR = EXECUTA_DIR / "dist"


def platform_key():
    """Anna platform key for the machine running this script."""
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}.get(platform.system())
    machine = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(
        platform.machine().lower()
    )
    if system is None or machine is None:
        raise SystemExit(f"unsupported build platform: {platform.system()} {platform.machine()}")
    return f"{system}-{machine}"


def load_config(key):
    cfg = json.loads((EXECUTA_DIR / "executa.json").read_text(encoding="utf-8"))
    artifacts = cfg["distribution"]["profiles"]["binary"]["binary_artifacts"]
    if key not in artifacts:
        raise SystemExit(f"executa.json declares no binary_artifacts for {key} (have: {', '.join(artifacts)})")
    return cfg, artifacts[key]


def check_version_sync(version):
    """The Executa version must match pyproject.toml and the plugin's PLUGIN_VERSION."""
    pyproject = (EXECUTA_DIR / "pyproject.toml").read_text(encoding="utf-8")
    plugin = SOURCE.read_text(encoding="utf-8")
    found = {
        "pyproject.toml": re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M),
        "PLUGIN_VERSION": re.search(r'^PLUGIN_VERSION\s*=\s*"([^"]+)"', plugin, re.M),
    }
    for where, match in found.items():
        if not match or match.group(1) != version:
            got = match.group(1) if match else "not found"
            raise SystemExit(f"version mismatch: executa.json={version} but {where}={got}")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_manifest(cfg, exe_stem):
    """Archive-level manifest.json read by the Anna Agent at install time."""
    return {
        "name": cfg["slug"],
        "version": cfg["version"],
        "runtime": {
            "binary": {
                "entrypoint": {"default": exe_stem, "windows-x86_64": f"{exe_stem}.exe"},
                "permissions": {exe_stem: "0o755"},
            }
        },
    }


def run_pyinstaller(exe_stem):
    out = BUILD_DIR / "pyinstaller"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noupx",
        "--clean",
        "--noconfirm",
        "--name", exe_stem,
        "--distpath", str(out / "dist"),
        "--workpath", str(out / "work"),
        "--specpath", str(out / "spec"),
    ]
    # --strip is unsupported on Windows. Never pass --noconsole: the Executa speaks stdio.
    if platform.system() != "Windows":
        cmd.append("--strip")
    cmd.append(str(SOURCE))
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=EXECUTA_DIR)
    return out / "dist"


def make_archive(fmt, archive_path, exe_path, entrypoint_name, manifest):
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    if fmt == "zip":
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(exe_path, entrypoint_name)
            zf.writestr("manifest.json", manifest_bytes)
        return
    with tarfile.open(archive_path, "w:gz") as tf:
        info = tf.gettarinfo(str(exe_path), arcname=entrypoint_name)
        info.mode, info.uid, info.gid, info.uname, info.gname = 0o755, 0, 0, "", ""
        with open(exe_path, "rb") as fh:
            tf.addfile(info, fh)
        minfo = tarfile.TarInfo("manifest.json")
        minfo.size, minfo.mode = len(manifest_bytes), 0o644
        tf.addfile(minfo, io.BytesIO(manifest_bytes))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clean", action="store_true", help="remove build/ and dist/ and exit")
    args = parser.parse_args()

    if args.clean:
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
        shutil.rmtree(DIST_DIR, ignore_errors=True)
        print("cleaned build/ and dist/")
        return

    key = platform_key()
    cfg, artifact = load_config(key)
    version = cfg["version"]
    check_version_sync(version)

    entrypoint = artifact["entrypoint"]
    fmt = artifact["format"]
    exe_stem = entrypoint[:-4] if entrypoint.endswith(".exe") else entrypoint
    archive_name = Path(artifact["path"].format(version=version)).name
    print(f"platform={key} version={version} entrypoint={entrypoint} archive={archive_name}", flush=True)

    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    DIST_DIR.mkdir(exist_ok=True)
    archive_path = DIST_DIR / archive_name
    for stale in (archive_path, archive_path.with_name(archive_name + ".sha256")):
        stale.unlink(missing_ok=True)

    exe_path = run_pyinstaller(exe_stem) / entrypoint
    if not exe_path.is_file():
        raise SystemExit(f"PyInstaller did not produce {exe_path}")

    make_archive(fmt, archive_path, exe_path, entrypoint, archive_manifest(cfg, exe_stem))
    digest = sha256_file(archive_path)
    archive_path.with_name(archive_name + ".sha256").write_bytes(f"{digest}  {archive_name}\n".encode("utf-8"))  # LF on every OS
    shutil.rmtree(BUILD_DIR, ignore_errors=True)

    print(f"archive: {archive_path}")
    print(f"sha256:  {digest}")


if __name__ == "__main__":
    main()
