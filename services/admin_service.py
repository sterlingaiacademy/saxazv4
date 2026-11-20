from database import get_db_connection
import json
import uuid
def get_classes(conn):
  cursor = conn.cursor()
  cursor.execute("SELECT * FROM classes ORDER BY order_index, id")
  return [dict(row) for row in cursor.fetchall()]

def get_subjects(conn, class_id):
  cursor = conn.cursor()
  cursor.execute("SELECT * FROM subjects WHERE class_id = ? ORDER BY order_index, id", (class_id,))
  return [dict(row) for row in cursor.fetchall()]

def get_chapters(conn, subject_id):
  cursor = conn.cursor()
  cursor.execute("SELECT * FROM chapters WHERE subject_id = ? ORDER BY order_index, id", (subject_id,))
  return [dict(row) for row in cursor.fetchall()]

def get_chapter(conn, chapter_id: int):
  cursor = conn.cursor()
  cursor.execute('SELECT * FROM chapters WHERE id = ?', (chapter_id,))
  row = cursor.fetchone()
  return dict(row) if row else None


def get_full_curriculum_tree(conn):
  # This fetches everything for the main view. In a very large app we might lazy-load,
  # but for curriculum builder, having it all is fine.
  classes = get_classes(conn)
  for c in classes:
    c['subjects'] = get_subjects(conn, c['id'])
    for s in c['subjects']:
      s['chapters'] = get_chapters(conn, s['id'])
  return classes

def create_class(conn, name: str, description: str = None, thumbnail_url: str = None):
  name = name.strip()
  if not name or len(name) > 120:
    raise ValueError("Class name must be between 1 and 120 characters")
  if name.isdigit():
    name = f"Grade {name}"
  cursor = conn.cursor()
  cursor.execute("SELECT id FROM classes WHERE lower(name) = lower(?)", (name,))
  if cursor.fetchone():
    raise ValueError("Class name already exists")
  cursor.execute("SELECT MAX(order_index) FROM classes")
  max_idx = cursor.fetchone()[0] or 0
  cursor.execute("INSERT INTO classes (name, description, thumbnail_url, order_index) VALUES (?, ?, ?, ?)", (name, description, thumbnail_url, max_idx + 1))
  conn.commit()
  return cursor.lastrowid

def create_subject(conn, class_id: int, name: str, description: str = None, thumbnail_url: str = None):
  name = name.strip()
  if not name or len(name) > 120:
    raise ValueError("Subject name must be between 1 and 120 characters")
  cursor = conn.cursor()
  cursor.execute("SELECT id FROM subjects WHERE class_id = ? AND lower(name) = lower(?)", (class_id, name))
  if cursor.fetchone():
    raise ValueError("Subject name already exists in this class")
  cursor.execute("SELECT MAX(order_index) FROM subjects WHERE class_id = ?", (class_id,))
  max_idx = cursor.fetchone()[0] or 0
  cursor.execute("INSERT INTO subjects (class_id, name, description, thumbnail_url, order_index) VALUES (?, ?, ?, ?, ?)", (class_id, name, description, thumbnail_url, max_idx + 1))
  conn.commit()
  return cursor.lastrowid

def create_chapter(conn, subject_id: int, name: str, description: str = None, thumbnail_url: str = None):
  name = name.strip()
  if not name or len(name) > 120:
    raise ValueError("Chapter name must be between 1 and 120 characters")
  cursor = conn.cursor()
  cursor.execute("SELECT id FROM chapters WHERE subject_id = ? AND lower(name) = lower(?)", (subject_id, name))
  if cursor.fetchone():
    raise ValueError("Chapter name already exists in this subject")
  cursor.execute("SELECT MAX(order_index) FROM chapters WHERE subject_id = ?", (subject_id,))
  max_idx = cursor.fetchone()[0] or 0
  cursor.execute("INSERT INTO chapters (subject_id, name, description, thumbnail_url, order_index) VALUES (?, ?, ?, ?, ?)", (subject_id, name, description, thumbnail_url, max_idx + 1))
  conn.commit()
  return cursor.lastrowid


def update_node_name(conn, table: str, id: int, name: str):
  allowed_tables = {'classes', 'subjects', 'chapters'}
  if table not in allowed_tables:
    raise ValueError("Invalid table")
  
  name = name.strip()
  if not name or len(name) > 120:
    raise ValueError("Name must be between 1 and 120 characters")

  if table == 'classes' and name.isdigit():
    name = f"Grade {name}"

    
  cursor = conn.cursor()
  
  if table == 'classes':
    cursor.execute("SELECT id FROM classes WHERE lower(name) = lower(?) AND id != ?", (name, id))
    if cursor.fetchone():
      raise ValueError("Class name already exists")
  elif table == 'subjects':
    cursor.execute("SELECT class_id FROM subjects WHERE id = ?", (id,))
    row = cursor.fetchone()
    if row:
      cursor.execute("SELECT id FROM subjects WHERE class_id = ? AND lower(name) = lower(?) AND id != ?", (row['class_id'], name, id))
      if cursor.fetchone():
        raise ValueError("Subject name already exists in this class")
  elif table == 'chapters':
    cursor.execute("SELECT subject_id FROM chapters WHERE id = ?", (id,))
    row = cursor.fetchone()
    if row:
      cursor.execute("SELECT id FROM chapters WHERE subject_id = ? AND lower(name) = lower(?) AND id != ?", (row['subject_id'], name, id))
      if cursor.fetchone():
        raise ValueError("Chapter name already exists in this subject")

  conn.execute(f"UPDATE {table} SET name = ? WHERE id = ?", (name, id))
  conn.commit()

