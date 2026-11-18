from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

import netlab
from .services import get_service
from .security import production_mode, validate_production_settings

if production_mode():
    validate_production_settings()

SESSION_COOKIE = "netlab_session"
CSRF_COOKIE = "netlab_csrf"
SESSION_TTL_SECONDS = 12 * 60 * 60
PASSWORD_ITERATIONS = 310_000
INVITATION_TTL_SECONDS = 7 * 24 * 60 * 60
PASSWORD_RESET_TTL_SECONDS = 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5


class LoginThrottle:
    """Small in-process throttle for the local prototype."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def blocked(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            attempts = [stamp for stamp in self._failures.get(key, []) if now - stamp < LOGIN_WINDOW_SECONDS]
            self._failures[key] = attempts
            if len(attempts) < LOGIN_MAX_FAILURES:
                return 0
            return max(1, int(LOGIN_WINDOW_SECONDS - (now - attempts[0])))

    def failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            attempts = [stamp for stamp in self._failures.get(key, []) if now - stamp < LOGIN_WINDOW_SECONDS]
            attempts.append(now)
            self._failures[key] = attempts[-LOGIN_MAX_FAILURES:]

    def success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


login_throttle = LoginThrottle()


def _email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("must be a valid email address")
    return value


def _password(value: str) -> str:
    if len(value) < 12:
        raise ValueError("password must contain at least 12 characters")
    if len(value) > 1024:
        raise ValueError("password is too long")
    return value


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return "$pbkdf2-sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, scheme, rounds, salt_text, digest_text = encoded.split("$")
        if scheme != "pbkdf2-sha256":
            return False
        rounds_int = int(rounds)
        if rounds_int < 100_000 or rounds_int > 2_000_000:
            return False
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(digest_text + "=" * (-len(digest_text) % 4))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds_int)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


_DUMMY_PASSWORD_HASH = hash_password("invalid-account-password-placeholder")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class EducationError(ValueError):
    pass


class DatabaseConnection:
    def __init__(self, connection: Any, postgres: bool) -> None:
        self.connection = connection
        self.postgres = postgres

    def __enter__(self) -> "DatabaseConnection":
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        try:
            return self.connection.__exit__(exc_type, exc_value, traceback)
        finally:
            self.connection.close()

    def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> Any:
        if self.postgres:
            statement = statement.replace("?", "%s").replace(" COLLATE NOCASE", "")
            statement = re.sub(r"ORDER BY ([a-zA-Z_.]+)($|,)", r"ORDER BY lower(\1)\2", statement)
        return self.connection.execute(statement, parameters)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)


def _integrity_error_types() -> tuple[type[Exception], ...]:
    try:
        import psycopg
    except ImportError:
        return (sqlite3.IntegrityError,)
    return (sqlite3.IntegrityError, psycopg.IntegrityError)


class EducationStore:
    """Relational store for accounts, educational assignments and laboratories."""

    def __init__(self, path: Path | str):
        value = str(path)
        self.database_url = value if "://" in value else None
        self.postgres = bool(self.database_url and self.database_url.startswith(("postgres://", "postgresql://")))
        if self.database_url and not self.postgres:
            parsed = urlparse(self.database_url)
            if parsed.scheme != "sqlite":
                raise ValueError("NETLAB_DATABASE_URL must use PostgreSQL or SQLite")
            value = unquote(parsed.path)
            if parsed.netloc and parsed.netloc != "localhost":
                value = f"//{parsed.netloc}{value}"
        self.path = Path(value)
        if not self.postgres:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if not self.postgres:
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def _connect(self) -> DatabaseConnection:
        if self.postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("PostgreSQL support requires psycopg; install backend requirements") from exc
            conn = psycopg.connect(self.database_url, row_factory=dict_row)
        else:
            conn = sqlite3.connect(self.path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
        return DatabaseConnection(conn, self.postgres)

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('teacher', 'student')),
                    created_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_hash TEXT NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_login_attempts (
                    key_hash TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL,
                    window_started_at DOUBLE PRECISION NOT NULL,
                    blocked_until DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS account_invitations (
                    token_hash TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('teacher', 'student')),
                    group_id TEXT,
                    created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at DOUBLE PRECISION NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL,
                    used_at DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at DOUBLE PRECISION NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL,
                    used_at DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS remote_workers (
                    id TEXT PRIMARY KEY,
                    worker_name TEXT NOT NULL,
                    last_heartbeat DOUBLE PRECISION NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('online','offline','degraded')),
                    capabilities TEXT NOT NULL DEFAULT '[]',
                    updated_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS worker_jobs (
                    id TEXT PRIMARY KEY,
                    worker_id TEXT,
                    action TEXT NOT NULL,
                    topology_json TEXT NOT NULL,
                    node_name TEXT,
                    command_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL CHECK (status IN ('queued','leased','running','completed','failed','dead')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    available_at DOUBLE PRECISION NOT NULL,
                    started_at DOUBLE PRECISION,
                    completed_at DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS execution_metrics (
                    id TEXT PRIMARY KEY,
                    worker_id TEXT,
                    job_id TEXT,
                    action TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    exit_code INTEGER,
                    recorded_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alert_notifications (
                    id TEXT PRIMARY KEY,
                    severity TEXT NOT NULL CHECK (severity IN ('warning','error','critical')),
                    source TEXT NOT NULL,
                    message TEXT NOT NULL,
                    acknowledged INTEGER NOT NULL DEFAULT 0,
                    created_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cleanup_attempts (
                    id TEXT PRIMARY KEY,
                    laboratory_id TEXT NOT NULL,
                    student_assignment_id TEXT,
                    student_user_id TEXT,
                    status TEXT NOT NULL CHECK (status IN ('pending','succeeded','failed')),
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    last_error TEXT,
                    created_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS groups (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    teacher_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at DOUBLE PRECISION NOT NULL,
                    UNIQUE(teacher_id, name)
                );
                CREATE TABLE IF NOT EXISTS group_members (
                    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    added_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (group_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS assignments (
                    id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                    created_by TEXT NOT NULL REFERENCES users(id),
                    title TEXT NOT NULL,
                    topology_json TEXT NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assignment_details (
                    assignment_id TEXT PRIMARY KEY REFERENCES assignments(id) ON DELETE CASCADE,
                    instructions TEXT NOT NULL DEFAULT '',
                    criteria_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS student_labs (
                    assignment_id TEXT NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    topology_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'assigned' CHECK (status IN ('assigned', 'in_progress', 'submitted')),
                    updated_at DOUBLE PRECISION NOT NULL,
                    submitted_at DOUBLE PRECISION,
                    PRIMARY KEY (assignment_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS student_lab_runtime (
                    assignment_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'stopped' CHECK (status IN ('stopped', 'running', 'expired', 'failed')),
                    updated_at DOUBLE PRECISION NOT NULL,
                    expires_at DOUBLE PRECISION,
                    PRIMARY KEY (assignment_id, user_id),
                    FOREIGN KEY (assignment_id, user_id)
                        REFERENCES student_labs(assignment_id, user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS student_submission_attempts (
                    id TEXT PRIMARY KEY,
                    assignment_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    topology_json TEXT NOT NULL,
                    submitted_at DOUBLE PRECISION NOT NULL,
                    feedback TEXT,
                    grade DOUBLE PRECISION,
                    reviewed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                    reviewed_at DOUBLE PRECISION,
                    UNIQUE(assignment_id, user_id, attempt),
                    FOREIGN KEY (assignment_id, user_id)
                        REFERENCES student_labs(assignment_id, user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS laboratories (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL UNIQUE,
                    topology_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'stopped' CHECK (status IN ('stopped', 'running', 'expired', 'failed')),
                    created_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS laboratory_versions (
                    laboratory_id TEXT NOT NULL REFERENCES laboratories(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    reason TEXT NOT NULL,
                    topology_json TEXT NOT NULL,
                    PRIMARY KEY (laboratory_id, version)
                );
                CREATE TABLE IF NOT EXISTS laboratory_members (
                    laboratory_id TEXT NOT NULL REFERENCES laboratories(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
                    added_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (laboratory_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS laboratory_events (
                    id TEXT PRIMARY KEY,
                    laboratory_id TEXT NOT NULL REFERENCES laboratories(id) ON DELETE CASCADE,
                    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                    message TEXT NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_groups_teacher ON groups(teacher_id);
                CREATE INDEX IF NOT EXISTS idx_members_user ON group_members(user_id);
                CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_window ON auth_login_attempts(window_started_at);
                CREATE INDEX IF NOT EXISTS idx_invitations_expiry ON account_invitations(expires_at);
                CREATE INDEX IF NOT EXISTS idx_password_resets_user ON password_reset_tokens(user_id, expires_at);
                CREATE INDEX IF NOT EXISTS idx_assignments_group ON assignments(group_id);
                CREATE INDEX IF NOT EXISTS idx_student_runtime_expiry ON student_lab_runtime(status, expires_at);
                CREATE INDEX IF NOT EXISTS idx_student_submissions ON student_submission_attempts(assignment_id,user_id,attempt);
                CREATE INDEX IF NOT EXISTS idx_laboratories_owner ON laboratories(owner_id);
                CREATE INDEX IF NOT EXISTS idx_laboratories_expiry ON laboratories(expires_at);
                CREATE INDEX IF NOT EXISTS idx_laboratory_versions_lab ON laboratory_versions(laboratory_id, version);
                CREATE INDEX IF NOT EXISTS idx_laboratory_members_user ON laboratory_members(user_id);
                CREATE INDEX IF NOT EXISTS idx_laboratory_events_lab ON laboratory_events(laboratory_id, created_at);
                """
            )
            if db.postgres:
                has_admin_column = db.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name='users' AND column_name='is_admin'"
                ).fetchone()
            else:
                has_admin_column = any(row["name"] == "is_admin" for row in db.execute("PRAGMA table_info(users)"))
            if not has_admin_column:
                db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            if db.postgres:
                has_invitation_group_column = db.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name='account_invitations' AND column_name='group_id'"
                ).fetchone()
            else:
                has_invitation_group_column = any(
                    row["name"] == "group_id"
                    for row in db.execute("PRAGMA table_info(account_invitations)")
                )
            if not has_invitation_group_column:
                db.execute("ALTER TABLE account_invitations ADD COLUMN group_id TEXT")
            if db.postgres:
                has_grade_column = db.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name='student_submission_attempts' AND column_name='grade'"
                ).fetchone()
            else:
                has_grade_column = any(
                    row["name"] == "grade"
                    for row in db.execute("PRAGMA table_info(student_submission_attempts)")
                )
            if not has_grade_column:
                db.execute("ALTER TABLE student_submission_attempts ADD COLUMN grade DOUBLE PRECISION")
            db.execute(
                "INSERT INTO laboratory_versions(laboratory_id,version,created_at,reason,topology_json) "
                "SELECT l.id,1,l.created_at,'migrated-current',l.topology_json FROM laboratories l "
                "WHERE NOT EXISTS (SELECT 1 FROM laboratory_versions v WHERE v.laboratory_id=l.id)"
            )

    def user_count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"])

    def bootstrap_teacher(
        self, email: str, display_name: str, password: str, role: str = "teacher",
    ) -> dict[str, str]:
        email = _email(email)
        display_name = display_name.strip()
        if not display_name or len(display_name) > 100:
            raise EducationError("display name must contain 1 to 100 characters")
        password = _password(password)
        if role not in {"teacher", "admin"}:
            raise EducationError("initial role must be teacher or admin")
        user = {"id": str(uuid.uuid4()), "email": email, "display_name": display_name, "role": role}
        try:
            with self._connect() as db:
                if db.postgres:
                    db.execute("LOCK TABLE users IN EXCLUSIVE MODE")
                if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                    raise EducationError("initial teacher account already exists")
                db.execute(
                    "INSERT INTO users(id,email,display_name,password_hash,role,created_at,is_admin) VALUES(?,?,?,?,?,?,?)",
                    (user["id"], email, display_name, hash_password(password), "teacher", time.time(), int(role == "admin")),
                )
        except _integrity_error_types() as exc:
            raise EducationError("an account with this email already exists") from exc
        return user

    def create_user(self, email: str, display_name: str, password: str, role: str) -> dict[str, str]:
        email = _email(email)
        display_name = display_name.strip()
        if not display_name or len(display_name) > 100:
            raise EducationError("display name must contain 1 to 100 characters")
        password = _password(password)
        if role not in {"admin", "teacher", "student"}:
            raise EducationError("role must be admin, teacher or student")
        user = {"id": str(uuid.uuid4()), "email": email, "display_name": display_name, "role": role}
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO users(id,email,display_name,password_hash,role,created_at,is_admin) VALUES(?,?,?,?,?,?,?)",
                    (user["id"], email, display_name, hash_password(password), "teacher" if role == "admin" else role, time.time(), int(role == "admin")),
                )
        except _integrity_error_types() as exc:
            raise EducationError("an account with this email already exists") from exc
        return user

    def authenticate(self, email: str, password: str) -> dict[str, str] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        password_hash = row["password_hash"] if row else _DUMMY_PASSWORD_HASH
        password_matches = verify_password(password, password_hash)
        if not row or not password_matches:
            return None
        return self.public_user(row)

    @staticmethod
    def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, str]:
        user = {key: str(row[key]) for key in ("id", "email", "display_name", "role")}
        if bool(row["is_admin"]) if "is_admin" in row.keys() else False:
            user["role"] = "admin"
        return user

    def issue_invitation(
        self, creator_id: str, email: str, display_name: str, role: str,
        group_id: str | None = None,
    ) -> tuple[dict[str, str], str]:
        email = _email(email)
        display_name = display_name.strip()
        if not display_name or len(display_name) > 100:
            raise EducationError("display name must contain 1 to 100 characters")
        if role not in {"teacher", "student"}:
            raise EducationError("invitation role must be teacher or student")
        if group_id and role != "student":
            raise EducationError("only student invitations can be linked to a group")
        token = secrets.token_urlsafe(32)
        now = time.time()
        try:
            with self._connect() as db:
                if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                    raise EducationError("an account with this email already exists")
                if group_id and not db.execute(
                    "SELECT id FROM groups WHERE id=? AND (teacher_id=? OR EXISTS "
                    "(SELECT 1 FROM users WHERE id=? AND is_admin=1))",
                    (group_id, creator_id, creator_id),
                ).fetchone():
                    raise EducationError("group not found")
                db.execute(
                    "DELETE FROM account_invitations WHERE email=? AND used_at IS NULL",
                    (email,),
                )
                db.execute(
                    "INSERT INTO account_invitations(token_hash,email,display_name,role,group_id,created_by,created_at,expires_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (_token_hash(token), email, display_name, role, group_id, creator_id, now, now + INVITATION_TTL_SECONDS),
                )
        except _integrity_error_types() as exc:
            raise EducationError("an invitation for this email already exists") from exc
        return {"email": email, "display_name": display_name, "role": role}, token

    def accept_invitation(self, token: str, password: str) -> dict[str, str]:
        password = _password(password)
        with self._connect() as db:
            if db.postgres:
                row = db.execute(
                    "SELECT * FROM account_invitations WHERE token_hash=? AND used_at IS NULL AND expires_at>? FOR UPDATE",
                    (_token_hash(token), time.time()),
                ).fetchone()
            else:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM account_invitations WHERE token_hash=? AND used_at IS NULL AND expires_at>?",
                    (_token_hash(token), time.time()),
                ).fetchone()
            if not row:
                raise EducationError("invitation is invalid or expired")
            if db.execute("SELECT 1 FROM users WHERE email=?", (row["email"],)).fetchone():
                raise EducationError("an account with this email already exists")
            user = {
                "id": str(uuid.uuid4()),
                "email": row["email"],
                "display_name": row["display_name"],
                "role": row["role"],
            }
            db.execute(
                "INSERT INTO users(id,email,display_name,password_hash,role,created_at,is_admin) VALUES(?,?,?,?,?,?,0)",
                (user["id"], user["email"], user["display_name"], hash_password(password), user["role"], time.time()),
            )
            db.execute(
                "UPDATE account_invitations SET used_at=? WHERE token_hash=? AND used_at IS NULL",
                (time.time(), _token_hash(token)),
            )
            if row["group_id"]:
                group = db.execute(
                    "SELECT id FROM groups WHERE id=?",
                    (row["group_id"],),
                ).fetchone()
                if not group:
                    raise EducationError("invitation group no longer exists")
                db.execute(
                    "INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)",
                    (row["group_id"], user["id"], time.time()),
                )
                db.execute(
                    "INSERT INTO student_labs(assignment_id,user_id,topology_json,status,updated_at) "
                    "SELECT a.id,?,a.topology_json,'assigned',? FROM assignments a WHERE a.group_id=?",
                    (user["id"], time.time(), row["group_id"]),
                )
            return user

    def issue_password_reset(self, user_id: str, issuer_id: str, issuer_role: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._connect() as db:
            target = db.execute(
                "SELECT role,is_admin FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
            if not target:
                raise EducationError("user not found")
            target_role = "admin" if target["is_admin"] else target["role"]
            if issuer_role != "admin":
                if target_role != "student":
                    raise EducationError("administrator role required to reset staff passwords")
                membership = db.execute(
                    "SELECT 1 FROM group_members m JOIN groups g ON g.id=m.group_id "
                    "WHERE m.user_id=? AND g.teacher_id=? LIMIT 1",
                    (user_id, issuer_id),
                ).fetchone()
                if not membership:
                    raise EducationError("student is not in one of your groups")
            db.execute(
                "UPDATE password_reset_tokens SET used_at=? WHERE user_id=? AND used_at IS NULL",
                (now, user_id),
            )
            db.execute(
                "INSERT INTO password_reset_tokens(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                (_token_hash(token), user_id, now, now + PASSWORD_RESET_TTL_SECONDS),
            )
        return token

    def reset_password(self, token: str, new_password: str) -> None:
        new_password = _password(new_password)
        now = time.time()
        with self._connect() as db:
            if db.postgres:
                row = db.execute(
                    "SELECT user_id FROM password_reset_tokens "
                    "WHERE token_hash=? AND used_at IS NULL AND expires_at>? FOR UPDATE",
                    (_token_hash(token), now),
                ).fetchone()
            else:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT user_id FROM password_reset_tokens "
                    "WHERE token_hash=? AND used_at IS NULL AND expires_at>?",
                    (_token_hash(token), now),
                ).fetchone()
            if not row:
                raise EducationError("password reset token is invalid or expired")
            db.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (hash_password(new_password), row["user_id"]),
            )
            db.execute(
                "UPDATE password_reset_tokens SET used_at=? WHERE token_hash=?",
                (now, _token_hash(token)),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))

    def create_session(self, user_id: str) -> tuple[str, str]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
            db.execute(
                "INSERT INTO sessions(token_hash,user_id,csrf_hash,expires_at) VALUES(?,?,?,?)",
                (_token_hash(token), user_id, _token_hash(csrf), time.time() + SESSION_TTL_SECONDS),
            )
        return token, csrf

    def session_user(self, token: str | None, csrf: str | None = None) -> dict[str, str] | None:
        if not token:
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT u.*, s.csrf_hash FROM sessions s JOIN users u ON u.id=s.user_id "
                "WHERE s.token_hash=? AND s.expires_at>?",
                (_token_hash(token), time.time()),
            ).fetchone()
        if not row or (csrf is not None and not hmac.compare_digest(row["csrf_hash"], _token_hash(csrf))):
            return None
        return self.public_user(row)

    def revoke_session(self, token: str | None) -> None:
        if token:
            with self._connect() as db:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))

    def login_throttle_remaining(self, keys: list[str]) -> int:
        now = time.time()
        with self._connect() as db:
            for key in keys:
                row = db.execute(
                    "SELECT blocked_until FROM auth_login_attempts WHERE key_hash=?",
                    (_token_hash(key),),
                ).fetchone()
                if row and row["blocked_until"] is not None and float(row["blocked_until"]) > now:
                    return max(1, math.ceil(float(row["blocked_until"]) - now))
        return 0

    def record_login_failure(self, keys: list[str]) -> None:
        now = time.time()
        window_start = now - LOGIN_WINDOW_SECONDS
        blocked_until = now + LOGIN_WINDOW_SECONDS
        for key in keys:
            with self._connect() as db:
                db.execute(
                    "DELETE FROM auth_login_attempts WHERE window_started_at<=? "
                    "AND (blocked_until IS NULL OR blocked_until<=?)",
                    (window_start, now),
                )
                db.execute(
                    "INSERT INTO auth_login_attempts(key_hash,failures,window_started_at,blocked_until) "
                    "VALUES(?,1,?,NULL) ON CONFLICT(key_hash) DO UPDATE SET "
                    "failures=CASE WHEN auth_login_attempts.window_started_at<=? THEN 1 ELSE auth_login_attempts.failures+1 END,"
                    "window_started_at=CASE WHEN auth_login_attempts.window_started_at<=? THEN excluded.window_started_at "
                    "ELSE auth_login_attempts.window_started_at END,"
                    "blocked_until=CASE WHEN (CASE WHEN auth_login_attempts.window_started_at<=? THEN 1 "
                    "ELSE auth_login_attempts.failures+1 END)>=? THEN ? ELSE NULL END",
                    (
                        _token_hash(key), now, window_start, window_start, window_start,
                        LOGIN_MAX_FAILURES, blocked_until,
                    ),
                )

    def clear_login_failures(self, keys: list[str]) -> None:
        with self._connect() as db:
            for key in keys:
                db.execute("DELETE FROM auth_login_attempts WHERE key_hash=?", (_token_hash(key),))

    def register_worker(
        self,
        worker_id: str,
        worker_name: str,
        capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        worker_id = worker_id.strip()
        worker_name = worker_name.strip()
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", worker_id):
            raise EducationError("worker id is invalid")
        if not worker_name or len(worker_name) > 128:
            raise EducationError("worker name must contain 1 to 128 characters")
        now = time.time()
        capabilities_json = json.dumps(sorted(set(capabilities or ["docker"])), separators=(",", ":"))
        with self._connect() as db:
            db.execute(
                "INSERT INTO remote_workers(id,worker_name,last_heartbeat,status,capabilities,updated_at) "
                "VALUES(?, ?, ?, 'online', ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET worker_name=excluded.worker_name,"
                "last_heartbeat=excluded.last_heartbeat,status='online',"
                "capabilities=excluded.capabilities,updated_at=excluded.updated_at",
                (worker_id, worker_name, now, capabilities_json, now),
            )
        return self.worker(worker_id)

    def worker(self, worker_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT id,worker_name,last_heartbeat,status,capabilities,updated_at "
                "FROM remote_workers WHERE id=?",
                (worker_id,),
            ).fetchone()
        if not row:
            raise EducationError("worker not found")
        result = dict(row)
        result["capabilities"] = json.loads(result["capabilities"])
        return result

    def workers(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._connect() as db:
            db.execute(
                "UPDATE remote_workers SET status='offline' "
                "WHERE last_heartbeat<? AND status!='offline'",
                (now - 90,),
            )
            rows = db.execute(
                "SELECT id,worker_name,last_heartbeat,status,capabilities,updated_at "
                "FROM remote_workers ORDER BY worker_name,last_heartbeat DESC",
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["capabilities"] = json.loads(item["capabilities"])
                result.append(item)
            return result

    def enqueue_job(
        self,
        topology: dict[str, Any],
        action: str,
        node_name: str | None = None,
        command: list[str] | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        if action not in {"up", "down", "verify", "status", "terminal", "observability"}:
            raise EducationError("unsupported worker action")
        if max_attempts not in range(1, 11):
            raise EducationError("max attempts must be between 1 and 10")
        job_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as db:
            db.execute(
                "INSERT INTO worker_jobs("
                "id,worker_id,action,topology_json,node_name,command_json,status,attempts,max_attempts,"
                "result_json,created_at,updated_at,available_at,started_at,completed_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id, None, action, json.dumps(topology, separators=(",", ":"), ensure_ascii=False),
                    node_name, json.dumps(command or [], separators=(",", ":")), "queued", 0,
                    max_attempts, "{}", now, now, now, None, None,
                ),
            )
        return self.job(job_id)

    def claim_job(self, worker_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as db:
            if db.postgres:
                db.execute("SELECT id FROM remote_workers WHERE id=? FOR UPDATE", (worker_id,))
            else:
                db.execute("BEGIN IMMEDIATE")
            worker = db.execute("SELECT id FROM remote_workers WHERE id=?", (worker_id,)).fetchone()
            if not worker:
                raise EducationError("worker is not registered")
            row = db.execute(
                "SELECT * FROM worker_jobs WHERE status='queued' AND available_at<=?"
                " ORDER BY created_at LIMIT 1",
                (now,),
            ).fetchone()
            if not row:
                return None
            job_id = row["id"]
            db.execute(
                "UPDATE remote_workers SET last_heartbeat=?,status='online',updated_at=? WHERE id=?",
                (now, now, worker_id),
            )
            db.execute(
                "UPDATE worker_jobs SET status='running',worker_id=?,attempts=attempts+1,"
                "started_at=?,updated_at=? WHERE id=?",
                (worker_id, now, now, job_id),
            )
            claimed = db.execute("SELECT * FROM worker_jobs WHERE id=?", (job_id,)).fetchone()
            return self._job_result(claimed)

    def complete_job(
        self,
        job_id: str,
        worker_id: str,
        ok: bool,
        exit_code: int,
        output: str,
        nodes: list[dict[str, str]] | None = None,
        observability: dict[str, Any] | None = None,
        duration_ms: int = 0,
    ) -> dict[str, Any]:
        now = time.time()
        result_payload = {
            "ok": bool(ok),
            "exit_code": int(exit_code),
            "output": output[-65536:],
            "nodes": nodes or [],
            "observability": observability,
        }
        with self._connect() as db:
            row = db.execute(
                "SELECT attempts,status,worker_id,max_attempts FROM worker_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if not row:
                raise EducationError("job not found")
            if row["worker_id"] != worker_id:
                raise EducationError("job is leased by another worker")
            status = "completed" if ok else "failed"
            if not ok and int(row["attempts"]) < int(row["max_attempts"]):
                status = "queued"
                delay = min(30, 2 ** max(0, int(row["attempts"]) - 1))
                db.execute(
                    "UPDATE worker_jobs SET status=?,worker_id=NULL,result_json=?,updated_at=?,"
                    "available_at=?,started_at=NULL,completed_at=NULL WHERE id=?",
                    (status, json.dumps(result_payload), now, now + delay, job_id),
                )
            else:
                if not ok:
                    status = "dead"
                db.execute(
                    "UPDATE worker_jobs SET status=?,result_json=?,updated_at=?,completed_at=? WHERE id=?",
                    (status, json.dumps(result_payload), now, now, job_id),
                )
            action_row = db.execute("SELECT action FROM worker_jobs WHERE id=?", (job_id,)).fetchone()
            db.execute(
                "INSERT INTO execution_metrics(id,worker_id,job_id,action,ok,duration_ms,exit_code,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()), worker_id, job_id, action_row["action"], int(bool(ok)),
                    max(0, int(duration_ms)), int(exit_code), now,
                ),
            )
        if not ok:
            self.record_alert(
                "error",
                f"worker:{worker_id}",
                f"Job {job_id} failed: {output[-500:] or f'exit {exit_code}'}",
            )
        return self.job(job_id)

    def requeue_expired_jobs(self, lease_seconds: int = 300) -> int:
        cutoff = time.time() - lease_seconds
        with self._connect() as db:
            result = db.execute(
                "UPDATE worker_jobs SET status='queued',worker_id=NULL,started_at=NULL,updated_at=? "
                "WHERE status='running' AND started_at<?",
                (time.time(), cutoff),
            )
            return max(0, int(result.rowcount))

    def job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM worker_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise EducationError("job not found")
        return self._job_result(row)

    @staticmethod
    def _job_result(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["topology"] = json.loads(result.pop("topology_json"))
        result["command"] = json.loads(result.pop("command_json"))
        result["result"] = json.loads(result.pop("result_json"))
        return result

    def execution_metrics(self, limit: int = 500) -> list[dict[str, Any]]:
        limit = min(max(1, limit), 5000)
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,worker_id,job_id,action,ok,duration_ms,exit_code,recorded_at "
                "FROM execution_metrics ORDER BY recorded_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def record_alert(self, severity: str, source: str, message: str) -> dict[str, Any]:
        if severity not in {"warning", "error", "critical"}:
            raise EducationError("invalid alert severity")
        alert_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as db:
            db.execute(
                "INSERT INTO alert_notifications(id,severity,source,message,acknowledged,created_at) "
                "VALUES(?,?,?,?,0,?)",
                (alert_id, severity, source[:128], message[:5000], now),
            )
        return {"id": alert_id, "severity": severity, "source": source, "message": message, "acknowledged": False, "created_at": now}

    def alerts(self, limit: int = 500) -> list[dict[str, Any]]:
        limit = min(max(1, limit), 5000)
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,severity,source,message,acknowledged,created_at "
                "FROM alert_notifications ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def record_cleanup_attempt(
        self,
        laboratory_id: str,
        succeeded: bool,
        error: str | None = None,
        student_assignment_id: str | None = None,
        student_user_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        cleanup_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute(
                "INSERT INTO cleanup_attempts("
                "id,laboratory_id,student_assignment_id,student_user_id,status,attempt_count,last_error,"
                "created_at,updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    cleanup_id, laboratory_id, student_assignment_id, student_user_id,
                    "succeeded" if succeeded else "failed", 1,
                    (error or "")[:5000] or None, now, now,
                ),
            )
        if not succeeded:
            self.record_alert(
                "error",
                "cleanup",
                f"Laboratory cleanup failed for {laboratory_id}: {(error or 'unknown error')[:500]}",
            )
        return {
            "id": cleanup_id,
            "laboratory_id": laboratory_id,
            "status": "succeeded" if succeeded else "failed",
        }

    def change_password(self, user_id: str, old_password: str, new_password: str) -> None:
        new_password = _password(new_password)
        with self._connect() as db:
            row = db.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
            if not row or not verify_password(old_password, row["password_hash"]):
                raise EducationError("current password is incorrect")
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), user_id))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    @staticmethod
    def _quota(name: str, default: int, maximum: int) -> int:
        try:
            value = int(os.getenv(name, str(default)))
        except ValueError as exc:
            raise EducationError(f"{name} must be an integer") from exc
        if not 1 <= value <= maximum:
            raise EducationError(f"{name} must be between 1 and {maximum}")
        return value

    @staticmethod
    def _quota_float(name: str, default: float, maximum: float) -> float:
        try:
            value = float(os.getenv(name, str(default)))
        except ValueError as exc:
            raise EducationError(f"{name} must be a number") from exc
        if not math.isfinite(value) or not 0 < value <= maximum:
            raise EducationError(f"{name} must be greater than 0 and at most {maximum}")
        return value

    @staticmethod
    def _resources(topology: dict[str, Any]) -> tuple[float, int]:
        cpu_cores = 0.0
        memory_mb = 0
        for node in topology["nodes"]:
            profile = get_service(node.get("service_id", ""))
            resources = profile.resources if profile else {"cpu_cores": 1, "memory_mb": 512}
            cpu_cores += float(resources.get("cpu_cores", 1))
            memory_mb += int(resources.get("memory_mb", 512))
        return cpu_cores, memory_mb

    def _check_laboratory_resources(self, topology: dict[str, Any]) -> None:
        cpu_limit = self._quota_float("NETLAB_MAX_CPU_CORES_PER_LAB", 8, 128)
        memory_limit = self._quota("NETLAB_MAX_MEMORY_MB_PER_LAB", 8192, 1_048_576)
        cpu_cores, memory_mb = self._resources(topology)
        if cpu_cores > cpu_limit:
            raise EducationError(f"laboratory exceeds the {cpu_limit:g}-CPU quota")
        if memory_mb > memory_limit:
            raise EducationError(f"laboratory exceeds the {memory_limit}-MB memory quota")

    def create_laboratory(
        self,
        owner_id: str,
        topology: dict[str, Any],
        version_reason: str = "initial",
    ) -> dict[str, Any]:
        try:
            netlab.validate_topology(topology)
        except (netlab.TopologyError, TypeError, KeyError) as exc:
            raise EducationError(f"invalid topology: {exc}") from exc
        max_labs = self._quota("NETLAB_MAX_LABS_PER_USER", 5, 100)
        max_nodes = self._quota("NETLAB_MAX_NODES_PER_LAB", 20, 200)
        ttl_hours = self._quota("NETLAB_LAB_TTL_HOURS", 24, 720)
        if len(topology["nodes"]) > max_nodes:
            raise EducationError(f"laboratory exceeds the {max_nodes}-node quota")
        self._check_laboratory_resources(topology)

        laboratory_id = str(uuid.uuid4())
        topology = dict(topology)
        topology["lab"] = f"{topology['lab'][:52].rstrip('-_')}-{laboratory_id[:8]}"
        topology["laboratory_id"] = laboratory_id
        try:
            netlab.validate_topology(topology)
        except netlab.TopologyError as exc:
            raise EducationError(f"invalid laboratory identifier: {exc}") from exc
        now = time.time()
        expires_at = now + ttl_hours * 3600
        try:
            with self._connect() as db:
                if db.postgres:
                    db.execute("SELECT id FROM users WHERE id=? FOR UPDATE", (owner_id,))
                else:
                    db.execute("BEGIN IMMEDIATE")
                count = db.execute(
                    "SELECT COUNT(*) AS count FROM laboratories WHERE owner_id=? AND expires_at>?",
                    (owner_id, now),
                ).fetchone()["count"]
                if int(count) >= max_labs:
                    raise EducationError(f"laboratory quota reached ({max_labs} per user)")
                db.execute(
                    "INSERT INTO laboratories(id,owner_id,name,topology_json,status,created_at,updated_at,expires_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        laboratory_id, owner_id, topology["lab"],
                        json.dumps(topology, separators=(",", ":"), ensure_ascii=False),
                        "stopped", now, now, expires_at,
                    ),
                )
                db.execute(
                    "INSERT INTO laboratory_members(laboratory_id,user_id,role,added_at) VALUES(?,?,?,?)",
                    (laboratory_id, owner_id, "owner", now),
                )
                self._append_laboratory_version(db, laboratory_id, topology, version_reason, now)
        except _integrity_error_types() as exc:
            raise EducationError("laboratory could not be created") from exc
        return {
            "id": laboratory_id, "name": topology["lab"], "status": "stopped",
            "created_at": now, "expires_at": expires_at, "role": "owner", "topology": topology,
        }

    def list_laboratories(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT l.id,l.name,l.status,l.created_at,l.expires_at,"
                "CASE WHEN l.owner_id=? THEN 'owner' ELSE m.role END AS role "
                "FROM laboratories l LEFT JOIN laboratory_members m "
                "ON m.laboratory_id=l.id AND m.user_id=? "
                "WHERE (l.owner_id=? OR m.user_id=?) AND l.expires_at>? ORDER BY l.created_at DESC",
                (user_id, user_id, user_id, user_id, time.time()),
            )
            return [dict(row) for row in rows]

    def laboratory(self, laboratory_id: str, user_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT l.id,l.name,l.status,l.created_at,l.expires_at,l.topology_json,"
                "CASE WHEN l.owner_id=? THEN 'owner' ELSE m.role END AS role "
                "FROM laboratories l LEFT JOIN laboratory_members m "
                "ON m.laboratory_id=l.id AND m.user_id=? "
                "WHERE l.id=? AND (l.owner_id=? OR m.user_id=?)",
                (user_id, user_id, laboratory_id, user_id, user_id),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["topology"] = json.loads(result.pop("topology_json"))
        return result

    def laboratory_by_name(self, name: str, user_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT l.id,l.name,l.status,l.created_at,l.expires_at,l.topology_json,"
                "CASE WHEN l.owner_id=? THEN 'owner' ELSE m.role END AS role "
                "FROM laboratories l LEFT JOIN laboratory_members m "
                "ON m.laboratory_id=l.id AND m.user_id=? "
                "WHERE l.name=? AND (l.owner_id=? OR m.user_id=?)",
                (user_id, user_id, name, user_id, user_id),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["topology"] = json.loads(result.pop("topology_json"))
        return result

    @staticmethod
    def _append_laboratory_version(
        db: DatabaseConnection,
        laboratory_id: str,
        topology: dict[str, Any],
        reason: str,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        latest = db.execute(
            "SELECT MAX(version) AS version FROM laboratory_versions WHERE laboratory_id=?",
            (laboratory_id,),
        ).fetchone()["version"]
        version = int(latest or 0) + 1
        timestamp = time.time() if created_at is None else created_at
        serialized_topology = json.dumps(topology, separators=(",", ":"), ensure_ascii=False)
        max_storage_mb = EducationStore._quota("NETLAB_MAX_STORAGE_MB_PER_LAB", 100, 10_240)
        existing_versions = db.execute(
            "SELECT topology_json FROM laboratory_versions WHERE laboratory_id=?",
            (laboratory_id,),
        )
        existing_bytes = sum(len(row["topology_json"].encode("utf-8")) for row in existing_versions)
        current = db.execute(
            "SELECT topology_json FROM laboratories WHERE id=?",
            (laboratory_id,),
        ).fetchone()
        if current:
            existing_bytes += len(current["topology_json"].encode("utf-8"))
        if int(existing_bytes) + len(serialized_topology.encode("utf-8")) > max_storage_mb * 1024 * 1024:
            raise EducationError(f"laboratory exceeds the {max_storage_mb}-MB storage quota")
        db.execute(
            "INSERT INTO laboratory_versions(laboratory_id,version,created_at,reason,topology_json) "
            "VALUES(?,?,?,?,?)",
            (
                laboratory_id,
                version,
                timestamp,
                reason[:120],
                serialized_topology,
            ),
        )
        return {
            "version": version,
            "lab": topology["lab"],
            "created_at": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
            "reason": reason[:120],
        }

    def save_laboratory_topology(
        self,
        laboratory_id: str,
        user_id: str,
        topology: dict[str, Any],
        reason: str = "save",
    ) -> dict[str, Any]:
        try:
            netlab.validate_topology(topology)
        except (netlab.TopologyError, TypeError, KeyError) as exc:
            raise EducationError(f"invalid topology: {exc}") from exc
        with self._connect() as db:
            if db.postgres:
                db.execute("SELECT id FROM laboratories WHERE id=? FOR UPDATE", (laboratory_id,))
            else:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT l.name,l.topology_json,l.expires_at,"
                "CASE WHEN l.owner_id=? THEN 'owner' ELSE m.role END AS role "
                "FROM laboratories l LEFT JOIN laboratory_members m "
                "ON m.laboratory_id=l.id AND m.user_id=? "
                "WHERE l.id=? AND (l.owner_id=? OR m.user_id=?)",
                (user_id, user_id, laboratory_id, user_id, user_id),
            ).fetchone()
            if not row or row["role"] == "viewer":
                raise EducationError("laboratory not found")
            if float(row["expires_at"]) <= time.time():
                raise EducationError("laboratory has expired")
            if topology.get("laboratory_id") != laboratory_id or topology["lab"] != row["name"]:
                raise EducationError("laboratory identity cannot be changed")
            if len(topology["nodes"]) > self._quota("NETLAB_MAX_NODES_PER_LAB", 20, 200):
                raise EducationError("laboratory exceeds the node quota")
            self._check_laboratory_resources(topology)
            db.execute(
                "UPDATE laboratories SET topology_json=?,updated_at=? WHERE id=?",
                (json.dumps(topology, separators=(",", ":"), ensure_ascii=False), time.time(), laboratory_id),
            )
            return self._append_laboratory_version(db, laboratory_id, topology, reason)

    def list_laboratory_versions(self, laboratory_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT v.version,v.created_at,v.reason,l.name FROM laboratory_versions v "
                "JOIN laboratories l ON l.id=v.laboratory_id "
                "WHERE v.laboratory_id=? ORDER BY v.version DESC",
                (laboratory_id,),
            )
            return [
                {
                    "version": row["version"],
                    "lab": row["name"],
                    "created_at": datetime.fromtimestamp(row["created_at"], timezone.utc).isoformat(),
                    "reason": row["reason"],
                }
                for row in rows
            ]

    def restore_laboratory_version(self, laboratory_id: str, user_id: str, version: int) -> dict[str, Any]:
        with self._connect() as db:
            if db.postgres:
                db.execute("SELECT id FROM laboratories WHERE id=? FOR UPDATE", (laboratory_id,))
            else:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT l.name,l.expires_at,CASE WHEN l.owner_id=? THEN 'owner' ELSE m.role END AS role "
                "FROM laboratories l LEFT JOIN laboratory_members m "
                "ON m.laboratory_id=l.id AND m.user_id=? "
                "WHERE l.id=? AND (l.owner_id=? OR m.user_id=?)",
                (user_id, user_id, laboratory_id, user_id, user_id),
            ).fetchone()
            if not row or row["role"] == "viewer":
                raise EducationError("laboratory not found")
            if float(row["expires_at"]) <= time.time():
                raise EducationError("laboratory has expired")
            historical = db.execute(
                "SELECT topology_json FROM laboratory_versions WHERE laboratory_id=? AND version=?",
                (laboratory_id, version),
            ).fetchone()
            if not historical:
                raise EducationError(f"topology version not found: {version}")
            topology = json.loads(historical["topology_json"])
            topology["laboratory_id"] = laboratory_id
            topology["lab"] = row["name"]
            try:
                netlab.validate_topology(topology)
            except netlab.TopologyError as exc:
                raise EducationError(f"stored topology is invalid: {exc}") from exc
            if len(topology["nodes"]) > self._quota("NETLAB_MAX_NODES_PER_LAB", 20, 200):
                raise EducationError("laboratory exceeds the node quota")
            self._check_laboratory_resources(topology)
            db.execute(
                "UPDATE laboratories SET topology_json=?,updated_at=? WHERE id=?",
                (json.dumps(topology, separators=(",", ":"), ensure_ascii=False), time.time(), laboratory_id),
            )
            self._append_laboratory_version(db, laboratory_id, topology, f"restore:{version}")
            return topology

    def export_laboratory(self, laboratory_id: str, user_id: str) -> dict[str, Any]:
        laboratory = self.laboratory(laboratory_id, user_id)
        if not laboratory:
            raise EducationError("laboratory not found")
        return {
            "format": "netlab-laboratory-v1",
            "topology": laboratory["topology"],
            "versions": self.list_laboratory_versions(laboratory_id),
        }

    def claim_laboratory_run(self, laboratory_id: str, user_id: str) -> dict[str, Any]:
        max_running = self._quota("NETLAB_MAX_RUNNING_LABS_PER_USER", 2, 100)
        with self._connect() as db:
            if db.postgres:
                db.execute("SELECT id FROM users WHERE id=? FOR UPDATE", (user_id,))
            else:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT l.owner_id,l.name,l.topology_json,l.expires_at,l.status,"
                "CASE WHEN l.owner_id=? THEN 'owner' ELSE m.role END AS role "
                "FROM laboratories l LEFT JOIN laboratory_members m "
                "ON m.laboratory_id=l.id AND m.user_id=? "
                "WHERE l.id=? AND (l.owner_id=? OR m.user_id=?)"
                + (" FOR UPDATE OF l" if db.postgres else ""),
                (user_id, user_id, laboratory_id, user_id, user_id),
            ).fetchone()
            if not row or row["role"] == "viewer":
                raise EducationError("laboratory not found")
            if row["status"] == "running":
                raise EducationError("laboratory is already running")
            now = time.time()
            if float(row["expires_at"]) <= now:
                raise EducationError("laboratory has expired")
            count = db.execute(
                "SELECT COUNT(*) AS count FROM laboratories l LEFT JOIN laboratory_members m "
                "ON m.laboratory_id=l.id AND m.user_id=? "
                "WHERE (l.owner_id=? OR m.role='editor') AND l.status='running' "
                "AND l.expires_at>? AND l.id<>?",
                (user_id, user_id, now, laboratory_id),
            ).fetchone()["count"]
            if int(count) >= max_running:
                raise EducationError(f"active laboratory quota reached ({max_running} per user)")
            running = db.execute(
                "SELECT l.topology_json FROM laboratories l LEFT JOIN laboratory_members m "
                "ON m.laboratory_id=l.id AND m.user_id=? "
                "WHERE (l.owner_id=? OR m.role='editor') AND l.status='running' "
                "AND l.expires_at>? AND l.id<>?",
                (user_id, user_id, now, laboratory_id),
            )
            total_cpu, total_memory = self._resources(json.loads(row["topology_json"]))
            for existing in running:
                cpu, memory = self._resources(json.loads(existing["topology_json"]))
                total_cpu += cpu
                total_memory += memory
            cpu_limit = self._quota_float("NETLAB_MAX_RUNNING_CPU_CORES_PER_USER", 8, 256)
            memory_limit = self._quota("NETLAB_MAX_RUNNING_MEMORY_MB_PER_USER", 8192, 2_097_152)
            if total_cpu > cpu_limit:
                raise EducationError(f"active laboratories exceed the {cpu_limit:g}-CPU user quota")
            if total_memory > memory_limit:
                raise EducationError(f"active laboratories exceed the {memory_limit}-MB user memory quota")
            db.execute(
                "UPDATE laboratories SET status='running',updated_at=? WHERE id=?",
                (now, laboratory_id),
            )
            return json.loads(row["topology_json"])

    def set_laboratory_status(self, laboratory_id: str, status: str) -> None:
        if status not in {"stopped", "running", "expired", "failed"}:
            raise EducationError("invalid laboratory status")
        with self._connect() as db:
            db.execute(
                "UPDATE laboratories SET status=?,updated_at=? WHERE id=?",
                (status, time.time(), laboratory_id),
            )

    def record_laboratory_event(self, laboratory_id: str, user_id: str | None, message: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO laboratory_events(id,laboratory_id,user_id,message,created_at) VALUES(?,?,?,?,?)",
                (str(uuid.uuid4()), laboratory_id, user_id, message[:1000], time.time()),
            )
            db.execute(
                "DELETE FROM laboratory_events WHERE laboratory_id=? AND id NOT IN "
                "(SELECT id FROM laboratory_events WHERE laboratory_id=? ORDER BY created_at DESC LIMIT 500)",
                (laboratory_id, laboratory_id),
            )

    def laboratory_events(self, laboratory_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT message,created_at FROM laboratory_events "
                "WHERE laboratory_id=? ORDER BY created_at DESC LIMIT 100",
                (laboratory_id,),
            )
            return [dict(row) for row in rows]

    def expired_laboratories(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            now = time.time()
            if db.postgres:
                rows = db.execute(
                    "SELECT id,topology_json,expires_at,updated_at FROM laboratories "
                    "WHERE expires_at<=? AND status IN ('running','stopped','failed') "
                    "AND (updated_at<expires_at OR updated_at<=?) "
                    "ORDER BY expires_at FOR UPDATE SKIP LOCKED",
                    (now, now - 60),
                ).fetchall()
            else:
                db.execute("BEGIN IMMEDIATE")
                rows = db.execute(
                    "SELECT id,topology_json,expires_at,updated_at FROM laboratories "
                    "WHERE expires_at<=? AND status IN ('running','stopped','failed') "
                    "AND (updated_at<expires_at OR updated_at<=?) ORDER BY expires_at",
                    (now, now - 60),
                ).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE laboratories SET updated_at=? WHERE id=?",
                    (now, row["id"]),
                )
            expired = [
                {"id": row["id"], "topology": json.loads(row["topology_json"])}
                for row in rows
            ]
            student_query = (
                "SELECT sr.assignment_id,sr.user_id,sl.topology_json FROM student_lab_runtime sr "
                "JOIN student_labs sl ON sl.assignment_id=sr.assignment_id AND sl.user_id=sr.user_id "
                "WHERE sr.expires_at<=? AND sr.status IN ('running','failed') AND sr.updated_at<=? "
                "ORDER BY sr.expires_at"
            )
            if db.postgres:
                student_query += " FOR UPDATE OF sr SKIP LOCKED"
            student_rows = db.execute(student_query, (now, now - 60)).fetchall()
            for row in student_rows:
                db.execute(
                    "UPDATE student_lab_runtime SET updated_at=? WHERE assignment_id=? AND user_id=?",
                    (now, row["assignment_id"], row["user_id"]),
                )
                expired.append({
                    "kind": "student",
                    "assignment_id": row["assignment_id"],
                    "user_id": row["user_id"],
                    "topology": json.loads(row["topology_json"]),
                })
            return expired

    def add_laboratory_member(self, laboratory_id: str, owner_id: str, email: str, role: str) -> None:
        if role not in {"editor", "viewer"}:
            raise EducationError("laboratory role must be editor or viewer")
        with self._connect() as db:
            owner = db.execute(
                "SELECT id FROM laboratories WHERE id=? AND owner_id=?",
                (laboratory_id, owner_id),
            ).fetchone()
            member = db.execute("SELECT id,role FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
            if not owner or not member:
                raise EducationError("laboratory or user not found")
            if member["role"] == "student" and role == "editor":
                raise EducationError("student execution requires an isolated student laboratory")
            try:
                db.execute(
                    "INSERT INTO laboratory_members(laboratory_id,user_id,role,added_at) VALUES(?,?,?,?)",
                    (laboratory_id, member["id"], role, time.time()),
                )
            except _integrity_error_types() as exc:
                raise EducationError("user is already a laboratory member") from exc

    def list_users(self) -> list[dict[str, str]]:
        with self._connect() as db:
            return [self.public_user(row) for row in db.execute("SELECT * FROM users ORDER BY display_name COLLATE NOCASE")]

    def create_group(self, teacher_id: str, name: str) -> dict[str, Any]:
        name = name.strip()
        if not name or len(name) > 100:
            raise EducationError("group name must contain 1 to 100 characters")
        group_id = str(uuid.uuid4())
        try:
            with self._connect() as db:
                db.execute("INSERT INTO groups(id,name,teacher_id,created_at) VALUES(?,?,?,?)", (group_id, name, teacher_id, time.time()))
        except _integrity_error_types() as exc:
            raise EducationError("a group with this name already exists") from exc
        return {"id": group_id, "name": name, "teacher_id": teacher_id, "members": 0}

    def list_groups(self, user: dict[str, str]) -> list[dict[str, Any]]:
        with self._connect() as db:
            if user["role"] in {"teacher", "admin"}:
                rows = db.execute(
                    "SELECT g.id,g.name,g.teacher_id,COUNT(m.user_id) AS members FROM groups g "
                    "LEFT JOIN group_members m ON m.group_id=g.id "
                    + ("" if user["role"] == "admin" else "WHERE g.teacher_id=? ")
                    + "GROUP BY g.id ORDER BY g.name",
                    () if user["role"] == "admin" else (user["id"],),
                )
            else:
                rows = db.execute(
                    "SELECT g.id,g.name,g.teacher_id,COUNT(m.user_id) AS members FROM groups g "
                    "JOIN group_members mine ON mine.group_id=g.id LEFT JOIN group_members m ON m.group_id=g.id "
                    "WHERE mine.user_id=? GROUP BY g.id ORDER BY g.name",
                    (user["id"],),
                )
            return [dict(row) for row in rows]

    def add_member(self, teacher_id: str, group_id: str, email: str) -> None:
        with self._connect() as db:
            group = db.execute(
                "SELECT id FROM groups WHERE id=? AND (teacher_id=? OR EXISTS "
                "(SELECT 1 FROM users WHERE id=? AND is_admin=1))",
                (group_id, teacher_id, teacher_id),
            ).fetchone()
            user = db.execute("SELECT id,role FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
            if not group:
                raise EducationError("group not found")
            if not user or user["role"] != "student":
                raise EducationError("student account not found")
            try:
                db.execute("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (group_id, user["id"], time.time()))
            except _integrity_error_types() as exc:
                raise EducationError("student is already in this group") from exc
            db.execute(
                "INSERT INTO student_labs(assignment_id,user_id,topology_json,status,updated_at) "
                "SELECT a.id,?,a.topology_json,'assigned',? FROM assignments a WHERE a.group_id=? "
                "AND NOT EXISTS (SELECT 1 FROM student_labs sl WHERE sl.assignment_id=a.id AND sl.user_id=?)",
                (user["id"], time.time(), group_id, user["id"]),
            )

    def create_assignment(
        self,
        teacher_id: str,
        group_id: str,
        title: str,
        topology: dict[str, Any],
        instructions: str = "",
        criteria: list[str] | None = None,
    ) -> dict[str, Any]:
        title = title.strip()
        if not title or len(title) > 120:
            raise EducationError("assignment title must contain 1 to 120 characters")
        instructions = instructions.strip()
        if len(instructions) > 5000:
            raise EducationError("assignment instructions must not exceed 5000 characters")
        criteria = [item.strip() for item in (criteria or []) if item.strip()]
        if len(criteria) > 20 or any(len(item) > 300 for item in criteria):
            raise EducationError("assignment criteria allow up to 20 items of 300 characters")
        topology = dict(topology)
        topology.pop("laboratory_id", None)
        try:
            netlab.validate_topology(topology)
        except (netlab.TopologyError, TypeError, KeyError) as exc:
            raise EducationError(f"invalid topology: {exc}") from exc
        max_nodes = self._quota("NETLAB_MAX_NODES_PER_LAB", 20, 200)
        if len(topology["nodes"]) > max_nodes:
            raise EducationError(f"laboratory exceeds the {max_nodes}-node quota")
        self._check_laboratory_resources(topology)
        assignment_id = str(uuid.uuid4())
        created_at = time.time()
        snapshot = json.dumps(topology, separators=(",", ":"), ensure_ascii=False)
        with self._connect() as db:
            group = db.execute(
                "SELECT id FROM groups WHERE id=? AND (teacher_id=? OR EXISTS "
                "(SELECT 1 FROM users WHERE id=? AND is_admin=1))",
                (group_id, teacher_id, teacher_id),
            ).fetchone()
            if not group:
                raise EducationError("group not found")
            db.execute(
                "INSERT INTO assignments(id,group_id,created_by,title,topology_json,created_at) VALUES(?,?,?,?,?,?)",
                (assignment_id, group_id, teacher_id, title, snapshot, created_at),
            )
            db.execute(
                "INSERT INTO assignment_details(assignment_id,instructions,criteria_json) VALUES(?,?,?)",
                (assignment_id, instructions, json.dumps(criteria, ensure_ascii=False)),
            )
            db.execute(
                "INSERT INTO student_labs(assignment_id,user_id,topology_json,status,updated_at) "
                "SELECT ?,user_id,?,'assigned',? FROM group_members WHERE group_id=?",
                (assignment_id, snapshot, created_at, group_id),
            )
        return {
            "id": assignment_id,
            "group_id": group_id,
            "title": title,
            "created_at": created_at,
            "instructions": instructions,
            "criteria": criteria,
        }

    def assignments_for_student(self, student_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT a.id,a.title,a.created_at,g.name AS group_name,sl.status,sl.topology_json,sl.submitted_at,"
                "COALESCE(sr.status,'stopped') AS runtime_status,COALESCE(d.instructions,'') AS instructions,"
                "COALESCE(d.criteria_json,'[]') AS criteria_json,"
                "(SELECT COUNT(*) FROM student_submission_attempts sa WHERE sa.assignment_id=a.id AND sa.user_id=sl.user_id) AS attempt_count,"
                "(SELECT sa.feedback FROM student_submission_attempts sa WHERE sa.assignment_id=a.id AND sa.user_id=sl.user_id ORDER BY sa.attempt DESC LIMIT 1) AS feedback,"
                "(SELECT sa.grade FROM student_submission_attempts sa WHERE sa.assignment_id=a.id AND sa.user_id=sl.user_id ORDER BY sa.attempt DESC LIMIT 1) AS grade "
                "FROM student_labs sl JOIN assignments a ON a.id=sl.assignment_id JOIN groups g ON g.id=a.group_id "
                "LEFT JOIN assignment_details d ON d.assignment_id=a.id "
                "LEFT JOIN student_lab_runtime sr ON sr.assignment_id=sl.assignment_id AND sr.user_id=sl.user_id "
                "WHERE sl.user_id=? ORDER BY a.created_at DESC",
                (student_id,),
            )
            return [self._assignment_result(row, include_topology=True) for row in rows]

    @staticmethod
    def _assignment_result(row: sqlite3.Row, include_topology: bool = False) -> dict[str, Any]:
        result = {key: row[key] for key in ("id", "title", "created_at", "group_name", "status", "submitted_at")}
        if "runtime_status" in row.keys():
            result["runtime_status"] = row["runtime_status"]
        if "instructions" in row.keys():
            result["instructions"] = row["instructions"]
            result["criteria"] = json.loads(row["criteria_json"])
            result["attempt_count"] = row["attempt_count"]
            result["feedback"] = row["feedback"]
            result["grade"] = row["grade"]
        if include_topology:
            result["topology"] = json.loads(row["topology_json"])
        return result

    @staticmethod
    def _student_laboratory_identity(assignment_id: str, student_id: str, template: dict[str, Any]) -> tuple[str, str]:
        laboratory_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"netlab-student-lab:{assignment_id}:{student_id}"))
        name = f"{template['lab'][:43]}-student-{laboratory_id[:12]}"
        return laboratory_id, name

    def student_laboratory(self, student_id: str, assignment_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT sl.topology_json,a.topology_json AS template_json,"
                "COALESCE(sr.status,'stopped') AS runtime_status,sr.expires_at "
                "FROM student_labs sl LEFT JOIN student_lab_runtime sr "
                "ON sr.assignment_id=sl.assignment_id AND sr.user_id=sl.user_id "
                "JOIN assignments a ON a.id=sl.assignment_id "
                "WHERE sl.assignment_id=? AND sl.user_id=?",
                (assignment_id, student_id),
            ).fetchone()
        if not row:
            return None
        topology = json.loads(row["topology_json"])
        if not topology.get("laboratory_id"):
            return None
        expected_id, expected_name = self._student_laboratory_identity(
            assignment_id, student_id, json.loads(row["template_json"]),
        )
        if topology.get("laboratory_id") != expected_id or topology.get("lab") != expected_name:
            raise EducationError("student laboratory identity is invalid")
        try:
            netlab.validate_topology(topology)
        except netlab.TopologyError as exc:
            raise EducationError(f"student laboratory topology is invalid: {exc}") from exc
        return {
            "topology": topology,
            "status": row["runtime_status"],
            "expires_at": row["expires_at"],
        }

    def clone_for_student(self, student_id: str, assignment_id: str) -> dict[str, Any]:
        with self._connect() as db:
            if db.postgres:
                db.execute("SELECT id FROM users WHERE id=? FOR UPDATE", (student_id,))
            else:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT a.topology_json,a.title FROM student_labs sl JOIN assignments a ON a.id=sl.assignment_id "
                "LEFT JOIN student_lab_runtime sr ON sr.assignment_id=sl.assignment_id AND sr.user_id=sl.user_id "
                "WHERE sl.assignment_id=? AND sl.user_id=?",
                (assignment_id, student_id),
            ).fetchone()
            if not row:
                raise EducationError("assignment not found")
            runtime = db.execute(
                "SELECT status FROM student_lab_runtime WHERE assignment_id=? AND user_id=?",
                (assignment_id, student_id),
            ).fetchone()
            if runtime and runtime["status"] in {"running", "failed"}:
                raise EducationError("clean up the student laboratory before resetting it")
            topology = json.loads(row["topology_json"])
            laboratory_id, topology["lab"] = self._student_laboratory_identity(assignment_id, student_id, topology)
            topology["laboratory_id"] = laboratory_id
            snapshot = json.dumps(topology, separators=(",", ":"), ensure_ascii=False)
            now = time.time()
            db.execute(
                "UPDATE student_labs SET topology_json=?,status='in_progress',updated_at=?,submitted_at=NULL "
                "WHERE assignment_id=? AND user_id=?",
                (snapshot, now, assignment_id, student_id),
            )
            db.execute(
                "INSERT INTO student_lab_runtime(assignment_id,user_id,status,updated_at,expires_at) "
                "VALUES(?,?,'stopped',?,NULL) ON CONFLICT(assignment_id,user_id) DO UPDATE SET "
                "status='stopped',updated_at=excluded.updated_at,expires_at=NULL",
                (assignment_id, student_id, now),
            )
            return topology

    def reset_student_laboratory(self, student_id: str, assignment_id: str) -> dict[str, Any]:
        with self._connect() as db:
            if db.postgres:
                db.execute("SELECT id FROM users WHERE id=? FOR UPDATE", (student_id,))
            else:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT a.topology_json FROM student_labs sl JOIN assignments a ON a.id=sl.assignment_id "
                "WHERE sl.assignment_id=? AND sl.user_id=?",
                (assignment_id, student_id),
            ).fetchone()
            if not row:
                raise EducationError("assignment not found")
            topology = json.loads(row["topology_json"])
            laboratory_id, topology["lab"] = self._student_laboratory_identity(
                assignment_id, student_id, topology,
            )
            topology["laboratory_id"] = laboratory_id
            snapshot = json.dumps(topology, separators=(",", ":"), ensure_ascii=False)
            now = time.time()
            db.execute(
                "UPDATE student_labs SET topology_json=?,status='in_progress',updated_at=?,submitted_at=NULL "
                "WHERE assignment_id=? AND user_id=?",
                (snapshot, now, assignment_id, student_id),
            )
            db.execute(
                "INSERT INTO student_lab_runtime(assignment_id,user_id,status,updated_at,expires_at) "
                "VALUES(?,?,'stopped',?,NULL) ON CONFLICT(assignment_id,user_id) DO UPDATE SET "
                "status='stopped',updated_at=excluded.updated_at,expires_at=NULL",
                (assignment_id, student_id, now),
            )
            return topology

    def save_student_topology(self, student_id: str, assignment_id: str, topology: dict[str, Any]) -> None:
        try:
            netlab.validate_topology(topology)
        except (netlab.TopologyError, TypeError, KeyError) as exc:
            raise EducationError(f"invalid topology: {exc}") from exc
        with self._connect() as db:
            if db.postgres:
                db.execute("SELECT id FROM users WHERE id=? FOR UPDATE", (student_id,))
            else:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT a.topology_json FROM student_labs sl JOIN assignments a ON a.id=sl.assignment_id "
                "WHERE sl.assignment_id=? AND sl.user_id=?",
                (assignment_id, student_id),
            ).fetchone()
            if not row:
                raise EducationError("assignment not found")
            runtime = db.execute(
                "SELECT status FROM student_lab_runtime WHERE assignment_id=? AND user_id=?",
                (assignment_id, student_id),
            ).fetchone()
            if runtime and runtime["status"] in {"running", "failed"}:
                raise EducationError("clean up the student laboratory before editing it")
            template = json.loads(row["topology_json"])
            laboratory_id, expected_name = self._student_laboratory_identity(assignment_id, student_id, template)
            if topology.get("laboratory_id") != laboratory_id or topology["lab"] != expected_name:
                raise EducationError("student laboratory identity cannot be changed")
            expected_topology = deepcopy(template)
            expected_topology["laboratory_id"] = laboratory_id
            expected_topology["lab"] = expected_name
            candidate_nodes = {node.get("name"): node for node in topology.get("nodes", []) if isinstance(node, dict)}
            if len(candidate_nodes) != len(expected_topology["nodes"]):
                raise EducationError("student copies may not add or remove nodes")
            for expected_node in expected_topology["nodes"]:
                candidate_node = candidate_nodes.get(expected_node["name"])
                if not candidate_node:
                    raise EducationError("student copies may not rename nodes")
                original_interfaces = expected_node.get("interfaces", [])
                candidate_interfaces = candidate_node.get("interfaces", [])
                if len(original_interfaces) != len(candidate_interfaces):
                    raise EducationError("student copies may not add or remove interfaces")
                for original_interface, candidate_interface in zip(original_interfaces, candidate_interfaces):
                    if (
                        original_interface.get("name") != candidate_interface.get("name")
                        or original_interface.get("network") != candidate_interface.get("network")
                    ):
                        raise EducationError("student copies may not change interface or network assignments")
                    for field in ("ipv4", "gateway"):
                        if field in candidate_interface:
                            original_interface[field] = candidate_interface[field]
                        else:
                            original_interface.pop(field, None)
                routes = candidate_node.get("routes", [])
                if not isinstance(routes, list) or len(routes) > 64:
                    raise EducationError("student copies may contain at most 64 static routes per node")
                if "routes" in expected_node or "routes" in candidate_node:
                    expected_node["routes"] = routes
                    candidate_node["routes"] = routes
            if topology != expected_topology:
                raise EducationError("students may only edit interface IPv4/gateways and static routes")
            if len(topology["nodes"]) > self._quota("NETLAB_MAX_NODES_PER_LAB", 20, 200):
                raise EducationError("laboratory exceeds the node quota")
            self._check_laboratory_resources(topology)
            result = db.execute(
                "UPDATE student_labs SET topology_json=?,status='in_progress',updated_at=?,submitted_at=NULL "
                "WHERE assignment_id=? AND user_id=?",
                (json.dumps(topology, separators=(",", ":"), ensure_ascii=False), time.time(), assignment_id, student_id),
            )
            if result.rowcount == 0:
                raise EducationError("assignment not found")

    def submit_assignment(self, student_id: str, assignment_id: str) -> None:
        with self._connect() as db:
            if db.postgres:
                db.execute("SELECT id FROM users WHERE id=? FOR UPDATE", (student_id,))
            else:
                db.execute("BEGIN IMMEDIATE")
            runtime = db.execute(
                "SELECT status FROM student_lab_runtime WHERE assignment_id=? AND user_id=?",
                (assignment_id, student_id),
            ).fetchone()
            if runtime and runtime["status"] in {"running", "failed"}:
                raise EducationError("clean up the student laboratory before submitting it")
            row = db.execute(
                "SELECT sl.topology_json,a.topology_json AS template_json FROM student_labs sl "
                "JOIN assignments a ON a.id=sl.assignment_id WHERE sl.assignment_id=? AND sl.user_id=?",
                (assignment_id, student_id),
            ).fetchone()
            if not row:
                raise EducationError("assignment not found")
            topology = json.loads(row["topology_json"])
            if not topology.get("laboratory_id"):
                raise EducationError("create your isolated copy before submitting it")
            expected_id, expected_name = self._student_laboratory_identity(
                assignment_id, student_id, json.loads(row["template_json"]),
            )
            if topology.get("laboratory_id") != expected_id or topology.get("lab") != expected_name:
                raise EducationError("student laboratory identity is invalid")
            attempt = int(db.execute(
                "SELECT COALESCE(MAX(attempt),0)+1 AS attempt FROM student_submission_attempts "
                "WHERE assignment_id=? AND user_id=?",
                (assignment_id, student_id),
            ).fetchone()["attempt"])
            submitted_at = time.time()
            db.execute(
                "INSERT INTO student_submission_attempts(id,assignment_id,user_id,attempt,topology_json,submitted_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()), assignment_id, student_id, attempt,
                    row["topology_json"], submitted_at,
                ),
            )
            db.execute(
                "UPDATE student_labs SET status='submitted',submitted_at=?,updated_at=? "
                "WHERE assignment_id=? AND user_id=?",
                (submitted_at, submitted_at, assignment_id, student_id),
            )

    def submission_history_for_student(self, student_id: str, assignment_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            assignment = db.execute(
                "SELECT 1 FROM student_labs WHERE assignment_id=? AND user_id=?",
                (assignment_id, student_id),
            ).fetchone()
            if not assignment:
                raise EducationError("assignment not found")
            rows = db.execute(
                "SELECT id,attempt,topology_json,submitted_at,feedback,grade,reviewed_at "
                "FROM student_submission_attempts WHERE assignment_id=? AND user_id=? ORDER BY attempt DESC",
                (assignment_id, student_id),
            )
            return [
                {
                    "id": row["id"],
                    "attempt": row["attempt"],
                    "topology": json.loads(row["topology_json"]),
                    "submitted_at": row["submitted_at"],
                    "feedback": row["feedback"],
                    "grade": row["grade"],
                    "reviewed_at": row["reviewed_at"],
                }
                for row in rows
            ]

    def submission_history_for_teacher(
        self, teacher_id: str, assignment_id: str, student_id: str,
    ) -> list[dict[str, Any]]:
        with self._connect() as db:
            assignment = db.execute(
                "SELECT a.group_id FROM assignments a JOIN groups g ON g.id=a.group_id "
                "WHERE a.id=? AND (g.teacher_id=? OR EXISTS "
                "(SELECT 1 FROM users WHERE id=? AND is_admin=1))",
                (assignment_id, teacher_id, teacher_id),
            ).fetchone()
            if not assignment:
                raise EducationError("assignment not found")
            rows = db.execute(
                "SELECT sa.id,sa.attempt,sa.topology_json,sa.submitted_at,sa.feedback,sa.grade,sa.reviewed_at,"
                "reviewer.display_name AS reviewed_by "
                "FROM student_submission_attempts sa "
                "JOIN group_members gm ON gm.group_id=? AND gm.user_id=sa.user_id "
                "LEFT JOIN users reviewer ON reviewer.id=sa.reviewed_by "
                "WHERE sa.assignment_id=? AND sa.user_id=? ORDER BY sa.attempt DESC",
                (assignment["group_id"], assignment_id, student_id),
            )
            history = [
                {
                    "id": row["id"],
                    "attempt": row["attempt"],
                    "topology": json.loads(row["topology_json"]),
                    "submitted_at": row["submitted_at"],
                    "feedback": row["feedback"],
                    "grade": row["grade"],
                    "reviewed_at": row["reviewed_at"],
                    "reviewed_by": row["reviewed_by"],
                }
                for row in rows
            ]
            if not history:
                member = db.execute(
                    "SELECT 1 FROM student_labs WHERE assignment_id=? AND user_id=?",
                    (assignment_id, student_id),
                ).fetchone()
                if not member:
                    raise EducationError("student assignment not found")
            return history

    def review_submission(
        self, teacher_id: str, assignment_id: str, student_id: str, submission_id: str,
        feedback: str, grade: float | None = None,
    ) -> None:
        feedback = feedback.strip()
        if not feedback or len(feedback) > 4000:
            raise EducationError("feedback must contain 1 to 4000 characters")
        if grade is not None and (not math.isfinite(grade) or not 0 <= grade <= 100):
            raise EducationError("grade must be between 0 and 100")
        with self._connect() as db:
            result = db.execute(
                "UPDATE student_submission_attempts SET feedback=?,grade=?,reviewed_by=?,reviewed_at=? "
                "WHERE id=? AND assignment_id=? AND user_id=? AND EXISTS ("
                "SELECT 1 FROM assignments a JOIN groups g ON g.id=a.group_id "
                "JOIN group_members gm ON gm.group_id=g.id AND gm.user_id=? "
                "WHERE a.id=? AND (g.teacher_id=? OR EXISTS "
                "(SELECT 1 FROM users WHERE id=? AND is_admin=1)) "
                "AND student_submission_attempts.assignment_id=a.id)",
                (
                    feedback, grade, teacher_id, time.time(), submission_id, assignment_id, student_id,
                    student_id, assignment_id, teacher_id, teacher_id,
                ),
            )
            if result.rowcount == 0:
                raise EducationError("submission not found")

    def claim_student_laboratory_run(self, student_id: str, assignment_id: str) -> dict[str, Any]:
        max_running = self._quota("NETLAB_MAX_RUNNING_LABS_PER_USER", 2, 100)
        with self._connect() as db:
            if db.postgres:
                db.execute("SELECT id FROM users WHERE id=? FOR UPDATE", (student_id,))
            else:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT sl.topology_json,a.topology_json AS template_json,"
                "COALESCE(sr.status,'stopped') AS runtime_status "
                "FROM student_labs sl LEFT JOIN student_lab_runtime sr "
                "ON sr.assignment_id=sl.assignment_id AND sr.user_id=sl.user_id "
                "JOIN assignments a ON a.id=sl.assignment_id "
                "WHERE sl.assignment_id=? AND sl.user_id=?",
                (assignment_id, student_id),
            ).fetchone()
            if not row:
                raise EducationError("assignment not found")
            topology = json.loads(row["topology_json"])
            if not topology.get("laboratory_id"):
                raise EducationError("create your isolated copy before deploying it")
            expected_id, expected_name = self._student_laboratory_identity(
                assignment_id, student_id, json.loads(row["template_json"]),
            )
            if topology.get("laboratory_id") != expected_id or topology.get("lab") != expected_name:
                raise EducationError("student laboratory identity is invalid")
            if row["runtime_status"] in {"running", "failed"}:
                raise EducationError("clean up the student laboratory before deploying it again")

            now = time.time()
            running = db.execute(
                "SELECT l.topology_json FROM laboratories l "
                "WHERE l.owner_id=? AND l.status='running' AND l.expires_at>? "
                "UNION ALL "
                "SELECT sl.topology_json FROM student_labs sl "
                "JOIN student_lab_runtime sr ON sr.assignment_id=sl.assignment_id AND sr.user_id=sl.user_id "
                "WHERE sl.user_id=? AND sr.status='running' AND sr.expires_at>?",
                (student_id, now, student_id, now),
            ).fetchall()
            if len(running) >= max_running:
                raise EducationError(f"active laboratory quota reached ({max_running} per user)")
            total_cpu, total_memory = self._resources(topology)
            for existing in running:
                cpu, memory = self._resources(json.loads(existing["topology_json"]))
                total_cpu += cpu
                total_memory += memory
            cpu_limit = self._quota_float("NETLAB_MAX_RUNNING_CPU_CORES_PER_USER", 8, 256)
            memory_limit = self._quota("NETLAB_MAX_RUNNING_MEMORY_MB_PER_USER", 8192, 2_097_152)
            if total_cpu > cpu_limit:
                raise EducationError(f"active laboratories exceed the {cpu_limit:g}-CPU user quota")
            if total_memory > memory_limit:
                raise EducationError(f"active laboratories exceed the {memory_limit}-MB user memory quota")
            expires_at = now + self._quota("NETLAB_LAB_TTL_HOURS", 24, 720) * 3600
            db.execute(
                "INSERT INTO student_lab_runtime(assignment_id,user_id,status,updated_at,expires_at) "
                "VALUES(?,?,'running',?,?) ON CONFLICT(assignment_id,user_id) DO UPDATE SET "
                "status='running',updated_at=excluded.updated_at,expires_at=excluded.expires_at",
                (assignment_id, student_id, now, expires_at),
            )
            return topology

    def set_student_laboratory_status(self, student_id: str, assignment_id: str, status: str) -> None:
        if status not in {"stopped", "running", "expired", "failed"}:
            raise EducationError("invalid student laboratory status")
        with self._connect() as db:
            result = db.execute(
                "UPDATE student_lab_runtime SET status=?,updated_at=?,"
                "expires_at=CASE WHEN ? IN ('stopped','expired') THEN NULL ELSE expires_at END "
                "WHERE assignment_id=? AND user_id=?",
                (status, time.time(), status, assignment_id, student_id),
            )
            if result.rowcount == 0:
                raise EducationError("assignment runtime not found")

    def submissions(self, teacher_id: str, group_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            group = db.execute(
                "SELECT id FROM groups WHERE id=? AND (teacher_id=? OR EXISTS "
                "(SELECT 1 FROM users WHERE id=? AND is_admin=1))",
                (group_id, teacher_id, teacher_id),
            ).fetchone()
            if not group:
                raise EducationError("group not found")
            return [dict(row) for row in db.execute(
                "SELECT a.id AS assignment_id,a.title,u.id AS student_id,u.email,u.display_name,sl.status,sl.updated_at,sl.submitted_at,"
                "COALESCE(sr.status,'stopped') AS runtime_status,"
                "(SELECT COUNT(*) FROM student_submission_attempts sa WHERE sa.assignment_id=a.id AND sa.user_id=sl.user_id) AS attempt_count,"
                "(SELECT sa.feedback FROM student_submission_attempts sa WHERE sa.assignment_id=a.id AND sa.user_id=sl.user_id ORDER BY sa.attempt DESC LIMIT 1) AS feedback,"
                "(SELECT sa.grade FROM student_submission_attempts sa WHERE sa.assignment_id=a.id AND sa.user_id=sl.user_id ORDER BY sa.attempt DESC LIMIT 1) AS grade "
                "FROM assignments a JOIN student_labs sl ON sl.assignment_id=a.id JOIN users u ON u.id=sl.user_id "
                "LEFT JOIN student_lab_runtime sr ON sr.assignment_id=sl.assignment_id AND sr.user_id=sl.user_id "
                "WHERE a.group_id=? ORDER BY a.created_at DESC,u.display_name COLLATE NOCASE",
                (group_id,),
            )]


_DEFAULT_DB = Path(os.getenv("NETLAB_DATA_DIR", Path(__file__).resolve().parents[2] / ".netlab-data")) / "education.sqlite3"
store = EducationStore(os.getenv("NETLAB_DATABASE_URL") or os.getenv("NETLAB_EDUCATION_DB", str(_DEFAULT_DB)))
router = APIRouter()


class BootstrapRequest(BaseModel):
    bootstrap_token: str = Field(min_length=1, max_length=500)
    email: str
    display_name: str
    password: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return _email(value)

    @field_validator("password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        return _password(value)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def bounded_email(cls, value: str) -> str:
        if len(value) > 254:
            raise ValueError("email is too long")
        return value


class CreateStudentRequest(BaseModel):
    email: str
    display_name: str
    password: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return _email(value)

    @field_validator("password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        return _password(value)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        return _password(value)


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str

    @field_validator("password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        return _password(value)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        return _password(value)


class InvitationRequest(BaseModel):
    email: str
    display_name: str
    role: str = "student"
    group_id: str | None = None

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return _email(value)


class GroupRequest(BaseModel):
    name: str


class AddMemberRequest(BaseModel):
    email: str


class AssignmentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    topology: dict[str, Any]
    instructions: str = Field(default="", max_length=5000)
    criteria: list[str] = Field(default_factory=list, max_length=20)


class SaveTopologyRequest(BaseModel):
    topology: dict[str, Any]


class SubmissionFeedbackRequest(BaseModel):
    feedback: str = Field(min_length=1, max_length=4000)
    grade: float | None = Field(default=None, ge=0, le=100)


class WorkerRegistrationRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    worker_name: str = Field(min_length=1, max_length=128)
    capabilities: list[str] = Field(default_factory=lambda: ["docker"], max_length=32)


class WorkerJobRequest(BaseModel):
    action: str
    topology: dict[str, Any]
    node_name: str | None = None
    command: list[str] = Field(default_factory=list, max_length=64)
    max_attempts: int = Field(default=3, ge=1, le=10)


def require_user(request: Request) -> dict[str, str]:
    user = store.session_user(request.cookies.get(SESSION_COOKIE))
    if not user:
        raise HTTPException(status_code=401, detail="authentication required")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf_cookie = request.cookies.get(CSRF_COOKIE)
        csrf_header = request.headers.get("x-netlab-csrf")
        if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
            raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
        if not store.session_user(request.cookies.get(SESSION_COOKIE), csrf_cookie):
            raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    return user


def require_teacher(user: dict[str, str] = Depends(require_user)) -> dict[str, str]:
    if user["role"] not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="teacher role required")
    return user


def _set_session(response: Response, user_id: str) -> str:
    token, csrf = store.create_session(user_id)
    secure = production_mode() or os.getenv("NETLAB_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure, samesite="strict", max_age=SESSION_TTL_SECONDS, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=secure, samesite="strict", max_age=SESSION_TTL_SECONDS, path="/")
    return csrf


def _clear_session(response: Response) -> None:
    secure = production_mode() or os.getenv("NETLAB_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=secure, samesite="strict", path="/")
    response.delete_cookie(CSRF_COOKIE, httponly=False, secure=secure, samesite="strict", path="/")


@router.get("/auth/state")
def auth_state() -> dict[str, Any]:
    return {
        "has_users": store.user_count() > 0,
        "bootstrap_enabled": bool(os.getenv("NETLAB_BOOTSTRAP_TOKEN")),
        "bootstrap_role": os.getenv("NETLAB_BOOTSTRAP_ROLE", "teacher"),
    }


@router.post("/auth/bootstrap")
def bootstrap(request: BootstrapRequest, response: Response, http_request: Request) -> dict[str, Any]:
    throttle_key = f"bootstrap:{http_request.client.host if http_request.client else 'unknown'}"
    retry_after = login_throttle.blocked(throttle_key)
    if retry_after:
        raise HTTPException(status_code=429, detail="too many setup attempts; retry later", headers={"Retry-After": str(retry_after)})
    secret = os.getenv("NETLAB_BOOTSTRAP_TOKEN", "")
    if not secret:
        raise HTTPException(status_code=503, detail="initial setup is disabled; configure NETLAB_BOOTSTRAP_TOKEN")
    if not hmac.compare_digest(request.bootstrap_token, secret):
        login_throttle.failure(throttle_key)
        raise HTTPException(status_code=403, detail="invalid setup token")
    try:
        user = store.bootstrap_teacher(
            request.email, request.display_name, request.password,
            os.getenv("NETLAB_BOOTSTRAP_ROLE", "teacher"),
        )
    except EducationError as exc:
        status = 409 if "already exists" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    login_throttle.success(throttle_key)
    csrf = _set_session(response, user["id"])
    return {"user": user, "csrf_token": csrf}


@router.post("/auth/invitations/accept")
def accept_invitation(request: AcceptInvitationRequest, response: Response) -> dict[str, Any]:
    try:
        user = store.accept_invitation(request.token, request.password)
    except EducationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    csrf = _set_session(response, user["id"])
    return {"user": user, "csrf_token": csrf}


@router.post("/auth/password/reset")
def reset_password(request: ResetPasswordRequest) -> dict[str, bool]:
    try:
        store.reset_password(request.token, request.new_password)
    except EducationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/execution/workers/register")
def register_remote_worker(
    request: WorkerRegistrationRequest,
    teacher: dict[str, str] = Depends(require_teacher),
) -> dict[str, Any]:
    try:
        worker = store.register_worker(request.worker_id, request.worker_name, request.capabilities)
    except EducationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"worker": worker}


@router.post("/execution/workers/{worker_id}/heartbeat")
def remote_worker_heartbeat(
    worker_id: str,
    teacher: dict[str, str] = Depends(require_teacher),
) -> dict[str, Any]:
    try:
        return {"worker": store.register_worker(worker_id, worker_id)}
    except EducationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/execution/workers")
def list_remote_workers(
    teacher: dict[str, str] = Depends(require_teacher),
) -> dict[str, Any]:
    return {"workers": store.workers()}


@router.post("/execution/jobs", status_code=201)
def enqueue_worker_job(
    request: WorkerJobRequest,
    teacher: dict[str, str] = Depends(require_teacher),
) -> dict[str, Any]:
    try:
        job = store.enqueue_job(
            request.topology,
            request.action,
            request.node_name,
            request.command,
            request.max_attempts,
        )
    except (EducationError, netlab.TopologyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job": job}


@router.get("/execution/jobs/{job_id}")
def get_worker_job(
    job_id: str,
    teacher: dict[str, str] = Depends(require_teacher),
) -> dict[str, Any]:
    try:
        return {"job": store.job(job_id)}
    except EducationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/execution/metrics")
def get_execution_metrics(
    limit: int = 500,
    teacher: dict[str, str] = Depends(require_teacher),
) -> dict[str, Any]:
    return {"metrics": store.execution_metrics(limit)}


@router.get("/execution/alerts")
def get_execution_alerts(
    limit: int = 500,
    teacher: dict[str, str] = Depends(require_teacher),
) -> dict[str, Any]:
    return {"alerts": store.alerts(limit)}


@router.post("/auth/login")
def login(request: LoginRequest, response: Response, http_request: Request) -> dict[str, Any]:
    client_ip = http_request.client.host if http_request.client else "unknown"
    throttle_key = f"login:{client_ip}"
    persistent_keys = [f"ip:{client_ip}", f"email:{request.email.strip().lower()}"]
    retry_after = (
        store.login_throttle_remaining(persistent_keys)
        if production_mode()
        else login_throttle.blocked(throttle_key)
    )
    if retry_after:
        raise HTTPException(status_code=429, detail="too many login attempts; retry later", headers={"Retry-After": str(retry_after)})
    user = store.authenticate(request.email, request.password)
    if not user:
        if production_mode():
            store.record_login_failure(persistent_keys)
        else:
            login_throttle.failure(throttle_key)
        raise HTTPException(status_code=401, detail="invalid email or password")
    if production_mode():
        store.clear_login_failures(persistent_keys)
    else:
        login_throttle.success(throttle_key)
    csrf = _set_session(response, user["id"])
    return {"user": user, "csrf_token": csrf}


@router.post("/auth/logout")
def logout(request: Request, response: Response, user: dict[str, str] = Depends(require_user)) -> dict[str, bool]:
    store.revoke_session(request.cookies.get(SESSION_COOKIE))
    _clear_session(response)
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict[str, str] = Depends(require_user)) -> dict[str, Any]:
    return {"user": user}


@router.post("/auth/password")
def change_password(request: ChangePasswordRequest, user: dict[str, str] = Depends(require_user)) -> dict[str, bool]:
    try:
        store.change_password(user["id"], request.current_password, request.new_password)
    except EducationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "reauthentication_required": True}


@router.get("/education/users")
def list_users(user: dict[str, str] = Depends(require_teacher)) -> dict[str, Any]:
    return {"users": store.list_users()}


@router.post("/education/users", status_code=201)
def create_student(request: CreateStudentRequest, teacher: dict[str, str] = Depends(require_teacher)) -> dict[str, Any]:
    try:
        return {"user": store.create_user(request.email, request.display_name, request.password, "student")}
    except EducationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/education/teachers", status_code=201)
def create_teacher(request: CreateStudentRequest, teacher: dict[str, str] = Depends(require_teacher)) -> dict[str, Any]:
    try:
        return {"user": store.create_user(request.email, request.display_name, request.password, "teacher")}
    except EducationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/education/invitations", status_code=201)
def create_invitation(
    request: InvitationRequest,
    teacher: dict[str, str] = Depends(require_teacher),
) -> dict[str, Any]:
    if request.role == "teacher" and teacher["role"] != "admin":
        raise HTTPException(status_code=403, detail="administrator role required to invite teachers")
    try:
        invitation, token = store.issue_invitation(
            teacher["id"], request.email, request.display_name, request.role, request.group_id,
        )
    except EducationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"invitation": invitation, "token": token, "expires_in": INVITATION_TTL_SECONDS}


@router.post("/education/users/{user_id}/password-reset")
def issue_password_reset(
    user_id: str,
    teacher: dict[str, str] = Depends(require_teacher),
) -> dict[str, Any]:
    try:
        token = store.issue_password_reset(user_id, teacher["id"], teacher["role"])
    except EducationError as exc:
        message = str(exc)
        status = 404 if message == "user not found" else 403 if "administrator role" in message or "your groups" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc
    return {"token": token, "expires_in": PASSWORD_RESET_TTL_SECONDS}


@router.get("/education/groups")
def list_groups(user: dict[str, str] = Depends(require_user)) -> dict[str, Any]:
    return {"groups": store.list_groups(user)}


@router.post("/education/groups", status_code=201)
def create_group(request: GroupRequest, teacher: dict[str, str] = Depends(require_teacher)) -> dict[str, Any]:
    try:
        return {"group": store.create_group(teacher["id"], request.name)}
    except EducationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/education/groups/{group_id}/members", status_code=201)
def add_group_member(group_id: str, request: AddMemberRequest, teacher: dict[str, str] = Depends(require_teacher)) -> dict[str, bool]:
    try:
        store.add_member(teacher["id"], group_id, request.email)
    except EducationError as exc:
        raise HTTPException(status_code=404 if str(exc) == "group not found" else 400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/education/groups/{group_id}/assignments", status_code=201)
def create_assignment(group_id: str, request: AssignmentRequest, teacher: dict[str, str] = Depends(require_teacher)) -> dict[str, Any]:
    try:
        assignment = store.create_assignment(
            teacher["id"], group_id, request.title, request.topology,
            request.instructions, request.criteria,
        )
    except EducationError as exc:
        raise HTTPException(status_code=404 if str(exc) == "group not found" else 400, detail=str(exc)) from exc
    return {"assignment": assignment}


@router.get("/education/groups/{group_id}/submissions")
def group_submissions(group_id: str, teacher: dict[str, str] = Depends(require_teacher)) -> dict[str, Any]:
    try:
        return {"submissions": store.submissions(teacher["id"], group_id)}
    except EducationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/education/assignments/{assignment_id}/students/{student_id}/submissions")
def student_submission_history(
    assignment_id: str,
    student_id: str,
    teacher: dict[str, str] = Depends(require_teacher),
) -> dict[str, Any]:
    try:
        return {"submissions": store.submission_history_for_teacher(teacher["id"], assignment_id, student_id)}
    except EducationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/education/assignments/{assignment_id}/students/{student_id}/submissions/{submission_id}/feedback")
def review_student_submission(
    assignment_id: str,
    student_id: str,
    submission_id: str,
    request: SubmissionFeedbackRequest,
    teacher: dict[str, str] = Depends(require_teacher),
) -> dict[str, bool]:
    try:
        store.review_submission(
            teacher["id"], assignment_id, student_id, submission_id, request.feedback, request.grade,
        )
    except EducationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/education/my-assignments")
def my_assignments(student: dict[str, str] = Depends(require_user)) -> dict[str, Any]:
    if student["role"] != "student":
        raise HTTPException(status_code=403, detail="student role required")
    return {"assignments": store.assignments_for_student(student["id"])}


@router.post("/education/my-assignments/{assignment_id}/clone")
def clone_assignment(assignment_id: str, student: dict[str, str] = Depends(require_user)) -> dict[str, Any]:
    if student["role"] != "student":
        raise HTTPException(status_code=403, detail="student role required")
    try:
        return {"topology": store.clone_for_student(student["id"], assignment_id)}
    except EducationError as exc:
        status = 404 if str(exc) == "assignment not found" else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/education/my-assignments/{assignment_id}/reset")
def reset_assignment_laboratory(
    assignment_id: str,
    student: dict[str, str] = Depends(require_user),
) -> dict[str, Any]:
    if student["role"] != "student":
        raise HTTPException(status_code=403, detail="student role required")
    try:
        laboratory = store.student_laboratory(student["id"], assignment_id)
        if laboratory:
            from .main import build_orchestrator

            result = build_orchestrator(laboratory["topology"]).action("down")
            if not result.ok:
                raise HTTPException(
                    status_code=502,
                    detail=f"student laboratory cleanup failed (exit {result.exit_code})",
                )
        topology = store.reset_student_laboratory(student["id"], assignment_id)
    except EducationError as exc:
        raise HTTPException(status_code=404 if str(exc) == "assignment not found" else 409, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"topology": topology}


@router.put("/education/my-assignments/{assignment_id}/topology")
def save_assignment_topology(assignment_id: str, request: SaveTopologyRequest, student: dict[str, str] = Depends(require_user)) -> dict[str, bool]:
    if student["role"] != "student":
        raise HTTPException(status_code=403, detail="student role required")
    try:
        store.save_student_topology(student["id"], assignment_id, request.topology)
    except EducationError as exc:
        raise HTTPException(status_code=404 if str(exc) == "assignment not found" else 400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/education/my-assignments/{assignment_id}/submit")
def submit_assignment(assignment_id: str, student: dict[str, str] = Depends(require_user)) -> dict[str, bool]:
    if student["role"] != "student":
        raise HTTPException(status_code=403, detail="student role required")
    try:
        store.submit_assignment(student["id"], assignment_id)
    except EducationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/education/my-assignments/{assignment_id}/submissions")
def my_submission_history(
    assignment_id: str,
    student: dict[str, str] = Depends(require_user),
) -> dict[str, Any]:
    if student["role"] != "student":
        raise HTTPException(status_code=403, detail="student role required")
    try:
        return {"submissions": store.submission_history_for_student(student["id"], assignment_id)}
    except EducationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def authenticate_websocket(cookie: str | None) -> dict[str, str] | None:
    return store.session_user(cookie)
