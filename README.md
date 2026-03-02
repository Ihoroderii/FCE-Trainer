# FCE Exam Trainer

A **Python-only** web app to practise for the **Cambridge B2 First (FCE)** exam. No JavaScript files: everything is server-rendered with **Flask** and **Jinja2**. Logic, data, and HTML generation are in Python; the only script on the page is a short inline timer (start/pause).

## Paper structure

- **Use of English:** Part 1 (multiple-choice cloze), Part 2 (open cloze), Part 3 (word formation), Part 4 (key word transformation, from DB + OpenAI).
- **Reading:** Part 5 (multiple choice), Part 6 (gapped text), Part 7 (multiple matching).
- **75-minute** timer in the header; you can move between parts in any order.

## How to run

### 1. Virtual environment (recommended)

```bash
cd fce_treining
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. OpenAI (for Part 4)

```bash
cp .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY=sk-...` (get a key from [OpenAI](https://platform.openai.com/api-keys)).

### 4. Start the server

```bash
python app.py
```

Open **http://localhost:3000**. All pages are rendered by the server; “Check answers” and “Next” use form POST/GET.

## Project layout (Python only)

- **app.py** — Flask app: routes, session, DB (SQLite), OpenAI for Part 4, HTML builders for each part, answer checking.
- **data.py** — All exercise data (Parts 1–3, 5–7) and seed tasks for Part 4.
- **templates/** — `base.html` (layout + inline timer), `index.html` (one form per part).
- **static/styles.css** — Styles only (no JS).
- **fce_trainer.db** — SQLite DB for Part 4 tasks (created on first run).

No `app.js`, `data.js`, or other JavaScript files. The app works like a classic server-rendered site (like a StoryAI-style project): every action is a request to the server, which returns full HTML.

## Code review (GitHub Actions)

On **push** and **pull_request** to `main`/`master`, the workflow in `.github/workflows/code-review.yml` runs:

- **Ruff** — lint and format check (see `pyproject.toml` for rules)
- **Bandit** — security checks on Python code
- **App import** — ensures the app module loads

To fix lint/format locally before pushing:

```bash
pip install ruff bandit
ruff check . --fix
ruff format .
bandit -r . -x .venv,.git
```

To make the format check strict (fail the workflow when code is not formatted), remove `continue-on-error: true` from the "Ruff (format check)" step in the workflow. You can also tighten `[tool.ruff.lint].ignore` in `pyproject.toml` over time (e.g. enable F841, I001) and fix reported issues.

## Adding more exercises

Edit **data.py**: `PART_1_DATA`, `PART_2_DATA`, `PART_3_DATA`, `PART_5_DATA`, `PART_6_DATA`, `PART_7_DATA`. Part 4 tasks are stored in the DB and can be generated via OpenAI.

Good luck with your FCE preparation.