def update_chapter_status(conn, id: int, status: str):
  if status not in ('draft', 'published'):
    raise ValueError("Invalid status")
  conn.execute("UPDATE chapters SET status = ? WHERE id = ?", (status, id))
  conn.commit()

def update_chapter_links(conn, chapter_id: int, video_description_url: str, real_life_url: str):
  """Save the admin-configured intro page YouTube links for a chapter."""
  conn.execute(
    "UPDATE chapters SET video_description_url = ?, real_life_url = ? WHERE id = ?",
    (video_description_url or '', real_life_url or '', chapter_id)
  )
  conn.commit()

def _cascade_delete_chapter(cursor, chapter_id: int):
  """Delete all content and exams under a chapter, including student attempts and answers."""
  cursor.execute("DELETE FROM content_progress WHERE content_item_id IN (SELECT id FROM content_items WHERE chapter_id = ?)", (chapter_id,))
  cursor.execute("DELETE FROM content_items WHERE chapter_id = ?", (chapter_id,))
  cursor.execute("SELECT id FROM exam_papers WHERE chapter_id = ?", (chapter_id,))
  paper_ids = [r[0] for r in cursor.fetchall()]
  for pid in paper_ids:
    # Delete student attempts and their answers
    cursor.execute("SELECT id FROM attempts WHERE exam_paper_id = ?", (pid,))
    attempt_ids = [r[0] for r in cursor.fetchall()]
    for aid in attempt_ids:
      cursor.execute("DELETE FROM answers WHERE attempt_id = ?", (aid,))
    cursor.execute("DELETE FROM attempts WHERE exam_paper_id = ?", (pid,))
    # Delete questions and modules
    cursor.execute("SELECT id FROM modules WHERE exam_paper_id = ?", (pid,))
    module_ids = [r[0] for r in cursor.fetchall()]
    for mid in module_ids:
      cursor.execute("DELETE FROM questions WHERE module_id = ?", (mid,))
    cursor.execute("DELETE FROM modules WHERE exam_paper_id = ?", (pid,))
  cursor.execute("DELETE FROM exam_papers WHERE chapter_id = ?", (chapter_id,))

def delete_node(conn, table: str, id: int):
  allowed_tables = {'classes', 'subjects', 'chapters'}
  if table not in allowed_tables:
    raise ValueError("Invalid table")
  cursor = conn.cursor()
  if table == 'classes':
    # Unlink students from this class before deletion to avoid FK violations
    cursor.execute("UPDATE users SET class_id = NULL WHERE class_id = ?", (id,))
    # Get all subject IDs under this class
    cursor.execute("SELECT id FROM subjects WHERE class_id = ?", (id,))
    subject_ids = [r[0] for r in cursor.fetchall()]
    for sid in subject_ids:
      cursor.execute("SELECT id FROM chapters WHERE subject_id = ?", (sid,))
      chapter_ids = [r[0] for r in cursor.fetchall()]
      for cid in chapter_ids:
        _cascade_delete_chapter(cursor, cid)
      cursor.execute("DELETE FROM chapters WHERE subject_id = ?", (sid,))
    cursor.execute("DELETE FROM subjects WHERE class_id = ?", (id,))
  elif table == 'subjects':
    cursor.execute("SELECT id FROM chapters WHERE subject_id = ?", (id,))
    chapter_ids = [r[0] for r in cursor.fetchall()]
    for cid in chapter_ids:
      _cascade_delete_chapter(cursor, cid)
    cursor.execute("DELETE FROM chapters WHERE subject_id = ?", (id,))
  elif table == 'chapters':
    _cascade_delete_chapter(cursor, id)
  conn.execute(f"DELETE FROM {table} WHERE id = ?", (id,))
  conn.commit()

def get_content_items(conn, chapter_id: int):
  cursor = conn.cursor()
  cursor.execute("SELECT * FROM content_items WHERE chapter_id = ? ORDER BY order_index, id", (chapter_id,))
  return [dict(row) for row in cursor.fetchall()]

def create_content_item(conn, chapter_id: int, item_type: str, title: str, media_url: str):
  if item_type not in ('video', 'audio', 'pdf', 'text', 'youtube'):
    raise ValueError("Invalid content item type")
  
  cursor = conn.cursor()
  cursor.execute("SELECT MAX(order_index) FROM content_items WHERE chapter_id = ?", (chapter_id,))
  max_idx = cursor.fetchone()[0] or 0
  
  cursor.execute(
    "INSERT INTO content_items (chapter_id, type, title, media_url, order_index) VALUES (?, ?, ?, ?, ?)",
    (chapter_id, item_type, title, media_url, max_idx + 1)
  )
  conn.commit()
  return cursor.lastrowid

def delete_content_item(conn, item_id: int):
  cursor = conn.cursor()
  cursor.execute("SELECT media_url FROM content_items WHERE id = ?", (item_id,))
  row = cursor.fetchone()
  media_url = row[0] if row else None
  conn.execute("DELETE FROM content_progress WHERE content_item_id = ?", (item_id,))
  conn.execute("DELETE FROM content_items WHERE id = ?", (item_id,))
  conn.commit()
  return media_url

# --- EXAM BUILDER FUNCTIONS ---

