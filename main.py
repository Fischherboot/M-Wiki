"""
M-WIKI – Internes Wiki | Moritzsoft
FastAPI + SQLite + Jinja2

Konfiguration in daten.json:
    - wiki_title : Titel auf der Startseite
    - session_secret : Cookie-Signing-Secret (wird beim ersten Start generiert)
    - users : Liste {username, password} im Klartext (von außen nicht einsehbar)
"""

from __future__ import annotations

import html as html_lib
import json
import re
import secrets
import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote as url_quote

import markdown as md_lib
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

# ---------------------------------------------------------------------------
# Pfade & Konfiguration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.resolve()
DATEN_FILE = BASE_DIR / "daten.json"
DB_FILE = BASE_DIR / "wiki.db"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_IMAGE_DIM = 2000          # Bilder über 2000px werden runterskaliert
MAX_TITLE_LEN = 200
MAX_CONTENT_LEN = 200_000     # 200 KB pro Topic – mehr als genug
MAX_COMMENT_LEN = 10_000
MAX_CATEGORY_NAME_LEN = 100

# Mobile User-Agent Erkennung (klassisch, simpel, "good enough")
MOBILE_UA_RE = re.compile(
    r"Mobi|Android|iPhone|iPod|BlackBerry|IEMobile|Opera Mini|webOS",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("mwiki")


# ---------------------------------------------------------------------------
# daten.json
# ---------------------------------------------------------------------------


def _default_daten() -> dict:
    return {
        "wiki_title": "Moritzsoft Wiki",
        "session_secret": secrets.token_urlsafe(48),
        "users": [{"username": "moritz", "password": "123"}],
    }


def load_daten() -> dict:
    if not DATEN_FILE.exists():
        data = _default_daten()
        DATEN_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        log.warning("daten.json wurde mit Defaults erstellt – BITTE Passwort ändern!")
        return data

    data = json.loads(DATEN_FILE.read_text(encoding="utf-8"))

    # Felder auto-ergänzen, falls fehlen
    changed = False
    if "wiki_title" not in data:
        data["wiki_title"] = "Moritzsoft Wiki"
        changed = True
    if (
        "session_secret" not in data
        or not data["session_secret"]
        or data["session_secret"].startswith("BITTE")
    ):
        data["session_secret"] = secrets.token_urlsafe(48)
        changed = True
        log.warning("session_secret in daten.json wurde neu generiert.")
    if "users" not in data or not data["users"]:
        data["users"] = [{"username": "moritz", "password": "123"}]
        changed = True

    if changed:
        DATEN_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    return data


DATEN = load_daten()


def verify_login(username: str, password: str) -> bool:
    for u in DATEN.get("users", []):
        if u.get("username") == username and u.get("password") == password:
            return True
    return False


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_id) REFERENCES categories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL DEFAULT '',
    category_id INTEGER,
    author TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
    author TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    original_name TEXT,
    topic_id INTEGER,
    uploaded_by TEXT,
    uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_topics_category ON topics(category_id);
