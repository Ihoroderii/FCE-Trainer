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
**Cons:** Manual deploy (git pull), free tier has limits (one app, subdomain only).

### Steps

1. **Sign up:** [pythonanywhere.com](https://www.pythonanywhere.com) → **Pricing & signup** → **Create a Beginner account** (free).

2. **Open a Bash console** from the dashboard.

3. **Clone your repo and set up the app:**
   ```bash
   cd ~
   git clone https://github.com/YOUR_USERNAME/fce_treining.git
   cd fce_treining
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Create a `.env` file** (so the app can read env vars):
   ```bash
   nano .env
   ```
   Add at least:
   ```
   SECRET_KEY=your-64-char-hex-from-secrets.token_hex(32)
   GOOGLE_AI_API_KEY=your-key
   ```
   Or use Groq/OpenAI. Save (Ctrl+O, Enter, Ctrl+X).

5. **Web tab:**  
   - **Add a new web app** → **Manual configuration** → Python 3.10 (or latest).  
   - Under **Code**, set:
     - **Source code:** `/home/YOUR_USERNAME/fce_treining`
     - **Working directory:** `/home/YOUR_USERNAME/fce_treining`

6. **WSGI file:** Click the WSGI configuration file link. Replace its contents with:
   ```python
   import sys
   path = '/home/YOUR_USERNAME/fce_treining'
   if path not in sys.path:
       sys.path.insert(0, path)
   import os
   from dotenv import load_dotenv
   load_dotenv(os.path.join(path, '.env'))
   from app import create_app
   app = create_app()
   ```
   Replace `YOUR_USERNAME` with your PythonAnywhere username. Save.

7. **Set virtualenv:** In the Web app page, **Virtualenv** section, set:
   `/home/YOUR_USERNAME/fce_treining/venv`

8. **Static files (optional but recommended):**  
   URL: `/static/`  
   Directory: `/home/YOUR_USERNAME/fce_treining/static`

9. **Reload the web app.** Your app will be at `https://YOUR_USERNAME.pythonanywhere.com`.

10. **To update later:** In Bash:
    ```bash
    cd ~/fce_treining && git pull && source venv/bin/activate && pip install -r requirements.txt
    ```
    Then reload the web app from the Web tab.

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
