import sqlite3
from datetime import datetime, timedelta
import json
from openai import OpenAI
import os
import hashlib
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def get_parent_analytics(conn, student_id: int):
  cursor = conn.cursor()
  
  # Time spent learning (seconds -> hours/mins)
  cursor.execute("SELECT SUM(progress_seconds) FROM content_progress WHERE student_id = ?", (student_id,))
  total_seconds = cursor.fetchone()[0] or 0
  
  # Add time spent taking exams
  cursor.execute("""
    SELECT SUM(
      CAST(strftime('%s', completed_at) - strftime('%s', started_at) AS INTEGER)
    ) 
    FROM attempts 
    WHERE student_id = ? AND completed_at IS NOT NULL
  """, (student_id,))
  exam_seconds = cursor.fetchone()[0] or 0
  total_seconds += exam_seconds
  
  hours = total_seconds // 3600
  minutes = (total_seconds % 3600) // 60
  time_spent = f"{hours}h {minutes}m"
  
  # Curriculum Completion
  # Find student class
  cursor.execute("SELECT class_id FROM users WHERE id = ?", (student_id,))
  class_id = cursor.fetchone()
  class_id = class_id[0] if class_id else 0
  
  cursor.execute("""
    SELECT COUNT(ci.id) FROM content_items ci
    JOIN chapters c ON ci.chapter_id = c.id
    JOIN subjects s ON c.subject_id = s.id
    WHERE s.class_id = ? AND c.status = 'published'
  """, (class_id,))
  total_content = cursor.fetchone()[0] or 0
  
  # Count distinct content items the student has completed
  cursor.execute("""
    SELECT COUNT(DISTINCT cp.content_item_id) 
    FROM content_progress cp
    JOIN content_items ci ON cp.content_item_id = ci.id
    JOIN chapters c ON ci.chapter_id = c.id
    JOIN subjects s ON c.subject_id = s.id
    WHERE cp.student_id = ? AND cp.completed = 1 AND s.class_id = ?
  """, (student_id, class_id))
  completed_content = cursor.fetchone()[0] or 0
  
  completion_percent = round((completed_content / total_content * 100) if total_content > 0 else 0)
  
  # Active Days (distinct days active across content or exams)
  cursor.execute("""
    SELECT COUNT(DISTINCT active_date) FROM (
      SELECT date(started_at) as active_date FROM attempts WHERE student_id = ? AND started_at IS NOT NULL
      UNION
      SELECT date(completed_at) as active_date FROM content_progress WHERE student_id = ? AND completed_at IS NOT NULL
    )
  """, (student_id, student_id))
  streak_days = cursor.fetchone()[0] or 0

  # All Exams taken (for the trend chart)
  cursor.execute("""
  SELECT 
    a.id, 
    ep.title, 
    COALESCE(SUM(ans.marks_awarded), a.total_marks_awarded, 0) as total_marks_awarded, 
    COALESCE(
      NULLIF(a.total_max_marks, 0),
      (SELECT SUM(q.max_marks) FROM questions q JOIN modules m ON q.module_id = m.id WHERE m.exam_paper_id = ep.id),
      ep.target_marks,
      0
    ) as total_max_marks, 
    COALESCE(MAX(ans.submitted_at), a.completed_at, a.started_at) as completed_at, 
    ep.type
  FROM attempts a
  JOIN exam_papers ep ON a.exam_paper_id = ep.id
  LEFT JOIN answers ans ON a.id = ans.attempt_id AND ans.is_latest = 1
  WHERE a.student_id = ? AND (a.status = 'completed' OR ans.id IS NOT NULL)
  GROUP BY a.id, ep.title, ep.type, a.started_at
  ORDER BY completed_at DESC
  """, (student_id,))
  all_exams = [dict(r) for r in cursor.fetchall()]

  # Mock Exam Retry History - group by question to see improvements
  # We fetch all answers for this student from mock exams, ordered by question and submitted_at
  cursor.execute("""
  SELECT ans.id, ans.question_id, q.question_text, ans.answer_text, ans.marks_awarded, ans.ai_feedback, ans.submitted_at, q.max_marks
  FROM answers ans
  JOIN questions q ON ans.question_id = q.id
  JOIN attempts a ON ans.attempt_id = a.id
  JOIN exam_papers ep ON a.exam_paper_id = ep.id
  WHERE a.student_id = ? AND ep.type = 'mock'
  ORDER BY ans.question_id, ans.submitted_at ASC
  """, (student_id,))
  
  all_mock_answers = cursor.fetchall()
  
  # Group by question to find retries
  grouped_retries = {}
  for row in all_mock_answers:
    qid = row["question_id"]
    if qid not in grouped_retries:
      grouped_retries[qid] = {
        "question_text": row["question_text"],
        "max_marks": row["max_marks"],
        "attempts": []
      }
    grouped_retries[qid]["attempts"].append({
      "answer_text": row["answer_text"],
      "marks_awarded": row["marks_awarded"],
      "ai_feedback": row["ai_feedback"],
      "submitted_at": row["submitted_at"]
    })
  
  # Filter to only questions with > 1 attempt for the 'retry history' view
  retry_history = [v for k, v in grouped_retries.items() if len(v["attempts"]) > 1]
  
  # Sort retry history by most recent attempt
  retry_history.sort(key=lambda x: x["attempts"][-1]["submitted_at"], reverse=True)

  # Recent Activity Feed
  cursor.execute("""
  SELECT 'exam' as type, ep.title as name, a.completed_at as timestamp, 
      a.total_marks_awarded || '/' || a.total_max_marks as details, ep.type as exam_type
  FROM attempts a
  JOIN exam_papers ep ON a.exam_paper_id = ep.id
  WHERE a.student_id = ? AND a.status = 'completed'
  
  UNION ALL
  
  SELECT 'content' as type, ci.title as name, cp.completed_at as timestamp,
      'Completed chapter content' as details, '' as exam_type
  FROM content_progress cp
  JOIN content_items ci ON cp.content_item_id = ci.id
  WHERE cp.student_id = ? AND cp.completed = 1 AND cp.completed_at IS NOT NULL
  
  ORDER BY timestamp DESC
  LIMIT 10
  """, (student_id, student_id))
  recent_activity = [dict(r) for r in cursor.fetchall()]

  # Mock Exam AI Tutor Usage Stats
  total_tutor_uses = 0
  pre_submit_tutor_uses = 0
  questions_with_tutor_count = 0
  try:
    cursor.execute("""
      SELECT 
        COUNT(*) as total_uses,
        COALESCE(SUM(CASE WHEN asked_before_submit = 1 THEN 1 ELSE 0 END), 0) as pre_submit_uses,
        COUNT(DISTINCT question_id) as distinct_questions
      FROM mock_exam_tutor_logs
      WHERE student_id = ?
    """, (student_id,))
    t_row = cursor.fetchone()
    if t_row:
      total_tutor_uses = t_row["total_uses"] or 0
      pre_submit_tutor_uses = t_row["pre_submit_uses"] or 0
      questions_with_tutor_count = t_row["distinct_questions"] or 0
  except Exception:
    pass

  return {
    "time_spent": time_spent,
    "completion_percent": completion_percent,
    "streak_days": streak_days,
    "total_chapters": total_content, # renamed variable conceptually but key kept for template
    "completed_chapters": completed_content,
    "all_exams": all_exams,
    "real_exams": [e for e in all_exams if e['type'] == 'real'],
    "retry_history": retry_history,
    "recent_activity": recent_activity,
    "total_tutor_uses": total_tutor_uses,
    "pre_submit_tutor_uses": pre_submit_tutor_uses,
    "questions_with_tutor_count": questions_with_tutor_count
  }


