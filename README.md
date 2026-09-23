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

### 3. Configure an AI provider (for generated tasks)

```bash
cp .env.example .env
```

Edit `.env` and set **one** key. Providers are tried in this order unless you
pin one with `AI_PROVIDER`:

| Provider | Env vars | Notes |
|---|---|---|
| DeepSeek | `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` | **primary**; paid, OpenAI-compatible |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL` | paid |
| Groq | `GROQ_API_KEY`, `GROQ_MODEL` | free tier |
| Google Gemini | `GOOGLE_AI_API_KEY`, `GOOGLE_AI_MODEL` | free tier; auto-fails over across models if one is retired or overloaded |
| Hugging Face | `HUGGINGFACE_API_KEY`, `HUGGINGFACE_MODEL` | free tier |

Force one with e.g. `AI_PROVIDER=deepseek`. Without any key the app still runs —
it just cannot generate new tasks.

The chosen provider powers task generation, answer explanations and writing
feedback. **RAG embeddings are configured separately** (see below), because
DeepSeek has no embeddings endpoint — the default deployment pairs a DeepSeek LLM
with free Gemini embeddings.

### 4. Start the server

```bash
python app.py
```

Open **http://localhost:3000**. All pages are rendered by the server; “Check answers” and “Next” use form POST/GET.

## Move to another computer

Your code can live in git, but secrets should not:

- keep `.env` local
- keep API keys and SMTP passwords out of git

Your saved app state can now be committed safely as a tracked snapshot:

```bash
python3 scripts/sync_portable_state.py
```

That command copies the important runtime data into `portable_state/`:

- `fce_trainer.db`
- generated listening audio
- generated transcripts

Commit `portable_state/` together with your code. On another computer:

1. Clone the repo.
2. Create `.env` from `.env.example` and add your keys.
3. Install dependencies.
4. Start the app.

If the live runtime files are missing, the app restores them automatically from `portable_state/`. You can also do it manually:

```bash
python3 scripts/restore_portable_state.py
```

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

## RAG example corpus (style reference for generated tasks)

Generated tasks are only as good as the examples the model sees. The RAG corpus
stores real FCE exercises and injects the closest matches into every generation
prompt as **style references** (the prompt always instructs the model to write an
original task and not copy them). Retrieval is wired into Parts 1–7 plus
"get phrases" — if the corpus is empty, generation still works and simply runs
without references.

### Where it is stored

The corpus lives in its own SQLite file, **`rag_examples.db`**, not in the main
app database. This is deliberate: material imported from a published student book
is copyrighted, and the main database is copied into the tracked
`portable_state/fce_trainer.db` and pushed to a public repository. Keeping the
corpus separate means imported text can never be committed. `rag_examples.db` and
`materials/` are both gitignored, and `sync_portable_state()` additionally strips
any `rag_examples` rows from the snapshot as a second line of defence.

Override the location with `RAG_DB_PATH` if you want it elsewhere.

### How retrieval works

Each example is embedded and ranked by cosine similarity to the query. Two
backends are supported, chosen with `RAG_EMBEDDING_BACKEND` (`auto` by default):

| Backend | Model | Cost | Notes |
|---|---|---|---|
| `local` | `BAAI/bge-small-en-v1.5` (384-dim) | free | `pip install fastembed`; offline after the first download. Preferred by `auto`. |
| `openai` | `text-embedding-3-small` (1536-dim) | paid | Needs credits. |

Each stored vector records the model that produced it, so vectors of different
widths are never compared. After switching backends, re-embed with
`python -m scripts.rag_manager rebuild-embeddings --all`.

With no backend available, retrieval degrades to keyword matching over the topic
and task text — it still returns references, but semantic matches are missed.

### Importing your own material

`scripts/import_examples.py` turns a PDF/DOCX/TXT book — or a folder of
screenshots — into corpus entries. It runs in three reviewable stages so
nothing enters the corpus unchecked:

```bash
# 1. PDF -> text with page markers (scanned PDFs are OCR'd automatically)
python -m scripts.import_examples extract materials/fce_student_book.pdf --pages 10-120

# 2. text -> JSON examples (AI-structured; review the file it writes)
python -m scripts.import_examples structure --text materials/fce_student_book.txt

# 3. JSON -> database + embeddings
python -m scripts.import_examples load materials/fce_student_book.examples.json --commit
```

Or all three at once:

```bash
python -m scripts.import_examples run materials/fce_student_book.pdf --commit
```

Notes:

- **Screenshots work too.** Point `extract` at a folder of images (`.png`,
  `.jpg`, `.webp`, …) and each is OCR'd with macOS Vision:
  ```bash
  python -m scripts.import_examples extract ~/Desktop --out materials/screenshots.txt
  python -m scripts.import_examples structure --text materials/screenshots.txt
  ```
  Each page records its source image name, so entries stay traceable.
- **Audit before loading.** `structure` output often includes textbook grammar
  and vocabulary drills ("from the box", "verb in brackets") and, occasionally,
  Listening/Writing tasks mislabelled with a part number. `audit` finds both:
  ```bash
  python -m scripts.import_examples audit materials/screenshots.examples.json --drop
  ```
  It auto-rejects only unambiguous cases; softer format warnings are reported for
  you to judge, since 3-option clozes and cropped pages are perfectly valid.
- **Scanned books work.** Many FCE books are page images with no text layer.
  `extract` detects that and falls back to OCR using the **macOS Vision**
  framework (the same engine as Preview's Live Text) — local, free, no API key.
  Install its dependencies once:
  ```bash
  pip install pymupdf pyobjc-framework-Vision
  ```
  Expect roughly a second per page. Force it with `--ocr`, disable with
  `--no-ocr`, and raise quality with `--dpi 300` if the scans are poor. OCR is
  macOS-only; elsewhere add a text layer with `ocrmypdf`, then use `--no-ocr`.
- `structure` uses your configured AI provider key and always writes a JSON file
  first, so you can read, fix or delete entries before loading.
- Use `--no-ai` for a faster, free pass that segments on printed "Part N"
  headings. It is cruder and cannot infer a part number that is not printed.
- `load` is a **dry run unless you pass `--commit`**. `--commit` also computes
  embeddings via `text-embedding-3-small`.
- `source_page` metadata records the real book page, so every entry can be traced
  back to its source.
- The extractor marks entries it believes are incomplete with
  `metadata.partial: true`.

### Managing the corpus

```bash
python -m scripts.rag_manager stats                    # counts by paper/part
python -m scripts.rag_manager list --paper reading     # browse
python -m scripts.rag_manager show 3                   # inspect one entry
python -m scripts.rag_manager add-json my_examples.json
python -m scripts.rag_manager rebuild-embeddings       # after bulk edits
python -m scripts.rag_manager delete 3
```

The schema, retrieval and prompt-injection code live in `app/rag/`.

Good luck with your FCE preparation.
