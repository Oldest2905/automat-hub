# The Automat Hub — DCP & Escrow System

## Project Structure

```
automat_hub/
├── backend/
│   ├── main.py                     # FastAPI app entry point
│   ├── config.py                   # Environment configuration
│   ├── core/
│   │   ├── hashing.py              # SHA-256 DCP hashing engine
│   │   ├── security.py             # JWT auth + API key management
│   │   └── database.py             # PostgreSQL connection
│   ├── models/
│   │   ├── dcp.py                  # DCP database models
│   │   └── escrow.py               # Escrow database models
│   ├── schemas/
│   │   ├── dcp.py                  # DCP Pydantic schemas
│   │   └── escrow.py               # Escrow Pydantic schemas
│   ├── routers/
│   │   ├── dcp.py                  # DCP API endpoints
│   │   └── escrow.py               # Escrow API endpoints
│   └── services/
│       ├── dcp_service.py          # DCP business logic
│       ├── escrow_service.py       # Escrow business logic
│       ├── qr_service.py           # QR code generation
│       └── notification_service.py # SMS/Email notifications
├── database/
│   └── migrations/
│       ├── 001_create_dcp_tables.sql
│       └── 002_create_escrow_tables.sql
├── frontend/
│   ├── pages/
│   │   ├── verify.html             # Public DCP verification page
│   │   └── escrow.html             # Escrow status page
│   └── components/
│       └── dcp_card.html           # DCP passport card component
├── requirements.txt
├── .env.example
└── docker-compose.yml
```

## Quick Start

```bash
# 1. Clone and install
pip install -r requirements.txt

# 2. Set environment variables
cp .env.example .env

# 3. Run database migrations
psql -U postgres -d automat_hub -f database/migrations/001_create_dcp_tables.sql
psql -U postgres -d automat_hub -f database/migrations/002_create_escrow_tables.sql

# 4. Start the server
uvicorn backend.main:app --reload

# 5. Visit API docs
http://localhost:8000/docs
```