def get_exam_papers(conn, chapter_id: int):
  cursor = conn.cursor()
  cursor.execute("SELECT * FROM exam_papers WHERE chapter_id = ? ORDER BY id", (chapter_id,))
  papers = [dict(row) for row in cursor.fetchall()]
  for paper in papers:
    paper_total_marks = 0
    cursor.execute("SELECT * FROM modules WHERE exam_paper_id = ? ORDER BY order_index, id", (paper['id'],))
    paper['modules'] = [dict(row) for row in cursor.fetchall()]
    for module in paper['modules']:
      cursor.execute("SELECT * FROM questions WHERE module_id = ? ORDER BY order_index, id", (module['id'],))
      module['questions'] = [dict(row) for row in cursor.fetchall()]
      paper_total_marks += len(module['questions']) * module['mark_value']
    paper['total_marks'] = paper_total_marks
  return papers

def get_exam_paper_full(conn, exam_id: int):
  cursor = conn.cursor()
  cursor.execute("SELECT * FROM exam_papers WHERE id = ?", (exam_id,))
  row = cursor.fetchone()
  if not row: return None
  paper = dict(row)
  
  cursor.execute("SELECT * FROM modules WHERE exam_paper_id = ? ORDER BY order_index, id", (exam_id,))
  paper['modules'] = [dict(r) for r in cursor.fetchall()]
  total_marks = 0
  for module in paper['modules']:
    cursor.execute("SELECT * FROM questions WHERE module_id = ? ORDER BY order_index, id", (module['id'],))
    module['questions'] = [dict(r) for r in cursor.fetchall()]
    total_marks += len(module['questions']) * (module.get('mark_value') or 0)
  paper['total_marks'] = total_marks
    
  return paper

def create_exam_paper(conn, chapter_id: int, type: str, title: str, unlock_threshold_percent: float = None, required_mock_percent: float = None, max_attempts: int = None, use_mock_questions: int = 0, target_marks: int = None):
  cursor = conn.cursor()
  cursor.execute(
    "INSERT INTO exam_papers (chapter_id, type, title, unlock_threshold_percent, required_mock_percent, max_attempts, use_mock_questions, target_marks) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    (chapter_id, type, title, unlock_threshold_percent, required_mock_percent, max_attempts, use_mock_questions, target_marks)
  )
  conn.commit()
  return cursor.lastrowid

def update_exam_status(conn, exam_id: int, status: str):
  cursor = conn.cursor()
  cursor.execute("UPDATE exam_papers SET status = ? WHERE id = ?", (status, exam_id))
  conn.commit()

def create_module(conn, exam_paper_id: int, name: str, mark_value: int, time_limit_seconds: int = 60, question_type: str = 'LONG_ANSWER'):
  cursor = conn.cursor()
  cursor.execute("SELECT MAX(order_index) FROM modules WHERE exam_paper_id = ?", (exam_paper_id,))
  max_idx = cursor.fetchone()[0] or 0
  cursor.execute(
    "INSERT INTO modules (exam_paper_id, name, mark_value, order_index, time_limit_seconds, question_type) VALUES (?, ?, ?, ?, ?, ?)",
    (exam_paper_id, name, mark_value, max_idx + 1, time_limit_seconds, question_type)
  )
  conn.commit()
  return cursor.lastrowid

def update_class_description(conn, class_id: int, description: str):
  description = description.strip() if description else ''
  conn.execute("UPDATE classes SET description = ? WHERE id = ?", (description or None, class_id))
  conn.commit()

def update_subject_description(conn, subject_id: int, description: str):
  description = description.strip() if description else ''
  conn.execute("UPDATE subjects SET description = ? WHERE id = ?", (description or None, subject_id))
  conn.commit()

def update_chapter_description(conn, chapter_id: int, description: str):
  description = description.strip() if description else ''
  conn.execute("UPDATE chapters SET description = ? WHERE id = ?", (description or None, chapter_id))
  conn.commit()

def update_module_name(conn, module_id: int, name: str, mark_value: int = None, time_limit_seconds: int = None, question_type: str = None):
  name = name.strip()
  if not name or len(name) > 120:
    raise ValueError("Module name must be between 1 and 120 characters")
  cursor = conn.cursor()
  cursor.execute("SELECT exam_paper_id, mark_value, time_limit_seconds, question_type FROM modules WHERE id = ?", (module_id,))
  row = cursor.fetchone()
  if row:
    cursor.execute("SELECT id FROM modules WHERE exam_paper_id = ? AND lower(name) = lower(?) AND id != ?", (row['exam_paper_id'], name, module_id))
    if cursor.fetchone():
      raise ValueError("A module with that name already exists in this exam")
    new_mark = mark_value if mark_value is not None else row['mark_value']
    new_time = time_limit_seconds if time_limit_seconds is not None else row['time_limit_seconds']
    new_type = question_type if question_type is not None else (row['question_type'] if 'question_type' in row.keys() else 'LONG_ANSWER')
    conn.execute("UPDATE modules SET name = ?, mark_value = ?, time_limit_seconds = ?, question_type = ? WHERE id = ?", (name, new_mark, new_time, new_type, module_id))
    if mark_value is not None and mark_value != row['mark_value']:
      conn.execute("UPDATE questions SET max_marks = ? WHERE module_id = ?", (new_mark, module_id))
  else:
    conn.execute("UPDATE modules SET name = ? WHERE id = ?", (name, module_id))
  conn.commit()

