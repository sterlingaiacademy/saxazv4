import datetime
from database import get_db_connection

IST_OFFSET = datetime.timedelta(hours=5, minutes=30)

def get_ist_now() -> datetime.datetime:
  return datetime.datetime.now(datetime.timezone.utc) + IST_OFFSET

def get_ist_today() -> datetime.date:
  return get_ist_now().date()

def get_ist_today_str() -> str:
  return get_ist_today().strftime('%Y-%m-%d')

def create_notification(conn, user_id: int, title: str, message: str, notif_type: str):
  cursor = conn.cursor()
  cursor.execute("""
    INSERT INTO notifications (user_id, title, message, type)
    VALUES (?, ?, ?, ?)
  """, (user_id, title, message, notif_type))
  conn.commit()

def record_daily_activity(conn, student_id: int, problems_delta: int = 0, modules_delta: int = 0, notify_streak: bool = True):
  """Records or increments daily_activity for today (in IST) when a student solves a problem or completes a module/exam."""
  if problems_delta <= 0 and modules_delta <= 0:
    return
  cursor = conn.cursor()
  today_str = get_ist_today_str()
  cursor.execute("SELECT id FROM daily_activity WHERE user_id = ? AND activity_date = ?", (student_id, today_str))
  da_row = cursor.fetchone()
  if da_row:
    cursor.execute("""
      UPDATE daily_activity
      SET problems_solved = COALESCE(problems_solved, 0) + ?,
          modules_completed = COALESCE(modules_completed, 0) + ?
      WHERE id = ?
    """, (max(0, problems_delta), max(0, modules_delta), da_row[0]))
    conn.commit()
  else:
    cursor.execute("""
      INSERT INTO daily_activity (user_id, activity_date, problems_solved, modules_completed)
      VALUES (?, ?, ?, ?)
    """, (student_id, today_str, max(0, problems_delta), max(0, modules_delta)))
    conn.commit()
    if notify_streak:
      create_notification(conn, student_id, "Streak Active!", "You're active today! Keep your daily learning streak burning!", "streak")

def recalculate_user_xp(conn, student_id: int, notify: bool = True):
  cursor = conn.cursor()
  
  cursor.execute("SELECT total_xp FROM users WHERE id = ?", (student_id,))
  row = cursor.fetchone()
  old_xp = row[0] if row and row[0] else 0

  # 1. Completed curriculum lessons/videos/PDFs (20 XP per completed lesson)
  cursor.execute("""
    SELECT COUNT(*) FROM content_progress
    WHERE student_id = ? AND completed = 1
  """, (student_id,))
  content_xp = (cursor.fetchone()[0] or 0) * 20

  # 2. Marks earned in exams across attempts (10 XP per mark awarded on latest answer per attempt)
  cursor.execute("""
    SELECT COALESCE(SUM(ans.marks_awarded), 0)
    FROM answers ans
    JOIN attempts a ON ans.attempt_id = a.id
    WHERE a.student_id = ? AND ans.is_latest = 1 AND ans.marks_awarded > 0
  """, (student_id,))
  exam_xp = float(cursor.fetchone()[0] or 0) * 10

  # 3. Digi-Library correct answers (10 XP per correct answer on latest attempt answer)
  digi_xp = 0
  try:
    cursor.execute("""
      SELECT COALESCE(SUM(CASE WHEN da.is_correct = 1 THEN 1 ELSE 0 END), 0)
      FROM digi_answers da
      JOIN digi_attempts datt ON da.attempt_id = datt.id
      WHERE datt.student_id = ? AND da.is_latest = 1
    """, (student_id,))
    digi_xp = int(cursor.fetchone()[0] or 0) * 10
  except Exception:
    digi_xp = 0

  new_total_xp = int(content_xp + exam_xp + digi_xp)
  
  if notify and new_total_xp > old_xp:
    xp_gained = new_total_xp - old_xp
    create_notification(conn, student_id, "XP Earned!", f"You just earned +{xp_gained} XP! Keep it up!", "xp")
    
  if new_total_xp != old_xp:
    cursor.execute("UPDATE users SET total_xp = ? WHERE id = ?", (new_total_xp, student_id))
    conn.commit()
  return new_total_xp

def format_seconds(seconds: int) -> str:
  if not seconds or seconds <= 0:
    return "0 mins"
  mins = seconds // 60
  hrs = mins // 60
  rem_mins = mins % 60
  if hrs > 0:
    return f"{hrs}h {rem_mins}m"
  elif mins > 0:
    return f"{mins} mins"
  else:
    return f"{seconds}s"

def track_subject_time(conn, student_id: int, subject_id: int, seconds: int = 15):
  if seconds <= 0:
    return
  seconds = min(seconds, 300) # prevent abnormal jumps
  cursor = conn.cursor()
  cursor.execute("""
    INSERT INTO subject_study_time (student_id, subject_id, seconds_studied, last_active_at)
    VALUES (?, ?, ?, datetime('now'))
    ON CONFLICT(student_id, subject_id) DO UPDATE SET
      seconds_studied = seconds_studied + excluded.seconds_studied,
      last_active_at = datetime('now')
  """, (student_id, subject_id, seconds))
  conn.commit()

def get_student_subjects(conn, class_id: int, student_id: int):
  cursor = conn.cursor()
  cursor.execute("SELECT * FROM subjects WHERE class_id = ? AND COALESCE(is_hidden, 0) = 0 ORDER BY order_index", (class_id,))
  subjects = [dict(row) for row in cursor.fetchall()]
  
  for sub in subjects:
    # Fetch seconds studied for this subject
    cursor.execute("SELECT seconds_studied FROM subject_study_time WHERE student_id = ? AND subject_id = ?", (student_id, sub['id']))
    time_row = cursor.fetchone()
    seconds = time_row[0] if time_row and time_row[0] else 0
    sub['seconds_studied'] = seconds
    sub['minutes_studied'] = round(seconds / 60, 1)
    sub['time_studied_str'] = format_seconds(seconds)

    # Get total items in subject (content + exams + questions)
    cursor.execute("""
      SELECT 
        (SELECT COUNT(*) FROM content_items ci JOIN chapters c ON ci.chapter_id = c.id WHERE c.subject_id = ? AND c.status = 'published') as total_content,
        (SELECT COUNT(*) FROM exam_papers ep JOIN chapters c ON ep.chapter_id = c.id WHERE c.subject_id = ? AND c.status = 'published' AND ep.status = 'published') as total_exams,
        (SELECT COUNT(*) FROM questions q JOIN modules m ON q.module_id = m.id JOIN exam_papers ep ON m.exam_paper_id = ep.id JOIN chapters c ON ep.chapter_id = c.id WHERE c.subject_id = ? AND c.status = 'published' AND ep.status = 'published' AND COALESCE(q.is_hidden, 0) = 0) as total_questions
    """, (sub['id'], sub['id'], sub['id']))
    counts = cursor.fetchone()
    total_content = int(counts[0] or 0)
    total_exams = int(counts[1] or 0)
    total_questions = int(counts[2] or 0)
    total_items = total_content + total_exams
    sub['total_content'] = total_content
    sub['total_exams'] = total_exams
    sub['total_items'] = total_items
    sub['total_questions'] = total_questions
    
    if total_items == 0:
      sub['completed_content'] = 0
      sub['completed_exams'] = 0
      sub['completed_items'] = 0
      sub['questions_answered'] = 0
      sub['progress_pct'] = 0
      sub['seconds_studied'] = 0
      sub['minutes_studied'] = 0
      sub['time_studied_str'] = "0 mins"
      continue
      
    # Get completed content items
    cursor.execute("""
      SELECT COUNT(DISTINCT cp.content_item_id) FROM content_progress cp
      JOIN content_items ci ON cp.content_item_id = ci.id
      JOIN chapters c ON ci.chapter_id = c.id
      WHERE c.subject_id = ? AND cp.student_id = ? AND cp.completed = 1 AND c.status = 'published'
    """, (sub['id'], student_id))
    completed_content = int(cursor.fetchone()[0] or 0)
    
    # Get completed exams
    cursor.execute("""
      SELECT COUNT(DISTINCT ep.id) FROM attempts a
      JOIN exam_papers ep ON a.exam_paper_id = ep.id
      JOIN chapters c ON ep.chapter_id = c.id
      WHERE c.subject_id = ? AND a.student_id = ? AND a.status = 'completed' AND c.status = 'published' AND ep.status = 'published'
    """, (sub['id'], student_id))
    completed_exams = int(cursor.fetchone()[0] or 0)

    # Get distinct questions answered in this subject (including in-progress exams)
    cursor.execute("""
      SELECT COUNT(DISTINCT ans.question_id)
      FROM answers ans
      JOIN questions q ON ans.question_id = q.id
      JOIN attempts a ON ans.attempt_id = a.id
      JOIN exam_papers ep ON a.exam_paper_id = ep.id
      JOIN chapters c ON ep.chapter_id = c.id
      WHERE c.subject_id = ? AND a.student_id = ? AND ans.is_latest = 1
        AND COALESCE(q.is_hidden, 0) = 0
        AND TRIM(COALESCE(ans.answer_text, '')) NOT IN ('', 'No answer provided', 'no answer provided')
    """, (sub['id'], student_id))
    questions_answered = int(cursor.fetchone()[0] or 0)

    # Partial exam credit for in-progress exams that are not yet marked 'completed'
    cursor.execute("""
      SELECT ep.id,
             (SELECT COUNT(*) FROM questions q JOIN modules m ON q.module_id = m.id WHERE m.exam_paper_id = ep.id AND COALESCE(q.is_hidden, 0) = 0) as ep_total_q,
             COUNT(DISTINCT ans.question_id) as ep_ans_q
      FROM attempts a
      JOIN exam_papers ep ON a.exam_paper_id = ep.id
      JOIN chapters c ON ep.chapter_id = c.id
      JOIN answers ans ON ans.attempt_id = a.id AND ans.is_latest = 1
      JOIN questions q2 ON ans.question_id = q2.id AND COALESCE(q2.is_hidden, 0) = 0
      WHERE c.subject_id = ? AND a.student_id = ? AND a.status != 'completed'
        AND c.status = 'published' AND ep.status = 'published'
        AND ep.id NOT IN (
          SELECT DISTINCT a2.exam_paper_id FROM attempts a2 WHERE a2.student_id = ? AND a2.status = 'completed'
        )
      GROUP BY ep.id
    """, (sub['id'], student_id, student_id))
    partial_exam_credit = 0.0
    for p_row in cursor.fetchall():
      ep_tot = int(p_row[1] or 0)
      ep_ans = int(p_row[2] or 0)
      if ep_tot > 0 and ep_ans > 0:
        partial_exam_credit += min(0.95, ep_ans / ep_tot)

    completed_items = completed_content + completed_exams
    effective_completed = completed_items + partial_exam_credit
    raw_pct = int(round((effective_completed / total_items) * 100)) if total_items > 0 else 0
    if raw_pct == 0 and (completed_items > 0 or questions_answered > 0):
      raw_pct = 5
    # Calculate total time studied in this subject (content video progress + exam attempt durations)
    cursor.execute("""
      SELECT COALESCE(SUM(cp.progress_seconds), 0)
      FROM content_progress cp
      JOIN content_items ci ON cp.content_item_id = ci.id
      JOIN chapters c ON ci.chapter_id = c.id
      WHERE c.subject_id = ? AND cp.student_id = ? AND c.status = 'published'
    """, (sub['id'], student_id))
    sub_content_secs = int(cursor.fetchone()[0] or 0)

    cursor.execute("""
      SELECT COALESCE(SUM(
        CASE
          WHEN COALESCE(a.time_taken_seconds, 0) > 0 THEN a.time_taken_seconds
          WHEN a.completed_at IS NOT NULL AND a.started_at IS NOT NULL
            THEN MAX(0, CAST(strftime('%s', a.completed_at) - strftime('%s', a.started_at) AS INTEGER))
          ELSE 0
        END
      ), 0)
      FROM attempts a
      JOIN exam_papers ep ON a.exam_paper_id = ep.id
      JOIN chapters c ON ep.chapter_id = c.id
      WHERE c.subject_id = ? AND a.student_id = ? AND c.status = 'published' AND ep.status = 'published'
    """, (sub['id'], student_id))
    sub_exam_secs = int(cursor.fetchone()[0] or 0)
    sub_total_secs = max(0, sub_content_secs + sub_exam_secs)

    sub['completed_content'] = completed_content
    sub['completed_exams'] = completed_exams
    sub['completed_items'] = completed_items
    sub['questions_answered'] = questions_answered
    sub['progress_pct'] = min(100, raw_pct)
    sub['seconds_studied'] = sub_total_secs
    sub['minutes_studied'] = round(sub_total_secs / 60.0, 1)
    sub['time_studied_str'] = format_seconds(sub_total_secs)
    
  return subjects

def get_student_chapters(conn, subject_id: int, student_id: int):
  cursor = conn.cursor()
  cursor.execute("SELECT * FROM chapters WHERE subject_id = ? AND status = 'published' ORDER BY order_index", (subject_id,))
  chapters = [dict(row) for row in cursor.fetchall()]
  
  prev_chapter_completed = True
  
  for ch in chapters:
    # Get content items count
    cursor.execute("SELECT COUNT(*) FROM content_items WHERE chapter_id = ?", (ch['id'],))
    total_content = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM content_items WHERE chapter_id = ? AND type IN ('youtube', 'video')", (ch['id'],))
    ch['video_count'] = cursor.fetchone()[0] or 4
    
    # Get exams count & IDs for direct quick-jumps
    cursor.execute("SELECT id, type, target_marks FROM exam_papers WHERE chapter_id = ? AND status = 'published' ORDER BY id", (ch['id'],))
    ep_rows = cursor.fetchall()
    total_exams = len(ep_rows)
    ch['mock_exam_id'] = next((r[0] for r in ep_rows if r[1] != 'real'), None)
    ch['real_exam_id'] = next((r[0] for r in ep_rows if r[1] == 'real'), None)

    # Total questions and marks in chapter's primary exam
    primary_ep_id = ch['mock_exam_id'] or ch['real_exam_id']
    if primary_ep_id:
      cursor.execute("""
        SELECT COUNT(q.id), COALESCE(SUM(q.max_marks), 0)
        FROM questions q
        JOIN modules m ON q.module_id = m.id
        WHERE m.exam_paper_id = ? AND COALESCE(q.is_hidden, 0) = 0
      """, (primary_ep_id,))
      q_stats = cursor.fetchone()
      ch['total_questions'] = int(q_stats[0] or 0) if q_stats else 0
      ch['total_exam_marks'] = int(round(float(q_stats[1] or 0))) if q_stats else 0
    else:
      ch['total_questions'] = 0
      ch['total_exam_marks'] = 0
    
    total_items = total_content + total_exams
    
    # Completed content
    cursor.execute("""
      SELECT COUNT(*) FROM content_progress cp
      JOIN content_items ci ON cp.content_item_id = ci.id
      WHERE ci.chapter_id = ? AND cp.student_id = ? AND cp.completed = 1
    """, (ch['id'], student_id))
    completed_content = cursor.fetchone()[0]
    
    # Completed exams (a user completes an exam if they have a 'completed' attempt)
    cursor.execute("""
      SELECT COUNT(DISTINCT ep.id) FROM attempts a
      JOIN exam_papers ep ON a.exam_paper_id = ep.id
      WHERE ep.chapter_id = ? AND a.student_id = ? AND a.status = 'completed' AND ep.status = 'published'
    """, (ch['id'], student_id))
    completed_exams = cursor.fetchone()[0]

    # Check if student has any started/answered attempt in this chapter
    cursor.execute("""
      SELECT COUNT(DISTINCT ans.question_id) FROM answers ans
      JOIN questions q ON ans.question_id = q.id
      JOIN attempts a ON ans.attempt_id = a.id
      JOIN exam_papers ep ON a.exam_paper_id = ep.id
      WHERE ep.chapter_id = ? AND a.student_id = ? AND ans.is_latest = 1 AND COALESCE(q.is_hidden, 0) = 0
    """, (ch['id'], student_id))
    answered_in_chapter = int(cursor.fetchone()[0] or 0)
    ch['questions_answered'] = answered_in_chapter
    
    total_completed = completed_content + completed_exams
    ch['is_started'] = (total_completed > 0) or (answered_in_chapter > 0)
    
    # Calculate progress percentage
    partial_exam = min(0.95, answered_in_chapter / ch['total_questions']) if (ch['total_questions'] > 0 and completed_exams == 0 and answered_in_chapter > 0) else 0.0
    raw_pct = int(round(((total_completed + partial_exam) / total_items) * 100)) if total_items > 0 else 0
    if raw_pct == 0 and answered_in_chapter > 0:
      raw_pct = 10
    ch['progress_pct'] = min(100, raw_pct)
    
    is_completed = (total_items > 0 and total_items == total_completed) or (total_items == 0)
    
    if is_completed:
      ch['state'] = 'completed'
      prev_chapter_completed = True
    elif prev_chapter_completed:
      ch['state'] = 'unlocked'
      prev_chapter_completed = False
    else:
      ch['state'] = 'locked'
      prev_chapter_completed = False
      
  return chapters

