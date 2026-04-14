"""
Root conftest — injects environment variables before any app modules are
imported.  Module-level code in session.py, auth.py, etc. calls
get_settings() at import time, so these must be set at the top level
(not inside a fixture).
"""
import os
from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("FERNET_MASTER_KEY", Fernet.generate_key().decode())
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-for-tests")
