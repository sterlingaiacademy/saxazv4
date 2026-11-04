-- Digi Library Schema (Books -> Subjects -> Question Banks -> Questions -> Attempts & Answers without marks)

CREATE TABLE IF NOT EXISTS digi_books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER REFERENCES classes(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    thumbnail_url TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('draft','published')),
    order_index INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS digi_subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES digi_books(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    thumbnail_url TEXT DEFAULT '',
    order_index INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS digi_question_banks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES digi_subjects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('draft','published')),
    order_index INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

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
);

CREATE TABLE IF NOT EXISTS digi_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_id INTEGER NOT NULL REFERENCES digi_question_banks(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'in_progress' CHECK(status IN ('in_progress','completed')),
    correct_count INTEGER DEFAULT 0,
    total_questions INTEGER DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

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
);

CREATE INDEX IF NOT EXISTS idx_digi_books_class ON digi_books(class_id);
CREATE INDEX IF NOT EXISTS idx_digi_subjects_book ON digi_subjects(book_id);
CREATE INDEX IF NOT EXISTS idx_digi_banks_subject ON digi_question_banks(subject_id);
CREATE INDEX IF NOT EXISTS idx_digi_questions_bank ON digi_questions(bank_id);
CREATE INDEX IF NOT EXISTS idx_digi_attempts_student ON digi_attempts(student_id);
CREATE INDEX IF NOT EXISTS idx_digi_attempts_bank ON digi_attempts(bank_id);
CREATE INDEX IF NOT EXISTS idx_digi_answers_attempt ON digi_answers(attempt_id);
CREATE INDEX IF NOT EXISTS idx_digi_answers_question ON digi_answers(question_id);