def get_published_curriculum(conn, student_class_id: int, student_id: int):
  # Only return published chapters and their parent tree
  cursor = conn.cursor()
  cursor.execute("""
    SELECT c.*, s.class_id
    FROM chapters c
    JOIN subjects s ON c.subject_id = s.id
    WHERE c.status = 'published' AND COALESCE(s.is_hidden, 0) = 0
    ORDER BY c.order_index, c.id
  """)
  published_chapters = [dict(row) for row in cursor.fetchall()]
  
  cursor.execute("SELECT * FROM classes WHERE id = ? ORDER BY order_index, id", (student_class_id,))
  classes = [dict(row) for row in cursor.fetchall()]
  
  cursor.execute("SELECT * FROM subjects WHERE class_id IN (SELECT id FROM classes WHERE id = ?) AND COALESCE(is_hidden, 0) = 0 ORDER BY order_index, id", (student_class_id,))
  subjects = [dict(row) for row in cursor.fetchall()]
  
  # Rebuild tree
  tree = []
  for cls in classes:
    cls_node = dict(cls)
    cls_node['subjects'] = []
    for sub in subjects:
      if sub['class_id'] == cls['id']:
        sub_node = dict(sub)
        
        # Calculate states for chapters in this subject
        sub_chapters = []
        prev_chapter_completed = True # first chapter is unlocked by default
        
        for ch in published_chapters:
          if ch['subject_id'] == sub['id']:
            chapter_node = dict(ch)
            
            # fetch total content items and completed content items for this chapter
            cursor.execute("SELECT COUNT(*) FROM content_items WHERE chapter_id = ?", (ch['id'],))
            total_content = cursor.fetchone()[0]
            
            cursor.execute("""
              SELECT COUNT(*) FROM content_progress cp
              JOIN content_items ci ON cp.content_item_id = ci.id
              WHERE ci.chapter_id = ? AND cp.student_id = ? AND cp.completed = 1
            """, (ch['id'], student_id))
            completed_content = cursor.fetchone()[0]
            
            is_completed = (total_content > 0 and total_content == completed_content) or (total_content == 0)
            
            if is_completed:
              chapter_node['state'] = 'completed'
              prev_chapter_completed = True
            elif prev_chapter_completed:
              chapter_node['state'] = 'unlocked'
              prev_chapter_completed = False
            else:
              chapter_node['state'] = 'locked'
              prev_chapter_completed = False
              
            sub_chapters.append(chapter_node)
            
        sub_node['chapters'] = sub_chapters
        if len(sub_chapters) > 0:
          cls_node['subjects'].append(sub_node)
          
    if len(cls_node['subjects']) > 0:
      tree.append(cls_node)
      
  return tree

def get_chapter_with_content(conn, chapter_id: int, student_id: int):
  cursor = conn.cursor()
  cursor.execute("""
    SELECT c.*, s.name as subject_name
    FROM chapters c
    LEFT JOIN subjects s ON c.subject_id = s.id
    WHERE c.id = ? AND c.status = 'published'
  """, (chapter_id,))
  row = cursor.fetchone()
  if not row: return None
  
  chapter = dict(row)
  cursor.execute("SELECT * FROM content_items WHERE chapter_id = ? AND type IN ('youtube', 'video') ORDER BY order_index, id", (chapter_id,))
  chapter['content'] = [dict(r) for r in cursor.fetchall()]
  return chapter

def get_content_item(conn, content_id: int):
  cursor = conn.cursor()
  cursor.execute("SELECT * FROM content_items WHERE id = ?", (content_id,))
  row = cursor.fetchone()
  return dict(row) if row else None

# --- CONTENT PROGRESS ---

def log_content_time(conn, student_id: int, content_item_id: int, seconds: int):
    cursor = conn.cursor()
    cursor.execute("""
      INSERT INTO content_progress (student_id, content_item_id, progress_seconds, percent_complete, completed)
      VALUES (?, ?, ?, 0, 0)
      ON CONFLICT(student_id, content_item_id) DO UPDATE SET 
        progress_seconds = IFNULL(progress_seconds, 0) + ?
    """, (student_id, content_item_id, seconds, seconds))
    conn.commit()

def mark_content_complete(conn, student_id: int, content_item_id: int):
  cursor = conn.cursor()
  
  # Check if it was already completed to avoid farming XP
  cursor.execute("SELECT completed FROM content_progress WHERE student_id = ? AND content_item_id = ?", (student_id, content_item_id))
  row = cursor.fetchone()
  was_completed = row[0] if row else 0
  
  cursor.execute("""
    INSERT INTO content_progress (student_id, content_item_id, percent_complete, completed, completed_at)
    VALUES (?, ?, 100, 1, CURRENT_TIMESTAMP)
    ON CONFLICT(student_id, content_item_id) DO UPDATE SET 
      percent_complete = 100, 
      completed = 1, 
      completed_at = CURRENT_TIMESTAMP
  """, (student_id, content_item_id))
  conn.commit()
  
  if not was_completed:
    # Look up content title
    cursor.execute("SELECT title FROM content_items WHERE id = ?", (content_item_id,))
    ci_row = cursor.fetchone()
    content_title = ci_row[0] if ci_row else "a module"
    create_notification(conn, student_id, "Module Completed!", f"You have finished '{content_title}'!", "completion")
    record_daily_activity(conn, student_id, problems_delta=0, modules_delta=1, notify_streak=True)
    recalculate_user_xp(conn, student_id, notify=True)
  else:
    record_daily_activity(conn, student_id, problems_delta=0, modules_delta=0, notify_streak=False)
    recalculate_user_xp(conn, student_id, notify=False)

def get_completed_content_ids(conn, student_id: int, chapter_id: int):
  cursor = conn.cursor()
  cursor.execute("""
    SELECT cp.content_item_id 
    FROM content_progress cp
    JOIN content_items ci ON cp.content_item_id = ci.id
    WHERE cp.student_id = ? AND cp.completed = 1 AND ci.chapter_id = ?
  """, (student_id, chapter_id))
  return [row[0] for row in cursor.fetchall()]

# --- STUDENT EXAMS ---

def format_duration_str(seconds: int | float | None) -> str:
  if not seconds or int(seconds) <= 0:
    return ""
  s = int(round(float(seconds)))
  mins = s // 60
  rem = s % 60
  if mins >= 60:
    hrs = mins // 60
    mins = mins % 60
    return f"{hrs}h {mins}m {rem:02d}s"
  if mins > 0:
    return f"{mins}m {rem:02d}s"
  return f"{rem}s"


def _compute_attempt_duration_seconds(row_dict: dict) -> int:
  try:
    explicit_sec = int(row_dict.get("time_taken_seconds") or 0)
    if explicit_sec > 0:
      return explicit_sec
  except Exception:
    pass
  st = row_dict.get("started_at")
  comp = row_dict.get("completed_at")
  if st and comp:
    try:
      dt1 = datetime.datetime.strptime(str(st).split(".")[0], "%Y-%m-%d %H:%M:%S")
      dt2 = datetime.datetime.strptime(str(comp).split(".")[0], "%Y-%m-%d %H:%M:%S")
      diff = int((dt2 - dt1).total_seconds())
      if 5 <= diff <= 14400:
        return diff
    except Exception:
      pass
  return 0


def get_mock_speed_stats(conn, exam_paper_id: int, student_id: int) -> dict:
  """
  Computes the student's Mock Exam speed mastery progression (20m -> 15m -> 10m -> Real Exam Ready).
  """
  cursor = conn.cursor()
  cursor.execute("""
    SELECT a.id, a.started_at, a.completed_at, COALESCE(a.time_taken_seconds, 0) as time_taken_seconds,
           COALESCE(a.total_marks_awarded, 0) as total_marks_awarded,
           COALESCE(a.total_max_marks, 31) as total_max_marks,
           e.chapter_id
    FROM attempts a
    JOIN exam_papers e ON a.exam_paper_id = e.id
    WHERE a.exam_paper_id = ? AND a.student_id = ? AND a.status = 'completed'
    ORDER BY COALESCE(a.completed_at, a.started_at) ASC, a.id ASC
  """, (exam_paper_id, student_id))
  rows = [dict(r) for r in cursor.fetchall()]

  chapter_id = rows[0]["chapter_id"] if rows else None
  if not chapter_id:
    cursor.execute("SELECT chapter_id FROM exam_papers WHERE id = ?", (exam_paper_id,))
    ch_r = cursor.fetchone()
    chapter_id = ch_r[0] if ch_r else None

  real_exam_id = None
  if chapter_id:
    cursor.execute("""
      SELECT id FROM exam_papers
      WHERE chapter_id = ? AND status = 'published' AND type = 'real'
      ORDER BY id LIMIT 1
    """, (chapter_id,))
    re_r = cursor.fetchone()
    if re_r:
      real_exam_id = re_r[0]

  history = []
  valid_times = []
  for idx, r in enumerate(rows, start=1):
    sec = _compute_attempt_duration_seconds(r)
    if sec <= 0:
      sec = 1200  # default 20m if unrecorded
    max_m = float(r.get("total_max_marks") or 31)
    aw_m = float(r.get("total_marks_awarded") or 0)
    pct = min(100, int(round((aw_m / max_m) * 100))) if max_m > 0 else 0
    valid_times.append(sec)
    history.append({
      "run_number": idx,
      "attempt_id": r["id"],
      "seconds": sec,
      "time_str": format_duration_str(sec),
      "pct": pct,
      "marks": int(aw_m) if aw_m.is_integer() else round(aw_m, 1),
      "max_marks": int(max_m) if max_m.is_integer() else round(max_m, 1),
    })

  best_sec = min(valid_times) if valid_times else 0
  first_sec = valid_times[0] if valid_times else 0
  last_sec = valid_times[-1] if valid_times else 0
  prev_sec = valid_times[-2] if len(valid_times) >= 2 else first_sec

  # Progressive Goal Ladder:
  # Stage 1: No run yet or best > 20m (1200s) -> Goal is 20m (1200s)
  # Stage 2: Best is between 15m and 20m (901s..1200s) -> Goal is 15m (900s)
  # Stage 3: Best is between 10m and 15m (601s..900s) -> Goal is 10m (600s)
  # Stage 4: Best <= 10m (600s) -> Speed Mastered! Goal is 10m (or beating personal best)
  if best_sec == 0 or best_sec > 1200:
    target_sec = 1200
    target_label = "20m 00s"
    stage_num = 1
    stage_title = "Stage 1 Goal: Complete in under 20 mins"
  elif best_sec > 900:
    target_sec = 900
    target_label = "15m 00s"
    stage_num = 2
    stage_title = "Stage 2 Goal: Improve time to under 15 mins"
  elif best_sec > 600:
    target_sec = 600
    target_label = "10m 00s"
    stage_num = 3
    stage_title = "Stage 3 Goal: Master speed in under 10 mins"
  else:
    target_sec = 600
    target_label = "10m 00s"
    stage_num = 4
    stage_title = "Speed Mastered (<10 mins) — Ready for Real Exam!"

  saved_vs_first = max(0, first_sec - best_sec) if (first_sec > 0 and best_sec > 0) else 0
  saved_vs_prev = (prev_sec - last_sec) if (len(valid_times) >= 2) else 0

  return {
    "completed_runs": len(history),
    "best_seconds": best_sec,
    "best_str": format_duration_str(best_sec) if best_sec > 0 else "—",
    "first_seconds": first_sec,
    "first_str": format_duration_str(first_sec) if first_sec > 0 else "—",
    "last_seconds": last_sec,
    "last_str": format_duration_str(last_sec) if last_sec > 0 else "—",
    "saved_vs_first_seconds": saved_vs_first,
    "saved_vs_first_str": format_duration_str(saved_vs_first) if saved_vs_first > 0 else "",
    "saved_vs_prev_seconds": saved_vs_prev,
    "saved_vs_prev_str": format_duration_str(abs(saved_vs_prev)) if saved_vs_prev != 0 else "",
    "target_seconds": target_sec,
    "target_str": target_label,
    "stage_num": stage_num,
    "stage_title": stage_title,
    "speed_ready_for_real": bool(best_sec > 0 and best_sec <= 900),
    "real_exam_id": real_exam_id,
    "history": history,
  }


