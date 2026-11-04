-- Add total_xp to users to track overall lifetime XP
ALTER TABLE users ADD COLUMN total_xp INTEGER DEFAULT 0;

-- Set total_xp equal to spent_xp initially so existing users don't lose progress entirely
UPDATE users SET total_xp = spent_xp WHERE spent_xp > 0;

-- Create daily_activity table to track streak progress
CREATE TABLE daily_activity (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    activity_date TEXT NOT NULL, -- YYYY-MM-DD
    problems_solved INTEGER DEFAULT 0,
    modules_completed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, activity_date)
);