def get_analytics_hash(analytics: dict):
  import hashlib, json
  # simple hash of the analytics dict strings to detect changes
  return hashlib.md5(json.dumps(str(analytics), sort_keys=True).encode()).hexdigest()

def generate_and_cache_ai_summary(conn, student_id: int, student_name: str, analytics: dict, summary_type: str = "main"):
  cursor = conn.cursor()
  
  column_name = "parent_summary"
  if summary_type == "mock":
    column_name = "parent_mock_summary"
  elif summary_type == "real":
    column_name = "parent_real_summary"
  
  cursor.execute(f"SELECT {column_name}, brutality_level FROM users WHERE id = ?", (student_id,))
  row = cursor.fetchone()
  
  existing_summary = row[0] if row else None
  brutality_level = row[1] if row and row[1] else 1
  
  data_hash = get_analytics_hash(analytics)
  hash_marker = f"<!-- datahash:{data_hash} brutality:{brutality_level} -->"
  
  # FIX: check the FULL hash_marker (data + brutality level), not just the data hash.
  # Previously only the data hash was checked, so changing brutality never triggered regeneration.
  should_update = False
  if not existing_summary:
    should_update = True
  elif f"brutality:{brutality_level}" not in existing_summary:
    should_update = True
  elif hash_marker not in existing_summary:
    # Data changed, auto-update
    should_update = True
    
  if not should_update and existing_summary:
    clean_summary = existing_summary.split("<!-- datahash")[0].strip()
    return clean_summary
  
  # Generate new summary
  if not client or not client.api_key:
    return "Summary is unavailable at this time due to missing API keys."
  
  system_messages = {
    1: (
      "You are a warm, caring academic tutor writing a gentle progress note for a parent. "
      "Your tone is kind, supportive and encouraging. Celebrate every win, no matter how small. "
      "Frame any shortcomings as normal parts of growth. Make the parent feel proud and hopeful."
    ),
    2: (
      "You are a cold, clinical performance analyst. You write facts only — no warmth, no encouragement, no softening. "
      "If the numbers are poor, state that directly. Use phrases like 'The data shows', 'Objectively speaking', 'Statistically'. "
      "Do not use positive language unless the data genuinely supports it. Be terse and precise. "
      "Do NOT add any closing remark about improvement or potential."
    ),
    3: (
      "You are a strict, disappointed academic supervisor writing a hard-hitting report for a parent. "
      "You are visibly frustrated. Call out laziness, wasted potential, and poor discipline directly. "
      "Make the parent feel they need to intervene right now. Do NOT soften anything. Do NOT add hope or encouragement. "
      "Do NOT say things like 'but there is still time' or 'with effort this can change'. "
      "Every sentence must carry weight and disappointment. "
      "\n\nExample of correct tone:\n"
      "'Your child's performance is frankly unacceptable. The effort being put in is minimal at best, and the results reflect that clearly. "
      "This level of disengagement will have real consequences and the time to address it is now, not later.'"
    ),
    4: (
      "You are delivering a final, desperate academic crisis warning to a parent. "
      "Your tone is grave, alarming, and relentless. You do NOT soften, encourage, or give hope. "
      "NEVER write phrases like 'there is still time', 'with dedication', 'improvement is possible', or anything positive. "
      "Use language that creates fear and urgency: 'academic failure is imminent', 'this is a crisis', "
      "'your child is actively destroying their future', 'every day of inaction makes this worse', 'the damage may already be irreversible'. "
      "Reference the specific numbers as damning evidence. "
      "\n\nExample of correct tone:\n"
      "'Your child is in academic freefall and the numbers make this impossible to ignore. "
      "The level of effort recorded is not just poor — it is alarming, and it points to a student who has disengaged entirely. "
      "Academic failure is not a distant risk here; it is the current trajectory. "
      "If drastic action is not taken immediately, the consequences will be severe and lasting. "
      "This is not a warning — this is a crisis.'"
    ),
  }

  user_prompts = {
    1: (
      "Write a warm, encouraging 4-5 sentence progress summary for this student's parent. "
      "Synthesize the provided data into a cohesive, highly personalized narrative. Do not just list facts; tell a story about their learning journey. "
      "Celebrate their effort and highlight any positive signs of growth."
    ),
    2: (
      "Write a clinical, data-driven 4-5 sentence performance report. "
      "Synthesize the data into a logical summary. "
      "State the facts plainly. No praise, no encouragement — just what the numbers say. No closing positive remark."
    ),
    3: (
      "Write a stern, 4-5 sentence report that openly criticises the student's effort and performance. "
      "Call out laziness and underperformance directly. Make the parent feel they must act immediately. "
      "Do not add any positive remarks, hope, or encouragement whatsoever — this is a wake-up call."
    ),
    4: (
      "Write a 4-5 sentence report that reads like a final crisis warning. "
      "Use phrases like 'academic failure is imminent' and 'your child is wasting their future'. "
      "Reference the specific data as hard proof of failure. "
      "Zero hope, zero encouragement, zero positive spin. "
      "End on the most alarming note possible. The parent should feel genuine fear for their child's future."
    ),
  }
  
  system_msg = system_messages.get(brutality_level, system_messages[1])
  user_instruction = user_prompts.get(brutality_level, user_prompts[1])
  
  # Build the data context
  data_context = f"Student name: {student_name}\n\n"
  if summary_type == "main":
    data_context += (
      f"Performance Data:\n"
      f"- Time spent learning: {analytics.get('time_spent', '0h')}\n"
      f"- Curriculum completed: {analytics.get('completion_percent', 0)}%\n"
      f"- Mock Exam questions retried: {len(analytics.get('retry_history', []))}\n"
      f"- AI Tutor assistance used during Mock Exams: {analytics.get('total_tutor_uses', 0)} times ({analytics.get('pre_submit_tutor_uses', 0)} before answering)\n"
      f"- Real Exams completed: {len(analytics.get('real_exams', []))}"
    )
  elif summary_type == "mock":
    retries = len(analytics.get('retry_history', []))
    total_mocks = len(analytics.get('mock_exams', []))
    tutor_uses = analytics.get('total_tutor_uses', 0)
    pre_submit_uses = analytics.get('pre_submit_tutor_uses', 0)
    tutor_qs = analytics.get('questions_with_tutor_count', 0)
    data_context += (
      f"Mock Exam Data:\n"
      f"- Mock Exams Taken: {total_mocks}\n"
      f"- Questions retried for improvement: {retries}\n"
      f"- AI Tutor ('Ask Tutor') used during Mock Exams: {tutor_uses} times across {tutor_qs} questions ({pre_submit_uses} times asked before submitting an answer)"
    )
  elif summary_type == "real":
    total_real = len(analytics.get('real_exams', []))
    total_xp_spent = sum([(e.get('purchased_extra_seconds') or 0) for e in analytics.get('real_exams', [])])
    data_context += f"Real Exam Data:\n- Real Exams Completed: {total_real}\n- Extra time purchased via XP: {total_xp_spent} seconds total"
  
  full_prompt = f"{user_instruction}\n\n{data_context}\n\nWrite directly to the parent. Start with 'Your child...' or 'Your son/daughter...'. Do not include headers or bullet points — write in flowing paragraph form only."
  
  try:
    try:
      response = client.chat.completions.create(
        model="gpt-5.4-nano",
        messages=[
          {"role": "system", "content": system_msg},
          {"role": "user", "content": full_prompt}
        ],
        temperature=0.95 if brutality_level >= 3 else 0.8,
        max_completion_tokens=220
      )
    except Exception as primary_err:
      print(f"Primary parent summary model (gpt-5.4-nano) notice: {primary_err}, falling back to gpt-5.4-mini...")
      response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[
          {"role": "system", "content": system_msg},
          {"role": "user", "content": full_prompt}
        ],
        temperature=0.95 if brutality_level >= 3 else 0.8,
        max_completion_tokens=220
      )
    summary = response.choices[0].message.content.strip()
    
    summary_with_hash = f"{summary}\n{hash_marker}"
    cursor.execute(f"UPDATE users SET {column_name} = ? WHERE id = ?", (summary_with_hash, student_id))
    conn.commit()
    return summary
  except Exception as e:
    print(f"Error generating parent summary: {e}")
    return "Summary could not be generated at this time."