def get_available_exams(conn, chapter_id: int, student_id: int):
  cursor = conn.cursor()
  # Strict chapter path: after a "Restart chapter", only attempts finished since the restart count
  # towards best scores and the real-exam unlock (attempt limits still count every attempt).
  since = chapter_path_since(conn, student_id, chapter_id)
  # 1. Fetch all published exams
  cursor.execute("SELECT * FROM exam_papers WHERE chapter_id = ? AND status = 'published' ORDER BY id", (chapter_id,))
  exams = [dict(row) for row in cursor.fetchall()]
  
  # 2. Get highest scores for this student in this topic for ALL completed exams (measured against full paper max marks)
  cursor.execute("""
    SELECT sub.exam_paper_id, MAX(CAST(sub.total_marks_awarded AS FLOAT) / CAST(sub.total_max_marks AS FLOAT) * 100) as highest_pct
    FROM (
        SELECT
          a.exam_paper_id,
          COALESCE(SUM(ans.marks_awarded), a.total_marks_awarded, 0) as total_marks_awarded,
          COALESCE(
            NULLIF((SELECT SUM(COALESCE(q.max_marks, m.mark_value, 1)) FROM questions q JOIN modules m ON q.module_id = m.id WHERE m.exam_paper_id = e.id AND COALESCE(q.is_hidden, 0) = 0 AND COALESCE(q.textbook_section, 'Questions') NOT IN ('HOTS', 'POWER_UP')), 0),
            NULLIF((SELECT SUM(COALESCE(q.max_marks, m.mark_value, 1)) FROM questions q JOIN modules m ON q.module_id = m.id JOIN exam_papers em ON m.exam_paper_id = em.id WHERE em.chapter_id = e.chapter_id AND em.type = 'mock' AND COALESCE(q.is_hidden, 0) = 0 AND COALESCE(q.textbook_section, 'Questions') NOT IN ('HOTS', 'POWER_UP')), 0),
            NULLIF(e.target_marks, 0),
            NULLIF(a.total_max_marks, 0),
            0
          ) as total_max_marks
        FROM attempts a
        JOIN exam_papers e ON a.exam_paper_id = e.id
        LEFT JOIN answers ans ON a.id = ans.attempt_id AND ans.is_latest = 1
        WHERE a.student_id = ? AND e.chapter_id = ? AND a.status = 'completed'
          AND (? IS NULL OR a.completed_at >= ?)
        GROUP BY a.id, a.exam_paper_id
    ) sub
    WHERE sub.total_max_marks > 0
    GROUP BY sub.exam_paper_id
  """, (student_id, chapter_id, since, since))
  
  exam_scores = {row['exam_paper_id']: row['highest_pct'] for row in cursor.fetchall()}
  
  # Attach highest scores & Mock Exam Speed Mastery stats to all exams
  for exam in exams:
    exam['highest_score'] = exam_scores.get(exam['id'])
    exam['is_locked'] = False # Default state
    exam['hots_count'] = 0
    exam['powerup_count'] = 0
    if exam.get('type') != 'real':
      exam['speed_stats'] = get_mock_speed_stats(conn, exam['id'], student_id)
      cursor.execute("""
        SELECT UPPER(TRIM(COALESCE(q.textbook_section, ''))), COUNT(*)
        FROM questions q
        JOIN modules m ON q.module_id = m.id
        WHERE m.exam_paper_id = ? AND COALESCE(q.is_hidden, 0) = 0
          AND UPPER(TRIM(COALESCE(q.textbook_section, ''))) IN ('HOTS', 'POWER_UP')
        GROUP BY UPPER(TRIM(COALESCE(q.textbook_section, '')))
      """, (exam['id'],))
      for sec_name, cnt in cursor.fetchall():
        if sec_name == 'HOTS':
          exam['hots_count'] = int(cnt or 0)
        elif sec_name == 'POWER_UP':
          exam['powerup_count'] = int(cnt or 0)
  
  # 3. Determine if Real exams are locked based on Mock exams.
  mock_exams = [e for e in exams if e['type'] == 'mock']
  real_exams = [e for e in exams if e['type'] == 'real']
  
  if real_exams:
    # Get highest score across any completed mock exam in this chapter
    highest_mock_score = 0.0
    for mock in mock_exams:
      score = exam_scores.get(mock['id'])
      if score is None:
        score = 0.0
      if score > highest_mock_score:
        highest_mock_score = score
        
    for real in real_exams:
      req_mock = real.get('required_mock_percent') or max(((m.get('unlock_threshold_percent') or 0) for m in mock_exams), default=None)
      if req_mock == 0:
        req_mock = None
      # Strict chapter path: the real exam unlocks only with 100% in a practice exam
      if mock_exams:
        req_mock = 100.0
      if req_mock is not None:
        real['required_mock_percent'] = float(req_mock)
      real['best_mock_pct'] = min(100, int(round(highest_mock_score))) if highest_mock_score > 0 else 0

      cursor.execute(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN COALESCE(tab_switch_count, 0) < 99 AND (? IS NULL OR completed_at >= ?) THEN 1 ELSE 0 END), 0) FROM attempts WHERE student_id = ? AND exam_paper_id = ? AND status = 'completed'",
        (since, since, student_id, real['id'])
      )
      att_cnt_row = cursor.fetchone()
      attempts_count = int(att_cnt_row[0] or 0) if att_cnt_row else 0
      valid_completed_real = int(att_cnt_row[1] or 0) if att_cnt_row else 0
      real['attempts_taken'] = attempts_count

      if req_mock is not None and highest_mock_score < float(req_mock) and valid_completed_real == 0:
        real['is_locked'] = True
        real['unlock_reason'] = f"Requires {int(round(float(req_mock)))}% in Mock Exam (Highest: {int(round(highest_mock_score))}%)"
        
      # Check max_attempts (only count completed attempts)
      max_att = real.get('max_attempts')
      if max_att is not None and attempts_count >= max_att:
        real['is_locked'] = True
        real['unlock_reason'] = f"Max attempts reached ({max_att}/{max_att})"
          
  return exams

def get_exam_paper_full(conn, exam_id: int, seed_id: int = None):
  cursor = conn.cursor()
  cursor.execute("SELECT * FROM exam_papers WHERE id = ?", (exam_id,))
  row = cursor.fetchone()
  if not row: return None
  paper = dict(row)
  
  if paper.get('type') == 'real' and paper.get('use_mock_questions') == 1:
    # Fetch the mock exam for the same topic
    cursor.execute("SELECT id FROM exam_papers WHERE chapter_id = ? AND type = 'mock' LIMIT 1", (paper['chapter_id'],))
    mock_row = cursor.fetchone()
    if mock_row:
      mock_id = mock_row['id']
      # Fetch modules from mock exam, ordered by mark_value asc
      cursor.execute("SELECT * FROM modules WHERE exam_paper_id = ? ORDER BY mark_value ASC, id ASC", (mock_id,))
      paper['modules'] = [dict(r) for r in cursor.fetchall()]
      
      target_marks = paper.get('target_marks') or 100
      
      import random
      rng = random.Random(seed_id if seed_id is not None else exam_id)
      total_mock_marks = 0
      for module in paper['modules']:
        cursor.execute(
          "SELECT * FROM questions WHERE module_id = ? AND COALESCE(is_hidden, 0) = 0 AND COALESCE(textbook_section, 'Questions') NOT IN ('HOTS', 'POWER_UP') ORDER BY order_index, id",
          (module['id'],)
        )
        mod_qs = []
        for q_row in cursor.fetchall():
          qd = dict(q_row)
          qd['original_module_id'] = module['id']
          qd['original_module_name'] = module['name']
          if not qd.get('max_marks'):
            qd['max_marks'] = module.get('mark_value') or 1
          mod_qs.append(qd)
        module['questions'] = mod_qs
        mval = module.get('mark_value') or 1
        total_mock_marks += len(module['questions']) * mval
        
      if total_mock_marks <= target_marks:
        # Take all visible questions in clean textbook order within each module
        for module in paper['modules']:
          module['questions'].sort(key=lambda x: (x.get('textbook_order') if (x.get('textbook_order') and int(x.get('textbook_order')) > 0) else 999999, x.get('id') or 0))
        paper['modules'] = [m for m in paper['modules'] if len(m['questions']) > 0]
      else:
        ratio = target_marks / total_mock_marks
        current_marks = 0
        selected_modules = []
        
        # Proportional pick
        for module in paper['modules']:
          mod_qs = list(module['questions'])
          rng.shuffle(mod_qs)
          mval = module.get('mark_value') or 1
          mod_marks = len(mod_qs) * mval
          target_mod_marks = mod_marks * ratio
          target_q_count = int(round(target_mod_marks / mval))
          
          selected_qs = mod_qs[:target_q_count]
          current_marks += len(selected_qs) * mval
          
          new_mod = dict(module)
          new_mod['questions'] = selected_qs
          selected_modules.append(new_mod)
        
        # Greedy fill if we are under target_marks
        if current_marks < target_marks:
          pool = []
          for i, module in enumerate(paper['modules']):
            orig_qs = module['questions']
            sel_qs = selected_modules[i]['questions']
            unsel = [q for q in orig_qs if q not in sel_qs]
            mval = module.get('mark_value') or 1
            for q in unsel:
              pool.append((q, mval, i))
              
          rng.shuffle(pool)
          
          for item in pool:
            q, mval, idx = item
            if current_marks + mval <= target_marks:
              selected_modules[idx]['questions'].append(q)
              current_marks += mval
            if current_marks == target_marks:
              break
              
        paper['modules'] = [m for m in selected_modules if len(m['questions']) > 0]

      # Also build mark_modules and textbook_modules for Real Exam UI toggle
      mark_modules = paper['modules']
      all_textbook_qs = []
      for mod in mark_modules:
        for qd in mod['questions']:
          all_textbook_qs.append(dict(qd))
      all_textbook_qs.sort(key=lambda x: (x.get('textbook_order') if (x.get('textbook_order') and int(x.get('textbook_order')) > 0) else 999999, x.get('id') or 0))
      for idx_tb, tq in enumerate(all_textbook_qs, start=1):
        tq['textbook_num'] = idx_tb
      first_mod_id = mark_modules[0]['id'] if mark_modules else paper['id']
      paper['mark_modules'] = mark_modules
      paper['textbook_modules'] = [
        {
          "id": first_mod_id,
          "exam_paper_id": paper['id'],
          "name": "Textbook Order",
          "mark_value": 1,
          "order_index": 1,
          "question_type": "CUSTOM",
          "questions": all_textbook_qs
        }
      ] if all_textbook_qs else []
      paper['default_sort_mode'] = 'textbook'
      return paper

  # Normal behavior: build both Mark-Based modules and Textbook-Order modules
  # Extra sections ('HOTS' and 'POWER_UP') are NEVER mixed into the main questions; they appear AFTER the main questions in dedicated bannered groups.
  import json as _json
  import re as _re

  def _parse_add_videos(raw_val):
    if not raw_val:
      return []
    if isinstance(raw_val, list):
      return list(raw_val)
    if isinstance(raw_val, str):
      try:
        parsed = _json.loads(raw_val)
        return parsed if isinstance(parsed, list) else []
      except Exception:
        return []
    return []

  def _tb_sort_key(q_obj):
    tb_ord = q_obj.get('textbook_order')
    return (int(tb_ord) if (tb_ord and int(tb_ord) > 0) else 999999, q_obj.get('id') or 0)

  cursor.execute("SELECT * FROM modules WHERE exam_paper_id = ? ORDER BY order_index, id", (paper['id'],))
  raw_mark_modules = [dict(r) for r in cursor.fetchall()]

  mark_modules = []
  main_textbook_qs = []
  hots_qs = []
  powerup_qs = []

  for module in raw_mark_modules:
    cursor.execute("SELECT * FROM questions WHERE module_id = ? AND COALESCE(is_hidden, 0) = 0 ORDER BY order_index, id", (module['id'],))
    mod_main_qs = []
    for q_row in cursor.fetchall():
      qd = dict(q_row)
      qd['original_module_id'] = module['id']
      qd['original_module_name'] = module['name']
      if not qd.get('max_marks'):
        qd['max_marks'] = module.get('mark_value') or 1
      qd['additional_videos'] = _parse_add_videos(qd.get('additional_videos'))
      sec_raw = str(qd.get('textbook_section') or 'Questions').strip().upper()
      if sec_raw == 'HOTS':
        qd['section_group'] = 'HOTS'
        qd['is_extra_question'] = True
        hots_qs.append(dict(qd))
      elif sec_raw == 'POWER_UP':
        qd['section_group'] = 'POWER_UP'
        qd['is_extra_question'] = True
        powerup_qs.append(dict(qd))
      else:
        qd['section_group'] = 'MAIN'
        qd['is_extra_question'] = False
        mod_main_qs.append(qd)
        main_textbook_qs.append(dict(qd))

    module['section_group'] = 'MAIN'
    module['is_extra_module'] = False
    module['questions'] = mod_main_qs
    if mod_main_qs:
      mark_modules.append(module)

  # Sort Main, HOTS, and Power Up strictly by textbook_order
  main_textbook_qs.sort(key=_tb_sort_key)
  hots_qs.sort(key=_tb_sort_key)
  powerup_qs.sort(key=_tb_sort_key)

  main_total = len(main_textbook_qs)
  main_by_id = {}
  for idx_tb, tq in enumerate(main_textbook_qs, start=1):
    tq['textbook_num'] = idx_tb
    tq['display_label'] = str(idx_tb)
    tq['short_badge'] = f"Q{idx_tb}"
    tq['header_counter'] = f"Question {idx_tb} of {main_total}"
    tq['part_badge'] = ""
    tq['banner_title'] = ""
    tq['banner_subtitle'] = ""
    tq['primary_video_label'] = "Video Explanation"
    main_by_id[tq['id']] = tq

  # Sync rich labels onto mark_modules copies as well
  for mod in mark_modules:
    for mq in mod['questions']:
      ref = main_by_id.get(mq['id'])
      if ref:
        for k in ('textbook_num', 'display_label', 'short_badge', 'header_counter', 'part_badge', 'banner_title', 'banner_subtitle', 'primary_video_label'):
          mq[k] = ref[k]

  last_hots_num = 0
  for hq in hots_qs:
    part_match = _re.match(r'^(\d+)\(([a-zA-Z])\)\.\s*', str(hq.get('question_text') or '').strip())
    if part_match:
      b_num = int(part_match.group(1))
      p_let = part_match.group(2).lower()
      last_hots_num = max(last_hots_num, b_num)
      hq['display_label'] = f"{b_num}({p_let})"
      hq['short_badge'] = f"HOTS {b_num}({p_let})"
      hq['header_counter'] = f"HOTS Extra • Question {b_num}({p_let})"
      hq['part_badge'] = f"HOTS Question {b_num} • Part ({p_let}) — Separate Video Mapped"
      hq['primary_video_label'] = f"Part {b_num}({p_let}) Video"
    else:
      last_hots_num += 1
      hq['display_label'] = str(last_hots_num)
      hq['short_badge'] = f"HOTS {last_hots_num}"
      hq['header_counter'] = f"HOTS Extra • Question {last_hots_num}"
      hq['part_badge'] = ""
      hq['primary_video_label'] = f"HOTS {last_hots_num} Video"
    hq['textbook_num'] = hq['display_label']
    hq['banner_title'] = "HOTS — Higher Order Thinking"
    hq['banner_subtitle'] = "Higher Order Thinking Questions"

  pu_total = len(powerup_qs)
  for idx_pu, pq in enumerate(powerup_qs, start=1):
    pq['textbook_num'] = str(idx_pu)
    pq['display_label'] = str(idx_pu)
    pq['short_badge'] = f"Power Up {idx_pu}"
    pq['header_counter'] = f"Power Up • Question {idx_pu} of {pu_total}"
    pq['part_badge'] = ""
    pq['banner_title'] = "Power Up — Exam Booster Practice"
    pq['banner_subtitle'] = "Multi-Statement MCQ"
    pq['primary_video_label'] = f"Power Up {idx_pu} Video"

  has_extra_sections = bool(hots_qs or powerup_qs)
  first_mod_id = mark_modules[0]['id'] if mark_modules else paper['id']

  textbook_modules = []
  if main_textbook_qs:
    textbook_modules.append({
      "id": first_mod_id,
      "exam_paper_id": paper['id'],
      "name": f"Main Textbook Exercises (1–{main_total})" if has_extra_sections else "Textbook Order",
      "mark_value": 1,
      "order_index": 1,
      "question_type": "CUSTOM",
      "section_group": "MAIN",
      "is_extra_module": False,
      "banner_title": "",
      "banner_subtitle": "",
      "questions": main_textbook_qs,
    })

  if hots_qs:
    hots_mod = {
      "id": 9000 + int(paper['id']),
      "exam_paper_id": paper['id'],
      "name": "HOTS — Higher Order Thinking",
      "mark_value": 2,
      "order_index": 90,
      "question_type": "SHORT_ANSWER",
      "section_group": "HOTS",
      "is_extra_module": True,
      "banner_title": "HOTS — Higher Order Thinking",
      "banner_subtitle": "Higher Order Thinking Questions",
      "questions": hots_qs,
    }
    textbook_modules.append(hots_mod)
    mark_modules.append({**hots_mod, "questions": [dict(q) for q in hots_qs]})

  if powerup_qs:
    pu_mod = {
      "id": 9500 + int(paper['id']),
      "exam_paper_id": paper['id'],
      "name": "Power Up — Exam Booster Practice",
      "mark_value": 1,
      "order_index": 95,
      "question_type": "MCQ",
      "section_group": "POWER_UP",
      "is_extra_module": True,
      "banner_title": "Power Up — Exam Booster Practice",
      "banner_subtitle": "Multi-Statement MCQ",
      "questions": powerup_qs,
    }
    textbook_modules.append(pu_mod)
    mark_modules.append({**pu_mod, "questions": [dict(q) for q in powerup_qs]})

  paper['has_extra_sections'] = has_extra_sections
  paper['main_questions_count'] = main_total
  paper['hots_questions_count'] = len(hots_qs)
  paper['powerup_questions_count'] = len(powerup_qs)
  paper['mark_modules'] = mark_modules
  paper['textbook_modules'] = textbook_modules
  # Default to Textbook Order; student can toggle to Mark-Based or switch sections anytime
  paper['modules'] = textbook_modules if textbook_modules else mark_modules
  paper['default_sort_mode'] = 'textbook'

  return paper

