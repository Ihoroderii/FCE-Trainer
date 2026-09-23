#!/usr/bin/env python3
"""Deploy this app to PythonAnywhere using their API.

Works on a **free** PythonAnywhere account: the API can upload files, run
commands through a console, and configure/reload a web app, so no SSH (a paid
feature) is required.

Usage:
    python -m scripts.deploy_pythonanywhere --username NAME --token TOKEN
    python -m scripts.deploy_pythonanywhere --username NAME --token TOKEN --dry-run

Get a token from: pythonanywhere.com -> Account -> API Token.
Add ``--host eu`` if your account lives on eu.pythonanywhere.com.

What it does
------------
1.  Packs the project (excluding .venv, .git, materials/, caches) into a tarball.
2.  Uploads it plus a generated ``.env`` through the Files API.
3.  Runs setup in a console: extract, create venv, ``pip install -r
    requirements-deploy.txt``, init the database.
4.  Writes the WSGI file, creates/updates the web app, sets the virtualenv,
    maps ``/static/``, and reloads.

The ``.env`` it writes contains a fresh SECRET_KEY and your AI keys. Pass
``--ai-key-env`` to choose which provider key to forward.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import secrets
import sys
import tarfile
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Directories skipped at any depth: machine-specific or regenerated on the host.
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "materials", "node_modules",
    ".pytest_cache", ".ruff_cache",
}
# Project-root-relative paths to skip. ".env" is critical: the local file holds
# real provider keys and would otherwise be extracted over the generated one.
# static/listening holds generated TTS audio; the tracked copy under
# portable_state/ is restored at startup, so shipping both would double ~28MB.
EXCLUDE_RELATIVE = {
    ".env",
    "fce_trainer.db",
    "rag_examples.db",
    "static/listening",
    "fce_deploy.tar.gz",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}

# The RAG corpus is deliberately NOT part of the code archive: its vectors are
# produced by whichever embedding backend the target host uses, so shipping the
# local copy would overwrite the host's vectors with an incompatible model.
# Upload it explicitly with --upload-corpus when you want to seed a host.
RAG_DB_NAME = "rag_examples.db"

DEFAULT_PYTHON = "python313"
CONSOLE_POLL_SECONDS = 3
CONSOLE_TIMEOUT_SECONDS = 900


def api_base(host: str) -> str:
    return "https://eu.pythonanywhere.com" if host == "eu" else "https://www.pythonanywhere.com"


class PythonAnywhere:
    """Minimal client for the parts of the PA API this deploy needs."""

    def __init__(self, username: str, token: str, host: str = "us"):
        self.username = username
        self.token = token
        self.base = f"{api_base(host)}/api/v0/user/{username}"
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Token {token}"

    def _check(self, resp: requests.Response, what: str) -> requests.Response:
        if resp.status_code >= 400:
            raise RuntimeError(f"{what} failed: HTTP {resp.status_code} {resp.text[:300]}")
        return resp

    def cpu(self) -> dict:
        return self._check(self.session.get(f"{self.base}/cpu/"), "cpu").json()

    def python_versions(self) -> dict:
        return self._check(
            self.session.get(f"{self.base}/default_python3_version/"), "python versions"
        ).json()

    def upload(self, local: Path, remote_path: str) -> None:
        with open(local, "rb") as handle:
            resp = self.session.post(
                f"{self.base}/files/path{remote_path}",
                files={"content": (local.name, handle)},
            )
        self._check(resp, f"upload {local.name}")

    def upload_bytes(self, payload: bytes, remote_path: str, name: str) -> None:
        resp = self.session.post(
            f"{self.base}/files/path{remote_path}",
            files={"content": (name, io.BytesIO(payload))},
        )
        self._check(resp, f"upload {name}")

    def download(self, remote_path: str) -> str | None:
        """Read a text file from the host, or None if it does not exist."""
        resp = self.session.get(f"{self.base}/files/path{remote_path}")
        if resp.status_code == 404:
            return None
        self._check(resp, f"download {remote_path}")
        return resp.text

    def list_webapps(self) -> list:
        return self._check(self.session.get(f"{self.base}/webapps/"), "list webapps").json()

    def create_webapp(self, domain: str, python_version: str) -> requests.Response:
        return self.session.post(
            f"{self.base}/webapps/",
            data={"domain_name": domain, "python_version": python_version},
        )

    def update_webapp(self, domain: str, **fields) -> None:
        self._check(
            self.session.patch(f"{self.base}/webapps/{domain}/", data=fields),
            "update webapp",
        )

    def add_static(self, domain: str, url: str, path: str) -> None:
        self.session.post(
            f"{self.base}/webapps/{domain}/static_files/",
            data={"url": url, "path": path},
        )

    def reload_webapp(self, domain: str) -> None:
        self._check(self.session.post(f"{self.base}/webapps/{domain}/reload/"), "reload webapp")

    # ── console execution ────────────────────────────────────────────────────

    def start_console(self, working_directory: str) -> int:
        resp = self._check(
            self.session.post(
                f"{self.base}/consoles/",
                data={"executable": "bash", "arguments": "", "working_directory": working_directory},
            ),
            "create console",
        )
        return resp.json()["id"]

    def console_output(self, console_id: int) -> str:
        resp = self.session.get(f"{self.base}/consoles/{console_id}/get_latest_output/")
        if resp.status_code >= 400:
            return ""
        try:
            return resp.json().get("output", "")
        except json.JSONDecodeError:
            return ""

    def send(self, console_id: int, text: str) -> None:
        self.session.post(
            f"{self.base}/consoles/{console_id}/send_input/",
            data={"input": text},
        )

    def kill_console(self, console_id: int) -> None:
        self.session.delete(f"{self.base}/consoles/{console_id}/")

    def run_commands(self, commands: list[str], working_directory: str) -> str:
        """Run shell commands in a console, returning all captured output."""
        console_id = self.start_console(working_directory)
        transcript = []
        try:
            # A sentinel lets us detect completion instead of guessing.
            sentinel = f"__DONE_{secrets.token_hex(4)}__"
            script = " && ".join(commands) + f"; echo {sentinel}\n"
            self.send(console_id, script)
            deadline = time.time() + CONSOLE_TIMEOUT_SECONDS
            seen = ""
            while time.time() < deadline:
                time.sleep(CONSOLE_POLL_SECONDS)
                output = self.console_output(console_id)
                if output and output != seen:
                    seen = output
                if sentinel in output:
                    break
                # Echo progress so a long pip install is not silent.
                if output:
                    transcript.append(output)
            transcript.append(seen)
            return "\n".join(t for t in transcript if t)
        finally:
            self.kill_console(console_id)


# ── packaging ────────────────────────────────────────────────────────────────

def build_tarball(destination: Path) -> Path:
    """Pack the project for upload, skipping machine-specific bulk."""
    def _filter(info: tarfile.TarInfo):
        rel = info.name.lstrip("./")
        parts = Path(rel).parts
        if any(part in EXCLUDE_DIRS for part in parts):
            return None
        if rel in EXCLUDE_RELATIVE or any(rel.startswith(p + "/") for p in EXCLUDE_RELATIVE):
            return None
        if rel.endswith(tuple(EXCLUDE_SUFFIXES)):
            return None
        return info

    with tarfile.open(destination, "w:gz") as tar:
        for entry in sorted(PROJECT_ROOT.iterdir()):
            if entry.name in EXCLUDE_DIRS or entry.name in EXCLUDE_RELATIVE:
                continue
            tar.add(entry, arcname=entry.name, filter=_filter)

    return destination


def parse_env(text: str | None) -> dict[str, str]:
    """Parse KEY=VALUE lines, ignoring comments and blanks."""
    values: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def build_env_file(args, existing: dict[str, str], *, prior_remote: dict[str, str] | None = None) -> bytes:
    """Render the remote .env: managed keys plus forwarded AI keys.

    A ``SECRET_KEY`` already present on the host is reused, so redeploying does
    not invalidate every existing login session.
    """
    prior = prior_remote or {}
    secret = prior.get("SECRET_KEY") or secrets.token_hex(32)

    lines = [
        "# Generated by scripts/deploy_pythonanywhere.py",
        f"SECRET_KEY={secret}",
        # No local embedding model on the host; Gemini embeddings are free and
        # googleapis.com is reachable from PythonAnywhere.
        "RAG_EMBEDDING_BACKEND=google",
        f"AI_PROVIDER={args.ai_provider}",
        # PythonAnywhere truncates its captured stderr on every reload, so mirror
        # logs into a rotating file that survives reloads (capped, small quota).
        f"LOG_LEVEL={prior.get('LOG_LEVEL') or 'INFO'}",
        f"LOG_FILE={prior.get('LOG_FILE') or 'logs/fce_trainer.log'}",
        # Log the retrieved examples and the full prompt sent to the LLM. The
        # rotating handler caps the size, so this stays bounded.
        f"LOG_AI_PROMPTS={prior.get('LOG_AI_PROMPTS') or '1'}",
    ]
    for name in ("GOOGLE_AI_API_KEY", "GOOGLE_AI_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL",
                 "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "GROQ_API_KEY", "GROQ_MODEL"):
        value = existing.get(name) or prior.get(name)
        if value:
            lines.append(f"{name}={value}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def read_local_env() -> dict[str, str]:
    """Read the local .env (if any) so AI keys can be forwarded."""
    path = PROJECT_ROOT / ".env"
    if not path.exists():
        return {}
    return parse_env(path.read_text(encoding="utf-8"))


WSGI_TEMPLATE = """import sys