def get_exam_report(conn, attempt_id: int, student_id: int):
  cursor = conn.cursor()
  cursor.execute("""
  SELECT a.*, ep.title, ep.type, u.name as student_name
  FROM attempts a
  JOIN exam_papers ep ON a.exam_paper_id = ep.id
  JOIN users u ON a.student_id = u.id
  WHERE a.id = ? AND a.student_id = ?
  """, (attempt_id, student_id))
  attempt = cursor.fetchone()
  if not attempt:
    return None
  
  cursor.execute("""
  SELECT ans.*, q.question_text, q.model_answer, q.max_marks, q.media_url, q.answer_media_url
  FROM answers ans
  JOIN questions q ON ans.question_id = q.id
  WHERE ans.attempt_id = ? AND ans.is_latest = 1
  ORDER BY q.order_index
  """, (attempt_id,))
  answers = [dict(row) for row in cursor.fetchall()]

  att_dict = dict(attempt)
  if not att_dict.get('total_max_marks') and answers:
    att_dict['total_max_marks'] = sum((ans.get('max_marks') or 0) for ans in answers)
  if att_dict.get('total_marks_awarded') is None:
    att_dict['total_marks_awarded'] = sum((ans.get('marks_awarded') or 0) for ans in answers)

  # Attach Mock Exam AI Tutor usage per question if any
  tutor_logs_by_qid = {}
  total_attempt_tutor_uses = 0
  try:
    cursor.execute("""
      SELECT id, question_id, question_number, asked_before_submit, user_message, ai_response, created_at
      FROM mock_exam_tutor_logs
      WHERE student_id = ? AND (attempt_id = ? OR (attempt_id IS NULL AND exam_paper_id = ?))
      ORDER BY created_at ASC, id ASC
    """, (student_id, attempt_id, att_dict.get('exam_paper_id')))
    for r in cursor.fetchall():
      rd = dict(r)
      qid = rd['question_id']
      tutor_logs_by_qid.setdefault(qid, []).append(rd)
      total_attempt_tutor_uses += 1
  except Exception:
    pass

  for ans in answers:
    q_logs = tutor_logs_by_qid.get(ans.get('question_id'), [])
    ans['tutor_logs'] = q_logs
    ans['tutor_uses_count'] = len(q_logs)
    ans['pre_submit_tutor_uses'] = sum(1 for l in q_logs if l.get('asked_before_submit'))

  att_dict['total_tutor_uses'] = total_attempt_tutor_uses
  
  return {
    "attempt": att_dict,
    "answers": answers
  }

