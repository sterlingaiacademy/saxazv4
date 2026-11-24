import sqlite3
import os
import shutil
from contextlib import contextmanager

# If deployed in Cloud Run or Vercel Serverless, use /tmp for writable SQLite DB
if os.environ.get("K_SERVICE") or os.environ.get("VERCEL"):
    DB_PATH = "/tmp/edusafari.db"
    _bundled_db = os.path.join(os.path.dirname(__file__), "edusafari.db")
    if os.environ.get("VERCEL") and not os.path.exists(DB_PATH) and os.path.exists(_bundled_db):
        try:
            shutil.copyfile(_bundled_db, DB_PATH)
        except Exception as _e:
            print(f"Vercel DB bootstrap warning: {_e}")
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "edusafari.db")

_data_migrated = False

def get_db_connection():
  """Create and return a database connection with WAL mode enabled."""
  global _data_migrated
  conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10.0)
  conn.row_factory = sqlite3.Row
  # Enable WAL mode and busy_timeout for better concurrency
  conn.execute('PRAGMA journal_mode = WAL;')
  conn.execute('PRAGMA synchronous = NORMAL;')
  conn.execute('PRAGMA busy_timeout = 5000;')
  # Enforce foreign key constraints
  conn.execute('PRAGMA foreign_keys = ON;')
  if not _data_migrated:
    _data_migrated = True
    try:
      _ensure_data_migrations(conn)
    except Exception as _mig_err:
      print(f"Data migration warning: {_mig_err}")
  return conn

@contextmanager
def get_db():
  """Context manager for database connections."""
  conn = get_db_connection()
  try:
    yield conn
  finally:
    conn.close()