path = '/home/{username}/fce_treining'
if path not in sys.path:
    sys.path.insert(0, path)

from dotenv import load_dotenv
load_dotenv(path + '/.env')

from app import create_app

application = create_app()
app = application
"""

# Free PythonAnywhere accounts cannot run a shell command without a human
# opening a console in a browser: SSH is paid-only, the consoles API replies
# "Console not yet started", and scheduled tasks are unavailable. So the parts
# that genuinely need a shell (venv + pip) are packaged as one script the user
# runs, while uploads, WSGI, web app config and reload all go through the API.
SETUP_SCRIPT_TEMPLATE = """#!/bin/bash
# One-shot setup for the FCE Trainer on PythonAnywhere.
# Run in a PythonAnywhere Bash console:   bash ~/pa_setup.sh
set -e

APP_DIR="$HOME/fce_treining"
PYTHON="{python_exe}"

echo ">>> extracting code into $APP_DIR"
mkdir -p "$APP_DIR"
tar xzf "$HOME/fce_deploy.tar.gz" -C "$APP_DIR"
rm -f "$HOME/fce_deploy.tar.gz"

echo ">>> installing .env"
if [ -f "$HOME/fce_deploy.env" ]; then
    mv "$HOME/fce_deploy.env" "$APP_DIR/.env"