def update_parent_settings(conn, student_id: int, locked: int, pin: str, sfx_mode: int = 1, sfx_custom: str = "{}", cursor_mode: int = 0, cursor_effect: str = "magic", brutality_level: int = 1, tts_voice: str = "af_bella", tts_engine: str = "kokoro", tts_mode: str = "manual"):
  cursor = conn.cursor()
  cursor.execute("""
  UPDATE users 
  SET parent_locked = ?, parent_pin = ?, parent_sfx_mode = ?, parent_sfx_custom = ?, parent_cursor_mode = ?, parent_cursor_effect = ?, brutality_level = ?, parent_tts_voice = ?, parent_tts_engine = ?, parent_tts_mode = ?
  WHERE id = ?
  """, (locked, pin, sfx_mode, sfx_custom, cursor_mode, cursor_effect, brutality_level, tts_voice, tts_engine, tts_mode, student_id))
  conn.commit()


def get_mock_exam_analytics(conn, student_id: int):
  cursor = conn.cursor()
  # Fetch all mock attempts
  cursor.execute("""
  SELECT 
    a.id, 
    a.exam_paper_id,
    ep.title, 
    COALESCE(SUM(ans.marks_awarded), a.total_marks_awarded, 0) as total_marks_awarded, 
    COALESCE(
      NULLIF(a.total_max_marks, 0),
      (SELECT SUM(q.max_marks) FROM questions q JOIN modules m ON q.module_id = m.id WHERE m.exam_paper_id = ep.id),
      ep.target_marks,
      0
    ) as total_max_marks, 
    COALESCE(MAX(ans.submitted_at), a.completed_at, a.started_at) as completed_at,
    COUNT(ans.id) as questions_attempted
  FROM attempts a
  JOIN exam_papers ep ON a.exam_paper_id = ep.id
  LEFT JOIN answers ans ON a.id = ans.attempt_id AND ans.is_latest = 1
  WHERE a.student_id = ? AND ep.type = 'mock' AND (a.status = 'completed' OR ans.id IS NOT NULL)
  GROUP BY a.id, ep.title, a.started_at
  ORDER BY completed_at DESC
  """, (student_id,))
  mock_exams = [dict(r) for r in cursor.fetchall()]

  # Fetch all Mock Exam AI Tutor usage logs for this student
  tutor_logs = []
  try:
    cursor.execute("""
      SELECT 
        l.id,
        l.exam_paper_id,
        ep.title as exam_title,
        l.attempt_id,
        l.question_id,
        l.question_number,
        l.module_name,
        l.asked_before_submit,
        l.user_message,
        l.ai_response,
        l.created_at,
        q.question_text,
        q.max_marks
      FROM mock_exam_tutor_logs l
      JOIN exam_papers ep ON l.exam_paper_id = ep.id
      JOIN questions q ON l.question_id = q.id
      WHERE l.student_id = ?
      ORDER BY l.created_at DESC, l.id DESC
    """, (student_id,))
    tutor_logs = [dict(r) for r in cursor.fetchall()]
  except Exception as e:
    print(f"Error fetching mock_exam_tutor_logs: {e}")

  # Group Tutor logs by question (preserving chronological order of prompts within each question, and sorting questions by most recent usage)
  grouped_tutor_by_q = {}
  tutor_count_by_attempt = {}
  tutor_count_by_qid = {}
  for log in reversed(tutor_logs):
    qid = log["question_id"]
    att_id = log.get("attempt_id")
    if att_id:
      tutor_count_by_attempt[att_id] = tutor_count_by_attempt.get(att_id, 0) + 1
    tutor_count_by_qid[qid] = tutor_count_by_qid.get(qid, 0) + 1

    key = f"{log['exam_paper_id']}_{qid}"
    if key not in grouped_tutor_by_q:
      grouped_tutor_by_q[key] = {
        "exam_paper_id": log["exam_paper_id"],
        "exam_title": log["exam_title"],
        "question_id": qid,
        "question_number": log["question_number"] or 1,
        "module_name": log["module_name"] or "",
        "question_text": log["question_text"],
        "max_marks": log["max_marks"],
        "usage_count": 0,
        "pre_submit_count": 0,
        "last_used_at": log["created_at"],
        "prompts": []
      }
    entry = grouped_tutor_by_q[key]
    entry["usage_count"] += 1
    if log.get("asked_before_submit"):
      entry["pre_submit_count"] += 1
    entry["last_used_at"] = log["created_at"]
    entry["prompts"].append({
      "id": log["id"],
      "user_message": log["user_message"],
      "ai_response": log["ai_response"],
      "asked_before_submit": bool(log.get("asked_before_submit")),
      "created_at": log["created_at"],
      "attempt_id": log.get("attempt_id")
    })

  tutor_by_question = list(grouped_tutor_by_q.values())
  tutor_by_question.sort(key=lambda x: x["last_used_at"] or "", reverse=True)

  for m in mock_exams:
    m["tutor_uses_count"] = tutor_count_by_attempt.get(m["id"], 0)

  # Mock Exam Retry History
  cursor.execute("""
  SELECT ans.id, ans.question_id, q.question_text, ans.answer_text, ans.marks_awarded, ans.ai_feedback, ans.submitted_at, q.max_marks
  FROM answers ans
  JOIN questions q ON ans.question_id = q.id
  JOIN attempts a ON ans.attempt_id = a.id
  JOIN exam_papers ep ON a.exam_paper_id = ep.id
  WHERE a.student_id = ? AND ep.type = 'mock'
  ORDER BY ans.question_id, ans.submitted_at ASC
  """, (student_id,))
  all_mock_answers = cursor.fetchall()
  
  grouped_retries = {}
  for row in all_mock_answers:
    qid = row["question_id"]
    if qid not in grouped_retries:
      grouped_retries[qid] = {
        "question_id": qid,
        "question_text": row["question_text"],
        "max_marks": row["max_marks"],
        "tutor_uses_count": tutor_count_by_qid.get(qid, 0),
        "attempts": []
      }
    grouped_retries[qid]["attempts"].append({
      "answer_text": row["answer_text"],
      "marks_awarded": row["marks_awarded"],
      "ai_feedback": row["ai_feedback"],
      "submitted_at": row["submitted_at"]
    })
  
  retry_history = [v for k, v in grouped_retries.items() if len(v["attempts"]) > 1]
  retry_history.sort(key=lambda x: x["attempts"][-1]["submitted_at"], reverse=True)

  total_tutor_uses = len(tutor_logs)
  pre_submit_tutor_uses = sum(1 for l in tutor_logs if l.get("asked_before_submit"))
  questions_with_tutor_count = len({l["question_id"] for l in tutor_logs})

  return {
    "mock_exams": mock_exams,
    "retry_history": retry_history,
    "tutor_logs": tutor_logs,
    "tutor_by_question": tutor_by_question,
    "total_tutor_uses": total_tutor_uses,
    "pre_submit_tutor_uses": pre_submit_tutor_uses,
    "questions_with_tutor_count": questions_with_tutor_count
  }