def create_question(conn, module_id: int, question_text: str, model_answer: str, max_marks: int, options: str = None, media_url: str = None, question_type: str = None):
  cursor = conn.cursor()
  cursor.execute("SELECT MAX(order_index) FROM questions WHERE module_id = ?", (module_id,))
  max_idx = cursor.fetchone()[0] or 0
  cursor.execute(
    "INSERT INTO questions (module_id, question_text, model_answer, max_marks, order_index, options, media_url, question_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    (module_id, question_text, model_answer, max_marks, max_idx + 1, options, media_url, question_type)
  )
  conn.commit()
  return cursor.lastrowid


def set_question_explanation_video(conn, question_id: int, video_url: str, video_type: str):
  cursor = conn.cursor()
  cursor.execute("UPDATE questions SET explanation_video_url = ?, explanation_video_type = ? WHERE id = ?", (video_url, video_type, question_id))
  conn.commit()

def get_question(conn, question_id: int):
  cursor = conn.cursor()
  cursor.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
  row = cursor.fetchone()
  if not row:
    return None
  q = dict(row)
  # Parse additional_videos from JSON column
  try:
    import json
    q['additional_videos'] = json.loads(q.get('additional_videos') or '[]')
  except Exception:
    q['additional_videos'] = []
  return q

def delete_exam_node(conn, table: str, id: int):
  allowed_tables = {'exam_papers', 'modules', 'questions'}
  if table not in allowed_tables:
    raise ValueError("Invalid exam node table")
  cursor = conn.cursor()
  if table == 'exam_papers':
    # Delete student attempts and their answers first
    cursor.execute("SELECT id FROM attempts WHERE exam_paper_id = ?", (id,))
    attempt_ids = [r[0] for r in cursor.fetchall()]
    for aid in attempt_ids:
      cursor.execute("DELETE FROM answers WHERE attempt_id = ?", (aid,))
    cursor.execute("DELETE FROM attempts WHERE exam_paper_id = ?", (id,))
    # Delete questions and modules
    cursor.execute("SELECT id FROM modules WHERE exam_paper_id = ?", (id,))
    module_ids = [r[0] for r in cursor.fetchall()]
    for mid in module_ids:
      cursor.execute("DELETE FROM questions WHERE module_id = ?", (mid,))
    cursor.execute("DELETE FROM modules WHERE exam_paper_id = ?", (id,))
  elif table == 'modules':
    cursor.execute("DELETE FROM questions WHERE module_id = ?", (id,))
  conn.execute(f"DELETE FROM {table} WHERE id = ?", (id,))
  conn.commit()

# --- ANALYTICS ---

def get_students_analytics(conn):
  cursor = conn.cursor()
  # Get all students
  cursor.execute("SELECT id, name, email, class_id FROM users WHERE role = 'student' ORDER BY name")
  students = [dict(r) for r in cursor.fetchall()]
  
  for student in students:
    s_class_id = student['class_id'] or 1
    # Get total available content count for this student's class (published & visible subjects only)
    cursor.execute("""
      SELECT COUNT(*) FROM content_items ci 
      JOIN chapters c ON ci.chapter_id = c.id 
      JOIN subjects s ON c.subject_id = s.id
      WHERE c.status = 'published' AND COALESCE(s.is_hidden, 0) = 0 AND s.class_id = ?
    """, (s_class_id,))
    student['total_content_available'] = cursor.fetchone()[0] or 0

    # Get content progress count (matching published & visible curriculum items)
    cursor.execute("""
      SELECT COUNT(DISTINCT cp.content_item_id)
      FROM content_progress cp
      JOIN content_items ci ON cp.content_item_id = ci.id
      JOIN chapters c ON ci.chapter_id = c.id
      JOIN subjects s ON c.subject_id = s.id
      WHERE cp.student_id = ? AND cp.completed = 1
        AND c.status = 'published' AND COALESCE(s.is_hidden, 0) = 0 AND s.class_id = ?
    """, (student['id'], s_class_id))
    student['content_completed'] = cursor.fetchone()[0] or 0
    
    # Get exam attempts (published & visible curriculum only)
    cursor.execute("""
      SELECT
        a.id,
        COALESCE(SUM(ans.marks_awarded), a.total_marks_awarded, 0) as total_marks_awarded,
        COALESCE(
          CASE WHEN e.type = 'mock' THEN NULLIF(SUM(COALESCE(q.max_marks, m.mark_value, 1)), 0) ELSE NULL END,
          NULLIF(a.total_max_marks, 0),
          NULLIF((SELECT SUM(COALESCE(q2.max_marks, m2.mark_value, 1)) FROM questions q2 JOIN modules m2 ON q2.module_id = m2.id WHERE m2.exam_paper_id = e.id AND COALESCE(q2.is_hidden, 0) = 0 AND COALESCE(q2.textbook_section, 'Questions') NOT IN ('HOTS', 'POWER_UP')), 0),
          e.target_marks,
          0
        ) as total_max_marks,
        COALESCE(MAX(ans.submitted_at), a.completed_at, a.started_at) as completed_at,
        e.title
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
        AND (a.status = 'completed' OR ans.id IS NOT NULL)
      GROUP BY a.id, e.id, e.type, e.title, a.started_at
      ORDER BY completed_at DESC
    """, (student['id'],))
    student['exam_attempts'] = [dict(r) for r in cursor.fetchall()]
    
  return students