def start_exam_attempt(conn, exam_paper_id: int, version: int, student_id: int, force_new: bool = False):
  import time
  cursor = conn.cursor()
  cursor.execute("SELECT id FROM exam_papers WHERE id = ?", (exam_paper_id or 1,))
  valid_ep = cursor.fetchone()
  if not valid_ep:
    cursor.execute("SELECT id FROM exam_papers ORDER BY id ASC LIMIT 1")
    first_ep = cursor.fetchone()
    exam_paper_id = first_ep[0] if first_ep else 1

  cursor.execute("SELECT id FROM users WHERE id = ?", (student_id,))
  if not cursor.fetchone():
    try:
      cursor.execute(
        "INSERT OR IGNORE INTO users (id, name, email, password_hash, role, class_id) VALUES (?, ?, ?, 'serverless', 'student', 1)",
        (student_id, f"Student {student_id}", f"student_{student_id}@saxaz.local")
      )
      conn.commit()
    except Exception:
      pass

  if force_new:
    # Close any empty in_progress attempts or mark non-empty in_progress attempts as abandoned/completed so a fresh timed run begins
    cursor.execute(
      "DELETE FROM attempts WHERE exam_paper_id = ? AND student_id = ? AND status = 'in_progress' AND id NOT IN (SELECT DISTINCT attempt_id FROM answers)",
      (exam_paper_id, student_id)
    )
    cursor.execute(
      "UPDATE attempts SET status = 'completed', completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP) WHERE exam_paper_id = ? AND student_id = ? AND status = 'in_progress'",
      (exam_paper_id, student_id)
    )
    conn.commit()
  else:
    cursor.execute(
      "SELECT id FROM attempts WHERE exam_paper_id = ? AND student_id = ? AND status = 'in_progress' ORDER BY id DESC LIMIT 1",
      (exam_paper_id, student_id)
    )
    existing = cursor.fetchone()
    if existing and existing[0] > 1000:
      return existing[0]
  # Encode exam_paper_id in the lowest 3 digits so any serverless instance can self-heal this attempt
  new_id = ((int(time.time() * 10) + (student_id % 997)) % 1000000) * 1000 + (int(exam_paper_id) % 1000)
  try:
    cursor.execute(
      "INSERT OR REPLACE INTO attempts (id, exam_paper_id, exam_paper_version, student_id, status) VALUES (?, ?, ?, ?, 'in_progress')",
      (new_id, exam_paper_id, version or 1, student_id)
    )
    conn.commit()
  except Exception:
    cursor.execute(
      "INSERT INTO attempts (exam_paper_id, exam_paper_version, student_id, status) VALUES (?, ?, ?, 'in_progress')",
      (exam_paper_id, version or 1, student_id)
    )
    new_id = cursor.lastrowid
    conn.commit()
  return new_id

def ensure_serverless_attempt(conn, attempt_id: int, student_id: int, exam_paper_id: int = None, question_id: int = None) -> int:
  cursor = conn.cursor()
  cursor.execute("SELECT id FROM users WHERE id = ?", (student_id,))
  if not cursor.fetchone():
    try:
      cursor.execute(
        "INSERT OR IGNORE INTO users (id, name, email, password_hash, role, class_id) VALUES (?, ?, ?, 'serverless', 'student', 1)",
        (student_id, f"Student {student_id}", f"student_{student_id}@saxaz.local")
      )
      conn.commit()
    except Exception:
      pass

  row = None
  if attempt_id and attempt_id > 0:
    cursor.execute("SELECT id, student_id, exam_paper_id FROM attempts WHERE id = ?", (attempt_id,))
    row = cursor.fetchone()
    if row and row[1] == student_id:
      return attempt_id

  ep_id = None
  if question_id:
    cursor.execute("SELECT m.exam_paper_id FROM questions q JOIN modules m ON q.module_id = m.id WHERE q.id = ?", (question_id,))
    q_row = cursor.fetchone()
    if q_row:
      ep_id = q_row[0]
  if not ep_id and exam_paper_id:
    try:
      ep_id = int(exam_paper_id)
    except Exception:
      ep_id = None
  if not ep_id and attempt_id and attempt_id > 1000:
    ep_id = attempt_id % 1000
  if not ep_id and row:
    ep_id = row[2]

  cursor.execute("SELECT id FROM exam_papers WHERE id = ?", (ep_id or 1,))
  valid_ep = cursor.fetchone()
  if not valid_ep:
    cursor.execute("SELECT id FROM exam_papers ORDER BY id ASC LIMIT 1")
    first_ep = cursor.fetchone()
    ep_id = first_ep[0] if first_ep else 1
  else:
    ep_id = valid_ep[0]

  if not attempt_id or attempt_id <= 0:
    return start_exam_attempt(conn, ep_id, 1, student_id)

  if not row:
    try:
      cursor.execute(
        "INSERT OR IGNORE INTO attempts (id, exam_paper_id, exam_paper_version, student_id, status) VALUES (?, ?, 1, ?, 'in_progress')",
        (attempt_id, ep_id, student_id)
      )
      conn.commit()
      cursor.execute("SELECT id FROM attempts WHERE id = ?", (attempt_id,))
      if cursor.fetchone():
        return attempt_id
    except Exception:
      pass

  # Collision or FK fallback: allocate a fresh collision-free attempt
  return start_exam_attempt(conn, ep_id, 1, student_id)

def get_attempt_saved_answers(conn, attempt_id: int) -> dict:
  cursor = conn.cursor()
  cursor.execute("SELECT student_id FROM attempts WHERE id = ?", (attempt_id,))
  att_row = cursor.fetchone()
  student_id = att_row[0] if att_row else None

  cursor.execute("""
    SELECT ans.id as ans_id, ans.question_id, ans.answer_text, ans.marks_awarded, ans.percent_correct,
           ans.ai_feedback, ans.drawing_url, COALESCE(ans.retry_count, 0) as retry_count,
           COALESCE(q.max_marks, m.mark_value, 1) as max_marks,
           q.model_answer, q.explanation_video_url, q.explanation_video_type, q.additional_videos
    FROM answers ans
    JOIN questions q ON ans.question_id = q.id
    JOIN modules m ON q.module_id = m.id
    WHERE ans.attempt_id = ? AND ans.is_latest = 1 AND COALESCE(q.is_hidden, 0) = 0
  """, (attempt_id,))
  out = {}
  for r in cursor.fetchall():
    row = dict(r)
    q_id = row['question_id']
    max_m = float(row.get('max_marks') or 1)
    marks = float(row.get('marks_awarded') or 0)
    retry_cnt = int(row.get('retry_count') or 0)

    # Check if there is a previous answer (either in the same attempt or an earlier attempt by this student)
    cursor.execute("""
      SELECT answer_text, marks_awarded
      FROM answers
      WHERE attempt_id = ? AND question_id = ? AND is_latest = 0 AND id < ?
      ORDER BY id DESC LIMIT 1
    """, (attempt_id, q_id, row['ans_id']))
    prev_row = cursor.fetchone()
    if not prev_row and student_id:
      cursor.execute("""
        SELECT a2.answer_text, a2.marks_awarded
        FROM answers a2
        JOIN attempts att2 ON a2.attempt_id = att2.id
        WHERE att2.student_id = ? AND a2.question_id = ? AND a2.attempt_id < ? AND a2.is_latest = 1
        ORDER BY a2.id DESC LIMIT 1
      """, (student_id, q_id, attempt_id))
      prev_row = cursor.fetchone()

    is_retry = bool(prev_row is not None or retry_cnt > 0)
    prev_marks = float(prev_row['marks_awarded'] or 0) if prev_row else None
    prev_ans = (prev_row['answer_text'] or "") if prev_row else ""
    imp_delta = round(marks - prev_marks, 2) if prev_marks is not None else 0.0
    imp_pct = round(((marks - prev_marks) / max_m) * 100.0, 1) if (prev_marks is not None and max_m > 0) else 0.0

    out[str(q_id)] = {
      "success": True,
      "marks": marks,
      "max_marks": max_m,
      "feedback": row.get('ai_feedback') or "",
      "ideal_answer": row.get('model_answer') or "",
      "is_correct": marks >= (max_m * 0.5),
      "explanation_video_url": row.get('explanation_video_url') or "",
      "explanation_video_type": row.get('explanation_video_type') or "",
      "additional_videos": row.get('additional_videos') or "[]",
      "is_retry": is_retry,
      "retry_count": max(retry_cnt, 1 if is_retry else 0),
      "previous_marks": prev_marks,
      "previous_answer": prev_ans,
      "improvement_delta": imp_delta,
      "improvement_pct": imp_pct,
      "_savedAnswerText": row.get('answer_text') or "",
      "_savedAttachedDrawing": row.get('drawing_url') or None,
    }
  return out