def auto_migrate():
    """Ensure newly added columns exist in the remote database."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Create notifications table if it doesn't exist
    c.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create subject_study_time table for live tracking of time spent per subject
    c.execute("""
        CREATE TABLE IF NOT EXISTS subject_study_time (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            seconds_studied INTEGER DEFAULT 0,
            last_active_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, subject_id)
        )
    """)
    
    # Add new columns to chapters table for intro page links
    for col_name, col_type in [
        ("video_description_url", "TEXT DEFAULT ''"),
        ("real_life_url", "TEXT DEFAULT ''"),
    ]:
        try:
            c.execute(f"ALTER TABLE chapters ADD COLUMN {col_name} {col_type}")
            print(f"Added column {col_name} to chapters")
        except Exception:
            pass  # Column already exists

    columns_to_add = [
        ("parent_locked", "INTEGER DEFAULT 0"),
        ("parent_pin", "TEXT DEFAULT ''"),
        ("parent_summary", "TEXT"),
        ("parent_summary_updated_at", "TEXT"),
        ("parent_mock_summary", "TEXT"),
        ("parent_real_summary", "TEXT"),
        ("brutality_level", "INTEGER DEFAULT 1"),
        ("tts_voice", "TEXT DEFAULT 'af_bella'"),
        ("tts_engine", "TEXT DEFAULT 'openai'"),
        ("tts_mode", "TEXT DEFAULT 'auto'"),
        ("tutor_lang", "TEXT DEFAULT 'en'"),
        ("sfx_enabled", "INTEGER DEFAULT 0"),
        ("sfx_mode", "INTEGER DEFAULT 0"),
        ("sfx_custom", "TEXT DEFAULT '{}'"),
        ("total_xp", "INTEGER DEFAULT 0"),
        ("coin_balance", "INTEGER DEFAULT 0"),
        ("cursor_mode", "INTEGER DEFAULT 1"),
        ("cursor_effect", "TEXT DEFAULT 'none'"),
        ("subject_intro_mode", "INTEGER DEFAULT 0"),
        ("game_prompt_mode", "TEXT DEFAULT 'always'"),
        # Enrolment form fields
        ("school", "TEXT"),
        ("chosen_class", "TEXT"),
        ("syllabus", "TEXT"),
        ("medium", "TEXT"),
        ("parent_name", "TEXT"),
        ("parent_phone", "TEXT"),
        ("parent_relationship", "TEXT"),
        ("parent_email", "TEXT"),
        ("country", "TEXT"),
        ("state", "TEXT"),
        ("district", "TEXT"),
        ("parent_tts_voice", "TEXT DEFAULT 'af_bella'"),
        ("parent_tts_engine", "TEXT DEFAULT 'openai'"),
        ("parent_tts_mode", "TEXT DEFAULT 'manual'"),
        ("parent_sfx_mode", "INTEGER DEFAULT 0"),
        ("parent_sfx_custom", "TEXT DEFAULT '{}'"),
        ("parent_cursor_mode", "INTEGER DEFAULT 1"),
        ("parent_cursor_effect", "TEXT DEFAULT 'none'"),
    ]
    
    # Also add is_parent to sessions table if it's somehow missing
    try:
        c.execute("ALTER TABLE sessions ADD COLUMN is_parent INTEGER DEFAULT 0")
        print("Added is_parent to sessions")
    except sqlite3.OperationalError as e:
        if "already exists" not in str(e).lower() and "duplicate column" not in str(e).lower():
            print(f"Migration warning (sessions): {e}")

    for col_name, col_type in columns_to_add:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            print(f"Added column {col_name}")
            
            # If it's a UI pref column, initialize it from the existing shared column
            if col_name in ["parent_sfx_mode", "parent_sfx_custom", "parent_cursor_mode", "parent_cursor_effect"]:
                base_col = col_name.replace("parent_", "")
                c.execute(f"UPDATE users SET {col_name} = {base_col}")
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e).lower() and "duplicate column" not in str(e).lower():
                print(f"Migration warning ({col_name}): {e}")
    
    # NOTE: Admin password is NOT auto-reset here.
    # To reset manually, run: python -c "import database; database.reset_admin_password('newpass')"
        
    # Ensure additional_videos column exists on content_items and questions
    for tbl in ['content_items', 'questions']:
        try:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN additional_videos TEXT DEFAULT '[]'")
            print(f"Added additional_videos to {tbl}")
        except Exception as e:
            if "already exists" not in str(e).lower() and "duplicate column" not in str(e).lower():
                print(f"Migration warning (additional_videos): {e}")

    # Ensure answer_media_url exists on questions table for model answer images
    try:
        c.execute("ALTER TABLE questions ADD COLUMN answer_media_url TEXT DEFAULT ''")
        print("Added answer_media_url to questions")
    except Exception as e:
        if "already exists" not in str(e).lower() and "duplicate column" not in str(e).lower():
            print(f"Migration warning (answer_media_url): {e}")

    # Ensure drawing_url exists on answers table for student attached drawings/rough work
    try:
        c.execute("ALTER TABLE answers ADD COLUMN drawing_url TEXT DEFAULT ''")
        print("Added drawing_url to answers")
    except Exception as e:
        if "already exists" not in str(e).lower() and "duplicate column" not in str(e).lower():
            print(f"Migration warning (drawing_url): {e}")

    # Ensure time_taken_seconds exists on attempts table for Mock & Real Exam completion timing
    try:
        c.execute("ALTER TABLE attempts ADD COLUMN time_taken_seconds INTEGER DEFAULT 0")
        print("Added time_taken_seconds to attempts")
    except Exception as e:
        if "already exists" not in str(e).lower() and "duplicate column" not in str(e).lower():
            print(f"Migration warning (time_taken_seconds): {e}")

    # Fix content_items type constraint to include youtube
    # SQLite doesn't support ALTER COLUMN, so we check the current schema
    try:
        c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='content_items'")
        schema = c.fetchone()
        if schema and "'youtube'" not in schema[0]:
            # Recreate the table with updated constraint while preserving all columns and FKs
            existing_cols = [r[1] for r in c.execute("PRAGMA table_info(content_items)").fetchall()]
            thumb_expr = "thumbnail_url" if "thumbnail_url" in existing_cols else "NULL"
            dur_expr = "duration_seconds" if "duration_seconds" in existing_cols else "NULL"
            add_vid_expr = "COALESCE(additional_videos, '[]')" if "additional_videos" in existing_cols else "'[]'"
            conn.execute("PRAGMA foreign_keys = OFF;")
            try:
                c.execute("""
                    CREATE TABLE IF NOT EXISTS content_items_new (
                        id INTEGER PRIMARY KEY,
                        chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
                        type TEXT NOT NULL CHECK(type IN ('video','audio','pdf','text','youtube','link')),
                        title TEXT NOT NULL,
                        thumbnail_url TEXT,
                        media_url TEXT,
                        duration_seconds INTEGER,
                        order_index INTEGER DEFAULT 0,
                        additional_videos TEXT DEFAULT '[]'
                    )
                """)
                c.execute(f"INSERT INTO content_items_new (id, chapter_id, type, title, thumbnail_url, media_url, duration_seconds, order_index, additional_videos) SELECT id, chapter_id, type, title, {thumb_expr}, media_url, {dur_expr}, order_index, {add_vid_expr} FROM content_items")
                c.execute("DROP TABLE content_items")
                c.execute("ALTER TABLE content_items_new RENAME TO content_items")
                conn.commit()
                print("Updated content_items CHECK constraint to include youtube/link types")
            finally:
                conn.execute("PRAGMA foreign_keys = ON;")
    except Exception as e:
        print(f"content_items constraint migration: {e}")

    # Fix users.class_id FK to allow setting null when class is deleted
    try:
        c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
        schema = c.fetchone()
        if schema and 'ON DELETE SET NULL' not in schema[0]:
            # Add class_id column update — we can't alter FK in SQLite,
            # but we ensure the column accepts NULL for safety
            c.execute("UPDATE users SET class_id = NULL WHERE class_id IS NOT NULL AND class_id NOT IN (SELECT id FROM classes)")
    except Exception as e:
        print(f"users class_id cleanup: {e}")

    # Purge expired or orphaned sessions
    try:
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        c.execute("DELETE FROM sessions WHERE expires_at < ? OR user_id NOT IN (SELECT id FROM users)", (now_iso,))
    except Exception:
        pass

    # Ensure user_exam_xp table and exam/question/answer columns exist on fresh bootstraps
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_exam_xp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            exam_paper_id INTEGER NOT NULL REFERENCES exam_papers(id) ON DELETE CASCADE,
            max_xp_awarded INTEGER DEFAULT 0,
            UNIQUE(student_id, exam_paper_id)
        )
    """)

    # Anti-farming one-time Coin Ledger & Shop Redemptions (5,000 Coins = Rs 50 INR)
    c.execute("""
        CREATE TABLE IF NOT EXISTS coin_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reward_key TEXT NOT NULL,
            coins INTEGER NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, reward_key)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS coin_redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            item_code TEXT NOT NULL,
            item_title TEXT NOT NULL,
            coins_spent INTEGER NOT NULL,
            inr_value INTEGER NOT NULL,
            coupon_code TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for tbl, col_name, col_type in [
        ("exam_papers", "use_mock_questions", "INTEGER DEFAULT 0"),
        ("exam_papers", "target_marks", "INTEGER"),
        ("exam_papers", "required_mock_percent", "REAL"),
        ("modules", "question_type", "TEXT DEFAULT 'LONG_ANSWER'"),
        ("questions", "options", "TEXT"),
        ("questions", "media_url", "TEXT"),
        ("questions", "explanation_video_url", "TEXT"),
        ("questions", "explanation_video_type", "TEXT"),
        ("questions", "question_type", "TEXT"),
        ("answers", "retry_count", "INTEGER DEFAULT 0"),
        ("answers", "is_latest", "INTEGER DEFAULT 1"),
    ]:
        try:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass
    
    # Create Digi Library tables (Books -> Subjects -> Question Banks -> Questions -> Attempts & Answers without marks)
    c.execute("""
        CREATE TABLE IF NOT EXISTS digi_books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER REFERENCES classes(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            thumbnail_url TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('draft','published')),
            order_index INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS digi_subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES digi_books(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            thumbnail_url TEXT DEFAULT '',
            order_index INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS digi_question_banks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL REFERENCES digi_subjects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('draft','published')),
            order_index INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS digi_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bank_id INTEGER NOT NULL REFERENCES digi_question_banks(id) ON DELETE CASCADE,
            section_name TEXT DEFAULT 'Questions',
            question_text TEXT NOT NULL,
            model_answer TEXT NOT NULL,
            options TEXT,
            question_type TEXT DEFAULT 'CUSTOM',
            media_url TEXT,
            answer_media_url TEXT DEFAULT '',
            explanation_video_url TEXT,
            explanation_video_type TEXT,
            additional_videos TEXT DEFAULT '[]',
            order_index INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS digi_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bank_id INTEGER NOT NULL REFERENCES digi_question_banks(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'in_progress' CHECK(status IN ('in_progress','completed')),
            correct_count INTEGER DEFAULT 0,
            total_questions INTEGER DEFAULT 0,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS digi_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id INTEGER NOT NULL REFERENCES digi_attempts(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES digi_questions(id) ON DELETE CASCADE,
            answer_text TEXT NOT NULL,
            is_correct INTEGER DEFAULT 0,
            ai_feedback TEXT,
            drawing_url TEXT DEFAULT '',
            retry_count INTEGER DEFAULT 0,
            is_latest INTEGER DEFAULT 1,
            submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Track AI Tutor usage during Mock Exams for Parent Portal transparency
    c.execute("""
        CREATE TABLE IF NOT EXISTS mock_exam_tutor_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            exam_paper_id INTEGER NOT NULL REFERENCES exam_papers(id) ON DELETE CASCADE,
            attempt_id INTEGER REFERENCES attempts(id) ON DELETE SET NULL,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            question_number INTEGER DEFAULT 1,
            module_name TEXT DEFAULT '',
            asked_before_submit INTEGER DEFAULT 1,
            user_message TEXT NOT NULL,
            ai_response TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Issues (magazine parts) a student has redeemed; Part 1 is always available
    c.execute("""
        CREATE TABLE IF NOT EXISTS student_issues (
            student_id INTEGER NOT NULL,
            part_no INTEGER NOT NULL,
            code TEXT,
            redeemed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (student_id, part_no)
        )
    """)

    # Strict chapter path (introduction > practice test > real exam); a restart starts the path again
    c.execute("""
        CREATE TABLE IF NOT EXISTS chapter_path (
            student_id INTEGER NOT NULL,
            chapter_id INTEGER NOT NULL,
            started_at TEXT,
            intro_done_at TEXT,
            mock_done_at TEXT,
            PRIMARY KEY (student_id, chapter_id)
        )
    """)
    try:
        if "mock_done_at" not in {r[1] for r in c.execute("PRAGMA table_info(chapter_path)").fetchall()}:
            c.execute("ALTER TABLE chapter_path ADD COLUMN mock_done_at TEXT")
    except Exception as e:
        print(f"chapter_path migration notice: {e}")

    # "Mock" exams are called "Practice Exam" for students (titles only; nothing else changes)
    try:
        c.execute("UPDATE exam_papers SET title = REPLACE(title, 'Mock Exam', 'Practice Exam') WHERE title LIKE '%Mock Exam%'")
        c.execute("UPDATE exam_papers SET title = REPLACE(title, 'Mock Test', 'Practice Exam') WHERE title LIKE '%Mock Test%'")
    except Exception as e:
        print(f"exam title rename notice: {e}")

    # MCQ "Why?" explanations: written once per question + choice, then reused (and their audio is saved once)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mcq_why_cache (
            cache_key TEXT PRIMARY KEY,
            question_id INTEGER,
            why TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Drop retired standalone tutor chat history tables if present
    c.execute("DROP TABLE IF EXISTS tutor_messages")
    c.execute("DROP TABLE IF EXISTS tutor_conversations")

    # Add performance indexes if they don't exist
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_answers_attempt ON answers(attempt_id)",
        "CREATE INDEX IF NOT EXISTS idx_attempts_student ON attempts(student_id)",
        "CREATE INDEX IF NOT EXISTS idx_attempts_exam ON attempts(exam_paper_id)",
        "CREATE INDEX IF NOT EXISTS idx_content_progress_student ON content_progress(student_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_users_class ON users(class_id)",
        "CREATE INDEX IF NOT EXISTS idx_module_results_attempt ON module_results(attempt_id)",
        "CREATE INDEX IF NOT EXISTS idx_daily_activity_user ON daily_activity(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_questions_module ON questions(module_id)",
        "CREATE INDEX IF NOT EXISTS idx_modules_exam ON modules(exam_paper_id)",
        "CREATE INDEX IF NOT EXISTS idx_chapters_subject ON chapters(subject_id)",
        "CREATE INDEX IF NOT EXISTS idx_subjects_class ON subjects(class_id)",
        "CREATE INDEX IF NOT EXISTS idx_content_items_chapter ON content_items(chapter_id)",
        "CREATE INDEX IF NOT EXISTS idx_exam_papers_chapter ON exam_papers(chapter_id)",
        "CREATE INDEX IF NOT EXISTS idx_answers_question ON answers(question_id)",
        "CREATE INDEX IF NOT EXISTS idx_digi_books_class ON digi_books(class_id)",
        "CREATE INDEX IF NOT EXISTS idx_digi_subjects_book ON digi_subjects(book_id)",
        "CREATE INDEX IF NOT EXISTS idx_digi_banks_subject ON digi_question_banks(subject_id)",
        "CREATE INDEX IF NOT EXISTS idx_digi_questions_bank ON digi_questions(bank_id)",
        "CREATE INDEX IF NOT EXISTS idx_digi_attempts_student ON digi_attempts(student_id)",
        "CREATE INDEX IF NOT EXISTS idx_digi_attempts_bank ON digi_attempts(bank_id)",
        "CREATE INDEX IF NOT EXISTS idx_digi_answers_attempt ON digi_answers(attempt_id)",
        "CREATE INDEX IF NOT EXISTS idx_digi_answers_question ON digi_answers(question_id)",
        "CREATE INDEX IF NOT EXISTS idx_mock_tutor_logs_student ON mock_exam_tutor_logs(student_id)",
        "CREATE INDEX IF NOT EXISTS idx_mock_tutor_logs_exam ON mock_exam_tutor_logs(exam_paper_id)",
        "CREATE INDEX IF NOT EXISTS idx_mock_tutor_logs_question ON mock_exam_tutor_logs(question_id)",
        "CREATE INDEX IF NOT EXISTS idx_mock_tutor_logs_attempt ON mock_exam_tutor_logs(attempt_id)",
    ]
    for idx_sql in indexes:
        try:
            c.execute(idx_sql)
        except Exception:
            pass

    # One-time data fix: standardize exam paper titles & Chapter 5 strict syllabus metadata
    try:
        # students see "Practice Exam" (not "Mock") everywhere
        c.execute("UPDATE exam_papers SET title = 'Practice Exam' WHERE title IN ('Mock Exam - 1', 'Mock Exam') AND chapter_id != 3")
        c.execute("UPDATE exam_papers SET title = REPLACE(title, 'Mock Exam — ', 'Practice Exam — ') WHERE title LIKE 'Mock Exam — %' AND chapter_id != 3")
        c.execute("UPDATE exam_papers SET title = REPLACE(title, 'Main Exam — ', 'Real Exam — ') WHERE title LIKE 'Main Exam — %' AND chapter_id != 3")
    except Exception:
        pass

    try:
        _ensure_data_migrations(conn)
    except Exception as _e:
        print(f"auto_migrate data seed warning: {_e}")

    conn.commit()
    conn.close()


def _extract_yt_id_simple(url: str) -> str:
    import re
    if not url:
        return ""
    m = re.search(r'(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/))([A-Za-z0-9_-]{11})', str(url))
    return m.group(1) if m else ""


def _ensure_data_migrations(conn):
    """Idempotent data migration for Class 10 Biology Chapter 5 playlist videos, thumbnails, textbook question order, and student dashboard seed data."""
    import datetime
    c = conn.cursor()

    # 0. Ensure textbook_order, textbook_section & is_hidden columns exist on questions and subjects, plus time_taken_seconds on attempts
    for col_sql in [
        "ALTER TABLE questions ADD COLUMN textbook_order INTEGER DEFAULT 0",
        "ALTER TABLE questions ADD COLUMN textbook_section TEXT DEFAULT ''",
        "ALTER TABLE questions ADD COLUMN is_hidden INTEGER DEFAULT 0",
        "ALTER TABLE subjects ADD COLUMN is_hidden INTEGER DEFAULT 0",
        "ALTER TABLE attempts ADD COLUMN time_taken_seconds INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN coin_balance INTEGER DEFAULT 0",
    ]:
        try:
            c.execute(col_sql)
        except Exception:
            pass
    try:
        c.execute("SELECT COUNT(*) FROM questions WHERE COALESCE(textbook_order, 0) = 0")
        if (c.fetchone()[0] or 0) > 0:
            from services.textbook_order_map import TEXTBOOK_ORDER_BY_QID
            c.executemany(
                "UPDATE questions SET textbook_order = ? WHERE id = ?",
                [(ord_idx, qid) for qid, ord_idx in TEXTBOOK_ORDER_BY_QID.items()],
            )
    except Exception as _ord_err:
        print(f"textbook_order migration warning: {_ord_err}")

    # 1. Class 10 Biology Chapter 5 (Life Processes, chapter_id=3) 4-Part Summary Playlist (PLZ89Lq0l8v6s)
    bio_ch5_videos = [
        (8, 3, 1, "Life Processes • Part 1: Chapter 5.1 Summary", "https://www.youtube.com/watch?v=KyI_RS3DZ1o", "https://i.ytimg.com/vi/KyI_RS3DZ1o/hqdefault.jpg", 285),
        (30, 3, 2, "Life Processes • Part 2: Chapter 5.2 Summary", "https://www.youtube.com/watch?v=M6x_Suq1i-w", "https://i.ytimg.com/vi/M6x_Suq1i-w/hqdefault.jpg", 275),
        (31, 3, 3, "Life Processes • Part 3: Chapter 5.3 Summary", "https://www.youtube.com/watch?v=0AiTscbhE5g", "https://i.ytimg.com/vi/0AiTscbhE5g/hqdefault.jpg", 279),
        (32, 3, 4, "Life Processes • Part 4: Chapter 5.4 Summary", "https://www.youtube.com/watch?v=WgUaxv5zyYY", "https://i.ytimg.com/vi/WgUaxv5zyYY/hqdefault.jpg", 304),
    ]
    for cid, ch_id, ord_idx, title, m_url, thumb_url, dur_sec in bio_ch5_videos:
        c.execute("SELECT id FROM content_items WHERE id = ?", (cid,))
        if c.fetchone():
            c.execute("""
                UPDATE content_items
                SET chapter_id = ?, type = 'youtube', title = ?, media_url = ?, thumbnail_url = ?, duration_seconds = ?, order_index = ?
                WHERE id = ?
            """, (ch_id, title, m_url, thumb_url, dur_sec, ord_idx, cid))
        else:
            c.execute("""
                INSERT INTO content_items (id, chapter_id, type, title, media_url, thumbnail_url, duration_seconds, order_index, additional_videos)
                VALUES (?, ?, 'youtube', ?, ?, ?, ?, ?, '[]')
            """, (cid, ch_id, title, m_url, thumb_url, dur_sec, ord_idx))

    c.execute("UPDATE chapters SET video_description_url = 'https://www.youtube.com/watch?v=KyI_RS3DZ1o', status = 'published' WHERE id = 3")
    # For the demo: keep ONLY Biology (id=5) and Chapter 5: Life Processes (id=3) visible; hide all other subjects & chapters while preserving their data
    c.execute("UPDATE subjects SET is_hidden = CASE WHEN id = 5 THEN 0 ELSE 1 END")
    c.execute("UPDATE chapters SET status = CASE WHEN id = 3 THEN 'published' ELSE 'draft' END")

    # 1b. Strict Verbatim Client Syllabus for Biology Chapter 5 (Mock Test 1, Mock Test 2, Mock Test 3, Real Exam)
    from services.bio_ch5_syllabus import (
        MOCK_TEST_1_MODULES, MOCK_TEST_1_QUESTIONS,
        MOCK_TEST_2_MODULES, MOCK_TEST_2_QUESTIONS,
        MOCK_TEST_3_MODULES, MOCK_TEST_3_QUESTIONS,
        REAL_EXAM_MODULES, REAL_EXAM_QUESTIONS,
    )

    ch5_papers = [
        # (id, chapter_id, type, title, unlock_pct, req_mock_pct, time_mins, status, max_attempts, use_mock_qs, target_marks)
        (13, 3, "mock", "Practice Exam 1", 100.0, None, None, "published", None, 0, 30),
        (45, 3, "mock", "Practice Exam 2", 100.0, None, None, "published", None, 0, 30),
        (46, 3, "mock", "Practice Exam 3", 100.0, None, None, "published", None, 0, 30),
        (14, 3, "real", "Real Exam", None, 100.0, 40, "published", 100, 0, 25),
    ]
    for ep_id, ch_id, ep_type, ep_title, unl_pct, req_mock_pct, t_mins, ep_st, max_att, use_mq, tgt_m in ch5_papers:
        c.execute("SELECT id FROM exam_papers WHERE id = ?", (ep_id,))
        if c.fetchone():
            c.execute(
                """
                UPDATE exam_papers
                SET chapter_id = ?, type = ?, title = ?, unlock_threshold_percent = ?, required_mock_percent = ?,
                    time_limit_minutes = ?, status = ?, max_attempts = ?, use_mock_questions = ?, target_marks = ?
                WHERE id = ?
                """,
                (ch_id, ep_type, ep_title, unl_pct, req_mock_pct, t_mins, ep_st, max_att, use_mq, tgt_m, ep_id),
            )
        else:
            c.execute(
                """
                INSERT INTO exam_papers (
                    id, chapter_id, type, title, unlock_threshold_percent, required_mock_percent,
                    time_limit_minutes, status, version, max_attempts, use_mock_questions, target_marks
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (ep_id, ch_id, ep_type, ep_title, unl_pct, req_mock_pct, t_mins, ep_st, max_att, use_mq, tgt_m),
            )

    all_ch5_modules = MOCK_TEST_1_MODULES + MOCK_TEST_2_MODULES + MOCK_TEST_3_MODULES + REAL_EXAM_MODULES
    for mod_id, ep_id, m_name, m_val, ord_i, t_lim, q_t in all_ch5_modules:
        c.execute("SELECT id FROM modules WHERE id = ?", (mod_id,))
        if c.fetchone():
            c.execute(
                """
                UPDATE modules
                SET exam_paper_id = ?, name = ?, mark_value = ?, order_index = ?, time_limit_seconds = ?, question_type = ?
                WHERE id = ?
                """,
                (ep_id, m_name, m_val, ord_i, t_lim, q_t, mod_id),
            )
        else:
            c.execute(
                """
                INSERT INTO modules (id, exam_paper_id, name, mark_value, order_index, time_limit_seconds, question_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (mod_id, ep_id, m_name, m_val, ord_i, t_lim, q_t),
            )

    all_ch5_questions = MOCK_TEST_1_QUESTIONS + MOCK_TEST_2_QUESTIONS + MOCK_TEST_3_QUESTIONS + REAL_EXAM_QUESTIONS
    strict_qids = [q[0] for q in all_ch5_questions]
    for q_id, mod_id, ord_i, tb_ord, max_m, q_t, q_txt, opts_j, mod_ans, ans_media in all_ch5_questions:
        c.execute("SELECT id FROM questions WHERE id = ?", (q_id,))
        if c.fetchone():
            c.execute(
                """
                UPDATE questions
                SET module_id = ?, question_text = ?, model_answer = ?, max_marks = ?, order_index = ?,
                    options = ?, explanation_video_url = '', explanation_video_type = '',
                    question_type = ?, additional_videos = '[]', answer_media_url = ?,
                    textbook_order = ?, textbook_section = 'Questions', is_hidden = 0
                WHERE id = ?
                """,
                (mod_id, q_txt, mod_ans, max_m, ord_i, opts_j, q_t, ans_media, tb_ord, q_id),
            )
        else:
            c.execute(
                """
                INSERT INTO questions (
                    id, module_id, question_text, model_answer, rubric_points, max_marks, order_index,
                    options, media_url, explanation_video_url, explanation_video_type,
                    question_type, additional_videos, answer_media_url, textbook_order, textbook_section, is_hidden
                )
                VALUES (?, ?, ?, ?, '[]', ?, ?, ?, NULL, '', '', ?, '[]', ?, ?, 'Questions', 0)
                """,
                (q_id, mod_id, q_txt, mod_ans, max_m, ord_i, opts_j, q_t, ans_media, tb_ord),
            )

    # Hide any legacy non-syllabus Chapter 5 questions so ONLY strict syllabus questions exist
    q_placeholders = ",".join(str(int(x)) for x in strict_qids)
    c.execute(f"""
        UPDATE questions
        SET is_hidden = CASE WHEN id IN ({q_placeholders}) THEN 0 ELSE 1 END
        WHERE module_id IN (SELECT id FROM modules WHERE exam_paper_id IN (13, 14, 45, 46))
    """)
    c.execute("""
        DELETE FROM answers
        WHERE question_id IN (SELECT id FROM questions WHERE COALESCE(is_hidden, 0) = 1)
    """)

    # 2. Populate thumbnail_url & duration_seconds for all YouTube content_items where missing
    c.execute("SELECT id, media_url, thumbnail_url, duration_seconds, order_index FROM content_items WHERE type IN ('youtube', 'video')")
    for row in c.fetchall():
        yt_id = _extract_yt_id_simple(row["media_url"] or "")
        new_thumb = row["thumbnail_url"] or (f"https://i.ytimg.com/vi/{yt_id}/hqdefault.jpg" if yt_id else None)
        new_dur = row["duration_seconds"] or (300 + ((row["order_index"] or 1) * 45))
        if new_thumb != row["thumbnail_url"] or new_dur != row["duration_seconds"]:
            c.execute("UPDATE content_items SET thumbnail_url = ?, duration_seconds = ? WHERE id = ?", (new_thumb, new_dur, row["id"]))

    # 3. Clean up broken 0.0/43 test attempt (269186039) for student nimesh (user_id=2)
    c.execute("DELETE FROM answers WHERE attempt_id = 269186039")
    c.execute("DELETE FROM attempts WHERE id = 269186039")
    c.execute("""
        DELETE FROM attempts
        WHERE student_id = 2
          AND COALESCE(total_marks_awarded, 0) = 0
          AND id NOT IN (SELECT DISTINCT attempt_id FROM answers WHERE marks_awarded > 0)
    """)

    # 4. Seed realistic, internally consistent student progress for user_id=2 (nimesh) if not yet seeded
    c.execute("SELECT id FROM users WHERE id = 2")
    if c.fetchone():
        ist_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
        ist_today = ist_now.date()

        def _dt_str(days_ago: int, hour: int = 16, minute: int = 30) -> str:
            d = ist_today - datetime.timedelta(days=days_ago)
            return f"{d.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}:00"

        # Seed completed video lessons in Physics (Ch 9), Biology (Ch 5), Chemistry (Ch 1), Mathematics (Ch 1)
        seed_cp = [
            (2, 1, 320, 100.0, 1, _dt_str(4, 15, 10)),
            (2, 24, 420, 100.0, 1, _dt_str(3, 16, 20)),
            (2, 25, 480, 100.0, 1, _dt_str(2, 17, 5)),
            (2, 8, 285, 100.0, 1, _dt_str(1, 18, 15)),
            (2, 30, 275, 100.0, 1, _dt_str(0, 9, 25)),
            (2, 7, 345, 100.0, 1, _dt_str(3, 18, 40)),
            (2, 36, 420, 100.0, 1, _dt_str(2, 19, 10)),
            (2, 10, 345, 100.0, 1, _dt_str(4, 17, 0)),
        ]
        for st_id, ci_id, prog_s, pct_c, comp, comp_at in seed_cp:
            c.execute("SELECT id FROM content_items WHERE id = ?", (ci_id,))
            if c.fetchone():
                c.execute("""
                    INSERT INTO content_progress (student_id, content_item_id, progress_seconds, percent_complete, completed, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(student_id, content_item_id) DO UPDATE SET
                        completed = 1,
                        percent_complete = 100.0,
                        completed_at = COALESCE(content_progress.completed_at, excluded.completed_at)
                """, (st_id, ci_id, prog_s, pct_c, comp, comp_at))

        # Seed 4 realistic exam attempts (1001..1004) with real question answers in Labour India textbook order (Q1..Q4)
        seed_attempts = [
            # (attempt_id, exam_paper_id, status, total_marks_awarded, total_max_marks, started_at, completed_at, answers_list)
            (
                1001, 17, "completed", 10.0, 13.0, _dt_str(4, 17, 15), _dt_str(4, 17, 42),
                [
                    (459, 35, "(i) 140 = 2^2 x 5 x 7, (ii) 156 = 2^2 x 3 x 13, (iii) 3825 = 3^2 x 5^2 x 17", 3.0, 100.0, "Spot on! All prime factorisations are written in canonical exponential form."),
                    (467, 36, "(i) LCM(26, 91) = 182, HCF = 13. Verification: 182 x 13 = 2366 = 26 x 91.", 4.0, 80.0, "Great verification on part (i) and (ii)! Include the full product check for (iii) as well."),
                    (460, 35, "12 = 2^2 x 3, 15 = 3 x 5, 21 = 3 x 7 -> HCF = 3, LCM = 420", 3.0, 100.0, "Full marks! Prime factorisation and LCM/HCF values are completely accurate."),
                    (453, 34, "LCM = 306 x 657 = 201042", 0.0, 0.0, "Remember to divide the product by HCF(306, 657) = 9: LCM = (306 x 657) / 9 = 22338."),
                ]
            ),
            (
                1002, 11, "completed", 4.5, 5.0, _dt_str(3, 18, 50), _dt_str(3, 19, 20),
                [
                    (266, 22, "Magnesium ribbon forms a protective layer of basic magnesium carbonate/oxide in moist air, so it is cleaned with sandpaper so it burns readily.", 2.0, 100.0, "Excellent explanation of the oxide coating and why cleaning is needed!"),
                    (238, 21, "(i) H2 + Cl2 -> 2HCl, (ii) 3BaCl2 + Al2(SO4)3 -> 3BaSO4 + 2AlCl3, (iii) 2Na + 2H2O -> 2NaOH + H2", 1.0, 100.0, "All three chemical equations are balanced accurately!"),
                    (239, 21, "BaCl2(aq) + Na2SO4(aq) -> BaSO4(s) + 2NaCl(aq); NaOH(aq) + HCl(aq) -> NaCl(aq) + H2O(l)", 0.5, 50.0, "Good balanced equations! Make sure all state symbols are clearly written for every reactant."),
                    (240, 21, "A. 3, 2, 2, 1", 1.0, 100.0, "Correct stoichiometric coefficients for the reaction of aluminium with steam."),
                ]
            ),
            (
                1003, 7, "completed", 5.5, 6.0, _dt_str(2, 17, 30), _dt_str(2, 18, 0),
                [
                    (168, 14, "Light rays parallel to the principal axis of a concave mirror converge at a point on the principal axis after reflection; this point is the principal focus.", 2.0, 100.0, "Clear and accurate textbook definition of principal focus!"),
                    (142, 13, "f = R / 2 = 20 / 2 = 10 cm", 1.0, 100.0, "Exact formula and calculation! Focal length is half the radius of curvature."),
                    (143, 13, "Concave mirror when object is placed between pole P and focus F.", 1.0, 100.0, "Excellent! A concave mirror produces a virtual, erect, and magnified image inside F."),
                    (169, 14, "Convex mirrors always form an erect, diminished image and provide a much wider field of view of traffic behind.", 1.5, 75.0, "Great points! Also mention that they are curved outwards which diverges rays."),
                ]
            ),
        ]
        c.execute("DELETE FROM answers WHERE attempt_id = 1004")
        c.execute("DELETE FROM attempts WHERE id = 1004")

        for att_id, ep_id, status, tot_aw, tot_max, st_at, comp_at, ans_rows in seed_attempts:
            c.execute("SELECT id FROM exam_papers WHERE id = ?", (ep_id,))
            if not c.fetchone():
                continue
            c.execute("""
                INSERT INTO attempts (id, exam_paper_id, exam_paper_version, student_id, status, total_marks_awarded, total_max_marks, started_at, completed_at)
                VALUES (?, ?, 1, 2, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    total_marks_awarded = excluded.total_marks_awarded,
                    total_max_marks = excluded.total_max_marks,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at
            """, (att_id, ep_id, status, tot_aw, tot_max, st_at, comp_at))

            expected_qids = {r[0] for r in ans_rows}
            c.execute("SELECT question_id FROM answers WHERE attempt_id = ?", (att_id,))
            existing_qids = {r[0] for r in c.fetchall()}
            if existing_qids != expected_qids:
                c.execute("DELETE FROM answers WHERE attempt_id = ?", (att_id,))
                for q_id, mod_id, ans_txt, m_aw, pct_corr, fb in ans_rows:
                    c.execute("SELECT id FROM questions WHERE id = ?", (q_id,))
                    if c.fetchone():
                        c.execute("""
                            INSERT INTO answers (attempt_id, question_id, module_id, answer_text, marks_awarded, percent_correct, ai_feedback, submitted_at, retry_count, is_latest, drawing_url)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1, '')
                        """, (att_id, q_id, mod_id, ans_txt, m_aw, pct_corr, fb, comp_at))

        # Seed 5-day streak in daily_activity for student_id=2 ending today in IST
        streak_seed = [
            (4, 4, 2),
            (3, 5, 2),
            (2, 4, 2),
            (1, 3, 1),
            (0, 4, 2),
        ]
        for days_ago, probs, mods in streak_seed:
            d_str = (ist_today - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d")
            c.execute("SELECT id, problems_solved, modules_completed FROM daily_activity WHERE user_id = 2 AND activity_date = ?", (d_str,))
            da_r = c.fetchone()
            if da_r:
                if (da_r[1] or 0) < probs or (da_r[2] or 0) < mods:
                    c.execute("UPDATE daily_activity SET problems_solved = MAX(COALESCE(problems_solved, 0), ?), modules_completed = MAX(COALESCE(modules_completed, 0), ?) WHERE id = ?", (probs, mods, da_r[0]))
            else:
                c.execute("INSERT INTO daily_activity (user_id, activity_date, problems_solved, modules_completed) VALUES (2, ?, ?, ?)", (d_str, probs, mods))

        # Seed subject_study_time for student_id=2
        study_times = [
            (2, 1, 2520),  # Physics: 42 mins
            (2, 5, 1980),  # Biology: 33 mins
            (2, 4, 1620),  # Chemistry: 27 mins
            (2, 2, 1440),  # Mathematics: 24 mins
        ]
        for st_id, sub_id, secs in study_times:
            c.execute("SELECT id FROM subjects WHERE id = ?", (sub_id,))
            if c.fetchone():
                c.execute("""
                    INSERT INTO subject_study_time (student_id, subject_id, seconds_studied, last_active_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(student_id, subject_id) DO UPDATE SET
                        seconds_studied = MAX(subject_study_time.seconds_studied, excluded.seconds_studied)
                """, (st_id, sub_id, secs))

        # Update user 2 XP to match real earned XP
        c.execute("SELECT COUNT(*) FROM content_progress WHERE student_id = 2 AND completed = 1")
        cp_xp = (c.fetchone()[0] or 0) * 20
        c.execute("""
            SELECT COALESCE(SUM(ans.marks_awarded), 0)
            FROM answers ans
            JOIN attempts a ON ans.attempt_id = a.id
            WHERE a.student_id = 2 AND ans.is_latest = 1 AND ans.marks_awarded > 0
        """)
        ex_xp = int(float(c.fetchone()[0] or 0) * 10)
        c.execute("UPDATE users SET total_xp = ? WHERE id = 2", (cp_xp + ex_xp,))

        # 5. Seed Biology Chapter 5 (Mock Test 1 id=13 [30M] & Real Exam id=14 [25M]) history for demo student accounts
        bio_mock_answers = [
            (1101, 25, "D. Glucose", 1.0, 100.0, "Correct! Glucose is the immediate product of photosynthesis."),
            (1102, 25, "C. Sphincter muscle", 1.0, 100.0, "Correct! Sphincter muscle regulates exit of food from stomach."),
            (1103, 25, "D. Translocation", 1.0, 100.0, "Correct! Soluble products of photosynthesis are transported by translocation."),
            (1104, 25, "B. Dialysis", 1.0, 100.0, "Correct! Artificial kidney purifies blood by dialysis."),
            (1105, 25, "D. Glomerulus", 1.0, 100.0, "Correct! Glomerulus is the bundle of capillaries in Bowman's capsule."),
            (1106, 25, "A. Both A and R are true and R is correct explanation of the assertion", 1.0, 100.0, "Correct! Villi increase surface area for absorption."),
            (1107, 25, "A. Both A and R are true and R is correct explanation of the assertion", 1.0, 100.0, "Correct! Four chambers prevent mixing of oxygenated and deoxygenated blood."),
            (1108, 26, "Lack of oxygen in muscle cells during sudden activity converts pyruvate into lactic acid, causing cramps.", 2.0, 100.0, "Complete and accurate!"),
            (1109, 26, "Septum separates left and right sides to prevent mixing of oxygenated and deoxygenated blood.", 2.0, 100.0, "Accurate explanation!"),
            (1110, 26, "No. Pulmonary veins carry oxygenated blood from lungs to heart, while other veins carry deoxygenated blood.", 2.0, 100.0, "Exact answer!"),
            (1111, 27, "Food moves due to involuntary wave-like muscular contractions in the oesophagus called peristalsis.", 2.5, 83.3, "Good explanation of peristalsis!"),
            (1112, 27, "Bile makes acidic food from stomach alkaline for pancreatic enzymes and emulsifies large fat globules into smaller globules.", 3.0, 100.0, "Both functions of bile are clearly stated!"),
            (1113, 27, "Transpiration is loss of water vapour from aerial parts of plants. It helps upward movement of water/minerals and temperature regulation, similar to sweating in humans.", 2.5, 83.3, "Well explained!"),
            (1114, 27, "Glucose breaks into pyruvate in cytoplasm. Aerobic in mitochondria gives CO2, H2O, ATP; anaerobic in muscles gives lactic acid; fermentation in yeast gives ethanol and CO2.", 2.5, 83.3, "Strong summary of all three pathways!"),
            (1115, 28, "(a) Yes. (b) Photosynthesis and respiration. (c) Sun. (d) Plants trap solar energy in food; respiration oxidises food into ATP. (e) Plants take up CO2 in photosynthesis and release O2, balancing respiration.", 3.5, 70.0, "Good coverage of all five subparts; include the respiration equation as well."),
        ]
        bio_high_answers = [
            (1401, 101, "B. Transport of water and minerals", 1.0, 100.0, "Correct! Xylem transports water and minerals."),
            (1402, 101, "B. Nephron", 1.0, 100.0, "Correct! Nephron is the structural and functional unit of kidney."),
            (1403, 101, "B. To prevent backflow of blood", 1.0, 100.0, "Correct! Valves prevent backflow of blood."),
            (1404, 101, "B. It requires ATP", 1.0, 100.0, "Correct! Translocation in phloem is an active process requiring ATP."),
            (1405, 101, "A. Both A and R true, R is correct explanation of A.", 1.0, 100.0, "Correct! Arteries have thick elastic walls due to high blood pressure from the heart."),
            (1406, 101, "A. Both A and R true, R is correct explanation of A.", 1.0, 100.0, "Correct! Plants store waste in leaves and shed them, so they do not need kidneys."),
            (1407, 102, "(a) Transpiration: Loss of water as water vapour from leaves through stomata.\n(b) Translocation: Transport of food through phloem from leaves to other parts of the plant.", 2.0, 100.0, "Both definitions are accurate!"),
            (1408, 102, "1. To make exchange of oxygen, food, CO2, and waste easy.\n2. To allow faster diffusion of substances.", 2.0, 100.0, "Full marks!"),
            (1409, 102, "Dialysis is cleaning blood using an artificial machine when kidneys fail. It is needed during kidney failure.", 2.0, 100.0, "Clear definition and condition!"),
            (1410, 103, "Labelled Human Excretory System diagram showing Kidney, Ureter, Urinary Bladder, and Urethra.", 2.5, 83.3, "Neat diagram with Kidney, Ureter, and Urinary Bladder clearly labelled!"),
            (1411, 104, "a. Platelets help in blood clotting. b. Clot plugs the wound to stop bleeding. c. Filtration, Reabsorption, Urine Formation. d. Glucose, amino acids, salts and most water are reabsorbed back into blood.", 4.5, 90.0, "Excellent case-study answers!"),
            (1412, 104, "(B) Human Excretory System: 1. Kidney - Filters blood. 2. Ureter - Carries urine from kidney to bladder. 3. Urinary Bladder - Stores urine. 4. Urethra - Removes urine from the body.", 4.0, 80.0, "All four parts and their functions are accurately stated!"),
        ]
        bio_low_real_answers = [
            (1401, 101, "B. Transport of water and minerals", 1.0, 100.0, "Correct!"),
            (1402, 101, "B. Nephron", 1.0, 100.0, "Correct!"),
            (1403, 101, "A. High pressure", 0.0, 0.0, "Valves are present to prevent backflow of blood."),
            (1404, 101, "B. It requires ATP", 1.0, 100.0, "Correct!"),
            (1405, 101, "A. Both A and R true, R is correct explanation of A.", 1.0, 100.0, "Correct!"),
            (1406, 101, "B. Both true, R is NOT correct explanation of A.", 0.0, 0.0, "R directly explains why plants do not require kidneys."),
            (1407, 102, "Transpiration is loss of water vapour through stomata. Translocation is food transport.", 1.5, 75.0, "Mention phloem explicitly in translocation."),
            (1408, 102, "To allow easy exchange of materials between blood and cells.", 1.0, 50.0, "Give a second point mentioning faster diffusion."),
            (1409, 102, "Dialysis cleans blood using a machine during kidney failure.", 2.0, 100.0, "Correct!"),
            (1410, 103, "Human Excretory System with kidneys and bladder.", 1.5, 50.0, "Ensure Kidney, Ureter, and Urinary Bladder are all neatly drawn and labelled."),
            (1411, 104, "a. Platelets clot blood. b. Clotting stops bleeding. c. Filtration and reabsorption.", 2.5, 50.0, "Include all three nephron steps and answer part d or e."),
            (1412, 104, "(A) Plants release oxygen and water vapour through stomata and shed old leaves.", 2.5, 50.0, "Write all 5 points of plant excretion for full 5 marks."),
        ]

        for demo_uid, base_att_id in [(2, 1000), (91445, 2000), (10, 3000)]:
            c.execute("SELECT id FROM users WHERE id = ?", (demo_uid,))
            if not c.fetchone():
                continue

            for ci_id, prog_s, days_ago in [(8, 285, 2), (30, 275, 1)]:
                c.execute("SELECT id FROM content_items WHERE id = ?", (ci_id,))
                if c.fetchone():
                    c.execute("""
                        INSERT INTO content_progress (student_id, content_item_id, progress_seconds, percent_complete, completed, completed_at)
                        VALUES (?, ?, ?, 100.0, 1, ?)
                        ON CONFLICT(student_id, content_item_id) DO UPDATE SET
                            completed = 1,
                            percent_complete = 100.0,
                            completed_at = COALESCE(content_progress.completed_at, excluded.completed_at)
                    """, (demo_uid, ci_id, prog_s, _dt_str(days_ago, 15, 30)))

            bio_attempts = [
                (base_att_id + 5, 13, "completed", 23.0, 30.0, _dt_str(3, 18, 0), _dt_str(3, 18, 20), 1215, bio_mock_answers),
                (base_att_id + 6, 14, "completed", 15.0, 25.0, _dt_str(2, 16, 0), _dt_str(2, 16, 28), 1680, bio_low_real_answers),
                (base_att_id + 7, 13, "completed", 26.0, 30.0, _dt_str(1, 17, 10), _dt_str(1, 17, 25), 880, bio_mock_answers),
                (base_att_id + 8, 14, "completed", 23.0, 25.0, _dt_str(0, 10, 15), _dt_str(0, 10, 34), 1125, bio_high_answers),
            ]
            for att_id, ep_id, status, tot_aw, tot_max, st_at, comp_at, dur_sec, ans_rows in bio_attempts:
                c.execute("SELECT id FROM exam_papers WHERE id = ?", (ep_id,))
                if not c.fetchone():
                    continue
                c.execute("""
                    INSERT INTO attempts (id, exam_paper_id, exam_paper_version, student_id, status, total_marks_awarded, total_max_marks, started_at, completed_at, time_taken_seconds)
                    VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        student_id = excluded.student_id,
                        status = excluded.status,
                        total_marks_awarded = excluded.total_marks_awarded,
                        total_max_marks = excluded.total_max_marks,
                        started_at = excluded.started_at,
                        completed_at = excluded.completed_at,
                        time_taken_seconds = excluded.time_taken_seconds
                """, (att_id, ep_id, demo_uid, status, tot_aw, tot_max, st_at, comp_at, dur_sec))

                expected_qids = {r[0] for r in ans_rows}
                c.execute("SELECT question_id FROM answers WHERE attempt_id = ?", (att_id,))
                existing_qids = {r[0] for r in c.fetchall()}
                if existing_qids != expected_qids:
                    c.execute("DELETE FROM answers WHERE attempt_id = ?", (att_id,))
                    for q_id, mod_id, ans_txt, m_aw, pct_corr, fb in ans_rows:
                        c.execute("SELECT id FROM questions WHERE id = ?", (q_id,))
                        if c.fetchone():
                            c.execute("""
                                INSERT INTO answers (attempt_id, question_id, module_id, answer_text, marks_awarded, percent_correct, ai_feedback, submitted_at, retry_count, is_latest, drawing_url)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1, '')
                            """, (att_id, q_id, mod_id, ans_txt, m_aw, pct_corr, fb, comp_at))

            # Ensure Biology study time & streak exist for demo_uid
            c.execute("""
                INSERT INTO subject_study_time (student_id, subject_id, seconds_studied, last_active_at)
                VALUES (?, 5, 2340, CURRENT_TIMESTAMP)
                ON CONFLICT(student_id, subject_id) DO UPDATE SET
                    seconds_studied = MAX(subject_study_time.seconds_studied, excluded.seconds_studied)
            """, (demo_uid,))
            for days_ago, probs, mods in [(3, 4, 1), (2, 5, 2), (1, 6, 2), (0, 5, 2)]:
                d_str = (ist_today - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d")
                c.execute("SELECT id, problems_solved, modules_completed FROM daily_activity WHERE user_id = ? AND activity_date = ?", (demo_uid, d_str))
                da_r = c.fetchone()
                if da_r:
                    c.execute("UPDATE daily_activity SET problems_solved = MAX(COALESCE(problems_solved, 0), ?), modules_completed = MAX(COALESCE(modules_completed, 0), ?) WHERE id = ?", (probs, mods, da_r[0]))
                else:
                    c.execute("INSERT INTO daily_activity (user_id, activity_date, problems_solved, modules_completed) VALUES (?, ?, ?, ?)", (demo_uid, d_str, probs, mods))

            c.execute("SELECT COUNT(*) FROM content_progress WHERE student_id = ? AND completed = 1", (demo_uid,))
            u_cp_xp = (c.fetchone()[0] or 0) * 20
            c.execute("""
                SELECT COALESCE(SUM(ans.marks_awarded), 0)
                FROM answers ans
                JOIN attempts a ON ans.attempt_id = a.id
                WHERE a.student_id = ? AND ans.is_latest = 1 AND ans.marks_awarded > 0
            """, (demo_uid,))
            u_ex_xp = int(float(c.fetchone()[0] or 0) * 10)
            c.execute("UPDATE users SET total_xp = MAX(COALESCE(total_xp, 0), ?) WHERE id = ?", (u_cp_xp + u_ex_xp, demo_uid))

            # Seed strict one-time anti-farming coin_ledger matching already-completed demo milestones (120 Coins = Rs 1.20)
            c.execute("""
                CREATE TABLE IF NOT EXISTS coin_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    reward_key TEXT NOT NULL,
                    coins INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(student_id, reward_key)
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS coin_redemptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    item_code TEXT NOT NULL,
                    item_title TEXT NOT NULL,
                    coins_spent INTEGER NOT NULL,
                    inr_value INTEGER NOT NULL,
                    coupon_code TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            demo_coins = [
                ("video:item:8", 5, "Watched Chapter Summary Part 1"),
                ("video:item:30", 5, "Watched Chapter Summary Part 2"),
                ("mock_pass:paper:13", 30, "Passed Mock Exam — Chapter 5: Life Processes"),
                ("mock_ace:paper:13", 10, "85%+ Mastery Bonus — Mock Exam Chapter 5"),
                ("real_tier1:paper:14", 30, "Completed Official Real Exam — Chapter 5 (50%+)"),
                ("real_tier2:paper:14", 20, "High Score Tier — Official Real Exam Chapter 5 (75%+)"),
                ("real_tier3:paper:14", 20, "Distinction Tier — Official Real Exam Chapter 5 (90%+)"),
            ]
            for r_key, r_coins, r_lbl in demo_coins:
                c.execute(
                    "INSERT OR IGNORE INTO coin_ledger (student_id, reward_key, coins, label) VALUES (?, ?, ?, ?)",
                    (demo_uid, r_key, r_coins, r_lbl),
                )
            c.execute("SELECT COALESCE(SUM(coins), 0) FROM coin_ledger WHERE student_id = ?", (demo_uid,))
            earned_c = int(c.fetchone()[0] or 0)
            c.execute("SELECT COALESCE(SUM(coins_spent), 0) FROM coin_redemptions WHERE student_id = ?", (demo_uid,))
            spent_c = int(c.fetchone()[0] or 0)
            c.execute("UPDATE users SET coin_balance = ? WHERE id = ?", (max(0, earned_c - spent_c), demo_uid))

            # Pre-seed SQLite-cached Parent Dashboard summaries stamped with completed-attempts hash (0 tokens until a new attempt finishes)
            import hashlib as _hl
            import json as _js
            c.execute("SELECT brutality_level, name, parent_summary, parent_mock_summary, parent_real_summary FROM users WHERE id = ?", (demo_uid,))
            u_sum_row = c.fetchone()
            b_lvl = (u_sum_row[0] if u_sum_row and u_sum_row[0] else 1)
            s_nm = ((u_sum_row[1] or "Your child").split()[0] if u_sum_row else "Your child")
            default_sums = {
                "main": (
                    "parent_summary",
                    u_sum_row[2] if u_sum_row else None,
                    f"Your child {s_nm} is making steady progress in Biology Chapter 5: Life Processes, having watched the core summary lessons and practiced diligently across Mock Test 1 before earning an impressive 92% score on the Official Real Exam. Their willingness to retry missed questions shows strong conceptual curiosity and growing exam confidence.",
                    "",
                ),
                "mock": (
                    "parent_mock_summary",
                    u_sum_row[3] if u_sum_row else None,
                    f"Your child {s_nm} has completed multiple practice runs in Mock Test 1 for Life Processes, improving from 67% on the opening run to 87% by reviewing key scoring points and retrying weak concepts. Encouraging one quick practice run on Mock Test 2 and Mock Test 3 will lock in full chapter mastery.",
                    " AND ep.type != 'real'",
                ),
                "real": (
                    "parent_real_summary",
                    u_sum_row[4] if u_sum_row else None,
                    f"Your child {s_nm} has completed two timed, proctored Official Real Exam attempts in Life Processes, advancing from 76% (19/25) to an outstanding 92% (23/25) with strong command of both MCQs and structured descriptive answers.",
                    " AND ep.type = 'real'",
                ),
            }
            for s_type, (col_n, cur_val, def_txt, extra_sql) in default_sums.items():
                c.execute(
                    f"""
                    SELECT a.id, a.exam_paper_id, ROUND(COALESCE(a.total_marks_awarded, 0), 2), ROUND(COALESCE(a.total_max_marks, 0), 2)
                    FROM attempts a
                    JOIN exam_papers ep ON a.exam_paper_id = ep.id
                    WHERE a.student_id = ? AND a.completed_at IS NOT NULL{extra_sql}
                    ORDER BY a.id ASC
                    """,
                    (demo_uid,),
                )
                att_h = _hl.md5(_js.dumps([list(r) for r in c.fetchall()], separators=(",", ":")).encode("utf-8")).hexdigest()
                marker = f"<!-- attemptshash:{att_h} brutality:{b_lvl} -->"
                if not cur_val or marker not in cur_val:
                    base_txt = cur_val.split("<!--")[0].strip() if cur_val and cur_val.split("<!--")[0].strip() else def_txt
                    c.execute(f"UPDATE users SET {col_n} = ? WHERE id = ?", (f"{base_txt}\n{marker}", demo_uid))

    # Permanently standardize all users on Expressive OpenAI TTS (`gpt-4o-mini-tts`)
    c.execute("UPDATE users SET tts_engine = 'openai' WHERE tts_engine IS NULL OR tts_engine != 'openai'")
    c.execute("UPDATE users SET parent_tts_engine = 'openai' WHERE parent_tts_engine IS NULL OR parent_tts_engine != 'openai'")

    conn.commit()

def reset_admin_password(new_password: str):
    """Utility to manually reset the admin password. Run from CLI only."""
    import bcrypt
    conn = get_db_connection()
    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    conn.execute("UPDATE users SET password_hash = ? WHERE role = 'admin'", (new_hash,))
    conn.commit()
    conn.close()
    print(f"Admin password reset successfully.")