def get_attempt_review(conn, attempt_id: int):
  cursor = conn.cursor()
  cursor.execute("""
    SELECT a.*, e.title as exam_title, u.name as student_name
    FROM attempts a
    JOIN exam_papers e ON a.exam_paper_id = e.id
    JOIN users u ON a.student_id = u.id
    WHERE a.id = ?
  """, (attempt_id,))
  row = cursor.fetchone()
  if not row: return None
  attempt = dict(row)
  
  # Get latest answers with question details
  cursor.execute("""
    SELECT a.*, q.question_text, q.model_answer, q.max_marks, m.name as module_name
    FROM answers a
    JOIN questions q ON a.question_id = q.id
    JOIN modules m ON a.module_id = m.id
    WHERE a.attempt_id = ? AND a.is_latest = 1
    ORDER BY m.order_index, m.id, q.order_index, q.id
  """, (attempt_id,))
  attempt['answers'] = [dict(r) for r in cursor.fetchall()]
  if not attempt.get('total_max_marks') and attempt['answers']:
    attempt['total_max_marks'] = sum((ans.get('max_marks') or 0) for ans in attempt['answers'])
  if attempt.get('total_marks_awarded') is None:
    attempt['total_marks_awarded'] = sum((ans.get('marks_awarded') or 0) for ans in attempt['answers'])
  return attempt

def get_dashboard_stats(conn):
  cursor = conn.cursor()
  
  # Total Students
  cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'student'")
  students_count = cursor.fetchone()[0] or 0
  
  # Total Classes
  cursor.execute("SELECT COUNT(*) FROM classes")
  classes_count = cursor.fetchone()[0] or 0
  
  # Total Completed Exams/Quizzes
  cursor.execute("""
    SELECT COUNT(DISTINCT a.id)
    FROM attempts a
    JOIN answers ans ON a.id = ans.attempt_id
  """)
  completed_exams_count = cursor.fetchone()[0] or 0
  
  # Performance Chart Data (Last 30 Days)
  cursor.execute("""
    SELECT * FROM (
        SELECT 
            date(ans.submitted_at) as date,
            SUM(ans.marks_awarded) as score,
            SUM(q.max_marks) as max
        FROM answers ans
        JOIN questions q ON ans.question_id = q.id
        WHERE ans.is_latest = 1
        GROUP BY date(ans.submitted_at)
        ORDER BY date DESC
        LIMIT 30
    ) ORDER BY date ASC
  """)
  rows = cursor.fetchall()
  
  performance_data = {
      "labels": [],
      "scores": [],
      "maxes": []
  }
  for r in rows:
      performance_data['labels'].append(r['date'])
      performance_data['scores'].append(r['score'])
      performance_data['maxes'].append(r['max'])
      
  return {
      "students_count": students_count,
      "classes_count": classes_count,
      "completed_exams_count": completed_exams_count,
      "performance_data": performance_data
  }

def add_video_attachment(conn, entity_type: str, entity_id: int, category: str, label: str, url: str, video_type: str = "youtube"):
  cursor = conn.cursor()
  if entity_type == "content_item":
    table = "content_items"
  elif entity_type == "digi_question":
    table = "digi_questions"
  else:
    table = "questions"
  cursor.execute(f"SELECT additional_videos FROM {table} WHERE id = ?", (entity_id,))
  row = cursor.fetchone()
  if not row:
    return None
  
  try:
    videos = json.loads(row['additional_videos'] or '[]')
  except:
    videos = []
    
  new_video = {
    "id": str(uuid.uuid4()),
    "category": category,
    "label": label,
    "url": url,
    "type": video_type
  }
  videos.append(new_video)
  
  cursor.execute(f"UPDATE {table} SET additional_videos = ? WHERE id = ?", (json.dumps(videos), entity_id))
  conn.commit()
  return new_video

def delete_additional_video(conn, entity_type: str, entity_id: int, video_id: str):
  cursor = conn.cursor()
  if entity_type == "content_item":
    table = "content_items"
  elif entity_type == "digi_question":
    table = "digi_questions"
  else:
    table = "questions"
  cursor.execute(f"SELECT additional_videos FROM {table} WHERE id = ?", (entity_id,))
  row = cursor.fetchone()
  if not row:
    return False
    
  try:
    videos = json.loads(row['additional_videos'] or '[]')
  except:
    return False
    
  filtered = [v for v in videos if v.get('id') != video_id]
  if len(filtered) == len(videos):
    return False
    
  cursor.execute(f"UPDATE {table} SET additional_videos = ? WHERE id = ?", (json.dumps(filtered), entity_id))
  conn.commit()
  return True


def update_node_thumbnail(conn, table: str, id: int, thumbnail_url: str):
  if table not in ['classes', 'subjects', 'chapters', 'digi_books', 'digi_subjects']:
    raise ValueError("Invalid table name")
  cursor = conn.cursor()
  cursor.execute(f"UPDATE {table} SET thumbnail_url = ? WHERE id = ?", (thumbnail_url, id))
  conn.commit()

def get_hierarchy_path(conn, **kwargs):
    pass