def save_answer(conn, attempt_id: int, question_id: int, module_id: int, answer_text: str, marks: float, max_marks: float, feedback: str, drawing_url: str = "", notify_xp: bool = True):
  cursor = conn.cursor()
  
  # Get student_id
  cursor.execute("SELECT student_id FROM attempts WHERE id = ?", (attempt_id,))
  student_row = cursor.fetchone()
  if not student_row:
      raise ValueError("Invalid attempt_id")
  student_id = student_row[0]
  
  # Get current max retry_count
  cursor.execute("SELECT MAX(retry_count) FROM answers WHERE attempt_id = ? AND question_id = ?", (attempt_id, question_id))
  row = cursor.fetchone()
  current_retry = row[0] if row[0] is not None else -1
  new_retry = current_retry + 1
  
  # Mark old answers as not latest
  cursor.execute("UPDATE answers SET is_latest = 0 WHERE attempt_id = ? AND question_id = ?", (attempt_id, question_id))
  
  percent = (marks / max_marks) * 100 if max_marks > 0 else 0
  cursor.execute(
    """INSERT INTO answers 
    (attempt_id, question_id, module_id, answer_text, marks_awarded, percent_correct, ai_feedback, retry_count, is_latest, drawing_url) 
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
    (attempt_id, question_id, module_id, answer_text, marks, percent, feedback, new_retry, drawing_url or "")
  )
  conn.commit()
  
  # UPDATE DAILY ACTIVITY (STREAK) — every non-blank answer counts toward today's problem solving
  is_blank = (answer_text or "").strip().lower() in ("", "no answer provided")
  if not is_blank:
      record_daily_activity(conn, student_id, problems_delta=1, modules_delta=0, notify_streak=True)
  else:
      record_daily_activity(conn, student_id, problems_delta=0, modules_delta=0, notify_streak=False)

  # UPDATE AUTHENTIC XP
  recalculate_user_xp(conn, student_id, notify=notify_xp)

def complete_attempt(conn, attempt_id: int, time_taken_seconds: int = None):
  cursor = conn.cursor()
  cursor.execute("""
    SELECT att.student_id, ep.type, att.started_at, COALESCE(att.time_taken_seconds, 0)
    FROM attempts att
    JOIN exam_papers ep ON att.exam_paper_id = ep.id
    WHERE att.id = ?
  """, (attempt_id,))
  s_row = cursor.fetchone()
  student_id = s_row[0] if s_row else None
  exam_type = s_row[1] if s_row else 'mock'
  started_at_val = s_row[2] if s_row else None
  existing_time_sec = int(s_row[3] or 0) if s_row else 0

  final_time_sec = existing_time_sec
  if time_taken_seconds is not None:
    try:
      t_val = int(round(float(time_taken_seconds)))
      if t_val > 0:
        final_time_sec = t_val
    except Exception:
      pass
  if final_time_sec <= 0 and started_at_val:
    try:
      dt_start = datetime.datetime.strptime(str(started_at_val).split(".")[0], "%Y-%m-%d %H:%M:%S")
      diff = int((datetime.datetime.utcnow() - dt_start).total_seconds())
      if 5 <= diff <= 14400:
        final_time_sec = diff
    except Exception:
      pass

  # Aggregate scores (only for the latest attempt per question)
  cursor.execute("""
    SELECT COALESCE(SUM(ans.marks_awarded), 0), COALESCE(SUM(COALESCE(q.max_marks, m.mark_value, 1)), 0)
    FROM answers ans
    JOIN questions q ON ans.question_id = q.id
    JOIN modules m ON q.module_id = m.id
    WHERE ans.attempt_id = ? AND ans.is_latest = 1 AND COALESCE(q.is_hidden, 0) = 0
      AND TRIM(COALESCE(ans.answer_text, '')) NOT IN ('', 'No answer provided', 'no answer provided')
  """, (attempt_id,))
  ans_row = cursor.fetchone()
  total_marks = float(ans_row[0] or 0) if ans_row else 0.0
  answered_max = float(ans_row[1] or 0) if ans_row else 0.0

  # Also sum max marks across ALL submitted latest answers (including 'No answer provided' in Real Exams)
  cursor.execute("""
    SELECT COALESCE(SUM(COALESCE(q.max_marks, m.mark_value, 1)), 0)
    FROM answers ans
    JOIN questions q ON ans.question_id = q.id
    JOIN modules m ON q.module_id = m.id
    WHERE ans.attempt_id = ? AND ans.is_latest = 1 AND COALESCE(q.is_hidden, 0) = 0
  """, (attempt_id,))
  all_ans_row = cursor.fetchone()
  all_submitted_max = float(all_ans_row[0] or 0) if all_ans_row else 0.0

  # Calculate full paper max marks from modules for the entire exam (so unfinished 1-question runs never fake 100%)
  cursor.execute("""
    SELECT COALESCE(
      NULLIF((
        SELECT SUM(COALESCE(q.max_marks, m.mark_value, 1))
        FROM modules m
        JOIN questions q ON q.module_id = m.id
        WHERE m.exam_paper_id = att.exam_paper_id AND COALESCE(q.is_hidden, 0) = 0
          AND COALESCE(q.textbook_section, 'Questions') NOT IN ('HOTS', 'POWER_UP')
      ), 0),
      NULLIF((
        SELECT SUM(COALESCE(q2.max_marks, m2.mark_value, 1))
        FROM exam_papers ep_mock
        JOIN modules m2 ON m2.exam_paper_id = ep_mock.id
        JOIN questions q2 ON q2.module_id = m2.id
        WHERE ep_mock.chapter_id = ep.chapter_id AND ep_mock.type = 'mock' AND COALESCE(q2.is_hidden, 0) = 0
          AND COALESCE(q2.textbook_section, 'Questions') NOT IN ('HOTS', 'POWER_UP')
      ), 0),
      0
    )
    FROM attempts att
    JOIN exam_papers ep ON att.exam_paper_id = ep.id
    WHERE att.id = ?
  """, (attempt_id,))
  tm_mod_row = cursor.fetchone()
  total_max = float(tm_mod_row[0] or 0) if tm_mod_row else 0.0
  if all_submitted_max > total_max:
    total_max = all_submitted_max

  # Fallback if still 0
  if total_max == 0 and all_submitted_max > 0:
    total_max = all_submitted_max
  if total_max == 0 and answered_max > 0:
    total_max = answered_max

  if total_max == 0:
    cursor.execute("""
      SELECT ep.target_marks
      FROM attempts att
      JOIN exam_papers ep ON att.exam_paper_id = ep.id
      WHERE att.id = ?
    """, (attempt_id,))
    tm_row = cursor.fetchone()
    total_max = float(tm_row[0] if tm_row and tm_row[0] else 0)
  
  cursor.execute(
    "UPDATE attempts SET status = 'completed', completed_at = CURRENT_TIMESTAMP, total_marks_awarded = ?, total_max_marks = ?, time_taken_seconds = CASE WHEN ? > 0 THEN ? ELSE COALESCE(time_taken_seconds, 0) END WHERE id = ?",
    (total_marks, total_max, final_time_sec, final_time_sec, attempt_id)
  )
  conn.commit()

  if student_id:
    record_daily_activity(conn, student_id, problems_delta=0, modules_delta=1, notify_streak=True)
    recalculate_user_xp(conn, student_id, notify=True)

def get_attempt_full(conn, attempt_id: int):
  cursor = conn.cursor()
  cursor.execute("""
    SELECT a.*, e.title as exam_title, e.chapter_id, e.type as exam_type
    FROM attempts a
    JOIN exam_papers e ON a.exam_paper_id = e.id
    WHERE a.id = ?
  """, (attempt_id,))
  row = cursor.fetchone()
  if not row:
    return None
  attempt = dict(row)
  if attempt.get('total_max_marks') is None:
    attempt['total_max_marks'] = 0
  if attempt.get('total_marks_awarded') is None:
    attempt['total_marks_awarded'] = 0

  # Attach the chapter's Mock Exam ID so Real Exam results can link directly to it
  attempt['mock_exam_id'] = None
  if attempt.get('chapter_id'):
    cursor.execute("""
      SELECT id FROM exam_papers
      WHERE chapter_id = ? AND status = 'published' AND COALESCE(type, 'mock') != 'real'
      ORDER BY id LIMIT 1
    """, (attempt['chapter_id'],))
    mock_row = cursor.fetchone()
    if mock_row:
      attempt['mock_exam_id'] = mock_row['id']
  
  # Get answers with question details (only latest)
  cursor.execute("""
    SELECT a.*, q.question_text, q.model_answer, COALESCE(q.max_marks, m.mark_value, 1) as max_marks,
           COALESCE(q.question_type, m.question_type, 'LONG_ANSWER') as question_type,
           q.options as options_json, q.media_url, q.answer_media_url, q.explanation_video_url, q.explanation_video_type,
           COALESCE(q.textbook_section, 'Questions') as textbook_section,
           m.name as module_name
    FROM answers a
    JOIN questions q ON a.question_id = q.id
    JOIN modules m ON a.module_id = m.id
    WHERE a.attempt_id = ? AND a.is_latest = 1 AND COALESCE(q.is_hidden, 0) = 0
    ORDER BY COALESCE(CASE WHEN q.textbook_order > 0 THEN q.textbook_order END, 999999), m.order_index, m.id, q.order_index, q.id
  """, (attempt_id,))
  answers_list = [dict(r) for r in cursor.fetchall()]
  student_id = attempt.get('student_id')

  for ans in answers_list:
    tb_sec = str(ans.get('textbook_section') or 'Questions').strip().upper()
    if tb_sec == 'HOTS':
      ans['section_group'] = 'HOTS'
      ans['is_extra'] = True
      ans['module_name'] = 'HOTS — Higher Order Thinking'
    elif tb_sec == 'POWER_UP':
      ans['section_group'] = 'POWER_UP'
      ans['is_extra'] = True
      ans['module_name'] = 'Power Up — Exam Booster Practice'
    else:
      ans['section_group'] = 'MAIN'
      ans['is_extra'] = False
    q_id = ans['question_id']
    curr_marks = float(ans.get('marks_awarded') or 0)
    max_m = float(ans.get('max_marks') or 1)
    retry_cnt = int(ans.get('retry_count') or 0)

    # Check if there is a previous answer in the same attempt or an earlier attempt by this student
    cursor.execute("""
      SELECT answer_text, marks_awarded
      FROM answers
      WHERE attempt_id = ? AND question_id = ? AND is_latest = 0 AND id < ?
      ORDER BY id DESC LIMIT 1
    """, (attempt_id, q_id, ans['id']))
    prev_row = cursor.fetchone()
    if not prev_row and student_id:
      cursor.execute("""
        SELECT a2.answer_text, a2.marks_awarded
        FROM answers a2
        JOIN attempts att2 ON a2.attempt_id = att2.id
        WHERE att2.student_id = ? AND a2.question_id = ? AND a2.attempt_id < ? AND a2.is_latest = 1
        ORDER BY a2.id DESC LIMIT 1
      """, (student_id, q_id, attempt_id))
      prev_row = cursor.fetchone()

    if prev_row is not None:
      prev_marks = float(prev_row['marks_awarded'] or 0)
      ans['is_retry'] = True
      ans['retry_count'] = max(retry_cnt, 1)
      ans['previous_marks'] = prev_marks
      ans['previous_answer'] = prev_row['answer_text'] or ""
      ans['improvement_delta'] = round(curr_marks - prev_marks, 2)
      ans['improvement_pct'] = round(((curr_marks - prev_marks) / max_m) * 100.0, 1) if max_m > 0 else 0.0
    else:
      ans['is_retry'] = False
      ans['retry_count'] = 0
      ans['previous_marks'] = None
      ans['previous_answer'] = ""
      ans['improvement_delta'] = 0.0
      ans['improvement_pct'] = 0.0

  # Build ordered module_groups: ALL Main modules FIRST, then HOTS (Extra), then POWER UP (Extra)
  import re as _re_att
  main_mod_map = {}
  main_mod_order = []
  hots_ans_group = []
  powerup_ans_group = []
  for ans in answers_list:
    sg = ans.get('section_group', 'MAIN')
    if sg == 'HOTS':
      hots_ans_group.append(ans)
    elif sg == 'POWER_UP':
      powerup_ans_group.append(ans)
    else:
      m_name = ans.get('module_name') or 'Main Questions'
      if m_name not in main_mod_map:
        main_mod_map[m_name] = []
        main_mod_order.append(m_name)
      main_mod_map[m_name].append(ans)

  def _assign_group_labels(grp_items, is_hots=False):
    last_num = 0
    for item in grp_items:
      raw_qt = str(item.get('question_text') or '').strip()
      pm = _re_att.match(r'^(\d+)\(([a-zA-Z])\)\.\s*(.*)$', raw_qt, _re_att.DOTALL)
      if pm:
        b_num = int(pm.group(1))
        p_let = pm.group(2).lower()
        last_num = max(last_num, b_num)
        item['display_label'] = f"{b_num}({p_let})"
        item['clean_question_text'] = pm.group(3).strip()
      else:
        last_num += 1
        item['display_label'] = str(last_num)
        item['clean_question_text'] = raw_qt

  module_groups = []
  for m_name in main_mod_order:
    grp = main_mod_map[m_name]
    _assign_group_labels(grp, is_hots=False)
    module_groups.append({
      "module_name": m_name,
      "section_group": "MAIN",
      "is_extra": False,
      "answers": grp,
    })
  if hots_ans_group:
    _assign_group_labels(hots_ans_group, is_hots=True)
    module_groups.append({
      "module_name": "HOTS — Higher Order Thinking",
      "section_group": "HOTS",
      "is_extra": True,
      "answers": hots_ans_group,
    })
  if powerup_ans_group:
    _assign_group_labels(powerup_ans_group, is_hots=False)
    module_groups.append({
      "module_name": "Power Up — Exam Booster Practice",
      "section_group": "POWER_UP",
      "is_extra": True,
      "answers": powerup_ans_group,
    })

  attempt['answers'] = answers_list
  attempt['module_groups'] = module_groups
  answered_max_sum = round(sum(float(ans.get('max_marks') or 0) for ans in attempt['answers']), 2)
  cursor.execute("""
    SELECT COALESCE(
      NULLIF((SELECT SUM(COALESCE(q.max_marks, m.mark_value, 1)) FROM questions q JOIN modules m ON q.module_id = m.id WHERE m.exam_paper_id = ? AND COALESCE(q.is_hidden, 0) = 0 AND COALESCE(q.textbook_section, 'Questions') NOT IN ('HOTS', 'POWER_UP')), 0),
      NULLIF(target_marks, 0),
      0
    )
    FROM exam_papers WHERE id = ?
  """, (attempt['exam_paper_id'], attempt['exam_paper_id']))
  ep_max_row = cursor.fetchone()
  paper_full_max = round(float(ep_max_row[0] or 0), 2) if ep_max_row else 0.0
  if paper_full_max > 0 and (attempt['total_max_marks'] == 0 or attempt['total_max_marks'] < paper_full_max):
    attempt['total_max_marks'] = int(paper_full_max) if paper_full_max.is_integer() else paper_full_max
  elif attempt['total_max_marks'] == 0 and answered_max_sum > 0:
    attempt['total_max_marks'] = int(answered_max_sum) if answered_max_sum.is_integer() else answered_max_sum
  if attempt['answers']:
    tot_aw = round(sum(float(ans.get('marks_awarded') or 0) for ans in attempt['answers']), 2)
    attempt['total_marks_awarded'] = int(tot_aw) if tot_aw.is_integer() else tot_aw
  attempt['paper_max_marks'] = int(paper_full_max) if (paper_full_max > 0 and paper_full_max.is_integer()) else (paper_full_max or attempt['total_max_marks'])
  attempt['overall_pct'] = min(100, int(round((float(attempt['total_marks_awarded']) / float(attempt['paper_max_marks'])) * 100))) if attempt['paper_max_marks'] > 0 else 0

  dur_sec = _compute_attempt_duration_seconds(attempt)
  attempt['time_taken_seconds'] = dur_sec
  attempt['time_taken_str'] = format_duration_str(dur_sec) if dur_sec > 0 else "—"
  if attempt.get('student_id') and attempt.get('exam_paper_id'):
    mock_ep_for_speed = attempt['exam_paper_id'] if attempt.get('exam_type') != 'real' else (attempt.get('mock_exam_id') or attempt['exam_paper_id'])
    attempt['speed_stats'] = get_mock_speed_stats(conn, mock_ep_for_speed, attempt['student_id'])
  else:
    attempt['speed_stats'] = None
  return attempt

def get_recent_attempts(conn, student_id: int, limit: int = 6, chapter_id: int = None):
  cursor = conn.cursor()
  chapter_filter_sql = " AND e.chapter_id = ? " if chapter_id is not None else ""
  params = [student_id]
  if chapter_id is not None:
    params.append(chapter_id)
  params.append(limit)
  cursor.execute(f"""
    SELECT 
      a.id,
      a.exam_paper_id,
      a.status,
      a.started_at,
      COALESCE(a.time_taken_seconds, 0) as time_taken_seconds,
      COALESCE(MAX(ans.submitted_at), a.completed_at, a.started_at) as completed_at, 
      COALESCE(SUM(ans.marks_awarded), a.total_marks_awarded, 0) as total_marks_awarded,
      COALESCE(SUM(COALESCE(q.max_marks, m.mark_value, 1)), 0) as answered_max_marks,
      COUNT(DISTINCT ans.question_id) as answered_count,
      COALESCE(
        NULLIF((SELECT COUNT(*) FROM questions q3 JOIN modules m3 ON q3.module_id = m3.id WHERE m3.exam_paper_id = e.id AND COALESCE(q3.is_hidden, 0) = 0 AND COALESCE(q3.textbook_section, 'Questions') NOT IN ('HOTS', 'POWER_UP')), 0),
        (SELECT COUNT(*) FROM questions q3 JOIN modules m3 ON q3.module_id = m3.id JOIN exam_papers em ON m3.exam_paper_id = em.id WHERE em.chapter_id = e.chapter_id AND em.type = 'mock' AND COALESCE(q3.is_hidden, 0) = 0 AND COALESCE(q3.textbook_section, 'Questions') NOT IN ('HOTS', 'POWER_UP'))
      ) as total_questions,
      COALESCE(
        NULLIF((SELECT SUM(COALESCE(q2.max_marks, m2.mark_value, 1)) FROM questions q2 JOIN modules m2 ON q2.module_id = m2.id WHERE m2.exam_paper_id = e.id AND COALESCE(q2.is_hidden, 0) = 0 AND COALESCE(q2.textbook_section, 'Questions') NOT IN ('HOTS', 'POWER_UP')), 0),
        NULLIF((SELECT SUM(COALESCE(q2.max_marks, m2.mark_value, 1)) FROM questions q2 JOIN modules m2 ON q2.module_id = m2.id JOIN exam_papers em2 ON m2.exam_paper_id = em2.id WHERE em2.chapter_id = e.chapter_id AND em2.type = 'mock' AND COALESCE(q2.is_hidden, 0) = 0 AND COALESCE(q2.textbook_section, 'Questions') NOT IN ('HOTS', 'POWER_UP')), 0),
        NULLIF(e.target_marks, 0),
        NULLIF(a.total_max_marks, 0),
        0
      ) as paper_max_marks, 
      e.title as exam_title,
      e.type as exam_type,
      e.chapter_id,
      c.name as chapter_name,
      s.id as subject_id,
      s.name as subject_name
    FROM attempts a
    JOIN exam_papers e ON a.exam_paper_id = e.id
    LEFT JOIN chapters c ON e.chapter_id = c.id
    LEFT JOIN subjects s ON c.subject_id = s.id
    LEFT JOIN answers ans ON a.id = ans.attempt_id AND ans.is_latest = 1
      AND TRIM(COALESCE(ans.answer_text, '')) NOT IN ('', 'No answer provided', 'no answer provided')
    LEFT JOIN questions q ON ans.question_id = q.id
    LEFT JOIN modules m ON q.module_id = m.id
    WHERE a.student_id = ?
      AND COALESCE(c.status, 'published') = 'published'
      AND COALESCE(s.is_hidden, 0) = 0
      {chapter_filter_sql}
      AND (ans.id IS NOT NULL OR a.status = 'completed' OR COALESCE(a.total_marks_awarded, 0) > 0)
    GROUP BY a.id, e.id, e.title, e.type, e.chapter_id, c.name, s.id, s.name, a.status, a.started_at
    ORDER BY completed_at DESC, a.id DESC
    LIMIT ?
  """, tuple(params))
  attempts = []
  for row in cursor.fetchall():
    attempt = dict(row)
    
    if attempt.get('completed_at'):
      try:
        dt = datetime.datetime.strptime(str(attempt['completed_at']).split('.')[0], '%Y-%m-%d %H:%M:%S')
        attempt['date_str'] = dt.strftime('%b %d, %Y')
      except Exception:
        attempt['date_str'] = str(attempt['completed_at'])[:10]
    else:
      attempt['date_str'] = 'Completed'
      
    total_m = round(float(attempt.get('total_marks_awarded') or 0), 1)
    if total_m.is_integer():
      total_m = int(total_m)
    attempt['total_marks_awarded'] = total_m

    paper_max_m = round(float(attempt.get('paper_max_marks') or 0), 1)
    if paper_max_m.is_integer():
      paper_max_m = int(paper_max_m)

    ans_max_m = round(float(attempt.get('answered_max_marks') or 0), 1)
    if ans_max_m.is_integer():
      ans_max_m = int(ans_max_m)
    attempt['answered_max_marks'] = ans_max_m

    # Measure both mock and real exams against full paper max marks so 1-question runs never fake 100%
    max_m = paper_max_m if paper_max_m > 0 else ans_max_m
    attempt['paper_max_marks'] = paper_max_m
    attempt['total_max_marks'] = max_m

    pct = (float(total_m) / float(max_m) * 100) if max_m > 0 else 0
    attempt['pct'] = min(100, int(round(pct)))
    attempt['overall_pct'] = min(100, int(round((float(total_m) / float(paper_max_m) * 100)))) if paper_max_m > 0 else attempt['pct']

    if pct >= 90:
      attempt['grade'] = 'A+'
      attempt['grade_color'] = 'success'
      attempt['grade_label'] = 'Excellent'
    elif pct >= 80:
      attempt['grade'] = 'A'
      attempt['grade_color'] = 'success'
      attempt['grade_label'] = 'Great'
    elif pct >= 70:
      attempt['grade'] = 'B'
      attempt['grade_color'] = 'warning'
      attempt['grade_label'] = 'Good'
    elif pct >= 60:
      attempt['grade'] = 'C'
      attempt['grade_color'] = 'warning'
      attempt['grade_label'] = 'Pass'
    else:
      attempt['grade'] = 'F'
      attempt['grade_color'] = 'error'
      attempt['grade_label'] = 'Needs Review'

    dur_sec = _compute_attempt_duration_seconds(attempt)
    attempt['time_taken_seconds'] = dur_sec
    attempt['time_taken_str'] = format_duration_str(dur_sec) if dur_sec > 0 else ''
    attempts.append(attempt)
  return attempts

def get_student_stats(conn, student_id: int):
  cursor = conn.cursor()
  today = get_ist_today()
  today_str = today.strftime('%Y-%m-%d')

  # 1. Fetch existing daily_activity rows
  cursor.execute("SELECT activity_date, problems_solved, modules_completed FROM daily_activity WHERE user_id = ? ORDER BY activity_date DESC", (student_id,))
  rows = cursor.fetchall()
  activity_by_date = {}
  for r in rows:
    d_key = r[0]
    p_solved = r[1] or 0
    m_comp = r[2] or 0
    if p_solved > 0 or m_comp > 0:
      if d_key in activity_by_date:
        activity_by_date[d_key] = (activity_by_date[d_key][0] + p_solved, activity_by_date[d_key][1] + m_comp)
      else:
        activity_by_date[d_key] = (p_solved, m_comp)

  # 2. Merge actual completed work dates in memory (without mutating daily_activity) so streak & charts stay accurate
  try:
    cursor.execute("""
      SELECT date(ans.submitted_at, '+5 hours', '+30 minutes') as d_ist, COUNT(*)
      FROM answers ans
      JOIN attempts a ON ans.attempt_id = a.id
      WHERE a.student_id = ? AND ans.submitted_at IS NOT NULL
        AND TRIM(COALESCE(ans.answer_text, '')) NOT IN ('', 'No answer provided', 'no answer provided')
      GROUP BY d_ist
    """, (student_id,))
    for d_str, cnt in cursor.fetchall():
      if d_str and d_str <= today_str:
        cur_p, cur_m = activity_by_date.get(d_str, (0, 0))
        activity_by_date[d_str] = (max(cur_p, cnt or 0), cur_m)

    cursor.execute("""
      SELECT date(completed_at, '+5 hours', '+30 minutes') as d_ist, COUNT(*)
      FROM attempts
      WHERE student_id = ? AND status = 'completed' AND completed_at IS NOT NULL
      GROUP BY d_ist
    """, (student_id,))
    for d_str, cnt in cursor.fetchall():
      if d_str and d_str <= today_str:
        cur_p, cur_m = activity_by_date.get(d_str, (0, 0))
        activity_by_date[d_str] = (cur_p, max(cur_m, cnt or 0))

    cursor.execute("""
      SELECT date(completed_at, '+5 hours', '+30 minutes') as d_ist, COUNT(*)
      FROM content_progress
      WHERE student_id = ? AND completed = 1 AND completed_at IS NOT NULL
      GROUP BY d_ist
    """, (student_id,))
    for d_str, cnt in cursor.fetchall():
      if d_str and d_str <= today_str:
        cur_p, cur_m = activity_by_date.get(d_str, (0, 0))
        activity_by_date[d_str] = (cur_p, max(cur_m, cnt or 0))

    cursor.execute("""
      SELECT date(completed_at, '+5 hours', '+30 minutes') as d_ist, COUNT(*)
      FROM digi_attempts
      WHERE student_id = ? AND status = 'completed' AND completed_at IS NOT NULL
      GROUP BY d_ist
    """, (student_id,))
    for d_str, cnt in cursor.fetchall():
      if d_str and d_str <= today_str:
        cur_p, cur_m = activity_by_date.get(d_str, (0, 0))
        activity_by_date[d_str] = (cur_p, max(cur_m, cnt or 0))
  except Exception:
    pass

  # 3. Recalculate XP so total_xp is always accurate to true earned XP
  total_xp = recalculate_user_xp(conn, student_id, notify=False)
  cursor.execute("SELECT total_xp, spent_xp FROM users WHERE id = ?", (student_id,))
  row = cursor.fetchone()
  total_xp = row[0] if row and row[0] is not None else total_xp
  spent_xp = row[1] if row and row[1] else 0
  current_xp = max(0, total_xp - spent_xp)

  # 4. Compute consecutive Day Streak from sorted unique active dates
  sorted_dates = []
  for d_str in activity_by_date.keys():
    try:
      d_obj = datetime.datetime.strptime(d_str, '%Y-%m-%d').date()
      if d_obj <= today:
        sorted_dates.append(d_obj)
    except Exception:
      pass
  sorted_dates = sorted(set(sorted_dates), reverse=True)

  streak_days = 0
  if sorted_dates:
    first_date = sorted_dates[0]
    if first_date == today or first_date == today - datetime.timedelta(days=1):
      streak_days = 1
      current_date = first_date
      for row_date in sorted_dates[1:]:
        if row_date == current_date - datetime.timedelta(days=1):
          streak_days += 1
          current_date = row_date
        elif row_date == current_date:
          continue
        else:
          break

  # 5. Activity Data for the chart (Daily, Weekly, Monthly)
  activity_data = {
    "daily": [],
    "weekly": [],
    "monthly": []
  }
  
  # 1. Daily (last 7 days)
  day_labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  day_short_labels = ['M', 'T', 'W', 'T', 'F', 'S', 'S']
  daily_max = 1
  for i in range(6, -1, -1):
    d = today - datetime.timedelta(days=i)
    d_str = d.strftime('%Y-%m-%d')
    solved, mods = activity_by_date.get(d_str, (0, 0))
    total_actions = int(solved + mods)
    if total_actions > daily_max:
      daily_max = total_actions
    activity_data['daily'].append({
      "label": day_labels[d.weekday()],
      "day_short": day_short_labels[d.weekday()],
      "date_str": d_str,
      "date": d_str,
      "value": total_actions,
      "questions_count": int(solved),
      "modules_count": int(mods),
      "problems": int(solved),
      "modules": int(mods),
      "duration_str": f"{solved} Question{'' if solved == 1 else 's'} Solved, {mods} Module{'' if mods == 1 else 's'} Completed",
      "is_today": (i == 0),
      "on": bool(total_actions > 0)
    })
  for item in activity_data['daily']:
    item['height_pct'] = max(12, int((item['value'] / daily_max) * 100)) if item['value'] > 0 else 0
    
  # 2. Weekly (last 4 weeks)
  weekly_max = 1
  current_week_start = today - datetime.timedelta(days=today.weekday())
  for i in range(3, -1, -1):
    week_start = current_week_start - datetime.timedelta(weeks=i)
    solved = 0
    mods = 0
    for day_offset in range(7):
      w_d_str = (week_start + datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
      d_s, d_m = activity_by_date.get(w_d_str, (0, 0))
      solved += d_s
      mods += d_m
    total_actions = int(solved + mods)
    if total_actions > weekly_max:
      weekly_max = total_actions
    
    if i == 0:
      label = "This Wk"
    elif i == 1:
      label = "Last Wk"
    else:
      label = week_start.strftime('%b %d')
      
    activity_data['weekly'].append({
      "label": label,
      "date_str": week_start.strftime('%Y-%m-%d'),
      "date": week_start.strftime('%Y-%m-%d'),
      "value": total_actions,
      "questions_count": int(solved),
      "modules_count": int(mods),
      "problems": int(solved),
      "modules": int(mods),
      "duration_str": f"{solved} Questions Solved, {mods} Modules Completed",
      "is_today": (i == 0)
    })
  for item in activity_data['weekly']:
    item['height_pct'] = max(12, int((item['value'] / weekly_max) * 100)) if item['value'] > 0 else 0
    
  # 3. Monthly (last 6 months)
  monthly_by_ym = {}
  for d_key, (d_s, d_m) in activity_by_date.items():
    ym = d_key[:7]
    prev_s, prev_m = monthly_by_ym.get(ym, (0, 0))
    monthly_by_ym[ym] = (prev_s + d_s, prev_m + d_m)

  monthly_max = 1
  for i in range(5, -1, -1):
    month = today.month - i
    year = today.year
    while month <= 0:
      month += 12
      year -= 1
      
    ym_key = f"{year}-{month:02d}"
    solved, mods = monthly_by_ym.get(ym_key, (0, 0))
    total_actions = int(solved + mods)
    if total_actions > monthly_max:
      monthly_max = total_actions
    
    label = datetime.date(year, month, 1).strftime('%b')
    activity_data['monthly'].append({
      "label": label,
      "date_str": ym_key,
      "date": ym_key,
      "value": total_actions,
      "questions_count": int(solved),
      "modules_count": int(mods),
      "problems": int(solved),
      "modules": int(mods),
      "duration_str": f"{solved} Questions Solved, {mods} Modules Completed",
      "is_today": (i == 0)
    })
  for item in activity_data['monthly']:
    item['height_pct'] = max(12, int((item['value'] / monthly_max) * 100)) if item['value'] > 0 else 0
    
  # 6. League calculation (strict solid #f7b317 / #231f20 palette)
  league = "Bronze"
  league_color = "[#231f20]"
  league_hex = "#231f20"
  league_gradient = "#f7b317"
  prev_tier_xp = 0
  next_tier_xp = 500
  if total_xp >= 3500:
    league = "Diamond"
    league_color = "[#f7b317]"
    league_hex = "#f7b317"
    league_gradient = "#f7b317"
    prev_tier_xp = 3500
    next_tier_xp = total_xp
  elif total_xp >= 1500:
    league = "Gold"
    league_color = "[#f7b317]"
    league_hex = "#f7b317"
    league_gradient = "#f7b317"
    prev_tier_xp = 1500
    next_tier_xp = 3500
  elif total_xp >= 500:
    league = "Silver"
    league_color = "[#231f20]"
    league_hex = "#231f20"
    league_gradient = "#f7b317"
    prev_tier_xp = 500
    next_tier_xp = 1500
    
  if league == "Diamond":
    league_progress = 100
  else:
    tier_span = max(1, next_tier_xp - prev_tier_xp)
    tier_earned = max(0, total_xp - prev_tier_xp)
    league_progress = min(100, max(6 if total_xp > 0 else 0, int((tier_earned / tier_span) * 100)))
  
  return {
    "xp_earned": total_xp,
    "current_xp": current_xp,
    "streak_days": streak_days,
    "activity_data": activity_data,
    "league": league,
    "league_color": league_color,
    "league_hex": league_hex,
    "league_gradient": league_gradient,
    "league_progress": league_progress,
    "next_tier_xp": next_tier_xp
  }


# ==========================================
# DIGI LIBRARY STUDENT SERVICES (Markless)
# ==========================================

def get_student_digi_books(conn, student_id: int):
  """Returns all published Digi Library books available to the student (matching their class_id or unassigned/all classes)."""
  cursor = conn.cursor()
  cursor.execute("SELECT class_id FROM users WHERE id = ?", (student_id,))
  user_row = cursor.fetchone()
  class_id = user_row['class_id'] if user_row else None

  if class_id:
    cursor.execute("""
      SELECT b.*, c.name as class_name
      FROM digi_books b
      LEFT JOIN classes c ON b.class_id = c.id
      WHERE b.status = 'published' AND (b.class_id IS NULL OR b.class_id = ?)
      ORDER BY b.order_index, b.id DESC
    """, (class_id,))
  else:
    cursor.execute("""
      SELECT b.*, c.name as class_name
      FROM digi_books b
      LEFT JOIN classes c ON b.class_id = c.id
      WHERE b.status = 'published'
      ORDER BY b.order_index, b.id DESC
    """)

  books = [dict(r) for r in cursor.fetchall()]

  for book in books:
    cursor.execute("SELECT COUNT(*) FROM digi_subjects WHERE book_id = ?", (book['id'],))
    book['subject_count'] = cursor.fetchone()[0] or 0

    cursor.execute("""
      SELECT COUNT(*)
      FROM digi_question_banks qb
      JOIN digi_subjects s ON qb.subject_id = s.id
      WHERE s.book_id = ? AND qb.status = 'published'
    """, (book['id'],))
    book['bank_count'] = cursor.fetchone()[0] or 0

  return books


def get_student_digi_book_details(conn, book_id: int, student_id: int):
  """Returns a Digi Library book and its subjects with progress stats styled just like Dashboard subjects."""
  cursor = conn.cursor()
  cursor.execute("""
    SELECT b.*, c.name as class_name
    FROM digi_books b
    LEFT JOIN classes c ON b.class_id = c.id
    WHERE b.id = ? AND b.status = 'published'
  """, (book_id,))
  row = cursor.fetchone()
  if not row:
    return None
  book = dict(row)

  cursor.execute("SELECT * FROM digi_subjects WHERE book_id = ? ORDER BY order_index, id", (book_id,))
  subjects = [dict(r) for r in cursor.fetchall()]
  if not subjects and book.get('class_id'):
    cursor.execute("""
      SELECT s.* FROM digi_subjects s
      JOIN digi_books b ON s.book_id = b.id
      WHERE b.class_id = ? AND b.status = 'published'
      ORDER BY s.order_index, s.id
    """, (book['class_id'],))
    subjects = [dict(r) for r in cursor.fetchall()]

  for subj in subjects:
    cursor.execute("""
      SELECT qb.id, qb.title, qb.description,
             (SELECT COUNT(*) FROM digi_questions dq WHERE dq.bank_id = qb.id) as question_count
      FROM digi_question_banks qb
      WHERE qb.subject_id = ? AND qb.status = 'published'
      ORDER BY qb.order_index, qb.id
    """, (subj['id'],))
    banks = [dict(r) for r in cursor.fetchall()]
    bank_ids = [b['id'] for b in banks]
    total_banks = len(bank_ids)
    subj['banks'] = banks
    subj['first_bank_id'] = bank_ids[0] if bank_ids else None
    subj['bank_count'] = total_banks

    cursor.execute("""
      SELECT COUNT(*)
      FROM digi_questions dq
      JOIN digi_question_banks qb ON dq.bank_id = qb.id
      WHERE qb.subject_id = ? AND qb.status = 'published'
    """, (subj['id'],))
    subj['question_count'] = cursor.fetchone()[0] or 0

    completed_banks = 0
    if total_banks > 0:
      placeholders = ','.join('?' for _ in bank_ids)
      cursor.execute(f"""
        SELECT COUNT(DISTINCT bank_id)
        FROM digi_attempts
        WHERE student_id = ? AND status = 'completed' AND bank_id IN ({placeholders})
      """, [student_id] + bank_ids)
      completed_banks = cursor.fetchone()[0] or 0

    subj['completed_banks'] = completed_banks
    subj['progress_pct'] = int((completed_banks / total_banks) * 100) if total_banks > 0 else 0

  book['subjects'] = subjects
  return book


def get_student_digi_subject_details(conn, subject_id: int, student_id: int):
  """Returns a Digi Library subject, its parent book, and all published Question Banks with student stats."""
  cursor = conn.cursor()
  cursor.execute("""
    SELECT s.*, b.title as book_title, b.thumbnail_url as book_thumbnail_url
    FROM digi_subjects s
    JOIN digi_books b ON s.book_id = b.id
    WHERE s.id = ? AND b.status = 'published'
  """, (subject_id,))
  row = cursor.fetchone()
  if not row:
    return None
  subject = dict(row)

  cursor.execute("""
    SELECT qb.*,
           (SELECT COUNT(*) FROM digi_questions dq WHERE dq.bank_id = qb.id) as question_count
    FROM digi_question_banks qb
    WHERE qb.subject_id = ? AND qb.status = 'published'
    ORDER BY qb.order_index, qb.id
  """, (subject_id,))
  banks = [dict(r) for r in cursor.fetchall()]

  for bank in banks:
    cursor.execute("""
      SELECT id, status, correct_count, total_questions, completed_at, started_at
      FROM digi_attempts
      WHERE bank_id = ? AND student_id = ?
      ORDER BY CASE WHEN status = 'completed' THEN 0 ELSE 1 END, id DESC
      LIMIT 1
    """, (bank['id'], student_id))
    last_att = cursor.fetchone()
    if last_att:
      bank['last_attempt'] = dict(last_att)
      cursor.execute("""
        SELECT COUNT(*) FROM digi_attempts WHERE bank_id = ? AND student_id = ? AND status = 'completed'
      """, (bank['id'], student_id))
      bank['attempts_count'] = cursor.fetchone()[0] or 0
    else:
      bank['last_attempt'] = None
      bank['attempts_count'] = 0

  subject['banks'] = banks
  return subject


def get_digi_bank_for_practice(conn, bank_id: int):
  """Returns a Question Bank formatted into the exact paper/modules/questions structure used by exam_take.html."""
  cursor = conn.cursor()
  cursor.execute("""
    SELECT qb.*, s.name as subject_name, s.book_id, s.thumbnail_url as subject_thumbnail_url, b.title as book_title, b.thumbnail_url as book_thumbnail_url
    FROM digi_question_banks qb
    JOIN digi_subjects s ON qb.subject_id = s.id
    JOIN digi_books b ON s.book_id = b.id
    WHERE qb.id = ? AND qb.status = 'published'
  """, (bank_id,))
  row = cursor.fetchone()
  if not row:
    return None
  bank = dict(row)

  cursor.execute("SELECT * FROM digi_questions WHERE bank_id = ? ORDER BY order_index, id", (bank_id,))
  questions = []
  for q_row in cursor.fetchall():
    q = dict(q_row)
    # Set max_marks = 1 internally for Alpine compatibility; UI hides marks completely when is_digi_library is True
    q['max_marks'] = 1
    questions.append(q)

  # Sibling chapters in the same subject
  cursor.execute("""
    SELECT qb.id, qb.title,
           (SELECT COUNT(*) FROM digi_questions dq WHERE dq.bank_id = qb.id) as question_count
    FROM digi_question_banks qb
    WHERE qb.subject_id = ? AND qb.status = 'published'
    ORDER BY qb.order_index, qb.id
  """, (bank['subject_id'],))
  subject_banks = [dict(r) for r in cursor.fetchall()]

  # All subjects in the same book (every subject is in the same book like a question bank)
  cursor.execute("""
    SELECT s.id, s.name,
           (SELECT qb2.id FROM digi_question_banks qb2 WHERE qb2.subject_id = s.id AND qb2.status = 'published' ORDER BY qb2.order_index, qb2.id LIMIT 1) as first_bank_id
    FROM digi_subjects s
    WHERE s.book_id = ?
    ORDER BY s.order_index, s.id
  """, (bank['book_id'],))
  book_subjects = [dict(r) for r in cursor.fetchall() if r['first_bank_id']]

  paper = {
    "id": bank['id'],
    "title": bank['title'],
    "description": bank.get('description', ''),
    "type": "question_bank",
    "version": 1,
    "status": bank['status'],
    "subject_id": bank['subject_id'],
    "subject_name": bank['subject_name'],
    "subject_thumbnail_url": bank.get('subject_thumbnail_url'),
    "book_id": bank['book_id'],
    "book_title": bank['book_title'],
    "book_thumbnail_url": bank.get('book_thumbnail_url'),
    "subject_banks": subject_banks,
    "book_subjects": book_subjects,
    "is_digi_library": True,
    "modules": [
      {
        "id": bank['id'],
        "name": bank['title'],
        "question_type": "CUSTOM",
        "mark_value": 1,
        "questions": questions
      }
    ] if questions else []
  }
  return paper


def start_digi_attempt(conn, bank_id: int, student_id: int):
  cursor = conn.cursor()
  cursor.execute(
    "SELECT id FROM digi_attempts WHERE bank_id = ? AND student_id = ? AND status = 'in_progress' ORDER BY id DESC LIMIT 1",
    (bank_id, student_id)
  )
  existing = cursor.fetchone()
  if existing:
    return existing[0]
  cursor.execute("SELECT COUNT(*) FROM digi_questions WHERE bank_id = ?", (bank_id,))
  total_q = cursor.fetchone()[0] or 0
  cursor.execute(
    "INSERT INTO digi_attempts (bank_id, student_id, status, total_questions) VALUES (?, ?, 'in_progress', ?)",
    (bank_id, student_id, total_q)
  )
  conn.commit()
  return cursor.lastrowid


def get_student_continue_state(conn, student_id: int, subjects: list, cookie_state: dict = None) -> dict:
  import urllib.parse
  cursor = conn.cursor()
  c_state = cookie_state if isinstance(cookie_state, dict) else {}

  # ---------------------------------------------------------
  # 1. Resolve Digital Library Continue State
  # ---------------------------------------------------------
  digi_cookie = c_state.get("digi") if isinstance(c_state.get("digi"), dict) else {}
  target_bank_id = digi_cookie.get("bank_id")
  target_q_idx = int(digi_cookie.get("question_idx") or 0)
  studied_cnt = int(digi_cookie.get("studied_count") or 0)
  digi_ts = float(digi_cookie.get("updated_at") or 0)

  if not target_bank_id:
    cursor.execute("""
      SELECT bank_id, correct_count, total_questions,
             strftime('%s', COALESCE(completed_at, started_at, CURRENT_TIMESTAMP)) as ts
      FROM digi_attempts
      WHERE student_id = ?
      ORDER BY id DESC LIMIT 1
    """, (student_id,))
    d_att = cursor.fetchone()
    if d_att:
      target_bank_id = d_att[0]
      studied_cnt = int(d_att[1] or 0)
      digi_ts = float(d_att[3] or 0)

  bank_row = None
  if target_bank_id:
    cursor.execute("""
      SELECT qb.id, qb.title, qb.subject_id, s.name as subject_name, s.book_id, b.title as book_title,
             (SELECT COUNT(*) FROM digi_questions dq WHERE dq.bank_id = qb.id) as total_q
      FROM digi_question_banks qb
      JOIN digi_subjects s ON qb.subject_id = s.id
      JOIN digi_books b ON s.book_id = b.id
      WHERE qb.id = ? AND qb.status = 'published'
    """, (target_bank_id,))
    bank_row = cursor.fetchone()

  if not bank_row:
    cursor.execute("""
      SELECT qb.id, qb.title, qb.subject_id, s.name as subject_name, s.book_id, b.title as book_title,
             (SELECT COUNT(*) FROM digi_questions dq WHERE dq.bank_id = qb.id) as total_q
      FROM digi_question_banks qb
      JOIN digi_subjects s ON qb.subject_id = s.id
      JOIN digi_books b ON s.book_id = b.id
      WHERE qb.status = 'published' AND b.status = 'published'
      ORDER BY b.order_index, b.id, s.order_index, s.id, qb.order_index, qb.id
      LIMIT 1
    """)
    bank_row = cursor.fetchone()

  digi_item = None
  if bank_row:
    b_dict = dict(bank_row)
    total_q = max(1, int(b_dict.get("total_q") or 1))
    q_idx = max(0, min(target_q_idx, total_q - 1))
    if studied_cnt <= 0 and q_idx > 0:
      studied_cnt = q_idx
    pct = min(100, int(round((studied_cnt / total_q) * 100))) if total_q > 0 else 0
    digi_item = {
      "kind": "digi",
      "bank_id": b_dict["id"],
      "title": b_dict["title"],
      "subject_id": b_dict["subject_id"],
      "subject_name": b_dict["subject_name"],
      "book_id": b_dict["book_id"],
      "book_title": b_dict["book_title"],
      "question_idx": q_idx,
      "question_num": q_idx + 1,
      "total_questions": total_q,
      "studied_count": studied_cnt,
      "progress_pct": pct,
      "subtitle": f"{b_dict['subject_name']} · Digital Library · Q{q_idx + 1} of {total_q}",
      "progress_label": f"{pct}% of {b_dict['subject_name']} chapter studied ({studied_cnt}/{total_q} Q&As)",
      "resume_url": f"/student/digi-library/banks/{b_dict['id']}?q={q_idx}",
      "secondary_url": f"/student/digi-library/books/{b_dict['book_id']}?subject={b_dict['subject_id']}",
      "secondary_label": "Open Book Page",
      "updated_at": digi_ts,
    }

  # ---------------------------------------------------------
  # 2. Resolve Exam / Course Continue State
  # ---------------------------------------------------------
  exam_cookie = c_state.get("exam") if isinstance(c_state.get("exam"), dict) else {}
  target_exam_id = exam_cookie.get("exam_id")
  target_ch_id = exam_cookie.get("chapter_id")
  target_q_id = exam_cookie.get("question_id")
  target_q_num = int(exam_cookie.get("question_num") or 1)
  answered_cnt = int(exam_cookie.get("answered_count") or 0)
  exam_ts = float(exam_cookie.get("updated_at") or 0)

  # Check most recent DB attempt as well so fresh database activity is always respected
  cursor.execute("""
    SELECT a.id as attempt_id, a.exam_paper_id, ep.chapter_id, a.status,
           (SELECT COUNT(*) FROM answers ans WHERE ans.attempt_id = a.id AND ans.is_latest = 1 AND TRIM(COALESCE(ans.answer_text, '')) NOT IN ('', 'No answer provided', 'no answer provided')) as ans_cnt,
           strftime('%s', COALESCE((SELECT MAX(ans2.submitted_at) FROM answers ans2 WHERE ans2.attempt_id = a.id), a.completed_at, a.started_at, CURRENT_TIMESTAMP)) as ts
    FROM attempts a
    JOIN exam_papers ep ON a.exam_paper_id = ep.id
    JOIN chapters c ON ep.chapter_id = c.id
    JOIN subjects s ON c.subject_id = s.id
    WHERE a.student_id = ? AND c.status = 'published' AND COALESCE(s.is_hidden, 0) = 0
    ORDER BY CASE WHEN a.status = 'in_progress' THEN 0 ELSE 1 END, ts DESC, a.id DESC
    LIMIT 1
  """, (student_id,))
  e_att = cursor.fetchone()
  if e_att:
    db_ts = float(e_att["ts"] or 0)
    if (not target_exam_id and not target_ch_id) or (db_ts > exam_ts and int(e_att["ans_cnt"] or 0) > 0):
      target_exam_id = e_att["exam_paper_id"]
      target_ch_id = e_att["chapter_id"]
      answered_cnt = int(e_att["ans_cnt"] or 0)
      exam_ts = max(exam_ts, db_ts)

  exam_item = None
  if target_exam_id:
    cursor.execute("""
      SELECT ep.id as exam_id, ep.title as exam_title, ep.chapter_id,
             c.name as chapter_name, c.subject_id, s.name as subject_name,
             (SELECT COUNT(*) FROM questions q JOIN modules m ON q.module_id = m.id WHERE m.exam_paper_id = ep.id AND COALESCE(q.is_hidden, 0) = 0) as total_q
      FROM exam_papers ep
      JOIN chapters c ON ep.chapter_id = c.id
      JOIN subjects s ON c.subject_id = s.id
      WHERE ep.id = ? AND c.status = 'published' AND COALESCE(s.is_hidden, 0) = 0
    """, (target_exam_id,))
    ep_row = cursor.fetchone()
    if ep_row:
      ep = dict(ep_row)
      # Sync answered_cnt with actual DB answers for this exam
      cursor.execute("""
        SELECT COUNT(DISTINCT ans.question_id)
        FROM answers ans
        JOIN questions q ON ans.question_id = q.id
        JOIN attempts a ON ans.attempt_id = a.id
        WHERE a.student_id = ? AND a.exam_paper_id = ? AND ans.is_latest = 1
          AND COALESCE(q.is_hidden, 0) = 0
          AND TRIM(COALESCE(ans.answer_text, '')) NOT IN ('', 'No answer provided', 'no answer provided')
      """, (student_id, ep["exam_id"]))
      db_ep_ans = int((cursor.fetchone() or [0])[0] or 0)
      answered_cnt = max(answered_cnt, db_ep_ans)

      # Verify target_q_id actually belongs to this exam, or find next unanswered question in textbook order
      if target_q_id:
        cursor.execute("""
          SELECT 1 FROM questions q
          JOIN modules m ON q.module_id = m.id
          WHERE q.id = ? AND m.exam_paper_id = ? AND COALESCE(q.is_hidden, 0) = 0
        """, (target_q_id, ep["exam_id"]))
        if not cursor.fetchone():
          target_q_id = None

      if not target_q_id and answered_cnt > 0:
        cursor.execute("""
          SELECT q.id, COALESCE(NULLIF(q.textbook_order, 0), 999999) as tb_ord
          FROM questions q
          JOIN modules m ON q.module_id = m.id
          WHERE m.exam_paper_id = ? AND COALESCE(q.is_hidden, 0) = 0
            AND q.id NOT IN (
              SELECT DISTINCT ans.question_id
              FROM answers ans
              JOIN attempts a ON ans.attempt_id = a.id
              WHERE a.student_id = ? AND a.exam_paper_id = ? AND ans.is_latest = 1
                AND TRIM(COALESCE(ans.answer_text, '')) NOT IN ('', 'No answer provided', 'no answer provided')
            )
          ORDER BY tb_ord ASC, q.id ASC
          LIMIT 1
        """, (ep["exam_id"], student_id, ep["exam_id"]))
        next_q_row = cursor.fetchone()
        if next_q_row:
          target_q_id = next_q_row[0]

      total_q = max(1, int(ep.get("total_q") or 1))
      q_num = max(1, min(target_q_num if target_q_num > 1 else (answered_cnt + 1), total_q))
      pct = min(100, int(round((answered_cnt / total_q) * 100))) if total_q > 0 else 0
      res_url = f"/student/exams/{ep['exam_id']}?question_id={target_q_id}" if target_q_id else f"/student/exams/{ep['exam_id']}"
      exam_item = {
        "kind": "exam",
        "exam_id": ep["exam_id"],
        "chapter_id": ep["chapter_id"],
        "title": ep["chapter_name"],
        "exam_title": ep["exam_title"],
        "subject_id": ep["subject_id"],
        "subject_name": ep["subject_name"],
        "question_id": target_q_id,
        "question_num": q_num,
        "total_questions": total_q,
        "answered_count": answered_cnt,
        "progress_pct": pct,
        "subtitle": f"{ep['subject_name']} · {ep['exam_title']} · Q{q_num} of {total_q}",
        "progress_label": f"{pct}% of {ep['exam_title']} completed ({answered_cnt}/{total_q} questions)",
        "resume_url": res_url,
        "secondary_url": f"/student/chapters/{ep['chapter_id']}",
        "secondary_label": "Chapter Summaries & Exams",
        "secondary_icon": "smart_display",
        "updated_at": exam_ts,
      }

  if not exam_item:
    # Fallback to target_ch_id or first incomplete chapter across subjects
    chosen_ch = None
    chosen_sub = None
    chosen_idx = 1
    for s in (subjects or []):
      for idx, ch in enumerate(s.get("chapters") or [], 1):
        if target_ch_id and int(ch["id"]) == int(target_ch_id):
          chosen_ch = ch
          chosen_sub = s
          chosen_idx = idx
          break
        if not chosen_ch and not (ch.get("state") == "completed" or ch.get("is_completed")):
          chosen_ch = ch
          chosen_sub = s
          chosen_idx = idx
      if chosen_ch and target_ch_id and int(chosen_ch["id"]) == int(target_ch_id):
        break

    if chosen_ch and chosen_sub:
      cursor.execute("SELECT id, title FROM exam_papers WHERE chapter_id = ? AND status = 'published' ORDER BY CASE WHEN type='mock' THEN 0 ELSE 1 END, id LIMIT 1", (chosen_ch["id"],))
      first_ep = cursor.fetchone()
      ep_id = first_ep["id"] if first_ep else None
      pct = int(chosen_ch.get("progress_pct") or chosen_sub.get("progress_pct") or 0)
      exam_item = {
        "kind": "exam",
        "exam_id": ep_id,
        "chapter_id": chosen_ch["id"],
        "title": chosen_ch["name"],
        "exam_title": first_ep["title"] if first_ep else "Practice Exam",
        "subject_id": chosen_sub["id"],
        "subject_name": chosen_sub["name"],
        "question_id": None,
        "question_num": 1,
        "total_questions": 0,
        "answered_count": 0,
        "progress_pct": pct,
        "subtitle": f"{chosen_sub['name']} · Chapter {chosen_idx}",
        "progress_label": f"{pct}% of {chosen_sub['name']} done",
        "resume_url": f"/student/chapters/{chosen_ch['id']}",
        "secondary_url": f"/student/exams/{ep_id}" if ep_id else f"/student/chapters/{chosen_ch['id']}?tab=exams",
        "secondary_label": "Practice quiz",
        "updated_at": exam_ts,
      }

  return {
    "active_mode": "exam",
    "digi": None,
    "exam": exam_item,
  }



def save_digi_answer(conn, attempt_id: int, question_id: int, answer_text: str, is_correct: bool, feedback: str, drawing_url: str = ""):
  cursor = conn.cursor()
  cursor.execute("SELECT student_id FROM digi_attempts WHERE id = ?", (attempt_id,))
  row = cursor.fetchone()
  if not row:
    raise ValueError("Invalid attempt_id")
  student_id = row[0]

  cursor.execute("SELECT MAX(retry_count) FROM digi_answers WHERE attempt_id = ? AND question_id = ?", (attempt_id, question_id))
  r_row = cursor.fetchone()
  current_retry = r_row[0] if r_row and r_row[0] is not None else -1
  new_retry = current_retry + 1

  cursor.execute("UPDATE digi_answers SET is_latest = 0 WHERE attempt_id = ? AND question_id = ?", (attempt_id, question_id))
  cursor.execute(
    """INSERT INTO digi_answers
       (attempt_id, question_id, answer_text, is_correct, ai_feedback, drawing_url, retry_count, is_latest)
       VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
    (attempt_id, question_id, answer_text, 1 if is_correct else 0, feedback, drawing_url or "", new_retry)
  )
  conn.commit()

  is_blank = (answer_text or "").strip().lower() in ("", "no answer provided")
  if not is_blank:
    record_daily_activity(conn, student_id, problems_delta=1, modules_delta=0, notify_streak=True)
  else:
    record_daily_activity(conn, student_id, problems_delta=0, modules_delta=0, notify_streak=False)

  # Recalculate XP so Digi-Library practice rewards XP just like mock practice
  recalculate_user_xp(conn, student_id, notify=True)


