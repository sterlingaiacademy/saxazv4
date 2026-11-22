import os
os.environ["PYTHONUTF8"] = "1"

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, FileResponse
from routers import auth, admin, student, parent, tts
import contextlib

import threading
import shutil
import time

_db_sync_lock = threading.Lock()
PERSISTENT_DB_PATH = os.environ.get("PERSISTENT_DB_PATH") or "/data/edusafari_v4.db"

def _sync_tmp_db_to_gcs(target_path=None):
    """Safely snapshots /tmp/edusafari.db to a local staging file in /tmp with DELETE journal mode,
    then writes it sequentially to GCSFuse (/data) so GCSFuse never encounters random-offset .db-shm writes.
    """
    import sqlite3, shutil
    target_path = target_path or PERSISTENT_DB_PATH
    with _db_sync_lock:
        stage_path = "/tmp/edusafari_stage.db"
        src = sqlite3.connect("/tmp/edusafari.db", timeout=10.0)
        dst = sqlite3.connect(stage_path, timeout=10.0)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        stage_conn = sqlite3.connect(stage_path, timeout=10.0)
        try:
            stage_conn.execute("PRAGMA journal_mode=DELETE;")
            stage_conn.commit()
        finally:
            stage_conn.close()
        shutil.copyfile(stage_path, target_path)


def db_sync_worker():
    """Background worker that safely syncs the in-memory DB to the persistent volume every 10s.
    Also creates hourly snapshots in /data/backups/ to prevent catastrophic data loss.
    """
    import datetime
    while True:
        time.sleep(10)
        try:
            if os.path.exists("/tmp/edusafari.db"):
                _sync_tmp_db_to_gcs(PERSISTENT_DB_PATH)
                
                # Hourly snapshots (retain latest 48 hourly backups)
                now = datetime.datetime.now()
                backup_dir = "/data/backups"
                os.makedirs(backup_dir, exist_ok=True)
                hourly_backup = os.path.join(backup_dir, f"edusafari_v4_{now.strftime('%Y%m%d_%H')}.db")
                if not os.path.exists(hourly_backup) and os.path.exists("/tmp/edusafari_stage.db"):
                    shutil.copyfile("/tmp/edusafari_stage.db", hourly_backup)
                    try:
                        backups = sorted(
                            [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.startswith("edusafari_v4_") and f.endswith(".db")]
                        )
                        for old_bak in backups[:-48]:
                            os.remove(old_bak)
                    except Exception:
                        pass
                    
        except Exception as e:
            print(f"Error syncing DB: {e}")

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    if os.environ.get("K_SERVICE"):
        # Clean up any stale WAL/SHM files on GCSFuse mount that cause OutOfOrderError
        for stale_ext in ("-shm", "-wal"):
            stale_file = f"{PERSISTENT_DB_PATH}{stale_ext}"
            if os.path.exists(stale_file):
                try:
                    os.remove(stale_file)
                except Exception:
                    pass

        # Load the DB from Cloud Storage into ultra-fast Memory (/tmp) first before opening with SQLite
        needs_seed = False
        if not os.path.exists(PERSISTENT_DB_PATH):
            needs_seed = True
        else:
            try:
                shutil.copyfile(PERSISTENT_DB_PATH, "/tmp/edusafari.db")
                import sqlite3
                conn = sqlite3.connect("/tmp/edusafari.db")
                try:
                    c = conn.cursor()
                    c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'")
                    if not c.fetchone():
                        needs_seed = True
                finally:
                    conn.close()
            except Exception as e:
                print(f"DB seed check error: {e}. Assuming DB is valid. NOT overwriting.")
                needs_seed = False

        if needs_seed:
            if os.path.exists("edusafari.db"):
                shutil.copyfile("edusafari.db", "/tmp/edusafari.db")
                _sync_tmp_db_to_gcs(PERSISTENT_DB_PATH)
                print(f"Seeded persistent volume ({PERSISTENT_DB_PATH}) with bundled edusafari.db")
            else:
                print("No bundled DB found. Bootstrapping schema from SQL migrations...")
                import sqlite3, glob
                conn = sqlite3.connect("/tmp/edusafari.db")
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=OFF")
                migration_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
                sql_files = sorted(glob.glob(os.path.join(migration_dir, "*.sql")))
                for sql_file in sql_files:
                    try:
                        with open(sql_file, "r") as f:
                            conn.executescript(f.read())
                        print(f"Applied migration: {os.path.basename(sql_file)}")
                    except Exception as e:
                        print(f"Migration error ({os.path.basename(sql_file)}): {e}")
                conn.commit()
                conn.close()
                _sync_tmp_db_to_gcs(PERSISTENT_DB_PATH)
                print("Schema bootstrapped successfully from migrations.")

        if os.path.exists("media"):
            def _copy_if_missing(src, dst, *, follow_symlinks=True):
                if not os.path.exists(dst):
                    shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
            shutil.copytree("media", "/data/media", dirs_exist_ok=True, copy_function=_copy_if_missing)
            print("Verified persistent media volume from bundled assets")
            
        # Start the background sync worker
        thread = threading.Thread(target=db_sync_worker, daemon=True)
        thread.start()

    # Run automatic migrations to ensure schema is up to date
    import database
    database.auto_migrate()

    # Initialize Google Gemini 3.8 Flash TTS (on-demand only; zero startup pre-warm)
    try:
        tts.init_gemini_tts()
    except Exception as e:
        print(f"[TTS] Warning initializing Gemini TTS: {e}")
    
    yield
    # SHUTDOWN (Graceful exit) — use safe sequential staged sync
    if os.environ.get("K_SERVICE"):
        try:
            if os.path.exists("/tmp/edusafari.db"):
                _sync_tmp_db_to_gcs(PERSISTENT_DB_PATH)
                print("Final DB sync complete on shutdown.")
        except Exception as e:
            print(f"Error on final sync: {e}")

