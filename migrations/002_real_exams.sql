-- 002_real_exams.sql
ALTER TABLE exam_papers ADD COLUMN required_mock_percent REAL;
ALTER TABLE exam_papers ADD COLUMN max_attempts INTEGER;
ALTER TABLE modules ADD COLUMN time_limit_seconds INTEGER DEFAULT 60;
ALTER TABLE users ADD COLUMN spent_xp INTEGER DEFAULT 0;
ALTER TABLE attempts ADD COLUMN tab_switch_count INTEGER DEFAULT 0;
ALTER TABLE attempts ADD COLUMN purchased_extra_seconds INTEGER DEFAULT 0;