def complete_digi_attempt(conn, attempt_id: int):
  cursor = conn.cursor()
  cursor.execute("SELECT student_id FROM digi_attempts WHERE id = ?", (attempt_id,))
  s_row = cursor.fetchone()
  student_id = s_row[0] if s_row else None

  cursor.execute("SELECT SUM(is_correct) FROM digi_answers WHERE attempt_id = ? AND is_latest = 1", (attempt_id,))
  correct_count = cursor.fetchone()[0] or 0

  cursor.execute("""
    SELECT COUNT(*)
    FROM digi_questions dq
    JOIN digi_attempts da ON da.bank_id = dq.bank_id
    WHERE da.id = ?
  """, (attempt_id,))
  total_q = cursor.fetchone()[0] or 0

  cursor.execute(
    "UPDATE digi_attempts SET status = 'completed', completed_at = CURRENT_TIMESTAMP, correct_count = ?, total_questions = ? WHERE id = ?",
    (correct_count, total_q, attempt_id)
  )
  conn.commit()

  if student_id:
    record_daily_activity(conn, student_id, problems_delta=0, modules_delta=1, notify_streak=True)
    recalculate_user_xp(conn, student_id, notify=True)


def get_digi_attempt_full(conn, attempt_id: int):
  cursor = conn.cursor()
  cursor.execute("""
    SELECT a.*, qb.title as bank_title, qb.subject_id, s.name as subject_name, s.book_id, b.title as book_title
    FROM digi_attempts a
    JOIN digi_question_banks qb ON a.bank_id = qb.id
    JOIN digi_subjects s ON qb.subject_id = s.id
    JOIN digi_books b ON s.book_id = b.id
    WHERE a.id = ?
  """, (attempt_id,))
  row = cursor.fetchone()
  if not row:
    return None
  attempt = dict(row)

  cursor.execute("""
    SELECT ans.*, q.question_text, q.model_answer, q.question_type, q.media_url, q.answer_media_url,
           q.explanation_video_url, q.explanation_video_type, q.additional_videos
    FROM digi_answers ans
    JOIN digi_questions q ON ans.question_id = q.id
    WHERE ans.attempt_id = ? AND ans.is_latest = 1
    ORDER BY q.order_index, q.id
  """, (attempt_id,))
  attempt['answers'] = [dict(r) for r in cursor.fetchall()]
  return attempt

