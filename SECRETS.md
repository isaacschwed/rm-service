# Secrets Documentation

This file documents every secret used by the RM Connector Service.  
**Secret names only. Never values. Never commit values anywhere.**

---

## Railway Environment Variables

| Variable | Purpose | Rotation Procedure |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string (asyncpg) | Update Railway var → redeploy |
| `REDIS_URL` | Redis connection string | Update Railway var → redeploy |
| `FERNET_MASTER_KEY` | Master key for HKDF per-company credential encryption | See rotation procedure below |
| `RM_BASE_URL` | Rent Manager API base URL | Update Railway var → redeploy |
| `ADMIN_API_KEY` | Protects admin endpoints | Generate new → update Railway → revoke old |
| `SENTRY_DSN` | Error monitoring ingest URL | Rotate in Sentry dashboard → update Railway var |

---

## Platform API Keys (stored as SHA-256 hashes in `service_api_keys` table)

| Platform | Variable Name (on platform's Railway service) |
|---|---|
| Resira | `RM_SERVICE_API_KEY` |
| Subsidy | `RM_SERVICE_API_KEY` |
| AP Automation | `RM_SERVICE_API_KEY` |

Raw keys issued exactly once. If lost, rotate — do not attempt to recover.

---

## Per-Company RM Credentials (stored encrypted in `rm_credentials` table)

Encrypted with Fernet using a per-company key derived via HKDF from `FERNET_MASTER_KEY`.  
Compromising one company's derived key does not expose others.  
Credentials never appear in logs, responses, or error messages.

---

## FERNET_MASTER_KEY Rotation Procedure

**This is a breaking operation. All cached tokens are invalidated. All stored credentials must be re-encrypted.**

1. Notify all platform owners — brief downtime required.
2. Generate new master key:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. Write a one-time migration script that:
   - Decrypts all `rm_credentials` rows with old key
   - Re-encrypts with new key
   - Updates all rows in a single transaction
4. Test migration against a DB snapshot first.
5. Run migration against production DB.
6. Update `FERNET_MASTER_KEY` in Railway.
7. Clear all `rm_auth_tokens` rows and Redis token cache.
8. Redeploy service.
9. Verify credential health check passes for all companies.

---

## ADMIN_API_KEY Rotation Procedure

1. Generate new key:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Update `ADMIN_API_KEY` in Railway.
3. Redeploy service.
4. Update admin UI config with new key.
5. Revoke old key — it is no longer valid immediately after redeploy.

---

## Platform API Key Rotation Procedure

Use admin endpoint: `POST /v1/admin/api-keys/rotate`  
Or via admin UI → API Keys → Rotate.

1. New raw key is generated and returned once — copy it immediately.
2. New key hash stored in `service_api_keys`.
3. Update platform's `RM_SERVICE_API_KEY` in Railway.
4. Redeploy platform.
5. Old key is deactivated.