fi

echo ">>> creating virtualenv with $PYTHON"
cd "$APP_DIR"
if [ ! -x venv/bin/python ]; then
    "$PYTHON" -m venv venv
fi

echo ">>> installing dependencies (this takes a few minutes)"
venv/bin/pip install --upgrade pip -q
venv/bin/pip install -r requirements-deploy.txt -q

echo ">>> verifying the app imports"
venv/bin/python -c "from app import create_app; create_app(); print('APP_OK')"

echo ">>> embedding any RAG examples that still need a vector"
# Incremental on purpose: a no-op when the corpus already matches this backend,
# so redeploys do not burn embedding quota re-embedding everything.
venv/bin/python -m scripts.rag_manager rebuild-embeddings || true

echo
echo "SETUP COMPLETE. Tell the agent, or reload the web app from the Web tab."
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy to PythonAnywhere via the API.")
    parser.add_argument("--username", required=True, help="PythonAnywhere username")
    parser.add_argument("--token", default=os.environ.get("PA_TOKEN", ""),
                        help="API token (or set PA_TOKEN). Account -> API Token.")
    parser.add_argument("--host", choices=["us", "eu"], default="us")
    parser.add_argument("--domain", help="Defaults to <username>.pythonanywhere.com")
    parser.add_argument("--python", default=DEFAULT_PYTHON,
                        help=f"Web app Python version (default {DEFAULT_PYTHON})")
    parser.add_argument("--ai-provider", default="deepseek",
                        help="AI_PROVIDER to set on the host (default deepseek). "
                             "Embeddings still use Gemini unless overridden.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check credentials and print the plan without changing anything")
    parser.add_argument("--reload-only", action="store_true",
                        help="Just reload the web app (after running the setup script)")
    parser.add_argument("--finalize", action="store_true",
                        help="Apply web app config + reload (run after the setup script)")
    parser.add_argument("--upload-corpus", metavar="DB",
                        help="Upload this RAG database to the host. Build it with the "
                             "SAME embedding backend the host uses "
                             "(see DEPLOY.md) or retrieval falls back to keywords.")
    args = parser.parse_args()

    if not args.token:
        print("error: no API token. Pass --token or set PA_TOKEN.", file=sys.stderr)
        print("       Get one at pythonanywhere.com -> Account -> API Token.", file=sys.stderr)
        return 2

    if args.finalize or args.reload_only:
        return finalize(args)

    domain = args.domain or f"{args.username}.pythonanywhere.com"
    home = f"/home/{args.username}"
    app_dir = f"{home}/fce_treining"
    remote_tar = f"{home}/fce_deploy.tar.gz"

    client = PythonAnywhere(args.username, args.token, args.host)

    print(f"PythonAnywhere: {args.host} | user={args.username} | domain={domain}")
    try:
        cpu = client.cpu()
        print(f"  CPU today: {cpu.get('daily_cpu_total_usage_seconds')}s "
              f"of {cpu.get('daily_cpu_limit_seconds')}s")
        versions = client.python_versions()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("       Check the username, token and --host (us/eu).", file=sys.stderr)
        return 1

    available = versions.get("available_python3_versions", [])
    python_version = args.python
    if available and python_version not in available:
        # Fall back to the newest version the account actually offers.
        ordered = sorted(available, key=lambda v: [int(p) for p in v.replace("python", "").split(".")])
        python_version = ordered[-1]
        print(f"  ! {args.python} unavailable; using {python_version} (options: {available})")
    print(f"  Python version: {python_version}")

    existing_webapps = []
    try:
        existing_webapps = [w.get("domain_name") for w in client.list_webapps()]
    except Exception:
        pass
    print(f"  Existing web apps: {existing_webapps or 'none'}")

    local_env = read_local_env()
    forward = [k for k in ("GOOGLE_AI_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY")
               if local_env.get(k)]
    print(f"  Forwarding AI keys: {forward or 'NONE (generation will not work!)'}")

    if args.dry_run:
        print("\nDry run — nothing was changed. Plan:")
        print(f"  1. pack project -> {home}/fce_deploy.tar.gz")
        print("  2. upload archive, generated .env and setup script")
        print(f"  3. write WSGI file, configure web app {domain} ({python_version})")
        print("  4. YOU run one command in a PythonAnywhere Bash console:")
        print("       bash ~/pa_setup.sh")
        print(f"  5. reload {domain}")
        return 0

    tarball = build_tarball(PROJECT_ROOT / "fce_deploy.tar.gz")
    size_mb = tarball.stat().st_size / 1_048_576
    print(f"\n[1/4] Packed {tarball.name} ({size_mb:.1f} MB)")

    print("[2/4] Uploading archive, .env and setup script…")
    client.upload(tarball, f"{home}/fce_deploy.tar.gz")
    # Reuse whatever the host already has so a redeploy keeps SECRET_KEY (and so
    # does not log every user out) and any host-specific overrides.
    prior_remote = {}
    for candidate in (f"{app_dir}/.env", f"{home}/fce_deploy.env"):
        try:
            found = client.download(candidate)
        except Exception:
            found = None
        if found:
            prior_remote = parse_env(found)
            print(f"      reusing settings from existing {candidate}")
            break
    client.upload_bytes(build_env_file(args, local_env, prior_remote=prior_remote),
                        f"{home}/fce_deploy.env", ".env")
    setup_script = SETUP_SCRIPT_TEMPLATE.format(
        username=args.username, python_exe=f"python{python_version}"
    )
    client.upload_bytes(setup_script.encode("utf-8"), f"{home}/pa_setup.sh", "pa_setup.sh")
    tarball.unlink(missing_ok=True)

    if args.upload_corpus:
        corpus = Path(args.upload_corpus).expanduser()
        if not corpus.exists():
            print(f"      ! corpus not found: {corpus}", file=sys.stderr)
            return 1
        client.upload(corpus, f"{app_dir}/{RAG_DB_NAME}")
        print(f"      uploaded corpus {corpus.name} ({corpus.stat().st_size // 1024} KB)")
    print("      done")

    print("[3/4] Configuring the web app…")
    wsgi_body = WSGI_TEMPLATE.format(username=args.username)
    wsgi_path = f"/var/www/{args.username}_pythonanywhere_com_wsgi.py"
    try:
        client.upload_bytes(wsgi_body.encode("utf-8"), wsgi_path, "wsgi.py")
        print(f"      wrote {wsgi_path}")
    except Exception as exc:
        print(f"      ! could not write WSGI file automatically: {exc}")
        print(f"        set it manually to:\n{wsgi_body}")

    if domain not in existing_webapps:
        resp = client.create_webapp(domain, python_version)
        if resp.status_code >= 400:
            print(f"      ! create webapp: HTTP {resp.status_code} {resp.text[:200]}")
            print("        Create it manually: Web tab -> Add a new web app -> Manual configuration.")
        else:
            print(f"      created web app {domain}")

    try:
        client.update_webapp(
            domain,
            # Must match the venv's interpreter or the app will not import.
            python_version=python_version,
            source_directory=app_dir,
            virtualenv_path=f"{app_dir}/venv",
            force_https=True,
        )
        print(f"      set python {python_version}, source dir, virtualenv and HTTPS")
    except Exception as exc:
        print(f"      ! webapp config: {exc}")

    try:
        client.add_static(domain, "/static/", f"{app_dir}/static")
        print("      mapped /static/")
    except Exception:
        pass

    print("\n[4/4] Uploads and configuration are done.")
    print("PythonAnywhere does not let a free account run shell commands without a")
    print("browser (no SSH, consoles are browser-gated, scheduled tasks blocked),")
    print("so the virtualenv and dependencies need one command from you.\n")
    print("  1. Open:  https://www.pythonanywhere.com/user/"
          f"{args.username}/consoles/")
    print("  2. Start a 'Bash' console and run:\n")
    print("         bash ~/pa_setup.sh\n")
    print("  3. Tell me when it prints SETUP COMPLETE and I will reload the app.\n")
    print(f"Your app will then be live at https://{domain}")
    return 0