CREATE INDEX IF NOT EXISTS idx_topics_title_lower ON topics(LOWER(title));
CREATE INDEX IF NOT EXISTS idx_comments_topic ON comments(topic_id);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
"""


def init_db() -> None:
    with sqlite3.connect(DB_FILE) as con:
        # WAL mode = bessere Concurrency (parallele Reads während Write)
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(SCHEMA)
    log.info("Datenbank initialisiert: %s", DB_FILE)


@contextmanager
def db():
    con = sqlite3.connect(DB_FILE, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


init_db()


# ---------------------------------------------------------------------------
# Markdown + Wikilinks
# ---------------------------------------------------------------------------

WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")


def render_markdown(text: str) -> str:
    """Markdown rendern + [[Wikilinks]] in <a>-Tags konvertieren.

    Wikilink-Target und Anzeigetext werden HTML-escaped, damit
    [[Foo|<script>alert(1)</script>]] kein XSS auslöst.
    """
    if not text:
        return ""

    # Topic-Map für Wikilinks
    with db() as con:
        rows = con.execute("SELECT id, title FROM topics").fetchall()
    title_to_id = {r["title"].lower(): r["id"] for r in rows}

    def replace_wikilink(match: re.Match) -> str:
        target_raw = match.group(1).strip()
        display_raw = (match.group(2) or target_raw).strip()
        # IMMER escapen – User-Input darf nicht roh ins HTML
        display = html_lib.escape(display_raw)
        target_url = url_quote(target_raw, safe="")
        tid = title_to_id.get(target_raw.lower())
        if tid is not None:
            return f'<a class="wikilink" href="/topic/{tid}">{display}</a>'
        # Fehlender Link – rot markiert
        return (
            f'<a class="wikilink broken" '
            f'href="/topic/new?title={target_url}" title="Topic existiert nicht">'
            f"{display}</a>"
        )

    # Wikilinks vor Markdown ersetzen (sonst stört Markdown das)
    text = WIKILINK_RE.sub(replace_wikilink, text)

    html = md_lib.markdown(
        text,
        extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
        output_format="html5",
    )
    return html


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(title="M-WIKI", docs_url=None, redoc_url=None, openapi_url=None)


# ---- Security Headers Middleware ------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Setzt grundlegende Sicherheits-Header für alle Responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), interest-cohort=()",
        )
        # Lockere CSP: Inline-Styles/Scripts werden gebraucht, Fonts von Google.
        # Bilder kommen von /uploads (same-origin) und data:/blob:.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "base-uri 'self';",
        )
        return response


# ---- Mobile Auto-Redirect Middleware --------------------------------------

class MobileRedirectMiddleware(BaseHTTPMiddleware):
    """
    Leitet Mobile-User auf der Startseite "/" automatisch nach "/app/" um –
    außer es wurde explizit Desktop bevorzugt (Cookie `prefer_desktop=1`
    oder Query-Param `?d=1`).
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        if path == "/" and method == "GET":
            # Wenn ?d=1 gesetzt: Cookie speichern und auf "/" ohne Param redirecten
            if request.query_params.get("d") == "1":
                resp = RedirectResponse(url="/", status_code=302)
                resp.set_cookie(
                    "prefer_desktop", "1",
                    max_age=60 * 60 * 24 * 365, samesite="lax", httponly=False,
                )
                return resp

            ua = request.headers.get("user-agent", "")
            prefer_desktop = request.cookies.get("prefer_desktop") == "1"
            if MOBILE_UA_RE.search(ua) and not prefer_desktop:
                return RedirectResponse(url="/app/", status_code=302)

        return await call_next(request)


# Reihenfolge der Middleware: zuletzt hinzugefügt = außen (LIFO).
# Wir wollen: Mobile-Redirect (außen) -> Security -> Session (innen)
app.add_middleware(
    SessionMiddleware,
    secret_key=DATEN["session_secret"],
    session_cookie="mwiki_session",
    https_only=False,  # bei reinem HTTPS hinter Proxy auf True setzen
    same_site="lax",
    max_age=60 * 60 * 24 * 30,  # 30 Tage
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(MobileRedirectMiddleware)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["wiki_title"] = lambda: DATEN.get("wiki_title", "Wiki")


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def current_user(request: Request) -> Optional[str]:
    return request.session.get("user")


def require_user(request: Request) -> str:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login erforderlich")
    return user


def login_redirect(request: Request) -> Optional[RedirectResponse]:
    """Gibt Redirect zurück, wenn nicht eingeloggt."""
    if not current_user(request):
        nxt = url_quote(request.url.path, safe="/")
        return RedirectResponse(url=f"/login?next={nxt}", status_code=303)
    return None


def is_safe_next_url(url: str) -> bool:
    """Verhindert Open-Redirect via ?next=... – nur relative Pfade ohne //."""
    if not url:
        return False
    if not url.startswith("/"):
        return False
    if url.startswith("//"):
        return False
    return True


def get_category_tree() -> dict:
    """Hierarchischer Kategorien-Baum für Sidebar."""
    with db() as con:
        cats = [dict(r) for r in con.execute(
            "SELECT id, name, parent_id FROM categories "
            "ORDER BY name COLLATE NOCASE"
        ).fetchall()]
        topics_per_cat: dict = {}
        for r in con.execute(
            "SELECT id, title, category_id FROM topics "
            "ORDER BY title COLLATE NOCASE"
        ).fetchall():
            topics_per_cat.setdefault(r["category_id"], []).append(
                {"id": r["id"], "title": r["title"]}
            )

    by_id = {
        c["id"]: {**c, "children": [], "topics": topics_per_cat.get(c["id"], [])}
        for c in cats
    }
    roots = []
    for c in by_id.values():
        if c["parent_id"] and c["parent_id"] in by_id:
            by_id[c["parent_id"]]["children"].append(c)
        else:
            roots.append(c)

    # Uncategorized Topics
    uncat = topics_per_cat.get(None, [])
    return {"roots": roots, "uncategorized": uncat}


def base_context(request: Request, **extra) -> dict:
    """Standard-Kontext für alle Templates."""
    ctx = {
        "request": request,
        "user": current_user(request),
        "wiki_title": DATEN.get("wiki_title", "Wiki"),
        "tree": get_category_tree(),
    }
    ctx.update(extra)
    return ctx


# ---------------------------------------------------------------------------
# Auth Routen
# ---------------------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/"):
    if not is_safe_next_url(next):
        next = "/"
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "wiki_title": DATEN.get("wiki_title", "Wiki"),
            "next": next,
            "error": None,
        },
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    if not is_safe_next_url(next):
        next = "/"

    if verify_login(username.strip(), password):
        request.session["user"] = username.strip()
        log.info("Login: %s", username)
        return RedirectResponse(url=next or "/", status_code=303)

    log.warning("Login fehlgeschlagen: %s", username)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "wiki_title": DATEN.get("wiki_title", "Wiki"),
            "next": next,
            "error": "Falscher Benutzername oder Passwort.",
        },
        status_code=401,
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ---------------------------------------------------------------------------
# Index & Topics
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if (r := login_redirect(request)):
        return r

    with db() as con:
        topic_count = con.execute("SELECT COUNT(*) AS c FROM topics").fetchone()["c"]
        cat_count = con.execute("SELECT COUNT(*) AS c FROM categories").fetchone()["c"]
        recent = [dict(r) for r in con.execute(
            "SELECT id, title, updated_at FROM topics "
            "ORDER BY updated_at DESC LIMIT 12"
        ).fetchall()]

    return templates.TemplateResponse(
        request,
        "index.html",
        base_context(
            request,
            topic_count=topic_count,
            cat_count=cat_count,
            recent=recent,
        ),
    )