# ---------------------------------------------------------------------------
# Strict chapter path: introduction > practice test > real exam, in that order.
# One row per student + chapter: when the path (re)started and when the introduction was finished.
# No row = the student never restarted: all their history counts (existing progress is kept).
# ---------------------------------------------------------------------------
def _ensure_chapter_path(conn):
  conn.execute("""
    CREATE TABLE IF NOT EXISTS chapter_path (
      student_id INTEGER NOT NULL,
      chapter_id INTEGER NOT NULL,
      started_at TEXT,
      intro_done_at TEXT,
      mock_done_at TEXT,
      PRIMARY KEY (student_id, chapter_id)
    )
  """)
  cols = {r[1] for r in conn.execute("PRAGMA table_info(chapter_path)").fetchall()}
  if "mock_done_at" not in cols:
    conn.execute("ALTER TABLE chapter_path ADD COLUMN mock_done_at TEXT")


def get_chapter_path_row(conn, student_id: int, chapter_id: int):
  _ensure_chapter_path(conn)
  r = conn.execute(
    "SELECT started_at, intro_done_at, mock_done_at FROM chapter_path WHERE student_id = ? AND chapter_id = ?",
    (student_id, chapter_id),
  ).fetchone()
  return {"started_at": r[0], "intro_done_at": r[1], "mock_done_at": r[2]} if r else None