def apply_webapp_config(client: PythonAnywhere, *, domain: str, username: str,
                        app_dir: str, python_version: str) -> None:
    """Point the web app at the code and virtualenv, map /static/ and reload.

    Two ordering constraints on the PythonAnywhere side:
      * a ``virtualenv_path`` is rejected until the venv exists, so this runs
        after the setup script;
      * the venv is validated against the web app's *current* Python, so the
        Python version must be switched in a separate request first.
    """
    try:
        client.update_webapp(domain, python_version=python_version)
        print(f"  set web app Python to {python_version}")
    except Exception as exc:
        print(f"  ! could not set python_version: {exc}")

    try:
        client.update_webapp(
            domain,
            source_directory=app_dir,
            virtualenv_path=f"{app_dir}/venv",
            force_https=True,
        )
        print(f"  configured {domain}: {app_dir}, venv, HTTPS")
    except Exception as exc:
        print(f"  ! webapp config: {exc}")
        raise

    wsgi_path = f"/var/www/{username}_pythonanywhere_com_wsgi.py"
    try:
        client.upload_bytes(WSGI_TEMPLATE.format(username=username).encode("utf-8"),
                            wsgi_path, "wsgi.py")
        print(f"  wrote {wsgi_path}")
    except Exception as exc:
        print(f"  ! could not write WSGI file: {exc}")

    try:
        client.add_static(domain, "/static/", f"{app_dir}/static")
        print("  mapped /static/")
    except Exception:
        pass

    client.reload_webapp(domain)
    print(f"  reloaded https://{domain}")


def finalize(args) -> int:
    """Apply web app config + reload once the venv exists on the host."""
    client = PythonAnywhere(args.username, args.token, args.host)
    domain = args.domain or f"{args.username}.pythonanywhere.com"
    app_dir = f"/home/{args.username}/fce_treining"

    versions = client.python_versions().get("available_python3_versions", [])
    python_version = args.python
    if versions and python_version not in versions:
        python_version = sorted(versions, key=lambda v: [int(p) for p in v.split(".")])[-1]

    print(f"Finalising {domain} (python {python_version})")
    try:
        apply_webapp_config(client, domain=domain, username=args.username,
                            app_dir=app_dir, python_version=python_version)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("  If it mentions 'No virtualenv detected', run the setup script first:",
              file=sys.stderr)
        print("    bash ~/pa_setup.sh", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