@app.get("/topic/new", response_class=HTMLResponse)
async def topic_new_form(request: Request, title: str = ""):
    if (r := login_redirect(request)):
        return r

    with db() as con:
        cats = [dict(r) for r in con.execute(
            "SELECT id, name FROM categories ORDER BY name COLLATE NOCASE"
        ).fetchall()]

    title = title[:MAX_TITLE_LEN]
    return templates.TemplateResponse(
        request,
        "edit.html",
        base_context(
            request,
            topic={"id": None, "title": title, "content": "", "category_id": None},
            cats=cats,
            mode="new",
        ),
    )


@app.post("/topic/new")
async def topic_create(
    request: Request,
    title: str = Form(...),
    content: str = Form(""),
    category_id: Optional[str] = Form(None),
):
    user = require_user(request)
    title = title.strip()[:MAX_TITLE_LEN]
    if not title:
        raise HTTPException(400, "Titel darf nicht leer sein")
    if len(content) > MAX_CONTENT_LEN:
        raise HTTPException(400, f"Inhalt zu lang (max {MAX_CONTENT_LEN} Zeichen).")

    cat_id = int(category_id) if category_id and category_id.isdigit() else None
    try:
        with db() as con:
            cur = con.execute(
                "INSERT INTO topics (title, content, category_id, author) "
                "VALUES (?, ?, ?, ?)",
                (title, content, cat_id, user),
            )
            tid = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"Topic mit Titel '{title}' existiert bereits.")

    log.info("Topic erstellt: %s (#%d) von %s", title, tid, user)
    return RedirectResponse(url=f"/topic/{tid}", status_code=303)


@app.get("/topic/{tid}", response_class=HTMLResponse)
async def topic_show(request: Request, tid: int):
    if (r := login_redirect(request)):
        return r

    with db() as con:
        topic = con.execute(
            "SELECT t.*, c.name AS category_name "
            "FROM topics t LEFT JOIN categories c ON t.category_id = c.id "
            "WHERE t.id = ?",
            (tid,),
        ).fetchone()
        if not topic:
            raise HTTPException(404, "Topic nicht gefunden")

        comments = [dict(r) for r in con.execute(
            "SELECT * FROM comments WHERE topic_id = ? ORDER BY created_at ASC",
            (tid,),
        ).fetchall()]

    rendered = render_markdown(topic["content"])

    return templates.TemplateResponse(
        request,
        "topic.html",
        base_context(
            request,
            topic=dict(topic),
            rendered=rendered,
            comments=comments,
        ),
    )


