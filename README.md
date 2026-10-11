# Hadith Finder

Hadith Finder is a source-grounded question-answering application for scanned Islamic books, currently focused on *Fazail-e-Amal*. Users can ask questions in Bangla or English and receive short answers backed by exact source passages, printed page numbers, PDF page numbers, and links to the original scanned page.

The project is designed around one rule: if the indexed book does not contain enough evidence, the assistant should say so instead of guessing.

## Project Goals

- Build a reliable Q&A system over scanned religious texts.
- Preserve citation trust by showing exact database text, not model-generated source text.
- Connect each answer to the original scanned page for human verification.
- Support Bangla spelling variation, OCR noise, old literary forms, Arabic, and Urdu passages.
- Keep ingestion reproducible, reviewable, and resumable.
- Make accuracy measurable through retrieval and end-to-end evaluation.
- Prepare the codebase for adding more books later.

## Current User Experience

1. The user asks a question in Bangla or English.
2. The backend retrieves relevant book paragraphs using hybrid search.
3. The answer model writes only from retrieved passages.
4. Citations are verified against the source IDs actually sent to the model.
5. The frontend shows:
   - concise answer text;
   - numbered citation chips;
   - exact original paragraph text from the database;
   - book section/chapter;
   - printed page number;
   - PDF page number;
   - a scanned page viewer with paragraph highlighting.

## Repository Structure

```text
.
+-- backend/                  FastAPI API, ingestion, retrieval, generation, tests
|   +-- app/
|   |   +-- api/              REST and streaming API routes
|   |   +-- citation/         Citation verification
|   |   +-- core/             Settings, logging, database, security, text normalization
|   |   +-- embeddings/       Embedding provider adapters
|   |   +-- generation/       Answer prompts and LLM integration
|   |   +-- models/           SQLAlchemy database models
|   |   +-- reranking/        LLM/Cohere/Jina reranking abstractions
|   |   +-- retrieval/        Hybrid retrieval, fusion, query understanding
|   |   +-- schemas/          Pydantic API schemas
|   |   +-- services/         Chat orchestration and storage
|   +-- ingestion/            PDF/OCR/layout/load/embed/upload pipeline
|   +-- eval/                 Evaluation datasets and runners
|   +-- tests/                Unit and integration tests
|   +-- alembic/              Database migrations
|   +-- Dockerfile            Backend container
+-- frontend/                 Next.js app
|   +-- src/app/              App routes and providers
|   +-- src/components/       Chat UI, source cards, page viewer, debug panel
|   +-- src/lib/              API client, types, i18n helpers
+-- docs/
|   +-- ARCHITECTURE.md       Detailed engineering notes and accuracy decisions
+-- sources/                  Original PDFs
+-- data/                     Local generated data/cache, ignored by Git
+-- docker-compose.yml        Local PostgreSQL/pgvector and optional Redis
+-- render.yaml               Render backend deployment blueprint
+-- .env.example              Backend and ingestion environment template
```

## Technology Stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS v4, shadcn-style components, TanStack Query |
| Backend API | FastAPI, Pydantic, SQLAlchemy, Alembic |
| Database | PostgreSQL with pgvector |
| Retrieval | Vector search, full-text search, trigram search, reciprocal rank fusion |
| Generation | Anthropic or OpenAI-compatible LLM provider |
| Embeddings | Gemini, OpenAI, Cohere, Voyage, or local model |
| OCR | Google Cloud Vision recommended, Tesseract fallback |
| Storage | Local files in development, Supabase Storage in production |
| Evaluation | Pytest plus retrieval/e2e evaluation scripts |
| Deployment | Backend on Render, frontend on Vercel, database/storage on Supabase |

## High-Level Architecture

```text
User question
    |
    v
Frontend chat UI
    |
    v
FastAPI chat endpoint
    |
    v
Query understanding
    |
    v
Hybrid retrieval: vector + keyword + trigram
    |
    v
Fusion and reranking
    |
    v
Grounded answer generation
    |
    v
Citation verification
    |
    v
Database re-read of verified source passages
    |
    v
Answer + exact sources + scanned page links
```

## Ingestion Pipeline

The ingestion pipeline converts a scanned PDF into searchable, citeable database records.

```text
PDF
  -> render page images
  -> OCR each page
  -> reconstruct layout and paragraphs
  -> detect printed page numbers and sections
  -> load books/pages/paragraphs/chunks into PostgreSQL
  -> create embeddings
  -> upload page images/PDF to storage
```

Pipeline stages:

- `render`: converts PDF pages into OCR and viewer images.
- `ocr`: extracts text, words, lines, boxes, and confidence values.
- `layout`: reconstructs headers, footers, paragraphs, scripts, and bounding boxes.
- `structure`: builds printed page mappings and section trees.
- `load`: writes normalized records to PostgreSQL.
- `embed`: creates and stores vector embeddings.
- `upload`: sends page images and source PDF to object storage.

The pipeline is cached and resumable. Re-running only repeats missing or changed work.

## Accuracy Strategy

Hadith Finder protects source accuracy in several ways:

- OCR output is treated as data, not as final truth.
- The original scanned page remains visible for every citation.
- Printed page numbers are detected and reviewed instead of guessed.
- Manual page and section overrides are supported.
- Retrieval combines semantic, keyword, and fuzzy matching.
- The answer model only sees selected source passages.
- Fabricated citation IDs are removed before the final response.
- Source cards are loaded from the database after generation.
- Evaluation scripts measure retrieval quality, citation validity, and groundedness.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for deeper engineering decisions.

## Environment Variables

Copy `.env.example` to `.env` in the project root and fill the required values.

Important backend variables:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL/pgvector connection string |
| `LLM_PROVIDER` | `anthropic` or `openai` |
| `LLM_API_KEY` | API key for answer generation, query planning, and default reranking |
| `LLM_MODEL` | Main answer model |
| `LLM_FAST_MODEL` | Optional cheaper/faster model for planning and reranking |
| `EMBEDDING_PROVIDER` | `gemini`, `openai`, `cohere`, `voyage`, or `local` |
| `EMBEDDING_API_KEY` | Embedding provider API key, unless using local embeddings |
| `EMBEDDING_DIM` | Vector dimension, currently expected to be `1024` |
| `OCR_PROVIDER` | `google_vision` or `tesseract` |
| `GOOGLE_VISION_API_KEY` | Required for Google Vision OCR |
| `STORAGE_BACKEND` | `local` or `supabase` |
| `SUPABASE_URL` | Supabase project URL for production storage |
| `SUPABASE_SERVICE_ROLE_KEY` | Backend/ingestion storage key, never expose in frontend |
| `CORS_ORIGINS` | Allowed frontend origins |
| `ENABLE_DEBUG` | Enables retrieval debug routes and UI support |
| `REDIS_URL` | Optional shared rate-limit storage |

The frontend uses public environment variables only. See `frontend/.env.example`.

## Local Development Setup

### 1. Start the database

```powershell
docker compose up -d db
```

Local database URL:

```text
postgresql://postgres:postgres@localhost:55432/hadith
```

Put that value in `.env` as `DATABASE_URL`.

### 2. Install backend dependencies

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m alembic upgrade head
```

### 3. Install frontend dependencies

```powershell
cd ..\frontend
npm install
```

### 4. Run the backend

```powershell
cd ..\backend
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Backend URLs:

- API health: `http://localhost:8000/health`
- API docs: `http://localhost:8000/docs`

### 5. Run the frontend

```powershell
cd ..\frontend
npm run dev
```

Frontend URL:

```text
http://localhost:3000
```

## Ingesting Fazail-e-Amal

Run commands from `backend/`.

Start with a small trial:

```powershell
.venv\Scripts\python -m ingestion run fazail-e-amal --pages 11,62,263,601 --stages render,ocr,layout
.venv\Scripts\python -m ingestion inspect fazail-e-amal 263
```

Run the full ingestion:

```powershell
.venv\Scripts\python -m ingestion run fazail-e-amal
```

Generate review reports:

```powershell
.venv\Scripts\python -m ingestion report fazail-e-amal
```

Reports are written under:

```text
data/work/fazail-e-amal/reports/
```

### Correct Printed Page Numbers

Use manual overrides when OCR or inference cannot verify a printed page:

```powershell
.venv\Scripts\python -m ingestion set-page fazail-e-amal 263 266
.venv\Scripts\python -m ingestion set-page fazail-e-amal 5 none
```

Overrides are stored in:

```text
backend/ingestion/books/fazail-e-amal/page_mapping.json
```

### Correct Sections

Section overrides are stored in:

```text
backend/ingestion/books/fazail-e-amal/sections.json
```

After editing section overrides:

```powershell
.venv\Scripts\python -m ingestion run fazail-e-amal --stages structure,load,embed
```

### Add Another Book

1. Add the PDF to `sources/`.
2. Create a new folder under `backend/ingestion/books/<book-slug>/`.
3. Copy and edit `book.yaml` from the existing book.
4. Run:

```powershell
.venv\Scripts\python -m ingestion run <book-slug>
```

The API and frontend are intended to support multiple books.

## API Overview

Base prefix:

```text
/api/v1
```

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/chat` | Ask a question and receive a complete JSON response |
| `POST` | `/chat/stream` | Ask a question and receive Server-Sent Events |
| `GET` | `/books` | List indexed books |
| `GET` | `/books/{book_id}` | Get one book with index and section details |
| `GET` | `/sources/{source_id}` | Get a verified source passage by stable ID |
| `GET` | `/pages/{page_id}` | Get page metadata and paragraph boxes |
| `GET` | `/pages/{page_id}/image` | Get the scanned page image |
| `GET` | `/debug/retrieve` | Debug retrieval without answer generation, when enabled |
| `GET` | `/debug/config` | View redacted effective config, when enabled |
| `GET` | `/health` | API and database health check |

Streaming chat events include status updates, sources, answer deltas, and a final payload.

## Evaluation Plan

Run backend tests:

```powershell
cd backend
.venv\Scripts\python -m pytest
```

Run retrieval evaluation:

```powershell
.venv\Scripts\python -m eval.run_eval
```

Run end-to-end evaluation with judge:

```powershell
.venv\Scripts\python -m eval.run_eval --mode e2e --judge
```

Generate synthetic evaluation data:

```powershell
.venv\Scripts\python -m eval.synthesize --n 150
```

Evaluate a custom dataset:

```powershell
.venv\Scripts\python -m eval.run_eval --dataset eval/datasets/synthetic.jsonl
```

Evaluation tracks:

- hit@1, hit@3, hit@5;
- mean reciprocal rank;
- paragraph accuracy;
- printed page accuracy;
- answer groundedness;
- citation validity;
- out-of-scope handling.

Results are written to:

```text
backend/eval/results/
```

## Deployment Plan

### Database and Storage: Supabase

1. Create a Supabase project.
2. Enable PostgreSQL with pgvector support.
3. Put the connection string in `DATABASE_URL`.
4. Run migrations:

```powershell
cd backend
.venv\Scripts\python -m alembic upgrade head
```

5. Set `STORAGE_BACKEND=supabase`.
6. Set `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `STORAGE_BUCKET`.
7. Run the ingestion upload stage to send page images and source PDFs to Supabase Storage.

### Backend: Render

Use `render.yaml` as the blueprint. Production settings should include:

- `APP_ENV=production`
- `ENABLE_DEBUG=false`
- `STORAGE_BACKEND=supabase`
- `DATABASE_URL` using the Supabase pooler URI
- `CORS_ORIGINS` set to the deployed frontend domain
- secret API keys configured in the Render dashboard

### Frontend: Vercel

1. Import the repository.
2. Set root directory to `frontend`.
3. Configure:

```text
NEXT_PUBLIC_API_BASE_URL=https://<render-backend-url>
```

4. Deploy.

## Security Plan

- Never commit `.env` or provider keys.
- Keep service-role storage keys only in backend/ingestion environments.
- Redact secrets in debug config output.
- Disable debug endpoints in production.
- Use CORS allow-lists.
- Keep rate limits enabled for chat endpoints.
- Use parameterized SQL through SQLAlchemy.
- Store scanned page files in controlled storage.
- Do not allow arbitrary user file uploads in the MVP.

## Product Roadmap

### Phase 1: MVP

- Complete ingestion for *Fazail-e-Amal*.
- Verify printed page mapping.
- Verify section tree.
- Run retrieval and e2e evaluation.
- Ship chat UI with citations and scanned page viewer.
- Deploy backend, frontend, database, and storage.

### Phase 2: Accuracy Hardening

- Expand curated evaluation dataset.
- Add more spelling variants and text normalization rules.
- Review low-confidence OCR pages.
- Add admin/review workflow for page and section corrections.
- Tune reranking thresholds.
- Track recurring failed queries from logs.

### Phase 3: Multi-Book Library

- Add more book configs.
- Support book filters in the UI.
- Add author, topic, and collection metadata.
- Improve section browsing.
- Add cross-book answers with grouped citations.

### Phase 4: User Features

- Save/share answer links.
- Add citation export.
- Add recent questions.
- Add Bangla/English UI language toggle improvements.
- Add mobile-first reading refinements.

### Phase 5: Operations

- Add scheduled evaluation runs.
- Add monitoring for latency, errors, and provider failures.
- Add backup/restore documentation.
- Add cost tracking for OCR, embeddings, and LLM calls.
- Add CI checks for linting, tests, and migrations.

## Development Workflow

Recommended loop:

1. Update code.
2. Run focused tests.
3. Run affected ingestion stages if layout/retrieval changed.
4. Run retrieval evaluation.
5. Inspect misses through the debug panel.
6. Update normalization, layout, thresholds, or fixtures.
7. Repeat until metrics and manual review are acceptable.

Useful commands:

```powershell
# Backend tests
cd backend
.venv\Scripts\python -m pytest

# Backend dev server
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# Frontend lint
cd ..\frontend
npm run lint

# Frontend dev server
npm run dev
```

## Data and Git Policy

Ignored local artifacts include:

- `.env` files;
- Python virtual environments and caches;
- Next.js build output;
- `node_modules`;
- local generated `data/`;
- evaluation results;
- local logs and databases.

Commit source code, configs, tests, migrations, docs, and book metadata overrides. Do not commit generated OCR/image/cache data unless the project intentionally adds a small fixture.

## Known Notes

- The current default corpus is *Fazail-e-Amal*.
- The source PDF is scanned, so OCR is mandatory.
- Google Vision is recommended for Bangla OCR quality.
- `EMBEDDING_DIM` is migration-sensitive. Keep it at `1024` unless you plan a database migration.
- Local development uses Docker PostgreSQL on host port `55432` to avoid common local PostgreSQL conflicts.

## License and Content Notice

Review the licensing and distribution rights for any source book before publishing scanned pages, OCR text, or a public search interface. This repository provides the technical system; content permissions should be confirmed separately for each book.

