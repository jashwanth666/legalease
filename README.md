# LegalEase — AI-Powered Legal Document Intelligence & Risk Assessment Platform

LegalEase helps startups, entrepreneurs, and small businesses screen contracts by extracting page-referenced clauses, identifying potential risks with transparent Python scoring, comparing clauses against illustrative reference templates via FAISS RAG, detecting missing clause categories, and generating downloadable ReportLab PDF reports.

> **Disclaimer:** LegalEase is an AI-assisted document review tool. Its findings are informational and may be incomplete or inaccurate. It does not provide legal advice or replace review by a qualified legal professional.

---

## Architecture & Tech Stack

- **Frontend:** Streamlit (8-page SaaS UI with custom navy/white/blue CSS)
- **Backend:** Python, FastAPI, Uvicorn
- **Generative AI:** Google Gemini API (`google-genai`, `langchain-google-genai`) with Pydantic structured outputs and explicit deterministic fallback when `GEMINI_API_KEY` is omitted
- **Agentic Orchestration:** LangGraph (`StateGraph` with parallel fan-out for Risk Assessment, RAG Comparison, and Missing Clause Detection, followed by Evidence Verification)
- **RAG & Embeddings:** FAISS + Sentence Transformers (`all-MiniLM-L6-v2` with offline deterministic fallback) + LangChain `BaseRetriever`
- **Document Processing:** PyMuPDF (`pymupdf`) for PDFs, `python-docx` for Word files
- **Persistence:** SQLite + SQLAlchemy 2.0
- **PDF Reports:** ReportLab
- **Testing:** Pytest

---

## Project Structure

- `backend/` — FastAPI server, LangGraph workflow (`graph/`), specialized agents (`agents/`), ingestion (`ingestion/`), FAISS retrieval (`retrieval/`), guardrails (`guardrails/`), scoring & PDF services (`services/`), and SQLite ORM (`database/`)
- `frontend/` — Multi-page Streamlit application (`app.py`, `pages/`, `components/`, `utils/api_client.py`)
- `data/sample_contracts/` — Demo `sample_nda.pdf` and `sample_service_agreement.pdf`
- `data/reference_templates/` — Illustrative templates (`nda/`, `service_agreement/`, `employment/`, `partnership/`)
- `storage/` — Uploaded binaries, extracted page JSON, SQLite database, and FAISS vector store
- `outputs/reports/` — Generated ReportLab PDF analysis reports
- `tests/` — Automated Pytest suite (`test_upload.py`, `test_extraction.py`, `test_risk.py`, `test_api.py`)

---

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r backend/requirements.txt
   ```

2. **Configure environment variables:**
   Copy `.env.example` to `.env` and optionally add your Gemini API key:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-2.5-flash
   ```
   *(If `GEMINI_API_KEY` is left empty, LegalEase runs in deterministic screening fallback mode and explicitly marks fallback outputs—never labeling fallback results as Gemini analysis.)*

3. **Run the application:**
   ```bash
   python run.py
   ```
   - FastAPI API Docs: `http://127.0.0.1:8000/docs`
   - Streamlit SaaS UI: `http://localhost:8501`

---

## FastAPI Endpoints

- `GET /health` — Server and Gemini configuration status
- `POST /api/upload` — Validate, store, and extract page-referenced text from PDF/DOCX
- `GET /api/documents` — List uploaded contracts
- `GET /api/documents/{document_id}` — Document metadata and extracted pages
- `POST /api/analyze/{document_id}` — Run full LangGraph analysis pipeline (user-triggered, non-blocking HTTP 202)
- `GET /api/status/{document_id}` — Real-time pipeline processing status and percent completion
- `GET /api/analysis/{document_id}` — Retrieve risk overview, findings, summary, metadata, and missing clauses
- `GET /api/metadata/{document_id}` — Retrieve 16 structured contract metadata fields with verified evidence citations
- `GET /api/clauses/{document_id}` — Retrieve segmented and classified clauses
- `GET /api/compare/{document_id}` — Side-by-side RAG comparisons against illustrative templates
- `GET /api/reports` & `GET /api/report/{document_id}` — List and download PDF reports
- `DELETE /api/documents/{document_id}` — Delete document, extracted text, DB rows, and PDF report

---

## Running Tests

```bash
python -m pytest tests/ -v
```

