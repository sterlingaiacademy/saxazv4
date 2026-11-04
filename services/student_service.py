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
  cursor.execute("SELECT * FROM subjects WHERE class_id = ? ORDER BY order_index", (class_id,))
  subjects = [dict(row) for row in cursor.fetchall()]
  
  for sub in subjects:
    # Fetch seconds studied for this subject
    cursor.execute("SELECT seconds_studied FROM subject_study_time WHERE student_id = ? AND subject_id = ?", (student_id, sub['id']))
    time_row = cursor.fetchone()
    seconds = time_row[0] if time_row and time_row[0] else 0
    sub['seconds_studied'] = seconds
    sub['minutes_studied'] = round(seconds / 60, 1)
    sub['time_studied_str'] = format_seconds(seconds)

    # Get total items in subject (content + exams)
    cursor.execute("""
      SELECT 
        (SELECT COUNT(*) FROM content_items ci JOIN chapters c ON ci.chapter_id = c.id WHERE c.subject_id = ? AND c.status = 'published') as total_content,
        (SELECT COUNT(*) FROM exam_papers ep JOIN chapters c ON ep.chapter_id = c.id WHERE c.subject_id = ? AND c.status = 'published' AND ep.status = 'published') as total_exams
    """, (sub['id'], sub['id']))
    counts = cursor.fetchone()
    total_items = counts[0] + counts[1]
    
    if total_items == 0:
      sub['progress_pct'] = 0
      continue
      
    # Get completed items
    cursor.execute("""
      SELECT COUNT(*) FROM content_progress cp
      JOIN content_items ci ON cp.content_item_id = ci.id
      JOIN chapters c ON ci.chapter_id = c.id
      WHERE c.subject_id = ? AND cp.student_id = ? AND cp.completed = 1 AND c.status = 'published'
    """, (sub['id'], student_id))
    completed_content = cursor.fetchone()[0]
    
    cursor.execute("""
      SELECT COUNT(DISTINCT ep.id) FROM attempts a
      JOIN exam_papers ep ON a.exam_paper_id = ep.id
      JOIN chapters c ON ep.chapter_id = c.id
      WHERE c.subject_id = ? AND a.student_id = ? AND a.status = 'completed' AND c.status = 'published' AND ep.status = 'published'
    """, (sub['id'], student_id))
    completed_exams = cursor.fetchone()[0]
    
    completed_items = completed_content + completed_exams
    sub['progress_pct'] = int((completed_items / total_items) * 100)
    
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
    
    # Get exams count
    cursor.execute("SELECT COUNT(*) FROM exam_papers WHERE chapter_id = ? AND status = 'published'", (ch['id'],))
    total_exams = cursor.fetchone()[0]
    
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
    
    total_completed = completed_content + completed_exams
    
    # Calculate progress percentage
    ch['progress_pct'] = int((total_completed / total_items * 100)) if total_items > 0 else 0
    
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
    WHERE c.status = 'published'
    ORDER BY c.order_index, c.id
  """)
  published_chapters = [dict(row) for row in cursor.fetchall()]
  
  cursor.execute("SELECT * FROM classes WHERE id = ? ORDER BY order_index, id", (student_class_id,))
  classes = [dict(row) for row in cursor.fetchall()]
  
  cursor.execute("SELECT * FROM subjects WHERE class_id IN (SELECT id FROM classes WHERE id = ?) ORDER BY order_index, id", (student_class_id,))
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
  cursor.execute("SELECT * FROM chapters WHERE id = ? AND status = 'published'", (chapter_id,))
  row = cursor.fetchone()
  if not row: return None
  
  chapter = dict(row)
  cursor.execute("SELECT * FROM content_items WHERE chapter_id = ? ORDER BY order_index, id", (chapter_id,))
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

def get_available_exams(conn, chapter_id: int, student_id: int):
  cursor = conn.cursor()
  # 1. Fetch all published exams
  cursor.execute("SELECT * FROM exam_papers WHERE chapter_id = ? AND status = 'published' ORDER BY id", (chapter_id,))
  exams = [dict(row) for row in cursor.fetchall()]
  
  # 2. Get highest scores for this student in this topic for ALL exams
  cursor.execute("""
    SELECT sub.exam_paper_id, MAX(CAST(sub.total_marks_awarded AS FLOAT) / CAST(sub.total_max_marks AS FLOAT) * 100) as highest_pct
    FROM (
        SELECT
          a.exam_paper_id,
          COALESCE(SUM(ans.marks_awarded), a.total_marks_awarded, 0) as total_marks_awarded,
          COALESCE(
            NULLIF(a.total_max_marks, 0),
            (SELECT SUM(q.max_marks) FROM questions q JOIN modules m ON q.module_id = m.id WHERE m.exam_paper_id = e.id),
            e.target_marks,
            0
          ) as total_max_marks
        FROM attempts a
        JOIN exam_papers e ON a.exam_paper_id = e.id
        LEFT JOIN answers ans ON a.id = ans.attempt_id AND ans.is_latest = 1
        WHERE a.student_id = ? AND e.chapter_id = ?
        GROUP BY a.id, a.exam_paper_id
    ) sub
    WHERE sub.total_max_marks > 0
    GROUP BY sub.exam_paper_id
  """, (student_id, chapter_id))
  
  exam_scores = {row['exam_paper_id']: row['highest_pct'] for row in cursor.fetchall()}
  
  # Attach highest scores to all exams (enables Retake UI)
  for exam in exams:
    exam['highest_score'] = exam_scores.get(exam['id'])
    exam['is_locked'] = False # Default state
  
  # 3. Determine if Real exams are locked based on Mock exams.
  mock_exams = [e for e in exams if e['type'] == 'mock']
  real_exams = [e for e in exams if e['type'] == 'real']
  
  if real_exams:
    # Get highest score across any mock exam in this topic
    highest_mock_score = 0.0
    for mock in mock_exams:
      score = exam_scores.get(mock['id'])
      if score is None:
        score = 0.0
      if score > highest_mock_score:
        highest_mock_score = score
        
    for real in real_exams:
      req_mock = real.get('required_mock_percent')
      if req_mock is not None and highest_mock_score < req_mock:
        real['is_locked'] = True
        real['unlock_reason'] = f"Requires {req_mock}% in Mock Exam (Highest: {int(highest_mock_score)}%)"
        
      # Check max_attempts (only count completed attempts)
      max_att = real.get('max_attempts')
      if max_att is not None:
        cursor.execute("SELECT COUNT(*) FROM attempts WHERE student_id = ? AND exam_paper_id = ? AND status = 'completed'", (student_id, real['id']))
        attempts_count = cursor.fetchone()[0]
        real['attempts_taken'] = attempts_count
        if attempts_count >= max_att:
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
        cursor.execute("SELECT * FROM questions WHERE module_id = ? ORDER BY id", (module['id'],))
        module['questions'] = [dict(q) for q in cursor.fetchall()]
        mval = module.get('mark_value') or 1
        total_mock_marks += len(module['questions']) * mval
        
      if total_mock_marks <= target_marks:
        # Target is too high or equal, just take all and shuffle deterministically per attempt
        for module in paper['modules']:
          rng.shuffle(module['questions'])
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
      return paper

  # Normal behavior
  cursor.execute("SELECT * FROM modules WHERE exam_paper_id = ? ORDER BY order_index, id", (paper['id'],))
  paper['modules'] = [dict(r) for r in cursor.fetchall()]
  
  for module in paper['modules']:
    cursor.execute("SELECT * FROM questions WHERE module_id = ? ORDER BY order_index, id", (module['id'],))
    module['questions'] = [dict(q) for q in cursor.fetchall()]
    
  return paper

def start_exam_attempt(conn, exam_paper_id: int, version: int, student_id: int):
  cursor = conn.cursor()
  cursor.execute(
    "INSERT INTO attempts (exam_paper_id, exam_paper_version, student_id, status) VALUES (?, ?, ?, 'in_progress')",
    (exam_paper_id, version, student_id)
  )
  conn.commit()
  return cursor.lastrowid

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

def complete_attempt(conn, attempt_id: int):
  cursor = conn.cursor()
  cursor.execute("SELECT student_id FROM attempts WHERE id = ?", (attempt_id,))
  s_row = cursor.fetchone()
  student_id = s_row[0] if s_row else None

  # Aggregate scores (only for the latest attempt per question)
  cursor.execute("SELECT SUM(marks_awarded) as total FROM answers WHERE attempt_id = ? AND is_latest = 1", (attempt_id,))
  row = cursor.fetchone()
  total_marks = row[0] or 0
  
  # Calculate total max marks from modules for the entire exam
  cursor.execute("""
    SELECT SUM(q.max_marks) 
    FROM attempts att
    JOIN modules m ON m.exam_paper_id = att.exam_paper_id
    JOIN questions q ON q.module_id = m.id
    WHERE att.id = ?
  """, (attempt_id,))
  total_max = cursor.fetchone()[0] or 0

  # Fallback for scrambled Real Exams (use_mock_questions = 1) where questions belong to mock modules
  if total_max == 0:
    cursor.execute("""
      SELECT SUM(q.max_marks)
      FROM answers ans
      JOIN questions q ON ans.question_id = q.id
      WHERE ans.attempt_id = ? AND ans.is_latest = 1
    """, (attempt_id,))
    total_max = cursor.fetchone()[0] or 0

  if total_max == 0:
    cursor.execute("""
      SELECT ep.target_marks
      FROM attempts att
      JOIN exam_papers ep ON att.exam_paper_id = ep.id
      WHERE att.id = ?
    """, (attempt_id,))
    tm_row = cursor.fetchone()
    total_max = (tm_row[0] if tm_row and tm_row[0] else 0)
  
  cursor.execute(
    "UPDATE attempts SET status = 'completed', completed_at = CURRENT_TIMESTAMP, total_marks_awarded = ?, total_max_marks = ? WHERE id = ?",
    (total_marks, total_max, attempt_id)
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
  
  # Get answers with question details (only latest)
  cursor.execute("""
    SELECT a.*, q.question_text, q.model_answer, q.max_marks, q.media_url, q.answer_media_url, q.explanation_video_url, q.explanation_video_type, m.name as module_name
    FROM answers a
    JOIN questions q ON a.question_id = q.id
    JOIN modules m ON a.module_id = m.id
    WHERE a.attempt_id = ? AND a.is_latest = 1
    ORDER BY m.order_index, m.id, q.order_index, q.id
  """, (attempt_id,))
  attempt['answers'] = [dict(r) for r in cursor.fetchall()]
  if attempt['total_max_marks'] == 0 and attempt['answers']:
    attempt['total_max_marks'] = sum((ans.get('max_marks') or 0) for ans in attempt['answers'])
  return attempt

def get_recent_attempts(conn, student_id: int, limit: int = 3):
  cursor = conn.cursor()
  cursor.execute("""
    SELECT 
      a.id, 
      COALESCE(a.completed_at, MAX(ans.submitted_at), a.started_at) as completed_at, 
      COALESCE(SUM(ans.marks_awarded), a.total_marks_awarded, 0) as total_marks_awarded, 
      COALESCE(
        NULLIF(a.total_max_marks, 0),
        (SELECT SUM(q2.max_marks) FROM questions q2 JOIN modules m2 ON q2.module_id = m2.id WHERE m2.exam_paper_id = e.id),
        e.target_marks,
        0
      ) as total_max_marks, 
      e.title as exam_title
    FROM attempts a
    JOIN exam_papers e ON a.exam_paper_id = e.id
    LEFT JOIN answers ans ON a.id = ans.attempt_id AND ans.is_latest = 1
    WHERE a.student_id = ? AND (a.status = 'completed' OR ans.id IS NOT NULL)
    GROUP BY a.id, e.title, a.started_at
    ORDER BY completed_at DESC
    LIMIT ?
  """, (student_id, limit))
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
      
    total_m = attempt.get('total_marks_awarded')
    total_m = total_m if total_m is not None else 0
    max_m = attempt.get('total_max_marks')
    max_m = max_m if max_m is not None else 0
    
    pct = (total_m / max_m * 100) if max_m > 0 else 0
    attempt['pct'] = int(pct)
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
  day_labels = ['M', 'T', 'W', 'T', 'F', 'S', 'S']
  daily_max = 1
  for i in range(6, -1, -1):
    d = today - datetime.timedelta(days=i)
    d_str = d.strftime('%Y-%m-%d')
    solved, mods = activity_by_date.get(d_str, (0, 0))
    score = solved + (mods * 5)
    if score > daily_max:
      daily_max = score
    activity_data['daily'].append({
      "label": day_labels[d.weekday()],
      "value": score,
      "duration_str": f"{solved} Questions, {mods} Modules",
      "is_today": (i == 0)
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
    score = solved + (mods * 5)
    if score > weekly_max:
      weekly_max = score
    
    if i == 0:
      label = "This Wk"
    elif i == 1:
      label = "Last Wk"
    else:
      label = week_start.strftime('%b %d')
      
    activity_data['weekly'].append({
      "label": label,
      "value": score,
      "duration_str": f"{solved} Questions, {mods} Modules",
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
    score = solved + (mods * 5)
    if score > monthly_max:
      monthly_max = score
    
    label = datetime.date(year, month, 1).strftime('%b')
    activity_data['monthly'].append({
      "label": label,
      "value": score,
      "duration_str": f"{solved} Questions, {mods} Modules",
      "is_today": (i == 0)
    })
  for item in activity_data['monthly']:
    item['height_pct'] = max(12, int((item['value'] / monthly_max) * 100)) if item['value'] > 0 else 0
    
  # 6. League calculation
  league = "Bronze"
  league_color = "amber-700"
  league_hex = "#d97706"
  league_gradient = "linear-gradient(90deg, #f59e0b 0%, #d97706 50%, #b45309 100%)"
  prev_tier_xp = 0
  next_tier_xp = 500
  if total_xp >= 3500:
    league = "Diamond"
    league_color = "cyan-400"
    league_hex = "#06b6d4"
    league_gradient = "linear-gradient(90deg, #22d3ee 0%, #06b6d4 50%, #3b82f6 100%)"
    prev_tier_xp = 3500
    next_tier_xp = total_xp
  elif total_xp >= 1500:
    league = "Gold"
    league_color = "yellow-400"
    league_hex = "#eab308"
    league_gradient = "linear-gradient(90deg, #facc15 0%, #f59e0b 50%, #eab308 100%)"
    prev_tier_xp = 1500
    next_tier_xp = 3500
  elif total_xp >= 500:
    league = "Silver"
    league_color = "gray-400"
    league_hex = "#64748b"
    league_gradient = "linear-gradient(90deg, #94a3b8 0%, #64748b 50%, #475569 100%)"
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

  for subj in subjects:
    cursor.execute("""
      SELECT qb.id
      FROM digi_question_banks qb
      WHERE qb.subject_id = ? AND qb.status = 'published'
    """, (subj['id'],))
    bank_ids = [r[0] for r in cursor.fetchall()]
    total_banks = len(bank_ids)
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
  cursor.execute("SELECT COUNT(*) FROM digi_questions WHERE bank_id = ?", (bank_id,))
  total_q = cursor.fetchone()[0] or 0
  cursor.execute(
    "INSERT INTO digi_attempts (bank_id, student_id, status, total_questions) VALUES (?, ?, 'in_progress', ?)",
    (bank_id, student_id, total_q)
  )
  conn.commit()
  return cursor.lastrowid


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

