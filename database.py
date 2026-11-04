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

def get_db_connection():
  """Create and return a database connection with WAL mode enabled."""
  conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10.0)
  conn.row_factory = sqlite3.Row
  # Enable WAL mode and busy_timeout for better concurrency
  conn.execute('PRAGMA journal_mode = WAL;')
  conn.execute('PRAGMA synchronous = NORMAL;')
  conn.execute('PRAGMA busy_timeout = 5000;')
  # Enforce foreign key constraints
  conn.execute('PRAGMA foreign_keys = ON;')
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
        ("tts_engine", "TEXT DEFAULT 'kokoro'"),
        ("tts_mode", "TEXT DEFAULT 'auto'"),
        ("sfx_enabled", "INTEGER DEFAULT 0"),
        ("sfx_mode", "INTEGER DEFAULT 0"),
        ("sfx_custom", "TEXT DEFAULT '{}'"),
        ("total_xp", "INTEGER DEFAULT 0"),
        ("cursor_mode", "INTEGER DEFAULT 1"),
        ("cursor_effect", "TEXT DEFAULT 'none'"),
        ("subject_intro_mode", "INTEGER DEFAULT 0"),
        ("parent_tts_voice", "TEXT DEFAULT 'af_bella'"),
        ("parent_tts_engine", "TEXT DEFAULT 'kokoro'"),
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

    for tbl, col_name, col_type in [
        ("exam_papers", "use_mock_questions", "INTEGER DEFAULT 0"),
        ("exam_papers", "target_marks", "INTEGER"),
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

        # Persistent AI Tutor Chat History (ChatGPT-style conversations & messages)
    c.execute("""
        CREATE TABLE IF NOT EXISTS tutor_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tutor_name TEXT DEFAULT 'bella',
            title TEXT NOT NULL DEFAULT 'New Chat',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS tutor_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES tutor_conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL DEFAULT '',
            emotion TEXT DEFAULT 'talking',
            image_url TEXT DEFAULT '',
            scratchpad_meta TEXT DEFAULT '{}',
            diagram_key TEXT DEFAULT '',
            diagram_title TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

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
        "CREATE INDEX IF NOT EXISTS idx_tutor_conv_student ON tutor_conversations(student_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_tutor_msg_conv ON tutor_messages(conversation_id, id ASC)",
    ]
    for idx_sql in indexes:
        try:
            c.execute(idx_sql)
        except Exception:
            pass

    # One-time data fix: rename "Mock Exam - 1" to "Practice Exam"
    try:
        c.execute("UPDATE exam_papers SET title = 'Practice Exam' WHERE title = 'Mock Exam - 1'")
        if c.rowcount > 0:
            print("Renamed 'Mock Exam - 1' to 'Practice Exam'")
    except Exception:
        pass

    conn.commit()
    conn.close()

def reset_admin_password(new_password: str):
    """Utility to manually reset the admin password. Run from CLI only."""
    import bcrypt
    conn = get_db_connection()
    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    conn.execute("UPDATE users SET password_hash = ? WHERE role = 'admin'", (new_hash,))
    conn.commit()
    conn.close()
    print(f"Admin password reset successfully.")
