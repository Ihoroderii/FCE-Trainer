# Proctor configuration (Mock exam)

The app uses the proctor from **an external directory** when available, then falls back to this local config.

## Build and run proctor together with FCE Trainer

Use three processes: **proctor backend**, **proctor frontend**, and **FCE app**. Default ports:

| Service            | URL                     | Port |
|--------------------|-------------------------|------|
| FCE Trainer         | http://localhost:3000  | 3000 |
| Proctor backend     | http://localhost:8000  | 8000 |
| Proctor frontend    | http://localhost:5173  | 5173 |

### 1. Proctor backend

```bash
cd /path/to/proctor/backend

# Optional: start PostgreSQL (if not already running)
# docker compose up -d postgres   # if proctor has docker-compose
# Or use your own Postgres and set DATABASE_URL in .env

cp .env.example .env
# Edit .env: set DATABASE_URL (and JWT_SECRET). LiveKit vars are not needed (WebRTC-only).

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Create tables and seed exam + proctor user (exam code DEMO, proctor@test.com / proctor123)
python -c "
import asyncio
from app.database import AsyncSessionLocal, engine, Base
from app.models import Exam, Proctor
from app.services.auth_service import hash_password

async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        db.add(Exam(code='DEMO', title='Demo Exam', duration_minutes=60))
        db.add(Proctor(email='proctor@test.com', hashed_password=hash_password('proctor123')))
        await db.commit()
asyncio.run(seed())
print('Exam DEMO and proctor proctor@test.com / proctor123 created')
"

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Proctor frontend

In a second terminal:

```bash
cd /path/to/proctor/frontend
npm install
npm run dev
```

Vite will serve the app at http://localhost:5173 and proxy `/api` and `/ws` to the backend (8000).

### 3. FCE Trainer

In a third terminal:

```bash
cd /path/to/fce_treining

# If proctor is not in ../proctor, point to it:
# export PROCTOR_DIR=/path/to/proctor

# Optional overrides (defaults are localhost:8000 and localhost:5173):
# export PROCTOR_BACKEND_URL=http://localhost:8000
# export PROCTOR_FRONTEND_URL=http://localhost:5173

python app.py
# Or: PORT=3000 python app.py
```

FCE runs at http://localhost:3000. The proctor loader will use the sibling `proctor` directory (or `PROCTOR_DIR`) and the config there.

### 4. Proctor config for FCE

In the **proctor** project root (e.g. `wrk/proctor`), ensure FCE can reach backend and frontend. Either:

- **config.json** in the proctor root with:
  ```json
  {
    "enabled": true,
    "name": "My proctor",
    "backend_url": "http://localhost:8000",
    "frontend_url": "http://localhost:5173",
    "exam_code": "DEMO"
  }
  ```
- Or set env when running FCE: `PROCTOR_BACKEND_URL`, `PROCTOR_FRONTEND_URL`, `PROCTOR_EXAM_CODE`.

### 5. Try the flow

1. Open http://localhost:3000 (FCE Trainer).
2. Log in if needed, go to **Take mock exam** → **Start exam**.
3. You are redirected to the proctor frontend (http://localhost:5173/entry?session_id=...).
4. The candidate exam page loads and asks for camera; proctors can watch at http://localhost:5173/proctor/login (proctor@test.com / proctor123) → Sessions → pick the session.

## External proctor (recommended)

To use the full proctor (e.g. LiveKit-based proctor in a sibling repo):

1. **Set the proctor root** (one of):
   - **Default:** Place the proctor in a sibling directory named `proctor`:
     - Project: `.../wrk/fce_treining`
     - Proctor: `.../wrk/proctor`
   - **Or** set the path explicitly:
     ```bash
     export PROCTOR_DIR=/path/to/proctor
     # or relative to the FCE app root:
     export PROCTOR_DIR=../proctor
     ```

2. **To have FCE actually call the proctor:** In the **external** proctor root, add `config.json` or `fce_config.json` with:
   - `backend_url` — proctor backend (e.g. `http://localhost:8000`)
   - `frontend_url` — proctor frontend (e.g. `http://localhost:5173`)
   - `exam_code` — exam code that exists in the proctor backend (e.g. `DEMO`; create via proctor’s seed data)
   Example (see also `wrk/proctor/fce_config.example.json`):
   ```json
   { "enabled": true, "name": "Proctor", "backend_url": "http://localhost:8000", "frontend_url": "http://localhost:5173", "exam_code": "DEMO" }
   ```
   Without this file, the app still considers the proctor “configured” if the directory has `backend/`, but “Start mock exam” will not call the proctor; it will only redirect to the FCE Use of English page.

3. Restart the FCE app. When a user clicks **Take mock exam** → **Start exam**, the FCE app will call `POST backend_url/api/session/join` (wrk/proctor) and redirect the candidate to the proctor frontend so they join the proctored session.

## Local fallback (this directory)

If no external proctor directory is found, the app uses this directory:

1. Copy the example config:
   ```bash
   cp config.example.json config.json
   ```
2. Set `"enabled": true` in `config.json` (and optional `"name"`).
3. Restart the app.

You can also enable via environment (no file):

- `PROCTOR_ENABLED=1` — enables mock exam.
- `PROCTOR_NAME=My proctor` — optional display name.

## Summary

| Source              | When used                          |
|---------------------|------------------------------------|
| `PROCTOR_DIR` / `../proctor` | If that path exists and has `backend/` or a config file |
| This directory      | If no external proctor is found    |