app = FastAPI(title="SAXAZ Studio (V2)", lifespan=lifespan)

if os.environ.get("K_SERVICE"):
    MEDIA_DIR = "/data/media"
else:
    MEDIA_DIR = "media"

if not os.environ.get("VERCEL"):
    os.makedirs("static/uploads/profiles", exist_ok=True)
    os.makedirs(MEDIA_DIR, exist_ok=True)
else:
    import database
    try:
        database.auto_migrate()
    except Exception as _mig_err:
        print(f"Vercel auto_migrate notice: {_mig_err}")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
templates = Jinja2Templates(directory="templates")

import json
import re

def parse_json_filter(value):
    if not value: return []
    if isinstance(value, (list, dict)): return value
    try: 
        # Clean trailing commas which JSON parser hates
        cleaned = re.sub(r',\s*([\]}])', r'\1', str(value))
        return json.loads(cleaned)
    except Exception as e: 
        print(f"Error parsing json in template: {e} for value: {value}")
        return []
templates.env.filters['parse_json'] = parse_json_filter

@app.middleware("http")
async def add_cache_control_header(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Include routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(student.router)
app.include_router(parent.router)
app.include_router(tts.router)


@app.get('/manifest.json', include_in_schema=False)
async def pwa_manifest():
    return FileResponse("static/manifest.json", media_type="application/manifest+json")


@app.get('/sw.js', include_in_schema=False)
async def pwa_service_worker():
    return FileResponse(
        "static/sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"}
    )


@app.get('/landing')
async def landing_page(request: Request):
    from database import get_db_connection
    from security import get_current_user
    conn = get_db_connection()
    user = None
    try:
        user = get_current_user(request, conn)
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="landing.html", context={"request": request, "user": user})


@app.get('/')
async def root(request: Request):
    from database import get_db_connection
    from security import get_current_user
    conn = get_db_connection()
    try:
        user = get_current_user(request, conn)
        if user:
            if user.get('is_parent'):
                return RedirectResponse(url="/parent/dashboard")
            elif user.get('role') == 'admin':
                return RedirectResponse(url="/admin/dashboard")
            else:
                return RedirectResponse(url="/student/dashboard")
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="landing.html", context={"request": request, "user": None})
