# Deploy FCE Trainer for free

This app runs as a Flask app with SQLite. Below are free hosting options. Pick one.

---

## Option 1: Render.com (easiest, free tier)

**Pros:** Connect GitHub, auto-deploy. No server to manage.  
**Cons:** Free tier has **ephemeral disk** — SQLite is reset on each deploy or after ~15 min inactivity (spin-down). User accounts and progress won’t persist long-term unless you upgrade or use a different DB.

### Steps

1. **Push your code to GitHub** (if not already):
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/fce_treining.git
   git push -u origin main
   ```

2. **Sign up:** [render.com](https://render.com) → Sign up (free, GitHub login works).

3. **New Web Service:**
   - Dashboard → **New +** → **Web Service**
   - Connect your GitHub repo `fce_treining`
   - Configure:
     - **Name:** `fce-trainer` (or any)
     - **Region:** choose nearest
     - **Branch:** `main`
     - **Runtime:** Python 3
     - **Build command:**
       ```bash
       pip install -r requirements.txt
       ```
     - **Start command:**
       ```bash
       python -m gunicorn --bind 0.0.0.0:$PORT wsgi:app
       ```
       (Using `python -m gunicorn` ensures the same Python that has your dependencies is used; plain `gunicorn` can be "command not found" on some hosts.)
   - **Instance type:** Free

4. **Environment variables** (Render → your service → **Environment**):
   - `SECRET_KEY` — required in production. Generate:
     ```bash
     python -c "import secrets; print(secrets.token_hex(32))"
     ```
   - At least one AI key so tasks can be generated, e.g.:
     - `GOOGLE_AI_API_KEY` (free tier at [aistudio.google.com](https://aistudio.google.com/apikey)), or
     - `OPENAI_API_KEY`, or
     - `GROQ_API_KEY`
   - Optional: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` (set redirect URI to `https://YOUR-SERVICE.onrender.com/login/google/authorized`)

5. **Deploy:** Click **Create Web Service**. Render builds and runs the app. Your URL will be like `https://fce-trainer.onrender.com`.

**Note:** On free tier the app may sleep after inactivity; first load can take 30–60 seconds.

---

## Option 2: PythonAnywhere (free tier, SQLite persists)

**Pros:** Persistent disk — SQLite and user data survive restarts.  
**Cons:** Manual deploy (git pull), free tier has limits (one app, subdomain only), and outbound internet is restricted on free accounts.

### Automated (recommended)

`scripts/deploy_pythonanywhere.py` drives the PythonAnywhere API for everything
the API allows: packing and uploading the project, writing the WSGI file,
configuring the web app and reloading.

**A free account cannot run shell commands without a browser.** SSH is paid-only,
the consoles API returns *"Console not yet started"*, and scheduled tasks return
*"not available on free accounts"*. Creating the virtualenv is therefore the one
step you run yourself, in a Bash console. Paid accounts can do it fully headless.