@app.get("/topic/{tid}/edit", response_class=HTMLResponse)
async def topic_edit_form(request: Request, tid: int):
    if (r := login_redirect(request)):
        return r

    with db() as con:
        topic = con.execute("SELECT * FROM topics WHERE id = ?", (tid,)).fetchone()
        if not topic:
            raise HTTPException(404, "Topic nicht gefunden")
        cats = [dict(r) for r in con.execute(
            "SELECT id, name FROM categories ORDER BY name COLLATE NOCASE"
        ).fetchall()]

    return templates.TemplateResponse(
        request,
        "edit.html",
        base_context(
            request,
            topic=dict(topic),
            cats=cats,
            mode="edit",
        ),
    )


@app.post("/topic/{tid}/edit")
async def topic_update(
    request: Request,
    tid: int,
    title: str = Form(...),
    content: str = Form(""),
    category_id: Optional[str] = Form(None),
):
    require_user(request)
    title = title.strip()[:MAX_TITLE_LEN]
    if not title:
        raise HTTPException(400, "Titel darf nicht leer sein")
    if len(content) > MAX_CONTENT_LEN:
        raise HTTPException(400, f"Inhalt zu lang (max {MAX_CONTENT_LEN} Zeichen).")

    cat_id = int(category_id) if category_id and category_id.isdigit() else None

    try:
        with db() as con:
            if not con.execute("SELECT 1 FROM topics WHERE id=?", (tid,)).fetchone():
                raise HTTPException(404, "Topic nicht gefunden")
            con.execute(
                "UPDATE topics SET title=?, content=?, category_id=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (title, content, cat_id, tid),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"Titel '{title}' existiert bereits.")

    log.info("Topic aktualisiert: %s (#%d)", title, tid)
    return RedirectResponse(url=f"/topic/{tid}", status_code=303)


@app.post("/topic/{tid}/delete")
async def topic_delete(request: Request, tid: int):
    require_user(request)
    with db() as con:
        con.execute("DELETE FROM topics WHERE id = ?", (tid,))
    log.info("Topic gelöscht: #%d", tid)
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# Kommentare
# ---------------------------------------------------------------------------


@app.post("/topic/{tid}/comment")
async def comment_add(
    request: Request,
    tid: int,
    content: str = Form(...),
):
    user = require_user(request)
    content = content.strip()[:MAX_COMMENT_LEN]
    if not content:
        raise HTTPException(400, "Kommentar darf nicht leer sein")
    with db() as con:
        # Existenz prüfen
        if not con.execute("SELECT 1 FROM topics WHERE id=?", (tid,)).fetchone():
            raise HTTPException(404, "Topic nicht gefunden")
        con.execute(
            "INSERT INTO comments (topic_id, author, content) VALUES (?, ?, ?)",
            (tid, user, content),
        )
    return RedirectResponse(url=f"/topic/{tid}#comments", status_code=303)


@app.post("/comment/{cid}/delete")
async def comment_delete(request: Request, cid: int):
    require_user(request)
    with db() as con:
        row = con.execute(
            "SELECT topic_id FROM comments WHERE id=?", (cid,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Kommentar nicht gefunden")
        con.execute("DELETE FROM comments WHERE id=?", (cid,))
    return RedirectResponse(url=f"/topic/{row['topic_id']}#comments", status_code=303)


# ---------------------------------------------------------------------------
# Kategorien
# ---------------------------------------------------------------------------


@app.get("/category/{cid}", response_class=HTMLResponse)
async def category_show(request: Request, cid: int):
    if (r := login_redirect(request)):
        return r

    with db() as con:
        cat = con.execute("SELECT * FROM categories WHERE id=?", (cid,)).fetchone()
        if not cat:
            raise HTTPException(404, "Kategorie nicht gefunden")
        topics = [dict(r) for r in con.execute(
            "SELECT id, title, updated_at FROM topics WHERE category_id=? "
            "ORDER BY title COLLATE NOCASE", (cid,),
        ).fetchall()]
        subcats = [dict(r) for r in con.execute(
            "SELECT id, name FROM categories WHERE parent_id=? "
            "ORDER BY name COLLATE NOCASE", (cid,),
        ).fetchall()]
        parent = None
        if cat["parent_id"]:
            parent_row = con.execute(
                "SELECT id, name FROM categories WHERE id=?", (cat["parent_id"],),
            ).fetchone()
            if parent_row:
                parent = dict(parent_row)

    return templates.TemplateResponse(
        request,
        "category.html",
        base_context(
            request,
            cat=dict(cat),
            topics=topics,
            subcats=subcats,
            parent=parent,
        ),
    )


@app.post("/category/new")
async def category_create(
    request: Request,
    name: str = Form(...),
    parent_id: Optional[str] = Form(None),
):
    require_user(request)
    name = name.strip()[:MAX_CATEGORY_NAME_LEN]
    if not name:
        raise HTTPException(400, "Name darf nicht leer sein")
    pid = int(parent_id) if parent_id and parent_id.isdigit() else None
    with db() as con:
        if pid is not None:
            # Existenz vom parent prüfen
            if not con.execute(
                "SELECT 1 FROM categories WHERE id=?", (pid,)
            ).fetchone():
                raise HTTPException(400, "Übergeordnete Kategorie existiert nicht.")
        cur = con.execute(
            "INSERT INTO categories (name, parent_id) VALUES (?, ?)",
            (name, pid),
        )
        cid = cur.lastrowid
    return RedirectResponse(url=f"/category/{cid}", status_code=303)


@app.post("/category/{cid}/edit")
async def category_rename(
    request: Request,
    cid: int,
    name: str = Form(...),
):
    require_user(request)
    name = name.strip()[:MAX_CATEGORY_NAME_LEN]
    if not name:
        raise HTTPException(400, "Name darf nicht leer sein")
    with db() as con:
        if not con.execute(
            "SELECT 1 FROM categories WHERE id=?", (cid,)
        ).fetchone():
            raise HTTPException(404, "Kategorie nicht gefunden")
        con.execute("UPDATE categories SET name=? WHERE id=?", (name, cid))
    return RedirectResponse(url=f"/category/{cid}", status_code=303)


@app.post("/category/{cid}/delete")
async def category_del(request: Request, cid: int):
    require_user(request)
    with db() as con:
        con.execute("DELETE FROM categories WHERE id=?", (cid,))
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# Suche
# ---------------------------------------------------------------------------


def _search_topics(q: str) -> list[dict]:
    q = q.strip()
    if not q:
        return []
    like = f"%{q}%"
    with db() as con:
        rows = con.execute(
            "SELECT id, title, "
            "  substr(content, max(1, instr(lower(content), lower(?)) - 40), 200) "
            "  AS snippet "
            "FROM topics WHERE title LIKE ? OR content LIKE ? "
            "ORDER BY title COLLATE NOCASE LIMIT 100",
            (q, like, like),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = ""):
    if (r := login_redirect(request)):
        return r

    results = _search_topics(q)
    return templates.TemplateResponse(
        request,
        "search.html",
        base_context(request, q=q.strip(), results=results),
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@app.post("/upload")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    topic_id: Optional[str] = Form(None),
):
    user = require_user(request)

    orig_name = Path(file.filename or "image").name
    ext = Path(orig_name).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(400, f"Erlaubt: {', '.join(sorted(ALLOWED_IMAGE_EXT))}")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            400, f"Datei zu groß (max {MAX_UPLOAD_BYTES // 1024 // 1024} MB)."
        )
    if not data:
        raise HTTPException(400, "Leere Datei.")

    new_name = (
        f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(6)}{ext}"
    )
    dest = UPLOAD_DIR / new_name
    dest.write_bytes(data)

    # Verifiziere dass es ein echtes Bild ist + ggf. resize
    try:
        with Image.open(dest) as im:
            im.verify()
        # nach verify() ist das Image-Objekt unbrauchbar -> neu öffnen
        with Image.open(dest) as im:
            im.load()
            w, h = im.size
            if max(w, h) > MAX_IMAGE_DIM:
                im.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))
                im.save(dest)
                log.info("Bild resized: %s (%dx%d)", new_name, w, h)
    except Exception as e:
        # Kein gültiges Bild -> Datei löschen und 400
        try:
            dest.unlink()
        except Exception:
            pass
        log.warning("Ungültige Bilddatei: %s (%s)", orig_name, e)
        raise HTTPException(400, "Datei ist kein gültiges Bild.")

    tid = int(topic_id) if topic_id and topic_id.isdigit() else None
    with db() as con:
        con.execute(
            "INSERT INTO images (filename, original_name, topic_id, uploaded_by) "
            "VALUES (?, ?, ?, ?)",
            (new_name, orig_name, tid, user),
        )

    return JSONResponse({"url": f"/uploads/{new_name}", "filename": new_name})


