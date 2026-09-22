"""
Bijoy Devnath portfolio — backend API
--------------------------------------
Replaces the Firebase (Firestore + Auth) calls the frontend used to make
with a small self-hosted Flask + SQLite API.

Endpoints
  POST   /api/auth/login        -> { token, email }
  GET    /api/auth/me           -> { email }                     [auth]

  GET    /api/projects          -> [ {id,tag,title,desc,img,created_at}, ... ]
  POST   /api/projects          -> { id }                        [auth]
  DELETE /api/projects/<id>                                      [auth]

  GET    /api/services          -> [ {id,title,desc,created_at}, ... ]
  POST   /api/services          -> { id }                        [auth]
  DELETE /api/services/<id>                                      [auth]

  POST   /api/messages          -> { ok:true }        (contact form, public)
  GET    /api/messages          -> [ {...}, ... ]                [auth]
  DELETE /api/messages/<id>                                      [auth]

  GET    /api/settings          -> { sub, about, years, ... }
  PUT    /api/settings          -> merged settings               [auth]

  POST   /api/pageview          -> 204                (public, fire-and-forget)
  GET    /api/stats             -> { views, messages, projects, services } [auth]

Run locally:
    pip install -r requirements.txt
    cp .env.example .env        # then edit it
    python app.py
"""

import os
import json
import time
import secrets
import sqlite3
import datetime
import functools

import jwt
from flask import Flask, request, jsonify, g, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

# --------------------------------------------------------------------------
# Tiny built-in .env loader (no extra dependency needed for this alone).
# Only fills in vars that aren't already set in the real environment.
# --------------------------------------------------------------------------

def _load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "site.db")
FRONTEND_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "frontend"))

JWT_EXPIRY_DAYS = int(os.environ.get("JWT_EXPIRY_DAYS", "7"))

# JWT secret: use the one from .env if present, otherwise generate a random
# one for this process. If it's auto-generated, tokens stop working after a
# restart (the owner just has to log in again) - fine for a single-admin site,
# but set JWT_SECRET in .env for a stable production deploy.
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    JWT_SECRET = secrets.token_hex(32)
    print("[warn] JWT_SECRET not set in environment - using a random secret "
          "for this run. Set JWT_SECRET in .env so logins survive restarts.")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

app = Flask(__name__)