1. **Get an API token:** [pythonanywhere.com](https://www.pythonanywhere.com) →
   **Account** → **API Token** → *Create new API token*.

2. **Upload everything:**
   ```bash
   python -m scripts.deploy_pythonanywhere --username YOUR_USERNAME --token YOUR_TOKEN
   # add --host eu  if your account is on eu.pythonanywhere.com
   # add --dry-run  to check credentials and print the plan without changing anything
   ```

3. **Create the virtualenv** — in the browser, open
   `https://www.pythonanywhere.com/user/YOUR_USERNAME/consoles/`, start a **Bash**
   console, and run:
   ```bash
   bash ~/pa_setup.sh
   ```
   That extracts the code to `~/fce_treining`, installs
   `requirements-deploy.txt`, verifies the app imports, and re-embeds the RAG
   corpus with Gemini. It prints `SETUP COMPLETE` when done.

4. **Point the web app at it and reload:**
   ```bash
   python -m scripts.deploy_pythonanywhere --username YOUR_USERNAME --token YOUR_TOKEN --finalize
   ```
   This sets the source directory, virtualenv and Python version, maps
   `/static/`, and reloads. It must run *after* step 3, because PythonAnywhere
   rejects a `virtualenv_path` that does not exist yet.

### Where to see the logs

PythonAnywhere keeps three log files per web app. Open the **Web** tab and use
the **Log files** links, or read them directly:

| File | Contains |
|---|---|
| `/var/log/USERNAME.pythonanywhere.com.error.log` | **Your app's output** — Python tracebacks and everything the `fce_trainer` logger writes |
| `/var/log/USERNAME.pythonanywhere.com.access.log` | Every HTTP request (method, path, status, timing) |
| `/var/log/USERNAME.pythonanywhere.com.server.log` | uWSGI server startup and worker messages |

Your app logs go to **stderr**, which is why they land in the *error* log — that
is expected, not a sign of a problem.

**PythonAnywhere truncates the error log on every reload**, so it only shows
output since the last reload. To keep history, the deploy generates a `.env`
with:

```
LOG_LEVEL=INFO
LOG_FILE=logs/fce_trainer.log
```

which mirrors everything into a rotating file (capped at 1 MB × 4, so it cannot
eat the disk quota) at:

```
~/fce_treining/logs/fce_trainer.log
```

Tail it from a console:

```bash
tail -f ~/fce_treining/logs/fce_trainer.log
```

Raise verbosity with `LOG_LEVEL=DEBUG` in `.env` and reload. On startup the app
records where it is logging:

```
FCE-Trainer starting (debug=False, AI=enabled, provider=google,
                      log_level=INFO, log_file=logs/fce_trainer.log)
```

**Free-tier gotchas worth knowing:**

- **Web apps expire every 3 months.** If your site shows PythonAnywhere's
  "Coming Soon" page, click **Run until 3 months from today** on the Web tab.
  There is no API for this.
- **Re-running step 2 later updates the code** (it overwrites the uploaded
  archive); follow with steps 3 and 4 to apply it.
- **Disk quota is 512 MB** and a virtualenv with numpy/Pillow is ~180 MB. Check
  usage with `du -sh ~` in a console. Old project copies and `~/.cache/pip` are
  the usual culprits:
  ```bash
  rm -rf ~/.cache/pip ~/OLD_PROJECT/venv
  ```
- **The venv Python must match the web app's Python.** `--finalize` handles this
  by switching `python_version` in a separate request first, because
  PythonAnywhere validates the venv against the app's *current* version.
- **Embeddings can hit the Gemini free-tier quota.** Rebuilding 178 examples
  needs roughly 178 embedding units and the free tier throttles with HTTP 429;
  the client retries with backoff and uses small batches, so re-running usually
  succeeds. If the quota is exhausted for the day, the host falls back to
  keyword matching — or build the corpus locally and upload the result:
  ```bash
  # locally
  cp rag_examples.db /tmp/rag_host.db
  RAG_DB_PATH=/tmp/rag_host.db RAG_EMBEDDING_BACKEND=google \
    python -m scripts.rag_manager rebuild-embeddings --all
  # then upload /tmp/rag_host.db to ~/fce_treining/rag_examples.db
  ```
  Stored vectors record their model, so vectors from a different backend are
  ignored rather than compared against the wrong query embedding.
- **Listening audio needs the outbound proxy.** edge-tts opens a websocket to
  `speech.platform.bing.com`, and PythonAnywhere only permits outbound traffic
  through `proxy.server:3128`. aiohttp's `trust_env` does not cover
  `ws_connect`, so `app/services/tts.py` passes `https_proxy` explicitly to
  `edge_tts.Communicate(proxy=...)`. Without it you get a 70-line traceback
  ending in `[Errno 101] Network is unreachable` and no audio. It is already
  handled, but worth knowing if you move to another locked-down host.

**Notes specific to this app on PythonAnywhere:**

- **Networking is fine.** Free accounts are restricted to an allowlist, but the
  hosts this app needs are on it: `googleapis.com` (Gemini), `api.openai.com`,
  `api.deepseek.com`, `api.groq.com`, `huggingface.co`, `github.com`,
  `tts.speech.microsoft.com` (listening audio) and `microsofttranslator.com`
  (vocabulary translation).
- **Embeddings use Gemini, not a local model.** `fastembed` is skipped because
  its ONNX runtime plus the model would eat much of the free 512MB disk quota.
  The deploy therefore sets `RAG_EMBEDDING_BACKEND=google`, which uses the free
  Gemini embedding API. After the first deploy, re-embed the corpus once:
  ```bash
  cd ~/fce_treining && venv/bin/python -m scripts.rag_manager rebuild-embeddings --all
  ```
  Without this, retrieval still works via keyword matching, just less precisely.
- **Listening audio is not uploaded.** `static/listening` is generated audio; the
  tracked copy in `portable_state/` is restored on first start.
- **`.env` is never packed into the upload.** The deploy writes a fresh one, so
  local secrets are not copied to the host.

### Manual steps (if you prefer)

1. **Sign up:** [pythonanywhere.com](https://www.pythonanywhere.com) → **Pricing & signup** → **Create a Beginner account** (free).

2. **Open a Bash console** from the dashboard.

3. **Clone your repo and set up the app:**
   ```bash
   cd ~
   git clone https://github.com/YOUR_USERNAME/FCE-Trainer.git
   cd FCE-Trainer
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements-deploy.txt
   ```
   If free-account network restrictions block `git clone`, upload the project zip in the **Files** tab and unpack it in your home directory instead.

4. **Create a `.env` file** (so the app can read env vars):
   ```bash
   cp .env.example .env
   nano .env
   ```
   Set at least:
   ```
   SECRET_KEY=your-64-char-hex-from-secrets.token_hex(32)
   FLASK_ENV=production
   ```
   Add AI / SMTP / Google OAuth keys only if your PythonAnywhere account can reach those services. The core Flask + SQLite app works without them. Save (Ctrl+O, Enter, Ctrl+X).

5. **Web tab:**  
   - **Add a new web app** → **Manual configuration** → Python 3.10 (or latest).  
   - Under **Code**, set:
     - **Source code:** `/home/YOUR_USERNAME/FCE-Trainer`
     - **Working directory:** `/home/YOUR_USERNAME/FCE-Trainer`

6. **WSGI file:** Click the WSGI configuration file link. Replace its contents with:
   ```python
   import os
   import sys
   from pathlib import Path

   PROJECT_HOME = Path("/home/YOUR_USERNAME/FCE-Trainer")
   if str(PROJECT_HOME) not in sys.path:
       sys.path.insert(0, str(PROJECT_HOME))
   os.chdir(PROJECT_HOME)

   from dotenv import load_dotenv
   load_dotenv(PROJECT_HOME / ".env")

   from wsgi import application
   ```
   The same template is included in this repo as `pythonanywhere_wsgi.py`. Replace `YOUR_USERNAME` with your PythonAnywhere username. Save.

7. **Set virtualenv:** In the Web app page, **Virtualenv** section, set:
   `/home/YOUR_USERNAME/FCE-Trainer/venv`

8. **Static files:** Do **not** add a `/static/` mapping for this project. The Flask app serves its assets from the site root (`/styles.css`, `/main.js`, etc.), so a PythonAnywhere `/static/` rule is unnecessary and misleading.

9. **Reload the web app.** Your app will be at `https://YOUR_USERNAME.pythonanywhere.com`.

10. **To update later:** In Bash:
    ```bash
    cd ~/FCE-Trainer
    git pull
    source venv/bin/activate
    pip install -r requirements.txt
    ```
    Then reload the web app from the Web tab.

11. **What to expect on a free account:**
    - Core Flask pages, auth, and SQLite persistence should work.
    - AI-generated tasks, external TTS, password reset email, and Google OAuth may fail if PythonAnywhere free cannot reach the required third-party services.

---

## Option 3: Fly.io (free allowance, optional persistent volume)

**Pros:** Free tier with a small VM; you can attach a volume so SQLite persists.  
**Cons:** Requires Docker and the Fly CLI.

### Steps

1. **Install:** [Fly CLI](https://fly.io/docs/hands-on/install-flyctl/) and sign up: `fly auth signup` or `fly auth login`.

2. **In your project folder** create `Dockerfile`:
   ```dockerfile
   FROM python:3.12-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   ENV PORT=8080
   EXPOSE 8080
   CMD gunicorn --bind 0.0.0.0:${PORT} wsgi:app
   ```

3. **Launch app:**
   ```bash
   fly launch --no-deploy
   ```
   When asked for an org, pick your personal one. Say no to PostgreSQL if asked.

4. **Set secrets (env vars):**
   ```bash
   fly secrets set SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
   fly secrets set GOOGLE_AI_API_KEY=your-key
   ```

5. **Optional — persist SQLite:** Create a volume and mount it so the DB file lives on the volume. Example:
   ```bash
   fly volumes create fce_data --size 1 --region lax
   ```
   Then in `fly.toml` add under `[mounts]`:
   ```toml
   [mounts]
     source = "fce_data"
     destination = "/data"
   ```
   And set env so the app uses `/data/fce_trainer.db` (you’d need a small code change to set `DB_PATH` from `DATABASE_URL` or `DB_PATH` env, e.g. `os.environ.get("DB_PATH", str(APP_ROOT / "fce_trainer.db"))` and set `DB_PATH=/data/fce_trainer.db` in secrets).

6. **Deploy:**
   ```bash
   fly deploy
   ```
   Your app will be at `https://YOUR_APP_NAME.fly.dev`.

---

## Checklist for any host

- [ ] Set **SECRET_KEY** in production (never use the dev default).
- [ ] Set at least one **AI API key** (e.g. Google AI, OpenAI, or Groq) so task generation works.
- [ ] If using **Google “Connect with Google”**: create OAuth credentials and set the redirect URI to `https://YOUR_DOMAIN/login/google/authorized`.
- [ ] For **Render**: remember the free instance sleeps and disk is ephemeral; for persistent data use PythonAnywhere or Fly.io with a volume.

---

## Quick comparison

|                | Render        | PythonAnywhere | Fly.io        |
|----------------|---------------|----------------|---------------|
| Ease           | Easiest       | Medium         | More setup    |
| SQLite persist | No (ephemeral)| Yes            | Yes (volume)  |
| Free tier      | Yes, sleeps  | Yes, limited   | Yes, allowance|

For a first deploy with minimal steps, use **Render**. If you need **persistent user data and progress**, use **PythonAnywhere** or **Fly.io** with a volume.