def update_exam_title(
    conn,
    exam_id: int,
    title: str,
    unlock_threshold_percent: float = None,
    required_mock_percent: float = None,
    max_attempts: int = None,
    use_mock_questions: int = None,
    target_marks: int = None,
    update_settings: bool = False
):
    title = title.strip()
    if not title or len(title) > 200:
        raise ValueError("Exam title must be between 1 and 200 characters")
    cursor = conn.cursor()
    if update_settings:
        cursor.execute(
            "UPDATE exam_papers SET title = ?, unlock_threshold_percent = ?, required_mock_percent = ?, max_attempts = ?, use_mock_questions = COALESCE(?, use_mock_questions), target_marks = ? WHERE id = ?",
            (title, unlock_threshold_percent, required_mock_percent, max_attempts, use_mock_questions, target_marks, exam_id)
        )
    else:
        cursor.execute("UPDATE exam_papers SET title = ? WHERE id = ?", (title, exam_id))
    conn.commit()

def update_question_details(
    conn,
    question_id: int,
    text: str,
    answer: str,
    options: str,
    media_url: str = None,
    answer_media_url: str = None,
    question_type: str = None,
    max_marks: int = None
):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
    row = cursor.fetchone()
    if not row:
        return
    cur_q = dict(row)
    final_media = media_url if media_url is not None else cur_q.get('media_url')
    final_ans_media = answer_media_url if answer_media_url is not None else cur_q.get('answer_media_url')
    final_type = question_type if question_type is not None else cur_q.get('question_type')
    final_marks = max_marks if max_marks is not None else cur_q.get('max_marks')
    clean_options = options.strip() if options else None
    if clean_options in ('', 'None', 'null'):
        clean_options = None

    cursor.execute(
        """UPDATE questions
           SET question_text = ?, model_answer = ?, options = ?, media_url = ?, answer_media_url = ?, question_type = ?, max_marks = ?
           WHERE id = ?""",
        (text, answer, clean_options, final_media, final_ans_media, final_type, final_marks, question_id)
    )
    conn.commit()


# ==========================================
# DIGI LIBRARY ADMIN SERVICES (Markless)
# ==========================================

def get_digi_library_tree(conn):
    """Fetches the complete Digi Library hierarchy: Books -> Subjects -> Question Banks (with question counts)."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.*, c.name as class_name
        FROM digi_books b
        LEFT JOIN classes c ON b.class_id = c.id
        ORDER BY b.order_index, b.id DESC
    """)
    books = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM digi_subjects ORDER BY order_index, id")
    subjects = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT qb.*,
               (SELECT COUNT(*) FROM digi_questions dq WHERE dq.bank_id = qb.id) as question_count
        FROM digi_question_banks qb
        ORDER BY qb.order_index, qb.id
    """)
    banks = [dict(r) for r in cursor.fetchall()]

    banks_by_subject = {}
    for b in banks:
        banks_by_subject.setdefault(b['subject_id'], []).append(b)

    subjects_by_book = {}
    for s in subjects:
        s['banks'] = banks_by_subject.get(s['id'], [])
        subjects_by_book.setdefault(s['book_id'], []).append(s)

    for book in books:
        book['subjects'] = subjects_by_book.get(book['id'], [])

    return books

def get_digi_book(conn, book_id: int):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.*, c.name as class_name
        FROM digi_books b
        LEFT JOIN classes c ON b.class_id = c.id
        WHERE b.id = ?
    """, (book_id,))
    row = cursor.fetchone()
    if not row:
        return None
    book = dict(row)
    cursor.execute("SELECT * FROM digi_subjects WHERE book_id = ? ORDER BY order_index, id", (book_id,))
    subjects = [dict(r) for r in cursor.fetchall()]
    for s in subjects:
        cursor.execute("""
            SELECT qb.*,
                   (SELECT COUNT(*) FROM digi_questions dq WHERE dq.bank_id = qb.id) as question_count
            FROM digi_question_banks qb
            WHERE qb.subject_id = ?
            ORDER BY qb.order_index, qb.id
        """, (s['id'],))
        s['banks'] = [dict(r) for r in cursor.fetchall()]
    book['subjects'] = subjects
    return book

def create_digi_book(conn, title: str, description: str = '', thumbnail_url: str = '', class_id: int = None):
    title = title.strip()
    if not title or len(title) > 200:
        raise ValueError("Book title must be between 1 and 200 characters")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO digi_books (title, description, thumbnail_url, class_id, status) VALUES (?, ?, ?, ?, 'published')",
        (title, (description or '').strip(), thumbnail_url or '', class_id)
    )
    conn.commit()
    return get_digi_book(conn, cursor.lastrowid)

def update_digi_book(conn, book_id: int, title: str, description: str = '', thumbnail_url: str = None, class_id: int = None, update_class: bool = False):
    title = title.strip()
    if not title or len(title) > 200:
        raise ValueError("Book title must be between 1 and 200 characters")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM digi_books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    if not row:
        return None
    cur = dict(row)
    final_thumb = thumbnail_url if thumbnail_url is not None else cur.get('thumbnail_url', '')
    final_class = class_id if update_class else cur.get('class_id')
    cursor.execute(
        "UPDATE digi_books SET title = ?, description = ?, thumbnail_url = ?, class_id = ? WHERE id = ?",
        (title, (description or '').strip(), final_thumb, final_class, book_id)
    )
    conn.commit()
    return get_digi_book(conn, book_id)

def toggle_digi_book_status(conn, book_id: int):
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM digi_books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    if not row:
        return None
    new_status = 'published' if row['status'] == 'draft' else 'draft'
    cursor.execute("UPDATE digi_books SET status = ? WHERE id = ?", (new_status, book_id))
    conn.commit()
    return get_digi_book(conn, book_id)

def delete_digi_book(conn, book_id: int):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM digi_books WHERE id = ?", (book_id,))
    conn.commit()

