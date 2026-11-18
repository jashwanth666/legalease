# LegalEase — AI-Powered Legal Document Intelligence & Risk Assessment Platform

LegalEase helps startups, entrepreneurs, and small businesses screen contracts by extracting page-referenced clauses, identifying potential risks with transparent Python scoring, comparing clauses against illustrative reference templates via FAISS RAG, detecting missing clause categories, and generating downloadable ReportLab PDF reports.

> **Disclaimer:** LegalEase is an AI-assisted document review tool. Its findings are informational and may be incomplete or inaccurate. It does not provide legal advice or replace review by a qualified legal professional.

---

## Architecture & Tech Stack

- **Frontend:** Streamlit (8-page SaaS UI with custom navy/white/blue CSS)
- **Backend:** Python, FastAPI, Uvicorn
- **Authentication & Security:** Argon2id password hashing, RFC 7519 HS256 JWT, HttpOnly secure cookies, CSRF-hardened headers/cookies, role-based access control (`admin`, `legal_reviewer`, `employee`), pluggable distributed sliding-window rate limiting (Redis-backed with thread-safe in-memory dev fallback), and tenant-isolated workspaces
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
- `tests/` — Automated Pytest suite (`test_upload.py`, `test_extraction.py`, `test_risk.py`, `test_api.py`, `test_auth.py`, `test_tenant_isolation.py`, `test_background_jobs.py`, `test_verification_hardening.py`, `test_admin_bootstrap.py`)

---

## Quick Start & Setup

### 1. Install dependencies
```bash
pip install -r backend/requirements.txt
```

### 2. Configure environment variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Generate secure secrets for JWT and Administrator Bootstrap:
```bash
python -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_hex(32))"
python -c "import secrets; print('ADMIN_BOOTSTRAP_SECRET=' + secrets.token_hex(32))"
```

Configure `.env`:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
JWT_SECRET_KEY=your_generated_jwt_secret_here
ADMIN_BOOTSTRAP_SECRET=your_generated_bootstrap_secret_here
ENVIRONMENT=development
```
*(If `GEMINI_API_KEY` is omitted, LegalEase runs in deterministic screening fallback mode and explicitly marks fallback outputs—never labeling fallback results as Gemini analysis.)*

### 3. Initialize the System Administrator
Before users can create accounts, initialize the primary system administrator:
- **Via Streamlit SaaS UI:** Navigate to `http://localhost:8501`. If no administrator has been initialized, the "🚀 System Admin Setup" tab will appear. Enter your administrator email, password, and the server's `ADMIN_BOOTSTRAP_SECRET`.
- **Via REST API:**
  ```bash
  curl -X POST http://127.0.0.1:8000/api/auth/bootstrap-admin \
    -H "Content-Type: application/json" \
    -d '{
      "email": "admin@enterprise.com",
      "password": "SecurePassword123!",
      "full_name": "Primary Administrator",
      "bootstrap_secret": "your_generated_bootstrap_secret_here",
      "tenant_id": "tenant_enterprise"
    }'
  ```
Once initialized, the bootstrap endpoint and UI are permanently disabled and return HTTP 409 Conflict for any subsequent attempts.

### 4. Run the application
```bash
python run.py
```
- FastAPI Swagger Docs: `http://127.0.0.1:8000/docs`
- Streamlit SaaS UI: `http://localhost:8501`

---

## Roles & Permissions

| Role | Permissions |
|---|---|
| **Admin** | Full system & organization access: upload, analyze, view, delete any document in tenant, rebuild reference templates, provision users, manage team active status. |
| **Legal Reviewer** | Reviewer access: upload, view, analyze documents, view team member roster, view metadata and comparisons. Can only delete their own uploaded documents. |
| **Employee** | Standard user access: upload and review their own contracts, view reports. Cannot delete others' contracts or manage users. |

### Public Registration vs. Organization Provisioning
- **Public Registration (`POST /api/auth/register`):** Creates strictly `employee` accounts in dedicated, server-assigned isolated workspaces. Client-supplied `tenant_id` parameters are intentionally not accepted or trusted; the server auto-assigns a unique tenant identifier to prevent tenant enumeration or unauthorized joining of existing organizations.
- **Admin Provisioning (`POST /api/auth/users`):** Authenticated administrators can provision team members (`employee`, `legal_reviewer`, `admin`) directly within their own organization.

### Distributed Rate Limiting
Authentication endpoints (`/api/auth/login`, `/api/auth/register`, `/api/auth/bootstrap-admin`) are protected by a sliding-window rate limiter:
- **Development Fallback:** When `REDIS_URL` is omitted, an in-memory thread-safe sliding-window counter is used automatically.
- **Production / Multi-Instance:** Configure `REDIS_URL=redis://localhost:6379/0` in `.env` to enable centralized Redis `INCR` + `EXPIRE` rate limiting across multiple backend instances.

---

## FastAPI Endpoints

### Authentication & User Management
- `GET /api/auth/bootstrap-status` — Public check whether system administrator setup is completed
- `POST /api/auth/bootstrap-admin` — One-time administrator provisioning via `ADMIN_BOOTSTRAP_SECRET`
- `POST /api/auth/register` — Public self-registration (strictly creates `employee` accounts)
- `POST /api/auth/login` — Authenticate and receive RFC 7519 HS256 JWT access token and HttpOnly cookie
- `POST /api/auth/logout` — Clear session cookies securely
- `GET /api/auth/me` — Authenticated user profile and organization context
- `POST /api/auth/users` — Admin provisions new team member in their tenant
- `GET /api/auth/users` — Admin and Legal Reviewer list organization team members
- `PATCH /api/auth/users/{user_id}` — Admin updates team member status with last-admin protection

### Documents & Analysis
- `GET /health` — Server and Gemini configuration status
- `POST /api/upload` — Validate, store, and extract page-referenced text from PDF/DOCX (tenant-isolated)
- `GET /api/documents` — List uploaded contracts for the authenticated tenant/user
- `GET /api/documents/{document_id}` — Document metadata and extracted pages
- `POST /api/analyze/{document_id}` — Run full LangGraph analysis pipeline (atomic CAS background task, non-blocking HTTP 202)
- `GET /api/status/{document_id}` — Real-time pipeline processing status and percent completion
- `GET /api/analysis/{document_id}` — Retrieve risk overview, findings, summary, metadata, and missing clauses
- `GET /api/metadata/{document_id}` — Retrieve 16 structured contract metadata fields with verified evidence citations
- `GET /api/clauses/{document_id}` — Retrieve segmented and classified clauses
- `GET /api/compare/{document_id}` — Side-by-side RAG comparisons against illustrative templates
- `POST /api/templates/rebuild` — Rebuild FAISS reference template vector store (Admin privilege required)
- `GET /api/reports` & `GET /api/report/{document_id}` — List and download PDF reports
- `DELETE /api/documents/{document_id}` — Delete document, extracted text, DB rows, and PDF report

---

## Running Tests

Execute the comprehensive automated test suite (including authentication, tenant isolation, atomic background jobs, evidence verification, and document workflows):

```bash
python -m pytest tests/ -v
```
