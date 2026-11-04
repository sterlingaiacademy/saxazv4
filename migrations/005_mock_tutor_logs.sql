-- Additive migration: Track AI Tutor usage in Mock Exams for Parent Portal
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
);

CREATE INDEX IF NOT EXISTS idx_mock_tutor_logs_student ON mock_exam_tutor_logs(student_id);
CREATE INDEX IF NOT EXISTS idx_mock_tutor_logs_exam ON mock_exam_tutor_logs(exam_paper_id);
CREATE INDEX IF NOT EXISTS idx_mock_tutor_logs_question ON mock_exam_tutor_logs(question_id);
CREATE INDEX IF NOT EXISTS idx_mock_tutor_logs_attempt ON mock_exam_tutor_logs(attempt_id);