def get_digi_subject(conn, subject_id: int):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM digi_subjects WHERE id = ?", (subject_id,))
    row = cursor.fetchone()
    if not row:
        return None
    subj = dict(row)
    cursor.execute("""
        SELECT qb.*,
               (SELECT COUNT(*) FROM digi_questions dq WHERE dq.bank_id = qb.id) as question_count
        FROM digi_question_banks qb
        WHERE qb.subject_id = ?
        ORDER BY qb.order_index, qb.id
    """, (subject_id,))
    subj['banks'] = [dict(r) for r in cursor.fetchall()]
    return subj

def create_digi_subject(conn, book_id: int, name: str, description: str = '', thumbnail_url: str = ''):
    name = name.strip()
    if not name or len(name) > 200:
        raise ValueError("Subject name must be between 1 and 200 characters")
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(order_index), 0) + 1 FROM digi_subjects WHERE book_id = ?", (book_id,))
    next_order = cursor.fetchone()[0]
    cursor.execute(
        "INSERT INTO digi_subjects (book_id, name, description, thumbnail_url, order_index) VALUES (?, ?, ?, ?, ?)",
        (book_id, name, (description or '').strip(), thumbnail_url or '', next_order)
    )
    conn.commit()
    return get_digi_subject(conn, cursor.lastrowid)

def move_digi_subject(conn, subject_id: int, direction: str):
    cursor = conn.cursor()
    cursor.execute("SELECT book_id FROM digi_subjects WHERE id = ?", (subject_id,))
    row = cursor.fetchone()
    if not row:
        return None
    book_id = row['book_id']
    cursor.execute("SELECT id FROM digi_subjects WHERE book_id = ? ORDER BY order_index, id", (book_id,))
    ids = [r['id'] for r in cursor.fetchall()]
    if subject_id not in ids:
        return get_digi_book(conn, book_id)
    idx = ids.index(subject_id)
    if direction == 'up' and idx > 0:
        ids[idx], ids[idx - 1] = ids[idx - 1], ids[idx]
    elif direction == 'down' and idx < len(ids) - 1:
        ids[idx], ids[idx + 1] = ids[idx + 1], ids[idx]
    for new_order, sid in enumerate(ids, start=1):
        cursor.execute("UPDATE digi_subjects SET order_index = ? WHERE id = ?", (new_order, sid))
    conn.commit()
    return get_digi_book(conn, book_id)

def update_digi_subject(conn, subject_id: int, name: str, description: str = '', thumbnail_url: str = None):
    name = name.strip()
    if not name or len(name) > 200:
        raise ValueError("Subject name must be between 1 and 200 characters")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM digi_subjects WHERE id = ?", (subject_id,))
    row = cursor.fetchone()
    if not row:
        return None
    cur = dict(row)
    final_thumb = thumbnail_url if thumbnail_url is not None else cur.get('thumbnail_url', '')
    cursor.execute(
        "UPDATE digi_subjects SET name = ?, description = ?, thumbnail_url = ? WHERE id = ?",
        (name, (description or '').strip(), final_thumb, subject_id)
    )
    conn.commit()
    return get_digi_subject(conn, subject_id)

def delete_digi_subject(conn, subject_id: int):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM digi_subjects WHERE id = ?", (subject_id,))
    conn.commit()