# --------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT, title TEXT NOT NULL, desc TEXT, img TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL, desc TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, email TEXT, message TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS page_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT,
    created_at TEXT NOT NULL
);
"""

DEFAULT_SERVICES = [
    {"title": "SEO Strategy", "desc": "A full roadmap built around your niche, competitors and search intent."},
    {"title": "Website SEO Audit", "desc": "A clear breakdown of what's holding your rankings back — and how to fix it."},
    {"title": "Keyword Research", "desc": "Finding the terms your customers actually search for, ranked by opportunity."},
    {"title": "On-Page SEO", "desc": "Structuring content, metadata and internal links for both users and search engines."},
    {"title": "Technical SEO", "desc": "Site speed, crawlability and indexing fixes that remove hidden ranking barriers."},
    {"title": "Google & Facebook Ads", "desc": "Campaigns built around a clear cost-per-result target, not just impressions."},
    {"title": "Digital Marketing Consultation", "desc": "A working session to map out your next quarter's marketing priorities."},
    {"title": "Digital Marketing Training", "desc": "Practical, project-based sessions for individuals or teams."},
    {"title": "Freelancing Guidance", "desc": "Positioning, pricing and platform strategy for freelancers starting out."},
]

DEFAULT_PROJECTS = [
    {"tag": "SEO · E-commerce", "title": "Organic Traffic Recovery", "desc": "A technical and on-page SEO overhaul to recover lost rankings after a site migration.", "img": "assets/result-1.jpg"},
    {"tag": "Google Ads · Lead Gen", "title": "Search Campaign Rebuild", "desc": "Restructured a lead-generation account around intent-based keyword groups.", "img": "assets/result-2.jpg"},
    {"tag": "Facebook Ads · Retail", "title": "Paid Social Funnel", "desc": "A three-stage funnel connecting awareness ads to retargeting and conversion.", "img": "assets/result-3.jpg"},
    {"tag": "Training · Freelancing", "title": "Freelancing Training Cohort", "desc": "A government-backed program guiding new freelancers toward their first paid orders.", "img": "assets/training-classroom-2.jpg"},
]

DEFAULT_SETTINGS = {
    "sub": "Digital Marketing Trainer & SEO Specialist",
    "about": "",
    "years": "4+",
    "projects": "1,900+",
    "rating": "4.9",
    "reviews": "232+",
    "email": "bijoydavnathofficial@gmail.com",
    "wa": "8801581565931",
}


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    # Seed / update the single admin account from env vars.
    if ADMIN_EMAIL and ADMIN_PASSWORD:
        existing = conn.execute("SELECT id FROM admin_users WHERE email = ?", (ADMIN_EMAIL,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO admin_users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (ADMIN_EMAIL, generate_password_hash(ADMIN_PASSWORD), now_iso()),
            )
            print(f"[info] Admin account created for {ADMIN_EMAIL}")
    elif conn.execute("SELECT COUNT(*) c FROM admin_users").fetchone()["c"] == 0:
        # No ADMIN_EMAIL/ADMIN_PASSWORD given and no admin exists yet - generate
        # one so the site is never left with a guessable default login.
        generated_pw = secrets.token_urlsafe(9)
        fallback_email = "admin@example.com"
        conn.execute(
            "INSERT INTO admin_users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (fallback_email, generate_password_hash(generated_pw), now_iso()),
        )
        print("=" * 66)
        print("[warn] No ADMIN_EMAIL / ADMIN_PASSWORD set - generated a login:")
        print(f"        email:    {fallback_email}")
        print(f"        password: {generated_pw}")
        print("       Set ADMIN_EMAIL / ADMIN_PASSWORD in .env instead, then")
        print("       delete backend/data/site.db and restart, so you control")
        print("       the real login.")
        print("=" * 66)

    if conn.execute("SELECT COUNT(*) c FROM services").fetchone()["c"] == 0:
        for s in DEFAULT_SERVICES:
            conn.execute(
                "INSERT INTO services (title, desc, created_at) VALUES (?, ?, ?)",
                (s["title"], s["desc"], now_iso()),
            )

    if conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"] == 0:
        for p in DEFAULT_PROJECTS:
            conn.execute(
                "INSERT INTO projects (tag, title, desc, img, created_at) VALUES (?, ?, ?, ?, ?)",
                (p["tag"], p["title"], p["desc"], p["img"], now_iso()),
            )

    if conn.execute("SELECT COUNT(*) c FROM settings WHERE key='site'").fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('site', ?)",
            (json.dumps(DEFAULT_SETTINGS),),
        )

    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# CORS (lets the frontend be hosted on a different origin than the API)
# --------------------------------------------------------------------------

@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return resp


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

_failed_attempts = {}  # key -> [timestamps]  (very small in-memory brute-force guard)
LOCK_THRESHOLD = 6
LOCK_WINDOW_SECONDS = 5 * 60


def create_token(row):
    payload = {
        "sub": row["id"],
        "email": row["email"],
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=JWT_EXPIRY_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def require_auth(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401
        token = auth_header.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Session expired, please log in again"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        g.admin = payload
        return fn(*args, **kwargs)
    return wrapper


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    key = f"{request.remote_addr}:{email}"
    attempts = [t for t in _failed_attempts.get(key, []) if time.time() - t < LOCK_WINDOW_SECONDS]
    if len(attempts) >= LOCK_THRESHOLD:
        return jsonify({"error": "Too many attempts. Try again in a few minutes."}), 429

    db = get_db()
    row = db.execute("SELECT * FROM admin_users WHERE email = ?", (email,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        attempts.append(time.time())
        _failed_attempts[key] = attempts
        return jsonify({"error": "Invalid email or password"}), 401

    _failed_attempts.pop(key, None)
    token = create_token(row)
    return jsonify({"token": token, "email": row["email"]})


@app.route("/api/auth/me")
@require_auth
def me():
    return jsonify({"email": g.admin["email"]})


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------

@app.route("/api/projects", methods=["GET"])
def list_projects():
    db = get_db()
    rows = db.execute("SELECT * FROM projects ORDER BY id ASC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/projects", methods=["POST"])
@require_auth
def add_project():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO projects (tag, title, desc, img, created_at) VALUES (?, ?, ?, ?, ?)",
        (data.get("tag", ""), title, data.get("desc", ""), data.get("img", ""), now_iso()),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.route("/api/projects/<int:pid>", methods=["DELETE"])
@require_auth
def delete_project(pid):
    db = get_db()
    db.execute("DELETE FROM projects WHERE id = ?", (pid,))
    db.commit()
    return ("", 204)


# --------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------

@app.route("/api/services", methods=["GET"])
def list_services():
    db = get_db()
    rows = db.execute("SELECT * FROM services ORDER BY id ASC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/services", methods=["POST"])
@require_auth
def add_service():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO services (title, desc, created_at) VALUES (?, ?, ?)",
        (title, data.get("desc", ""), now_iso()),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.route("/api/services/<int:sid>", methods=["DELETE"])
@require_auth
def delete_service(sid):
    db = get_db()
    db.execute("DELETE FROM services WHERE id = ?", (sid,))
    db.commit()
    return ("", 204)


# --------------------------------------------------------------------------
# Contact messages
# --------------------------------------------------------------------------

@app.route("/api/messages", methods=["POST"])
def submit_message():
    data = request.get_json(silent=True) or {}
    db = get_db()
    db.execute(
        "INSERT INTO messages (name, email, message, created_at) VALUES (?, ?, ?, ?)",
        ((data.get("name") or "").strip(), (data.get("email") or "").strip(),
         (data.get("message") or "").strip(), now_iso()),
    )
    db.commit()
    return jsonify({"ok": True}), 201


@app.route("/api/messages", methods=["GET"])
@require_auth
def list_messages():
    db = get_db()
    rows = db.execute("SELECT * FROM messages ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/messages/<int:mid>", methods=["DELETE"])
@require_auth
def delete_message(mid):
    db = get_db()
    db.execute("DELETE FROM messages WHERE id = ?", (mid,))
    db.commit()
    return ("", 204)


# --------------------------------------------------------------------------
# Settings (single row: site text/config)
# --------------------------------------------------------------------------

@app.route("/api/settings", methods=["GET"])
def get_settings():
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key = 'site'").fetchone()
    return jsonify(json.loads(row["value"]) if row else DEFAULT_SETTINGS)


@app.route("/api/settings", methods=["PUT"])
@require_auth
def update_settings():
    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key = 'site'").fetchone()
    merged = json.loads(row["value"]) if row else dict(DEFAULT_SETTINGS)
    merged.update({k: v for k, v in data.items() if v is not None})
    db.execute(
        "INSERT INTO settings (key, value) VALUES ('site', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps(merged),),
    )
    db.commit()
    return jsonify(merged)


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------

@app.route("/api/pageview", methods=["POST"])
def track_pageview():
    data = request.get_json(silent=True) or {}
    db = get_db()
    db.execute(
        "INSERT INTO page_views (path, created_at) VALUES (?, ?)",
        (data.get("path", "/"), now_iso()),
    )
    db.commit()
    return ("", 204)


@app.route("/api/stats", methods=["GET"])
@require_auth
def stats():
    db = get_db()

    def count(table):
        return db.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]

    return jsonify({
        "views": count("page_views"),
        "messages": count("messages"),
        "projects": count("projects"),
        "services": count("services"),
    })


# --------------------------------------------------------------------------
# Serve the frontend (handy for same-origin local/dev deploys; skip this and
# host the frontend elsewhere if you prefer a fully separate API)
# --------------------------------------------------------------------------

@app.route("/")
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>")
def serve_static(filename):
    return send_from_directory(FRONTEND_DIR, filename)


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
