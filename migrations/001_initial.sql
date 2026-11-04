-- USERS
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    role TEXT CHECK(role IN ('admin','student')) NOT NULL,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    theme_preference TEXT DEFAULT 'light',
    parent_locked INTEGER DEFAULT 0,
    parent_pin TEXT,
    parent_summary TEXT,
    parent_summary_updated_at TEXT,
    tts_voice TEXT DEFAULT 'af_bella',
    class_id INTEGER REFERENCES classes(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    is_parent INTEGER DEFAULT 0
);

-- CURRICULUM TREE
CREATE TABLE classes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    thumbnail_url TEXT,
    order_index INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE subjects (
    id INTEGER PRIMARY KEY,
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    thumbnail_url TEXT,
    order_index INTEGER DEFAULT 0
);

CREATE TABLE chapters (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    thumbnail_url TEXT,
    order_index INTEGER DEFAULT 0,
    status TEXT CHECK(status IN ('draft','published')) DEFAULT 'draft'
);

-- TEACHING SECTION
CREATE TABLE content_items (
    id INTEGER PRIMARY KEY,
    chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    type TEXT CHECK(type IN ('video','audio','pdf','text')) NOT NULL,
    title TEXT NOT NULL,
    thumbnail_url TEXT,
    media_url TEXT NOT NULL,
    duration_seconds INTEGER,             -- null for text/pdf
    order_index INTEGER DEFAULT 0
);

CREATE TABLE content_progress (
    id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content_item_id INTEGER NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    progress_seconds INTEGER DEFAULT 0,   -- for video/audio
    percent_complete REAL DEFAULT 0,      -- for text/pdf (scroll %) or computed for media
    completed INTEGER DEFAULT 0,
    completed_at TEXT,
    UNIQUE(student_id, content_item_id)
);

-- EXAM PAPERS (both mock and real use the same shape)
CREATE TABLE exam_papers (
    id INTEGER PRIMARY KEY,
    chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    type TEXT CHECK(type IN ('mock','real')) NOT NULL,
    title TEXT NOT NULL,
    unlock_threshold_percent REAL,        -- only meaningful for type='mock'
    time_limit_minutes INTEGER,
    status TEXT CHECK(status IN ('draft','published')) DEFAULT 'draft',
    version INTEGER DEFAULT 1,            -- bump on edit after publish; old attempts keep old version
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE modules (
    id INTEGER PRIMARY KEY,
    exam_paper_id INTEGER NOT NULL REFERENCES exam_papers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,                   -- e.g. "2 Mark Questions"
    mark_value INTEGER NOT NULL,          -- 2, 3, 5, etc.
    order_index INTEGER DEFAULT 0
);

CREATE TABLE questions (
    id INTEGER PRIMARY KEY,
    module_id INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    model_answer TEXT NOT NULL,           -- admin-authored full correct answer; the core grading reference
    rubric_points TEXT,                   -- OPTIONAL, V2: JSON array [{point, weight}] for finer-grained essay grading
    max_marks INTEGER NOT NULL,
    order_index INTEGER DEFAULT 0
);

-- ATTEMPTS
CREATE TABLE attempts (
    id INTEGER PRIMARY KEY,
    exam_paper_id INTEGER NOT NULL REFERENCES exam_papers(id) ON DELETE CASCADE,
    exam_paper_version INTEGER NOT NULL,  -- snapshot of version at attempt time
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT CHECK(status IN ('in_progress','completed')) DEFAULT 'in_progress',
    total_marks_awarded REAL,
    total_max_marks REAL,
    overall_feedback TEXT,                -- AI-generated, whole-paper level
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE TABLE answers (
    id INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    module_id INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,   -- denormalized, avoids join for scoring
    answer_text TEXT NOT NULL,
    marks_awarded REAL,
    percent_correct REAL,
    ai_feedback TEXT,
    submitted_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE module_results (
    id INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    module_id INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    marks_awarded REAL,
    max_marks REAL,
    grade_label TEXT,                     -- e.g. "B", "Needs Improvement"
    feedback TEXT
);