def get_real_exam_analytics(conn, student_id: int):
  cursor = conn.cursor()
  # Fetch all real attempts
  cursor.execute("""
  SELECT 
    a.id, 
    ep.title, 
    COALESCE(SUM(ans.marks_awarded), a.total_marks_awarded, 0) as total_marks_awarded, 
    COALESCE(
      NULLIF(a.total_max_marks, 0),
      (SELECT SUM(q.max_marks) FROM questions q JOIN modules m ON q.module_id = m.id WHERE m.exam_paper_id = ep.id),
      ep.target_marks,
      0
    ) as total_max_marks, 
    a.started_at, 
    COALESCE(MAX(ans.submitted_at), a.completed_at, a.started_at) as completed_at, 
    a.purchased_extra_seconds
  FROM attempts a
  JOIN exam_papers ep ON a.exam_paper_id = ep.id
  LEFT JOIN answers ans ON a.id = ans.attempt_id AND ans.is_latest = 1
  WHERE a.student_id = ? AND ep.type = 'real' AND (a.status = 'completed' OR ans.id IS NOT NULL)
  GROUP BY a.id, ep.title, a.started_at, a.purchased_extra_seconds
  ORDER BY completed_at DESC
  """, (student_id,))
  
  real_exams = []
  for row in cursor.fetchall():
    r = dict(row)
    # Calculate duration
    from datetime import datetime
    try:
      start = datetime.fromisoformat(r['started_at'])
      end = datetime.fromisoformat(r['completed_at'])
      duration_secs = int((end - start).total_seconds())
    except:
      duration_secs = 0
      
    r['duration_seconds'] = duration_secs
    r['duration_str'] = f"{duration_secs // 60}m {duration_secs % 60}s"
    real_exams.append(r)

  return {
    "real_exams": real_exams
  }