@app.get("/uploads/{filename}")
async def serve_upload(request: Request, filename: str):
    if not current_user(request):
        raise HTTPException(401)
    # Pfad-Traversal verhindern
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400)
    path = UPLOAD_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(
        path,
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ---------------------------------------------------------------------------
# API (für Autocomplete & mobile App)
# ---------------------------------------------------------------------------


@app.get("/api/topics")
async def api_topics(request: Request, q: str = ""):
    require_user(request)
    with db() as con:
        if q:
            like = f"%{q}%"
            rows = con.execute(
                "SELECT id, title FROM topics WHERE title LIKE ? "
                "ORDER BY title COLLATE NOCASE LIMIT 30",
                (like,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, title FROM topics ORDER BY title COLLATE NOCASE"
            ).fetchall()
    return [{"id": r["id"], "title": r["title"]} for r in rows]


@app.get("/api/tree")
async def api_tree(request: Request):
    require_user(request)
    return get_category_tree()


@app.get("/api/topic/{tid}")
async def api_topic(request: Request, tid: int):
    require_user(request)
    with db() as con:
        topic = con.execute(
            "SELECT t.*, c.name AS category_name "
            "FROM topics t LEFT JOIN categories c ON t.category_id = c.id "
            "WHERE t.id = ?",
            (tid,),
        ).fetchone()
        if not topic:
            raise HTTPException(404)
        comments = [dict(r) for r in con.execute(
            "SELECT * FROM comments WHERE topic_id=? ORDER BY created_at ASC",
            (tid,),
        ).fetchall()]
    d = dict(topic)
    d["rendered"] = render_markdown(d["content"])
    d["comments"] = comments
    return d


@app.get("/api/recent")
async def api_recent(request: Request, limit: int = 20):
    require_user(request)
    limit = max(1, min(50, limit))
    with db() as con:
        rows = con.execute(
            "SELECT id, title, updated_at FROM topics "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/search")
async def api_search(request: Request, q: str = ""):
    """Saubere Such-API – Mobile-App nutzt das statt HTML zu parsen."""
    require_user(request)
    results = _search_topics(q)
    return {"q": q.strip(), "count": len(results), "results": results}


# ---------------------------------------------------------------------------
# Mobile App
# ---------------------------------------------------------------------------


@app.get("/app", response_class=HTMLResponse)
@app.get("/app/", response_class=HTMLResponse)
async def mobile_app(request: Request):
    if not current_user(request):
        return RedirectResponse(url="/login?next=/app/", status_code=303)
    return templates.TemplateResponse(
        request,
        "app.html",
        {
            "request": request,
            "wiki_title": DATEN.get("wiki_title", "Wiki"),
            "user": current_user(request),
        },
    )


# ---------------------------------------------------------------------------
# Health & Favicon
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# Kleine SVG-Favicon inline – kein 404 mehr
_FAVICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    b'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0">'
    b'<stop offset="0%" stop-color="#8c52ff"/>'
    b'<stop offset="100%" stop-color="#ff914d"/></linearGradient></defs>'
    b'<rect width="64" height="64" rx="10" fill="#0a0a0c"/>'
    b'<text x="32" y="46" font-family="Georgia,serif" font-size="40" '
    b'font-weight="700" text-anchor="middle" fill="url(#g)">M</text></svg>'
)


@app.get("/favicon.ico")
@app.get("/favicon.svg")
async def favicon():
    return Response(
        content=_FAVICON_SVG,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ---------------------------------------------------------------------------
# Fehlerbehandlung
# ---------------------------------------------------------------------------


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    is_api = request.url.path.startswith("/api/")
    accept = request.headers.get("accept", "")
    wants_json = is_api or "application/json" in accept

    # 401 ohne JSON-Wunsch → Redirect zum Login
    if exc.status_code == 401 and not wants_json:
        nxt = url_quote(request.url.path, safe="/")
        return RedirectResponse(url=f"/login?next={nxt}", status_code=303)

    if wants_json:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    # HTML-Fehlerseite
    try:
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "request": request,
                "wiki_title": DATEN.get("wiki_title", "Wiki"),
                "user": current_user(request),
                "tree": get_category_tree(),
                "code": exc.status_code,
                "message": exc.detail,
            },
            status_code=exc.status_code,
        )
    except Exception:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled exception on %s: %s", request.url.path, exc)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "Interner Fehler"}, status_code=500)
    try:
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "request": request,
                "wiki_title": DATEN.get("wiki_title", "Wiki"),
                "user": current_user(request),
                "tree": {"roots": [], "uncategorized": []},
                "code": 500,
                "message": "Interner Fehler",
            },
            status_code=500,
        )
    except Exception:
        return JSONResponse({"error": "Interner Fehler"}, status_code=500)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=3503,
        log_level="info",
    )
