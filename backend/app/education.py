from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

import netlab

SESSION_COOKIE = "netlab_session"
CSRF_COOKIE = "netlab_csrf"
SESSION_TTL_SECONDS = 12 * 60 * 60
PASSWORD_ITERATIONS = 310_000


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


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class EducationError(ValueError):
    pass


class EducationStore:
    """SQLite store for local prototype accounts and educational assignments."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

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
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_hash TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS groups (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    teacher_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at REAL NOT NULL,
                    UNIQUE(teacher_id, name)
                );
                CREATE TABLE IF NOT EXISTS group_members (
                    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    added_at REAL NOT NULL,
                    PRIMARY KEY (group_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS assignments (
                    id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                    created_by TEXT NOT NULL REFERENCES users(id),
                    title TEXT NOT NULL,
                    topology_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS student_labs (
                    assignment_id TEXT NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    topology_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'assigned' CHECK (status IN ('assigned', 'in_progress', 'submitted')),
                    updated_at REAL NOT NULL,
                    submitted_at REAL,
                    PRIMARY KEY (assignment_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_groups_teacher ON groups(teacher_id);
                CREATE INDEX IF NOT EXISTS idx_members_user ON group_members(user_id);
                CREATE INDEX IF NOT EXISTS idx_assignments_group ON assignments(group_id);
                """
            )

    def user_count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def bootstrap_teacher(self, email: str, display_name: str, password: str) -> dict[str, str]:
        email = _email(email)
        display_name = display_name.strip()
        if not display_name or len(display_name) > 100:
            raise EducationError("display name must contain 1 to 100 characters")
        password = _password(password)
        user = {"id": str(uuid.uuid4()), "email": email, "display_name": display_name, "role": "teacher"}
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                    raise EducationError("initial teacher account already exists")
                db.execute(
                    "INSERT INTO users(id,email,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)",
                    (user["id"], email, display_name, hash_password(password), "teacher", time.time()),
                )
        except sqlite3.IntegrityError as exc:
            raise EducationError("an account with this email already exists") from exc
        return user

    def create_user(self, email: str, display_name: str, password: str, role: str) -> dict[str, str]:
        email = _email(email)
        display_name = display_name.strip()
        if not display_name or len(display_name) > 100:
            raise EducationError("display name must contain 1 to 100 characters")
        password = _password(password)
        if role not in {"teacher", "student"}:
            raise EducationError("role must be teacher or student")
        user = {"id": str(uuid.uuid4()), "email": email, "display_name": display_name, "role": role}
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO users(id,email,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)",
                    (user["id"], email, display_name, hash_password(password), role, time.time()),
                )
        except sqlite3.IntegrityError as exc:
            raise EducationError("an account with this email already exists") from exc
        return user

    def authenticate(self, email: str, password: str) -> dict[str, str] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            return None
        return self.public_user(row)

    @staticmethod
    def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, str]:
        return {key: str(row[key]) for key in ("id", "email", "display_name", "role")}

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

    def change_password(self, user_id: str, old_password: str, new_password: str) -> None:
        new_password = _password(new_password)
        with self._connect() as db:
            row = db.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
            if not row or not verify_password(old_password, row["password_hash"]):
                raise EducationError("current password is incorrect")
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), user_id))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

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
        except sqlite3.IntegrityError as exc:
            raise EducationError("a group with this name already exists") from exc
        return {"id": group_id, "name": name, "teacher_id": teacher_id, "members": 0}

    def list_groups(self, user: dict[str, str]) -> list[dict[str, Any]]:
        with self._connect() as db:
            if user["role"] == "teacher":
                rows = db.execute(
                    "SELECT g.id,g.name,g.teacher_id,COUNT(m.user_id) AS members FROM groups g "
                    "LEFT JOIN group_members m ON m.group_id=g.id WHERE g.teacher_id=? GROUP BY g.id ORDER BY g.name",
                    (user["id"],),
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
            group = db.execute("SELECT id FROM groups WHERE id=? AND teacher_id=?", (group_id, teacher_id)).fetchone()
            user = db.execute("SELECT id,role FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
            if not group:
                raise EducationError("group not found")
            if not user or user["role"] != "student":
                raise EducationError("student account not found")
            try:
                db.execute("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (group_id, user["id"], time.time()))
            except sqlite3.IntegrityError as exc:
                raise EducationError("student is already in this group") from exc
            db.execute(
                "INSERT INTO student_labs(assignment_id,user_id,topology_json,status,updated_at) "
                "SELECT a.id,?,a.topology_json,'assigned',? FROM assignments a WHERE a.group_id=? "
                "AND NOT EXISTS (SELECT 1 FROM student_labs sl WHERE sl.assignment_id=a.id AND sl.user_id=?)",
                (user["id"], time.time(), group_id, user["id"]),
            )

    def create_assignment(self, teacher_id: str, group_id: str, title: str, topology: dict[str, Any]) -> dict[str, Any]:
        title = title.strip()
        if not title or len(title) > 120:
            raise EducationError("assignment title must contain 1 to 120 characters")
        try:
            netlab.validate_topology(topology)
        except (netlab.TopologyError, TypeError, KeyError) as exc:
            raise EducationError(f"invalid topology: {exc}") from exc
        assignment_id = str(uuid.uuid4())
        created_at = time.time()
        snapshot = json.dumps(topology, separators=(",", ":"), ensure_ascii=False)
        with self._connect() as db:
            group = db.execute("SELECT id FROM groups WHERE id=? AND teacher_id=?", (group_id, teacher_id)).fetchone()
            if not group:
                raise EducationError("group not found")
            db.execute(
                "INSERT INTO assignments(id,group_id,created_by,title,topology_json,created_at) VALUES(?,?,?,?,?,?)",
                (assignment_id, group_id, teacher_id, title, snapshot, created_at),
            )
            db.execute(
                "INSERT INTO student_labs(assignment_id,user_id,topology_json,status,updated_at) "
                "SELECT ?,user_id,?,'assigned',? FROM group_members WHERE group_id=?",
                (assignment_id, snapshot, created_at, group_id),
            )
        return {"id": assignment_id, "group_id": group_id, "title": title, "created_at": created_at}

    def assignments_for_student(self, student_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT a.id,a.title,a.created_at,g.name AS group_name,sl.status,sl.topology_json,sl.submitted_at "
                "FROM student_labs sl JOIN assignments a ON a.id=sl.assignment_id JOIN groups g ON g.id=a.group_id "
                "WHERE sl.user_id=? ORDER BY a.created_at DESC",
                (student_id,),
            )
            return [self._assignment_result(row, include_topology=True) for row in rows]

    @staticmethod
    def _assignment_result(row: sqlite3.Row, include_topology: bool = False) -> dict[str, Any]:
        result = {key: row[key] for key in ("id", "title", "created_at", "group_name", "status", "submitted_at")}
        if include_topology:
            result["topology"] = json.loads(row["topology_json"])
        return result

    def clone_for_student(self, student_id: str, assignment_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT a.topology_json FROM student_labs sl JOIN assignments a ON a.id=sl.assignment_id "
                "WHERE sl.assignment_id=? AND sl.user_id=?",
                (assignment_id, student_id),
            ).fetchone()
            if not row:
                raise EducationError("assignment not found")
            topology = json.loads(row["topology_json"])
            topology["lab"] = f"{topology['lab']}-student-{student_id[:8]}"
            snapshot = json.dumps(topology, separators=(",", ":"), ensure_ascii=False)
            db.execute(
                "UPDATE student_labs SET topology_json=?,status='in_progress',updated_at=?,submitted_at=NULL "
                "WHERE assignment_id=? AND user_id=?",
                (snapshot, time.time(), assignment_id, student_id),
            )
            return topology

    def save_student_topology(self, student_id: str, assignment_id: str, topology: dict[str, Any]) -> None:
        try:
            netlab.validate_topology(topology)
        except (netlab.TopologyError, TypeError, KeyError) as exc:
            raise EducationError(f"invalid topology: {exc}") from exc
        with self._connect() as db:
            result = db.execute(
                "UPDATE student_labs SET topology_json=?,status='in_progress',updated_at=?,submitted_at=NULL "
                "WHERE assignment_id=? AND user_id=?",
                (json.dumps(topology, separators=(",", ":"), ensure_ascii=False), time.time(), assignment_id, student_id),
            )
            if result.rowcount == 0:
                raise EducationError("assignment not found")

    def submit_assignment(self, student_id: str, assignment_id: str) -> None:
        with self._connect() as db:
            result = db.execute(
                "UPDATE student_labs SET status='submitted',submitted_at=?,updated_at=? WHERE assignment_id=? AND user_id=?",
                (time.time(), time.time(), assignment_id, student_id),
            )
            if result.rowcount == 0:
                raise EducationError("assignment not found")

    def submissions(self, teacher_id: str, group_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            group = db.execute("SELECT id FROM groups WHERE id=? AND teacher_id=?", (group_id, teacher_id)).fetchone()
            if not group:
                raise EducationError("group not found")
            return [dict(row) for row in db.execute(
                "SELECT a.id AS assignment_id,a.title,u.email,u.display_name,sl.status,sl.updated_at,sl.submitted_at "
                "FROM assignments a JOIN student_labs sl ON sl.assignment_id=a.id JOIN users u ON u.id=sl.user_id "
                "WHERE a.group_id=? ORDER BY a.created_at DESC,u.display_name COLLATE NOCASE",
                (group_id,),
            )]


_DEFAULT_DB = Path(os.getenv("NETLAB_DATA_DIR", Path(__file__).resolve().parents[2] / ".netlab-data")) / "education.sqlite3"
store = EducationStore(Path(os.getenv("NETLAB_EDUCATION_DB", _DEFAULT_DB)))
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


class GroupRequest(BaseModel):
    name: str


class AddMemberRequest(BaseModel):
    email: str


class AssignmentRequest(BaseModel):
    title: str
    topology: dict[str, Any]


class SaveTopologyRequest(BaseModel):
    topology: dict[str, Any]


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
    if user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="teacher role required")
    return user


def _set_session(response: Response, user_id: str) -> str:
    token, csrf = store.create_session(user_id)
    secure = os.getenv("NETLAB_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure, samesite="strict", max_age=SESSION_TTL_SECONDS, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=secure, samesite="strict", max_age=SESSION_TTL_SECONDS, path="/")
    return csrf


def _clear_session(response: Response) -> None:
    secure = os.getenv("NETLAB_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=secure, samesite="strict", path="/")
    response.delete_cookie(CSRF_COOKIE, httponly=False, secure=secure, samesite="strict", path="/")


@router.get("/auth/state")
def auth_state() -> dict[str, Any]:
    return {"has_users": store.user_count() > 0, "bootstrap_enabled": bool(os.getenv("NETLAB_BOOTSTRAP_TOKEN"))}


@router.post("/auth/bootstrap")
def bootstrap(request: BootstrapRequest, response: Response) -> dict[str, Any]:
    secret = os.getenv("NETLAB_BOOTSTRAP_TOKEN", "")
    if not secret:
        raise HTTPException(status_code=503, detail="initial setup is disabled; configure NETLAB_BOOTSTRAP_TOKEN")
    if not hmac.compare_digest(request.bootstrap_token, secret):
        raise HTTPException(status_code=403, detail="invalid setup token")
    try:
        user = store.bootstrap_teacher(request.email, request.display_name, request.password)
    except EducationError as exc:
        status = 409 if "already exists" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    csrf = _set_session(response, user["id"])
    return {"user": user, "csrf_token": csrf}


@router.post("/auth/login")
def login(request: LoginRequest, response: Response) -> dict[str, Any]:
    user = store.authenticate(request.email, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="invalid email or password")
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
        assignment = store.create_assignment(teacher["id"], group_id, request.title, request.topology)
    except EducationError as exc:
        raise HTTPException(status_code=404 if str(exc) == "group not found" else 400, detail=str(exc)) from exc
    return {"assignment": assignment}


@router.get("/education/groups/{group_id}/submissions")
def group_submissions(group_id: str, teacher: dict[str, str] = Depends(require_teacher)) -> dict[str, Any]:
    try:
        return {"submissions": store.submissions(teacher["id"], group_id)}
    except EducationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


def authenticate_websocket(cookie: str | None) -> dict[str, str] | None:
    return store.session_user(cookie)