def chapter_path_since(conn, student_id: int, chapter_id: int):
  try:
    row = get_chapter_path_row(conn, student_id, chapter_id)
  except Exception:
    return None
  return (row or {}).get("started_at") or None


def chapter_path_state(conn, student_id: int, chapter_id: int, exams=None) -> dict:
  """Which stage the student is on: 'intro', 'mock' or 'real' (the only one they may open)."""
  row = get_chapter_path_row(conn, student_id, chapter_id)
  if row:
    intro_done = bool(row.get("intro_done_at"))
  else:
    try:
      intro_done = conn.execute(
        "SELECT 1 FROM coin_ledger WHERE student_id = ? AND reward_key = ? LIMIT 1",
        (student_id, f"nutshell:ch:{chapter_id}"),
      ).fetchone() is not None
    except Exception:
      intro_done = False
  if exams is None:
    exams = get_available_exams(conn, chapter_id, student_id)
  mocks = [e for e in exams if e.get("type") == "mock"]
  reals = [e for e in exams if e.get("type") == "real"]
  scores = [float(e["highest_score"]) for e in mocks if e.get("highest_score") is not None]
  best_mock = max(scores) if scores else None
  real_unlocked = bool(reals) and not reals[0].get("is_locked")
  mock_passed = (not mocks) or real_unlocked or (best_mock is not None and best_mock >= 100)
  real_scores = [float(e["highest_score"]) for e in reals if e.get("highest_score") is not None]
  best_real = max(real_scores) if real_scores else None
  # On to the real exam only after the student confirmed it in the popup (a row records it);
  # students without a row (never restarted) keep their old progress.
  went_to_real = bool(row.get("mock_done_at")) if row else mock_passed
  if not intro_done:
    stage = "intro"
  elif mocks and not went_to_real:
    stage = "mock"
  elif reals:
    stage = "real"
  else:
    stage = "mock" if mocks else "intro"
  return {
    "stage": stage,
    "intro_done": intro_done,
    "mock_passed": bool(mock_passed),
    "real_unlocked": real_unlocked,
    "restarted": bool(row and row.get("started_at")),
    "can_go_real": bool(intro_done and mocks and not went_to_real and real_unlocked),
    # the chapter is complete with 100% in the real exam
    "chapter_complete": bool(stage == "real" and best_real is not None and best_real >= 100),
  }


def mark_chapter_intro_done(conn, student_id: int, chapter_id: int):
  _ensure_chapter_path(conn)
  conn.execute(
    """INSERT INTO chapter_path (student_id, chapter_id, started_at, intro_done_at)
       VALUES (?, ?, NULL, CURRENT_TIMESTAMP)
       ON CONFLICT(student_id, chapter_id) DO UPDATE SET intro_done_at = COALESCE(intro_done_at, CURRENT_TIMESTAMP)""",
    (student_id, chapter_id),
  )
  conn.commit()


def mark_chapter_went_to_real(conn, student_id: int, chapter_id: int) -> bool:
  """The student confirmed "go to the real exam" (only allowed after passing the practice exam)."""
  st = chapter_path_state(conn, student_id, chapter_id)
  if not st.get("can_go_real"):
    return st.get("stage") == "real"
  _ensure_chapter_path(conn)
  conn.execute(
    """INSERT INTO chapter_path (student_id, chapter_id, started_at, intro_done_at, mock_done_at)
       VALUES (?, ?, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
       ON CONFLICT(student_id, chapter_id) DO UPDATE SET mock_done_at = CURRENT_TIMESTAMP""",
    (student_id, chapter_id),
  )
  conn.commit()
  return True


def restart_chapter_path(conn, student_id: int, chapter_id: int):
  """Start the chapter again from the introduction. Scores, answers and coins are kept."""
  _ensure_chapter_path(conn)
  conn.execute(
    """INSERT INTO chapter_path (student_id, chapter_id, started_at, intro_done_at)
       VALUES (?, ?, CURRENT_TIMESTAMP, NULL)
       ON CONFLICT(student_id, chapter_id) DO UPDATE SET started_at = CURRENT_TIMESTAMP, intro_done_at = NULL, mock_done_at = NULL""",
    (student_id, chapter_id),
  )
  conn.commit()

# ---------------------------------------------------------------------------
# Issues (magazine parts), like saxaz.com: every student has Part 1; redeeming the password printed in a
# magazine adds the next part. The real password format is not known yet, so for now any password the
# student types adds the next part (dummy redeem).
# ---------------------------------------------------------------------------
MAX_ISSUE_PARTS = 12


def _ensure_student_issues(conn):
  conn.execute("""
    CREATE TABLE IF NOT EXISTS student_issues (
      student_id INTEGER NOT NULL,
      part_no INTEGER NOT NULL,
      code TEXT,
      redeemed_at TEXT DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (student_id, part_no)
    )
  """)


def get_student_issue_parts(conn, student_id: int) -> list[int]:
  _ensure_student_issues(conn)
  rows = conn.execute("SELECT part_no FROM student_issues WHERE student_id = ?", (student_id,)).fetchall()
  parts = {1} | {int(r[0]) for r in rows if r and r[0]}
  return sorted(parts)


def redeem_issue(conn, student_id: int, code: str) -> dict:
  """Dummy redeem: a password (any, 4+ characters) adds the next issue part."""
  code = (code or "").strip()
  if len(code) < 4:
    return {"success": False, "error": "Type the password from the first page of your magazine."}
  _ensure_student_issues(conn)
  parts = get_student_issue_parts(conn, student_id)
  nxt = max(parts) + 1
  if nxt > MAX_ISSUE_PARTS:
    return {"success": False, "error": "You already have every issue."}
  conn.execute(
    "INSERT OR IGNORE INTO student_issues (student_id, part_no, code) VALUES (?, ?, ?)",
    (student_id, nxt, code[:64]),
  )
  conn.commit()
  return {"success": True, "part": nxt}

# ---------------------------------------------------------------------------
# Shop: redeeming coins unlocks only after all 3 practice exams of the chapter are completed
# ---------------------------------------------------------------------------
SHOP_PRACTICE_CHAPTER_ID = 3  # Biology Chapter 5 (the chapter with live content)


def shop_unlock_state(conn, student_id: int) -> dict:
  mocks = conn.execute(
    "SELECT id, title FROM exam_papers WHERE chapter_id = ? AND type = 'mock' AND status = 'published' ORDER BY id",
    (SHOP_PRACTICE_CHAPTER_ID,),
  ).fetchall()
  done_ids = {
    int(r[0]) for r in conn.execute(
      "SELECT DISTINCT exam_paper_id FROM attempts WHERE student_id = ? AND status = 'completed'",
      (student_id,),
    ).fetchall()
  }
  total = len(mocks)
  done = [m for m in mocks if int(m[0]) in done_ids]
  missing = [str(m[1]) for m in mocks if int(m[0]) not in done_ids]
  return {"unlocked": total == 0 or len(done) >= total, "done": len(done), "total": total, "missing": missing}

# ---------------------------------------------------------------------------
# Sticker book (achievements): every sticker is different and is earned by doing something real.
# Images: static/images/stickers/sticker_<key>.webp
# ---------------------------------------------------------------------------
STICKERS = [
  # key, name, how to get it
  ("story_finished",   "Story Finished",   "Finish the chapter introduction"),
  ("plant_chef",       "Plant Chef",       "Win the plant food game"),
  ("food_explorer",    "Food Explorer",    "Win the food journey game"),
  ("deep_breather",    "Deep Breather",    "Win the breathing game"),
  ("blood_crew",       "Blood Crew",       "Win the blood crew game"),
  ("super_pump",       "Super Pump",       "Win the heart super-pump game"),
  ("clean_filter",     "Clean Filter",     "Win the kidney filter game"),
  ("team_hero",        "Team Hero",        "Win the life-process heroes game"),
  ("heart_builder",    "Heart Builder",    "Build the heart in the heart activity"),
  ("blood_flow_pro",   "Blood Flow Pro",   "Trace the blood flow in the heart activity"),
  ("first_steps",      "First Steps",      "Finish your first exam"),
  ("practice_perfect", "Practice Perfect", "Get 100% in a practice exam"),
  ("practice_pro",     "Practice Pro",     "Finish all 3 practice exams"),
  ("chapter_champion", "Chapter Champion", "Get 100% in the real exam"),
  ("coin_collector",   "Coin Collector",   "Earn 100 coins"),
  ("on_fire",          "On Fire",          "Study 3 days in a row"),
]


def get_student_stickers(conn, student_id: int, attempts=None, streak_days: int = 0, chapter_id: int = 3) -> list[dict]:
  try:
    claimed = {str(r[0]) for r in conn.execute("SELECT reward_key FROM coin_ledger WHERE student_id = ?", (student_id,)).fetchall()}
    coins_earned = int(conn.execute("SELECT COALESCE(SUM(coins), 0) FROM coin_ledger WHERE student_id = ? AND coins > 0", (student_id,)).fetchone()[0] or 0)
  except Exception:
    claimed, coins_earned = set(), 0
  try:
    intro_done = bool(chapter_path_state(conn, student_id, chapter_id).get("intro_done"))
  except Exception:
    intro_done = f"nutshell:ch:{chapter_id}" in claimed
  if attempts is None:
    attempts = get_recent_attempts(conn, student_id, limit=200)
  done = [a for a in attempts if a.get("status") == "completed"]
  best_mock = max([int(a.get("overall_pct") or 0) for a in done if a.get("exam_type") != "real"] or [0])
  best_real = max([int(a.get("overall_pct") or 0) for a in done if a.get("exam_type") == "real"] or [0])
  try:
    all_practice = bool(shop_unlock_state(conn, student_id).get("unlocked"))
  except Exception:
    all_practice = False
  g = lambda name: f"game:ch:{chapter_id}:{name}" in claimed
  earned = {
    "story_finished": intro_done,
    "plant_chef": g("leaf"), "food_explorer": g("food"), "deep_breather": g("breathe"), "blood_crew": g("blood"),
    "super_pump": g("pump"), "clean_filter": g("kidney"), "team_hero": g("team"),
    "heart_builder": f"heart_s1:ch:{chapter_id}" in claimed,
    "blood_flow_pro": f"heart_s2:ch:{chapter_id}" in claimed,
    "first_steps": len(done) >= 1,
    "practice_perfect": best_mock >= 100,
    "practice_pro": all_practice,
    "chapter_champion": best_real >= 100,
    "coin_collector": coins_earned >= 100,
    "on_fire": int(streak_days or 0) >= 3,
  }
  return [{"key": k, "name": n, "how": h, "earned": bool(earned.get(k))} for k, n, h in STICKERS]
