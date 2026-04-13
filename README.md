# Rent Manager Connector Service

Single point of contact for all Rent Manager API operations across Resira, Subsidy, and AP Automation.

No platform ever calls Rent Manager directly. Every RM operation from every company on every platform goes through this service.

---

## Local Setup

### Prerequisites
- Python 3.12+
- PostgreSQL 15+
- Redis 7+

### Install

```bash
git clone <repo>
cd rm-service
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Fill in DATABASE_URL, REDIS_URL, FERNET_MASTER_KEY, ADMIN_API_KEY
```

Generate a Fernet master key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Database

```bash
# Create DB
createdb rm_service

# Run migrations
alembic upgrade head
```

### Run

```bash
uvicorn app.main:app --reload --port 8000
```

Health check:
```bash
curl http://localhost:8000/health
```

### Test

```bash
pytest tests/unit/
```

---

## Railway Deployment

1. Create new Railway service — point to this repo
2. Add all env vars from `SECRETS.md` (names) — see `.env.example` for the full list
3. Enable Railway PostgreSQL daily backups immediately at project setup
4. Railway uses `railway.toml` and `Procfile` automatically
5. Health check is `GET /health` — configured in `railway.toml`

---

## Build Order

See `MASTER_SPEC.md` for full spec and build order. Current status:

- [x] Step 1: Project setup — FastAPI, structlog, Sentry, Redis, DB, health endpoint, graceful shutdown
- [ ] Step 2: Database schema — all tables, indexes, immutability trigger
- [ ] Step 3: Service API key auth middleware
- [ ] Step 4: Credential storage — HKDF + Fernet
- [ ] Step 5: Company registration endpoint
- [ ] Step 6: RM auth flow
- ...

---

## Secrets

See `SECRETS.md` for all secret names and rotation procedures.
Never commit secret values. Never log credentials.