def get_digi_bank(conn, bank_id: int):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT qb.*,
               s.name as subject_name, s.book_id,
               b.title as book_title,
               (SELECT COUNT(*) FROM digi_questions dq WHERE dq.bank_id = qb.id) as question_count
        FROM digi_question_banks qb
        JOIN digi_subjects s ON qb.subject_id = s.id
        JOIN digi_books b ON s.book_id = b.id
        WHERE qb.id = ?
    """, (bank_id,))
    row = cursor.fetchone()
    if not row:
        return None
    bank = dict(row)
    cursor.execute("SELECT * FROM digi_questions WHERE bank_id = ? ORDER BY order_index, id", (bank_id,))
    bank['questions'] = [dict(r) for r in cursor.fetchall()]
    return bank

def create_digi_bank(conn, subject_id: int, title: str, description: str = ''):
    title = title.strip()
    if not title or len(title) > 200:
        raise ValueError("Chapter title must be between 1 and 200 characters")
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(order_index), 0) + 1 FROM digi_question_banks WHERE subject_id = ?", (subject_id,))
    next_order = cursor.fetchone()[0]
    cursor.execute(
        "INSERT INTO digi_question_banks (subject_id, title, description, status, order_index) VALUES (?, ?, ?, 'published', ?)",
        (subject_id, title, (description or '').strip(), next_order)
    )
    conn.commit()
    return get_digi_bank(conn, cursor.lastrowid)

def move_digi_bank(conn, bank_id: int, direction: str):
    cursor = conn.cursor()
    cursor.execute("SELECT subject_id FROM digi_question_banks WHERE id = ?", (bank_id,))
    row = cursor.fetchone()
    if not row:
        return None
    subject_id = row['subject_id']
    cursor.execute("SELECT id FROM digi_question_banks WHERE subject_id = ? ORDER BY order_index, id", (subject_id,))
    ids = [r['id'] for r in cursor.fetchall()]
    if bank_id not in ids:
        return get_digi_subject(conn, subject_id)
    idx = ids.index(bank_id)
    if direction == 'up' and idx > 0:
        ids[idx], ids[idx - 1] = ids[idx - 1], ids[idx]
    elif direction == 'down' and idx < len(ids) - 1:
        ids[idx], ids[idx + 1] = ids[idx + 1], ids[idx]
    for new_order, bid in enumerate(ids, start=1):
        cursor.execute("UPDATE digi_question_banks SET order_index = ? WHERE id = ?", (new_order, bid))
    conn.commit()
    return get_digi_subject(conn, subject_id)

def update_digi_bank(conn, bank_id: int, title: str, description: str = ''):
    title = title.strip()
    if not title or len(title) > 200:
        raise ValueError("Chapter title must be between 1 and 200 characters")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE digi_question_banks SET title = ?, description = ? WHERE id = ?",
        (title, (description or '').strip(), bank_id)
    )
    conn.commit()
    return get_digi_bank(conn, bank_id)

def toggle_digi_bank_status(conn, bank_id: int):
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM digi_question_banks WHERE id = ?", (bank_id,))
    row = cursor.fetchone()
    if not row:
        return None
    new_status = 'published' if row['status'] == 'draft' else 'draft'
    cursor.execute("UPDATE digi_question_banks SET status = ? WHERE id = ?", (new_status, bank_id))
    conn.commit()
    return get_digi_bank(conn, bank_id)

def delete_digi_bank(conn, bank_id: int):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM digi_question_banks WHERE id = ?", (bank_id,))
    conn.commit()

def get_digi_question(conn, question_id: int):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM digi_questions WHERE id = ?", (question_id,))
    row = cursor.fetchone()
    return dict(row) if row else None

def create_digi_question(
    conn,
    bank_id: int,
    question_text: str,
    model_answer: str,
    options: str = None,
    question_type: str = 'CUSTOM',
    media_url: str = None,
    answer_media_url: str = '',
    explanation_video_url: str = None,
    explanation_video_type: str = None,
    section_name: str = 'Questions'
):
    question_text = question_text.strip()
    model_answer = model_answer.strip()
    if not question_text:
        raise ValueError("Question text cannot be empty")
    if not model_answer:
        raise ValueError("Model answer cannot be empty")
    clean_options = options.strip() if options else None
    if clean_options in ('', 'None', 'null'):
        clean_options = None
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(order_index), 0) + 1 FROM digi_questions WHERE bank_id = ?", (bank_id,))
    next_order = cursor.fetchone()[0]
    cursor.execute(
        """INSERT INTO digi_questions
           (bank_id, section_name, question_text, model_answer, options, question_type, media_url, answer_media_url, explanation_video_url, explanation_video_type, order_index)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (bank_id, section_name or 'Questions', question_text, model_answer, clean_options, question_type or 'CUSTOM', media_url, answer_media_url or '', explanation_video_url, explanation_video_type, next_order)
    )
    conn.commit()
    return get_digi_question(conn, cursor.lastrowid)

def move_digi_question(conn, question_id: int, direction: str):
    cursor = conn.cursor()
    cursor.execute("SELECT bank_id FROM digi_questions WHERE id = ?", (question_id,))
    row = cursor.fetchone()
    if not row:
        return None
    bank_id = row['bank_id']
    cursor.execute("SELECT id FROM digi_questions WHERE bank_id = ? ORDER BY order_index, id", (bank_id,))
    ids = [r['id'] for r in cursor.fetchall()]
    if question_id not in ids:
        return get_digi_bank(conn, bank_id)
    idx = ids.index(question_id)
    if direction == 'up' and idx > 0:
        ids[idx], ids[idx - 1] = ids[idx - 1], ids[idx]
    elif direction == 'down' and idx < len(ids) - 1:
        ids[idx], ids[idx + 1] = ids[idx + 1], ids[idx]
    for new_order, qid in enumerate(ids, start=1):
        cursor.execute("UPDATE digi_questions SET order_index = ? WHERE id = ?", (new_order, qid))
    conn.commit()
    return get_digi_bank(conn, bank_id)

def update_digi_question(
    conn,
    question_id: int,
    question_text: str,
    model_answer: str,
    options: str = None,
    question_type: str = None,
    media_url: str = None,
    answer_media_url: str = None
):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM digi_questions WHERE id = ?", (question_id,))
    row = cursor.fetchone()
    if not row:
        return None
    cur_q = dict(row)
    final_media = media_url if media_url is not None else cur_q.get('media_url')
    final_ans_media = answer_media_url if answer_media_url is not None else cur_q.get('answer_media_url')
    final_type = question_type if question_type is not None else cur_q.get('question_type', 'CUSTOM')
    clean_options = options.strip() if options else None
    if clean_options in ('', 'None', 'null'):
        clean_options = None
    cursor.execute(
        """UPDATE digi_questions
           SET question_text = ?, model_answer = ?, options = ?, question_type = ?, media_url = ?, answer_media_url = ?
           WHERE id = ?""",
        (question_text.strip(), model_answer.strip(), clean_options, final_type, final_media, final_ans_media, question_id)
    )
    conn.commit()
    return get_digi_question(conn, question_id)

def update_digi_question_explanation_video(conn, question_id: int, video_url: str, video_type: str):
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE digi_questions SET explanation_video_url = ?, explanation_video_type = ? WHERE id = ?",
        (video_url, video_type, question_id)
    )
    conn.commit()
    return get_digi_question(conn, question_id)

def delete_digi_question(conn, question_id: int):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM digi_questions WHERE id = ?", (question_id,))
    conn.commit()


