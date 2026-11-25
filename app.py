"""単語帳 — JLPT N1 flashcards with spaced repetition.

Cards live as JSON files in content/ (one file per class day). On every start
the app syncs those files into the database, so adding a new file and pushing
to GitHub is all it takes to publish new cards (Railway redeploys on push).
Review progress and settings live only in the database.
"""
import json
import os
import secrets
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import (JSON, Column, Float, Integer, MetaData, String, Table, Text,
                        create_engine, select)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

BASE = Path(__file__).parent
CONTENT_DIR = BASE / "content"

app = Flask(__name__)
app.permanent_session_lifetime = timedelta(days=365)
app.config.update(SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=bool(os.environ.get("RAILWAY_ENVIRONMENT")))

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

db_url = os.environ.get("DATABASE_URL", f"sqlite:///{BASE / 'local.db'}")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
engine = create_engine(db_url, pool_pre_ping=True)
IS_PG = engine.dialect.name == "postgresql"

meta = MetaData()
cards = Table(
    "cards", meta,
    Column("id", String(40), primary_key=True),
    Column("type", String(16), nullable=False),
    Column("day", Integer, nullable=False, default=0),
    Column("ord", Integer, nullable=False, default=0),
    Column("front", Text, nullable=False),
    Column("reading", Text),
    Column("meaning", Text),
    Column("example", Text),
    Column("example_es", Text),
    Column("examples", JSON),
    Column("note", Text),
)
reviews = Table(
    "reviews", meta,
    Column("card_id", String(40), primary_key=True),
    Column("state", String(10), nullable=False),
    Column("due", String(10), nullable=False),
    Column("ivl", Integer, nullable=False, default=0),
    Column("ease", Float, nullable=False, default=2.5),
    Column("reps", Integer, nullable=False, default=0),
    Column("lapses", Integer, nullable=False, default=0),
    Column("first", String(10)),
    Column("last", String(10)),
)
settings = Table(
    "settings", meta,
    Column("key", String(40), primary_key=True),
    Column("value", Text),
)


def upsert(conn, table, row, key):
    ins = (pg_insert if IS_PG else sqlite_insert)(table).values(**row)
    conn.execute(ins.on_conflict_do_update(
        index_elements=[key], set_={k: v for k, v in row.items() if k != key}))


def sync_content():
    """Load every content/*.json file into the cards table (insert or update)."""
    n = 0
    with engine.begin() as conn:
        for path in sorted(CONTENT_DIR.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for c in data.get("cards", []):
                if not c.get("id") or not c.get("front"):
                    continue
                upsert(conn, cards, {
                    "id": c["id"], "type": c.get("type", "vocab"),
                    "day": int(c.get("day") or data.get("day") or 0),
                    "ord": int(c.get("order") or 0), "front": c["front"],
                    "reading": c.get("reading"), "meaning": c.get("meaning"),
                    "example": c.get("example"), "example_es": c.get("exampleEs"),
                    "examples": c.get("examples") or [], "note": c.get("note"),
                }, "id")
                n += 1
    return n


def get_setting(key):
    with engine.connect() as conn:
        r = conn.execute(select(settings.c.value).where(settings.c.key == key)).first()
    return r[0] if r else None


def set_setting(key, value):
    with engine.begin() as conn:
        upsert(conn, settings, {"key": key, "value": value}, "key")


meta.create_all(engine)
print(f"[tangocho] db={engine.dialect.name} · synced {sync_content()} cards from content/")

# Session key: env var if given, otherwise one generated once and kept in the database.
_sk = os.environ.get("SECRET_KEY") or get_setting("secret_key")
if not _sk:
    _sk = secrets.token_hex(32)
    set_setting("secret_key", _sk)
    _sk = get_setting("secret_key") or _sk
app.secret_key = _sk


def password_hash():
    return get_setting("password_hash")


def needs_setup():
    return not APP_PASSWORD and not password_hash()


@app.before_request
def force_https():
    # Railway terminates TLS and forwards the original scheme in X-Forwarded-Proto.
    if request.headers.get("X-Forwarded-Proto", "https") == "http":
        return redirect(request.url.replace("http://", "https://", 1), code=301)


@app.after_request
def security_headers(resp):
    if request.headers.get("X-Forwarded-Proto") == "https":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    return resp


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("ok"):
            if request.path.startswith("/api/"):
                return jsonify(error="login"), 401
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    setup = needs_setup()
    if request.method == "POST":
        pw = request.form.get("password", "")
        if setup:
            if len(pw) < 8:
                error = "Usa al menos 8 caracteres."
            elif pw != request.form.get("password2", ""):
                error = "Las contraseñas no coinciden."
            else:
                set_setting("password_hash", generate_password_hash(pw))
                session.permanent = True
                session["ok"] = True
                return redirect(url_for("index"))
        else:
            ok = (APP_PASSWORD and secrets.compare_digest(pw, APP_PASSWORD)) or \
                 (password_hash() and check_password_hash(password_hash(), pw))
            if ok:
                session.permanent = True
                session["ok"] = True
                return redirect(url_for("index"))
            error = "Contraseña incorrecta."
    return render_template("login.html", error=error, setup=setup)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.get("/api/state")
@login_required
def api_state():
    with engine.connect() as conn:
        cs = [dict(r._mapping) for r in conn.execute(select(cards).order_by(cards.c.day, cards.c.ord, cards.c.id))]
        rs = {r.card_id: {k: v for k, v in r._mapping.items() if k != "card_id"}
              for r in conn.execute(select(reviews))}
        st = {r.key: r.value for r in conn.execute(select(settings))}
    out = []
    for c in cs:
        out.append({"id": c["id"], "type": c["type"], "day": c["day"], "order": c["ord"],
                    "front": c["front"], "reading": c["reading"], "meaning": c["meaning"],
                    "example": c["example"], "exampleEs": c["example_es"],
                    "examples": c["examples"] or [], "note": c["note"]})
    return jsonify(cards=out, srs=rs, settings={"newPerDay": int(st.get("newPerDay", 15))})


@app.post("/api/review")
@login_required
def api_review():
    d = request.get_json(force=True) or {}
    cid, s = d.get("card_id"), d.get("state") or {}
    if not cid or s.get("state") not in ("learn", "review") or not s.get("due"):
        return jsonify(error="bad request"), 400
    row = {"card_id": str(cid)[:40], "state": s["state"], "due": str(s["due"])[:10],
           "ivl": int(s.get("ivl", 0)), "ease": float(s.get("ease", 2.5)),
           "reps": int(s.get("reps", 0)), "lapses": int(s.get("lapses", 0)),
           "first": str(s.get("first", ""))[:10], "last": str(s.get("last", ""))[:10]}
    with engine.begin() as conn:
        upsert(conn, reviews, row, "card_id")
    return jsonify(ok=True)


@app.post("/api/settings")
@login_required
def api_settings():
    d = request.get_json(force=True) or {}
    v = max(1, min(60, int(d.get("newPerDay", 15))))
    with engine.begin() as conn:
        upsert(conn, settings, {"key": "newPerDay", "value": str(v)}, "key")
    return jsonify(ok=True, newPerDay=v)


@app.get("/health")
def health():
    return "ok"


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
