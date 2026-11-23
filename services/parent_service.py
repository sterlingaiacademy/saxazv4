import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from services import ai_brain

load_dotenv(override=True)

_oa_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
openai_client = OpenAI(api_key=_oa_key, timeout=8.0, max_retries=0) if _oa_key else None
client = openai_client
_PARENT_OPENAI_COOLDOWN_UNTIL = 0.0

VALID_PARENT_LANGS = {
  "en": "English",
  "ml": "Malayalam",
  "hi": "Hindi",
  "ta": "Tamil",
  "ar": "Arabic",
}

VALID_TTS_VOICES = {"af_bella", "af_sarah", "am_adam", "am_michael"}
VALID_TTS_MODES = {"auto", "manual", "off"}


def _get_table_columns(conn, table_name: str) -> set:
  try:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {r[1] for r in rows}
  except Exception:
    return set()


def _clean_num(val):
  num = float(val or 0)
  return int(num) if num.is_integer() else round(num, 1)


def _format_seconds_short(seconds_val: int) -> str:
  secs = max(0, int(seconds_val or 0))
  if secs >= 3600:
    hrs = secs // 3600
    mins = (secs % 3600) // 60
    return f"{hrs}h {mins}m"
  mins = secs // 60
  rem = secs % 60
  return f"{mins}m {rem}s"


def _compute_attempt_duration(row_dict: dict) -> tuple:
  recorded = int(row_dict.get("time_taken_seconds") or 0)
  if recorded > 0:
    return recorded, _format_seconds_short(recorded)

  started_raw = str(row_dict.get("started_at") or "").strip()
  completed_raw = str(row_dict.get("completed_at") or "").strip()
  if started_raw and completed_raw:
    try:
      start_dt = datetime.fromisoformat(started_raw.replace("Z", ""))
      end_dt = datetime.fromisoformat(completed_raw.replace("Z", ""))
      diff = max(0, int((end_dt - start_dt).total_seconds()))
      return diff, _format_seconds_short(diff)
    except Exception:
      pass
  return 0, "0m 0s"


def get_parent_lang(user_or_row, override_lang: str = None) -> str:
  if override_lang:
    cand = str(override_lang).strip().lower()
    if cand in VALID_PARENT_LANGS:
      return cand
  if user_or_row:
    data = dict(user_or_row) if not isinstance(user_or_row, dict) else user_or_row
    for key in ("parent_tts_engine", "tutor_lang"):
      cand = str(data.get(key) or "").strip().lower()
      if cand in VALID_PARENT_LANGS:
        return cand
  return "en"


def resolve_class_display_name(conn, user_dict: dict) -> str:
  if not user_dict:
    return "Class 10"
  existing = str(user_dict.get("class_name") or "").strip()
  if existing:
    return existing
  class_id = user_dict.get("class_id") or 1
  try:
    row = conn.execute("SELECT name FROM classes WHERE id = ?", (class_id,)).fetchone()
    if row and row[0]:
      raw_name = str(row[0]).strip()
      if raw_name.lower().startswith("grade "):
        return "Class " + raw_name[6:].strip()
      return raw_name
  except Exception:
    pass
  chosen = str(user_dict.get("chosen_class") or "").strip()
  if chosen.isdigit() and int(chosen) >= 6:
    return f"Class {chosen}"
  return "Class 10"


def get_parent_analytics(conn, student_id: int):
  import services.student_service as student_service
  cursor = conn.cursor()
  att_cols = _get_table_columns(conn, "attempts")
  sub_cols = _get_table_columns(conn, "subjects")
  q_cols = _get_table_columns(conn, "questions")

  time_taken_expr = "COALESCE(time_taken_seconds, 0)" if "time_taken_seconds" in att_cols else "0"
  sub_hidden_clause = "AND COALESCE(s.is_hidden, 0) = 0" if "is_hidden" in sub_cols else ""
  q_hidden_clause = "AND COALESCE(q3.is_hidden, 0) = 0" if "is_hidden" in q_cols else ""
  q2_hidden_clause = "AND COALESCE(q2.is_hidden, 0) = 0" if "is_hidden" in q_cols else ""

  cursor.execute(
    "SELECT COALESCE(SUM(progress_seconds), 0) FROM content_progress WHERE student_id = ?",
    (student_id,),
  )
  total_seconds = int(cursor.fetchone()[0] or 0)

  cursor.execute(
    f"""
    SELECT COALESCE(SUM(
      CASE
        WHEN {time_taken_expr} > 0 THEN {time_taken_expr}
        WHEN completed_at IS NOT NULL AND started_at IS NOT NULL
          THEN MAX(0, CAST(strftime('%s', completed_at) - strftime('%s', started_at) AS INTEGER))
        ELSE 0
      END
    ), 0)
    FROM attempts
    WHERE student_id = ?
    """,
    (student_id,),
  )
  exam_seconds = int(cursor.fetchone()[0] or 0)
  total_seconds += max(0, exam_seconds)

  hours = total_seconds // 3600
  minutes = (total_seconds % 3600) // 60
  time_spent = f"{hours}h {minutes}m"

  cursor.execute("SELECT class_id FROM users WHERE id = ?", (student_id,))
  class_row = cursor.fetchone()
  class_id = class_row[0] if (class_row and class_row[0]) else 1

  cursor.execute(
    f"""
    SELECT COUNT(ci.id) FROM content_items ci
    JOIN chapters c ON ci.chapter_id = c.id
    JOIN subjects s ON c.subject_id = s.id
    WHERE s.class_id = ? AND c.status = 'published' {sub_hidden_clause}
    """,
    (class_id,),
  )
  total_content = cursor.fetchone()[0] or 0

  cursor.execute(
    f"""
    SELECT COUNT(DISTINCT cp.content_item_id)
    FROM content_progress cp
    JOIN content_items ci ON cp.content_item_id = ci.id
    JOIN chapters c ON ci.chapter_id = c.id
    JOIN subjects s ON c.subject_id = s.id
    WHERE cp.student_id = ? AND cp.completed = 1 AND s.class_id = ? AND c.status = 'published' {sub_hidden_clause}
    """,
    (student_id, class_id),
  )
  completed_content = cursor.fetchone()[0] or 0

  subjects_for_mastery = student_service.get_student_subjects(conn, class_id, student_id)
  if subjects_for_mastery:
    completion_percent = int(
      round(sum(s.get("progress_pct", 0) for s in subjects_for_mastery) / len(subjects_for_mastery))
    )
  else:
    completion_percent = round((completed_content / total_content * 100) if total_content > 0 else 0)

  live_stats = student_service.get_student_stats(conn, student_id)
  streak_days = int(live_stats.get("streak_days") or 0)

  att_time_sel = "a.time_taken_seconds," if "time_taken_seconds" in att_cols else "0 AS time_taken_seconds,"
  att_tab_sel = "COALESCE(a.tab_switch_count, 0) AS tab_switch_count," if "tab_switch_count" in att_cols else "0 AS tab_switch_count,"

  cursor.execute(
    f"""
    SELECT
      a.id,
      a.exam_paper_id,
      a.status,
      a.started_at,
      {att_time_sel}
      {att_tab_sel}
      ep.title,
      c.name as chapter_name,
      s.name as subject_name,
      COALESCE(SUM(ans.marks_awarded), a.total_marks_awarded, 0) as total_marks_awarded,
      COALESCE(SUM(COALESCE(q.max_marks, m.mark_value, 1)), 0) as answered_max_marks,
      COUNT(DISTINCT ans.question_id) as answered_count,
      COALESCE(
        NULLIF((SELECT COUNT(*) FROM questions q3 JOIN modules m3 ON q3.module_id = m3.id WHERE m3.exam_paper_id = ep.id {q_hidden_clause}), 0),
        (SELECT COUNT(*) FROM questions q3 JOIN modules m3 ON q3.module_id = m3.id JOIN exam_papers em ON m3.exam_paper_id = em.id WHERE em.chapter_id = ep.chapter_id AND em.type = 'mock' {q_hidden_clause})
      ) as total_questions,
      COALESCE(
        NULLIF(a.total_max_marks, 0),
        NULLIF((SELECT SUM(COALESCE(q2.max_marks, m2.mark_value, 1)) FROM questions q2 JOIN modules m2 ON q2.module_id = m2.id WHERE m2.exam_paper_id = ep.id {q2_hidden_clause}), 0),
        NULLIF((SELECT SUM(COALESCE(q2.max_marks, m2.mark_value, 1)) FROM questions q2 JOIN modules m2 ON q2.module_id = m2.id JOIN exam_papers em2 ON m2.exam_paper_id = em2.id WHERE em2.chapter_id = ep.chapter_id AND em2.type = 'mock' {q2_hidden_clause}), 0),
        ep.target_marks,
        0
      ) as total_max_marks,
      COALESCE(a.completed_at, MAX(ans.submitted_at), a.started_at) as completed_at,
      ep.type
    FROM attempts a
    JOIN exam_papers ep ON a.exam_paper_id = ep.id
    LEFT JOIN chapters c ON ep.chapter_id = c.id
    LEFT JOIN subjects s ON c.subject_id = s.id
    LEFT JOIN answers ans ON a.id = ans.attempt_id AND ans.is_latest = 1
      AND TRIM(COALESCE(ans.answer_text, '')) NOT IN ('', 'No answer provided', 'no answer provided')
    LEFT JOIN questions q ON ans.question_id = q.id
    LEFT JOIN modules m ON q.module_id = m.id
    WHERE a.student_id = ? AND c.status = 'published' {sub_hidden_clause}
      AND (ans.id IS NOT NULL OR a.status = 'completed' OR COALESCE(a.total_marks_awarded, 0) > 0)
    GROUP BY a.id, ep.id, ep.title, ep.type, c.name, s.name, a.status, a.started_at
    ORDER BY completed_at DESC, a.id DESC
    """,
    (student_id,),
  )
  all_exams = []
  for row in cursor.fetchall():
    ex = dict(row)
    dur_secs, dur_str = _compute_attempt_duration(ex)
    ex["duration_seconds"] = dur_secs
    ex["time_taken_str"] = dur_str
    ex["duration_str"] = dur_str
    m_awarded = float(ex.get("total_marks_awarded") or 0)
    tot_max = float(ex.get("total_max_marks") or 0)
    ans_max = float(ex.get("answered_max_marks") or 0)
    denom = tot_max if tot_max > 0 else ans_max
    ex["total_marks_awarded"] = _clean_num(m_awarded)
    ex["total_max_marks"] = _clean_num(denom)
    ex["score_pct"] = min(100, int(round((m_awarded / denom) * 100))) if denom > 0 else 0
    all_exams.append(ex)

  distinct_subs = {
    (ex.get("subject_name") or "").strip()
    for ex in all_exams
    if (ex.get("subject_name") or "").strip()
  }
  multi_subject = len(distinct_subs) > 1

  def _build_exam_point(ex):
    pct = ex.get("score_pct", 0)
    sub_name = (ex.get("subject_name") or "Exam").strip()
    ch_name = (ex.get("chapter_name") or ex.get("title") or "").strip()
    ex_type = "Real" if ex.get("type") == "real" else "Mock"
    raw_ts = str(ex.get("completed_at") or "").strip()
    date_iso = raw_ts[:10] if len(raw_ts) >= 10 else ""
    short_dt = date_iso
    if date_iso:
      try:
        short_dt = datetime.strptime(date_iso, "%Y-%m-%d").strftime("%b %d")
      except Exception:
        short_dt = date_iso
    if multi_subject:
      sub_prefix = sub_name[:4] if len(sub_name) > 5 else sub_name
      short_label = f"{sub_prefix} {ex_type}" + (f" · {short_dt}" if short_dt else "")
    else:
      short_label = f"{ex_type} · {short_dt}" if short_dt else f"{ex_type} #{ex.get('id')}"
    return {
      "attempt_id": ex.get("id"),
      "exam_id": ex.get("exam_paper_id"),
      "exam_type": ex.get("type") or "mock",
      "date_str": date_iso,
      "label": short_label,
      "full_title": f"{sub_name} · {ex_type} Exam — {ch_name}" + (f" ({short_dt})" if short_dt else ""),
      "score_pct": pct,
      "percentage": pct,
      "marks_str": f"{ex['total_marks_awarded']}/{ex['total_max_marks']} marks",
      "status": ex.get("status") or "in_progress",
    }

  chron_all_points = [_build_exam_point(ex) for ex in reversed(all_exams)]
  exam_trend = chron_all_points[-8:] if len(chron_all_points) > 8 else list(chron_all_points)

  cursor.execute(
    """
    SELECT ans.id, ans.question_id, q.question_text, ans.answer_text, ans.marks_awarded, ans.ai_feedback, ans.submitted_at, q.max_marks
    FROM answers ans
    JOIN questions q ON ans.question_id = q.id
    JOIN attempts a ON ans.attempt_id = a.id
    JOIN exam_papers ep ON a.exam_paper_id = ep.id
    WHERE a.student_id = ? AND ep.type = 'mock'
    ORDER BY ans.question_id, ans.submitted_at ASC
    """,
    (student_id,),
  )
  grouped_retries = {}
  for row in cursor.fetchall():
    qid = row["question_id"]
    if qid not in grouped_retries:
      grouped_retries[qid] = {
        "question_text": row["question_text"],
        "max_marks": _clean_num(row["max_marks"]),
        "attempts": [],
      }
    grouped_retries[qid]["attempts"].append({
      "answer_text": row["answer_text"],
      "marks_awarded": _clean_num(row["marks_awarded"]),
      "ai_feedback": row["ai_feedback"],
      "submitted_at": row["submitted_at"],
    })

  retry_history = [v for v in grouped_retries.values() if len(v["attempts"]) > 1]
  retry_history.sort(key=lambda x: x["attempts"][-1]["submitted_at"] or "", reverse=True)

  cursor.execute(
    """
    SELECT 'exam' as type, ep.title as name, a.completed_at as timestamp,
        a.total_marks_awarded || '/' || a.total_max_marks as details, ep.type as exam_type,
        a.id as attempt_id
    FROM attempts a
    JOIN exam_papers ep ON a.exam_paper_id = ep.id
    WHERE a.student_id = ? AND a.status = 'completed'

    UNION ALL

    SELECT 'content' as type, ci.title as name, cp.completed_at as timestamp,
        'Completed chapter lesson' as details, '' as exam_type,
        NULL as attempt_id
    FROM content_progress cp
    JOIN content_items ci ON cp.content_item_id = ci.id
    WHERE cp.student_id = ? AND cp.completed = 1 AND cp.completed_at IS NOT NULL

    ORDER BY timestamp DESC
    LIMIT 10
    """,
    (student_id, student_id),
  )
  recent_activity = [dict(r) for r in cursor.fetchall()]

  total_tutor_uses = 0
  pre_submit_tutor_uses = 0
  questions_with_tutor_count = 0
  try:
    cursor.execute(
      """
      SELECT
        COUNT(*) as total_uses,
        COALESCE(SUM(CASE WHEN asked_before_submit = 1 THEN 1 ELSE 0 END), 0) as pre_submit_uses,
        COUNT(DISTINCT question_id) as distinct_questions
      FROM mock_exam_tutor_logs
      WHERE student_id = ?
      """,
      (student_id,),
    )
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
    "xp_earned": int(live_stats.get("xp_earned") or 0),
    "league": live_stats.get("league") or "Bronze",
    "total_chapters": total_content,
    "completed_chapters": completed_content,
    "all_exams": all_exams,
    "exam_trend": exam_trend,
    "mock_exams": [e for e in all_exams if e["type"] != "real"],
    "real_exams": [e for e in all_exams if e["type"] == "real"],
    "retry_history": retry_history,
    "recent_activity": recent_activity,
    "total_tutor_uses": total_tutor_uses,
    "pre_submit_tutor_uses": pre_submit_tutor_uses,
    "questions_with_tutor_count": questions_with_tutor_count,
  }


def get_chapter_milestone_summary(conn, student_id: int, class_id: int = None):
  cursor = conn.cursor()
  sub_cols = _get_table_columns(conn, "subjects")
  q_cols = _get_table_columns(conn, "questions")
  ep_cols = _get_table_columns(conn, "exam_papers")

  if not class_id:
    row = cursor.execute("SELECT class_id FROM users WHERE id = ?", (student_id,)).fetchone()
    class_id = row[0] if (row and row[0]) else 1

  sub_hidden_clause = "AND COALESCE(s.is_hidden, 0) = 0" if "is_hidden" in sub_cols else ""
  q_hidden_clause = "AND COALESCE(q.is_hidden, 0) = 0" if "is_hidden" in q_cols else ""
  target_marks_expr = "ep.target_marks" if "target_marks" in ep_cols else "NULL"

  cursor.execute(
    f"""
    SELECT
      c.id AS chapter_id,
      c.name AS chapter_name,
      s.id AS subject_id,
      s.name AS subject_name
    FROM chapters c
    JOIN subjects s ON c.subject_id = s.id
    WHERE s.class_id = ? AND c.status = 'published' {sub_hidden_clause}
    ORDER BY COALESCE(s.order_index, 999), s.id, COALESCE(c.order_index, 999), c.id
    """,
    (class_id,),
  )
  chapters = [dict(r) for r in cursor.fetchall()]

  results = []
  for ch in chapters:
    ch_id = ch["chapter_id"]
    sub_name = (ch["subject_name"] or "").strip()
    ch_name = (ch["chapter_name"] or "").strip()
    display_title = f"{sub_name} — {ch_name}" if sub_name else ch_name

    cursor.execute(
      "SELECT COUNT(*) FROM content_items WHERE chapter_id = ?",
      (ch_id,),
    )
    videos_total = int(cursor.fetchone()[0] or 0)

    cursor.execute(
      """
      SELECT COUNT(DISTINCT cp.content_item_id)
      FROM content_progress cp
      JOIN content_items ci ON cp.content_item_id = ci.id
      WHERE cp.student_id = ? AND ci.chapter_id = ? AND cp.completed = 1
      """,
      (student_id, ch_id),
    )
    videos_done = int(cursor.fetchone()[0] or 0)

    cursor.execute(
      f"""
      SELECT
        ep.id,
        ep.title,
        ep.type,
        COALESCE(
          NULLIF({target_marks_expr}, 0),
          NULLIF((SELECT SUM(COALESCE(q.max_marks, m.mark_value, 1))
                  FROM modules m JOIN questions q ON q.module_id = m.id
                  WHERE m.exam_paper_id = ep.id {q_hidden_clause}), 0),
          CASE WHEN ep.type = 'real' THEN 25 ELSE 30 END
        ) AS target_marks
      FROM exam_papers ep
      WHERE ep.chapter_id = ? AND COALESCE(ep.status, 'published') = 'published'
      ORDER BY ep.id ASC
      """,
      (ch_id,),
    )
    papers = [dict(r) for r in cursor.fetchall()]

    def _mock_sort_key(p):
      t = (p.get("title") or "").lower()
      if "1" in t:
        return (0, p["id"])
      if "2" in t:
        return (1, p["id"])
      if "3" in t:
        return (2, p["id"])
      return (3, p["id"])

    mock_papers = sorted([p for p in papers if p.get("type") != "real"], key=_mock_sort_key)
    real_papers = [p for p in papers if p.get("type") == "real"]

    def _build_paper_stats(paper, fallback_title: str, paper_type: str, default_marks: int):
      if not paper:
        return {
          "id": None,
          "title": fallback_title,
          "type": paper_type,
          "target_marks": default_marks,
          "best_pct": None,
          "best_marks": None,
          "attempts_count": 0,
          "latest_attempt_id": None,
          "is_unlocked": paper_type != "real",
        }

      pid = paper["id"]
      t_marks = _clean_num(paper.get("target_marks") or default_marks)
      cursor.execute(
        """
        SELECT
          a.id,
          COALESCE((SELECT SUM(ans_s.marks_awarded) FROM answers ans_s WHERE ans_s.attempt_id = a.id AND ans_s.is_latest = 1), a.total_marks_awarded, 0) AS marks_awarded,
          COALESCE(NULLIF(a.total_max_marks, 0), ?) AS max_marks,
          COALESCE(a.completed_at, a.started_at) AS ts
        FROM attempts a
        WHERE a.student_id = ? AND a.exam_paper_id = ?
          AND (a.status = 'completed' OR a.completed_at IS NOT NULL)
        ORDER BY ts DESC, a.id DESC
        """,
        (t_marks, student_id, pid),
      )
      att_rows = cursor.fetchall()
      attempts_count = len(att_rows)
      if attempts_count == 0:
        return {
          "id": pid,
          "title": fallback_title if paper_type == "mock" and fallback_title.startswith("Mock Test") and (paper.get("title") or "").startswith("Mock Test") else (paper.get("title") or fallback_title),
          "type": paper_type,
          "target_marks": t_marks,
          "best_pct": None,
          "best_marks": None,
          "attempts_count": 0,
          "latest_attempt_id": None,
          "is_unlocked": paper_type != "real",
        }

      scored = []
      for ar in att_rows:
        aw = float(ar["marks_awarded"] or 0)
        mx = float(ar["max_marks"] or t_marks or 1)
        pct = min(100, int(round((aw / mx) * 100))) if mx > 0 else 0
        scored.append({"id": ar["id"], "awarded": aw, "max_marks": mx, "pct": pct})

      best_item = max(scored, key=lambda x: (x["pct"], x["awarded"], x["id"]))
      raw_title = (paper.get("title") or "").strip()
      clean_title = raw_title if raw_title in ("Mock Test 1", "Mock Test 2", "Mock Test 3", "Real Exam") else fallback_title

      return {
        "id": pid,
        "title": clean_title,
        "type": paper_type,
        "target_marks": t_marks,
        "best_pct": best_item["pct"],
        "best_marks": _clean_num(best_item["awarded"]),
        "attempts_count": attempts_count,
        "latest_attempt_id": scored[0]["id"],
        "is_unlocked": True,
      }

    mock_cards = []
    for slot_idx in range(3):
      p_obj = mock_papers[slot_idx] if slot_idx < len(mock_papers) else None
      mock_cards.append(_build_paper_stats(p_obj, f"Mock Test {slot_idx + 1}", "mock", 30))

    best_mock_scores = [m["best_pct"] for m in mock_cards if m["best_pct"] is not None]
    best_mock_pct = max(best_mock_scores) if best_mock_scores else None
    is_real_unlocked = bool((best_mock_pct or 0) >= 80)

    real_paper_obj = real_papers[0] if real_papers else None
    real_card = _build_paper_stats(real_paper_obj, "Real Exam", "real", 25)
    real_card["is_unlocked"] = is_real_unlocked

    cursor.execute(
      f"""
      SELECT
        a.id AS attempt_id,
        ep.title AS exam_title,
        q.id AS question_id,
        q.question_text,
        COALESCE(ans.marks_awarded, 0) AS marks_awarded,
        COALESCE(q.max_marks, m.mark_value, 1) AS max_marks,
        COALESCE(a.completed_at, a.started_at) AS attempt_ts
      FROM attempts a
      JOIN exam_papers ep ON a.exam_paper_id = ep.id
      JOIN modules m ON m.exam_paper_id = ep.id
      JOIN questions q ON q.module_id = m.id {q_hidden_clause}
      LEFT JOIN answers ans ON ans.attempt_id = a.id AND ans.question_id = q.id AND ans.is_latest = 1
      WHERE a.student_id = ?
        AND ep.chapter_id = ?
        AND (a.status = 'completed' OR a.completed_at IS NOT NULL)
      ORDER BY attempt_ts DESC, a.id DESC, COALESCE(q.order_index, 0) ASC, q.id ASC
      """,
      (student_id, ch_id),
    )
    seen_qids = set()
    weak_questions = []
    for qr in cursor.fetchall():
      qid = qr["question_id"]
      if qid in seen_qids:
        continue
      seen_qids.add(qid)
      aw = float(qr["marks_awarded"] or 0)
      mx = float(qr["max_marks"] or 1)
      if aw < mx:
        weak_questions.append({
          "question_id": qid,
          "question_text": qr["question_text"],
          "marks_awarded": _clean_num(aw),
          "max_marks": _clean_num(mx),
          "exam_title": qr["exam_title"],
          "attempt_id": qr["attempt_id"],
          "chapter_name": ch_name,
          "subject_name": sub_name,
        })
        if len(weak_questions) >= 5:
          break

    results.append({
      "chapter_id": ch_id,
      "subject_id": ch["subject_id"],
      "subject_name": sub_name,
      "chapter_name": ch_name,
      "title": display_title,
      "videos_done": videos_done,
      "videos_total": videos_total,
      "best_mock_pct": best_mock_pct,
      "best_real_pct": real_card["best_pct"],
      "is_real_unlocked": is_real_unlocked,
      "milestones": mock_cards + [real_card],
      "mock_milestones": mock_cards,
      "real_milestone": real_card,
      "weak_questions": weak_questions,
    })

  return results


def get_completed_attempts_hash(conn, student_id: int, summary_type: str = "main") -> str:
  """
  Fingerprint strictly completed attempts for `student_id` (filtered by `summary_type`)
  so SQLite-cached Parent Dashboard summaries ONLY regenerate when a new attempt is completed!
  """
  type_clause = ""
  if summary_type == "mock":
    type_clause = " AND ep.type != 'real'"
  elif summary_type == "real":
    type_clause = " AND ep.type = 'real'"
  rows = conn.execute(
    f"""
    SELECT a.id, a.exam_paper_id, ROUND(COALESCE((SELECT SUM(ans_s.marks_awarded) FROM answers ans_s WHERE ans_s.attempt_id = a.id AND ans_s.is_latest = 1), a.total_marks_awarded, 0), 2), ROUND(COALESCE(a.total_max_marks, 0), 2)
    FROM attempts a
    JOIN exam_papers ep ON a.exam_paper_id = ep.id
    WHERE a.student_id = ? AND a.completed_at IS NOT NULL{type_clause}
    ORDER BY a.id ASC
    """,
    (student_id,),
  ).fetchall()
  payload = json.dumps([list(r) for r in rows], separators=(",", ":"))
  return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _build_constructive_fallback_summary(student_name: str, analytics: dict, summary_type: str = "main") -> str:
  name = (student_name or "Your child").strip()
  if summary_type == "mock":
    mocks = analytics.get("mock_exams") or []
    retries = len(analytics.get("retry_history") or [])
    if mocks:
      best_pct = max((m.get("score_pct", 0) for m in mocks), default=0)
      return (
        f"{name} has completed {len(mocks)} practice mock attempt{'s' if len(mocks) != 1 else ''} "
        f"with a top score of {best_pct}%, and revisited {retries} practice question{'s' if retries != 1 else ''} to strengthen understanding. "
        f"Reviewing any partial-score answers before the next attempt will help build steady exam confidence."
      )
    return (
      f"{name} has not completed a practice mock test yet. "
      f"Starting with Mock Test 1 after watching the chapter video lessons is a great next step."
    )
  if summary_type == "real":
    reals = analytics.get("real_exams") or []
    if reals:
      best_pct = max((r.get("score_pct", 0) for r in reals), default=0)
      return (
        f"{name} has completed {len(reals)} official timed exam{'s' if len(reals) != 1 else ''} "
        f"with a best official score of {best_pct}%. "
        f"Inspecting the graded answer sheet together is a helpful way to reinforce missed concepts."
      )
    return (
      f"{name} has not taken an official timed exam yet. "
      f"Scoring 80% or higher on a chapter Mock Test unlocks the Official Real Exam."
    )

  comp = analytics.get("completion_percent", 0)
  spent = analytics.get("time_spent", "0h 0m")
  mocks_cnt = len(analytics.get("mock_exams") or [])
  reals_cnt = len(analytics.get("real_exams") or [])
  return (
    f"{name} has completed {comp}% of the active syllabus with {spent} of recorded study time, "
    f"across {mocks_cnt} practice mock test{'s' if mocks_cnt != 1 else ''} and {reals_cnt} official exam{'s' if reals_cnt != 1 else ''}. "
    f"Focusing next on any questions that lost marks in recent papers will steadily strengthen mastery."
  )


def generate_and_cache_ai_summary(
  conn,
  student_id: int,
  student_name: str,
  analytics: dict,
  summary_type: str = "main",
  lang: str = None,
):
  global _PARENT_OPENAI_COOLDOWN_UNTIL
  cursor = conn.cursor()
  user_cols = _get_table_columns(conn, "users")

  column_name = "parent_summary"
  if summary_type == "mock":
    column_name = "parent_mock_summary"
  elif summary_type == "real":
    column_name = "parent_real_summary"

  sel_fields = [column_name]
  if "parent_tts_engine" in user_cols:
    sel_fields.append("parent_tts_engine")
  if "tutor_lang" in user_cols:
    sel_fields.append("tutor_lang")

  cursor.execute(f"SELECT {', '.join(sel_fields)} FROM users WHERE id = ?", (student_id,))
  row = cursor.fetchone()
  row_dict = dict(row) if row else {}

  existing_summary = row_dict.get(column_name)
  lang_code = get_parent_lang(row_dict, override_lang=lang)
  lang_name = VALID_PARENT_LANGS.get(lang_code, "English")

  att_hash = get_completed_attempts_hash(conn, student_id, summary_type)
  hash_marker = f"<!-- attemptshash:{att_hash} lang:{lang_code} v:2 -->"

  clean_existing = ""
  if existing_summary and "v:2" in existing_summary:
    clean_existing = existing_summary.split("<!--")[0].strip()

  is_toxic_legacy = any(
    bad in (existing_summary or "")
    for bad in ("brutality:2", "brutality:3", "brutality:4", "academic freefall", "destroying their future")
  )
  is_cache_hit = (
    bool(clean_existing)
    and not is_toxic_legacy
    and (
      hash_marker in (existing_summary or "")
      or (
        lang_code == "en"
        and f"attemptshash:{att_hash}" in (existing_summary or "")
        and "lang:" not in (existing_summary or "")
        and False
      )
    )
  )
  if is_cache_hit:
    return clean_existing

  _nm = (student_name or "Your child").strip()
  student_name = _nm[:1].upper() + _nm[1:]
  fallback_text = _build_constructive_fallback_summary(student_name, analytics, summary_type)

  if not ai_brain.available():
    if clean_existing and not is_toxic_legacy and (lang_code == "en" or f"lang:{lang_code}" in (existing_summary or "")):
      return clean_existing
    return fallback_text

  system_msg = (
    "You are a respectful, constructive academic advisor writing a concise 2-3 sentence progress summary for a parent. "
    "Be clear, warm, objective, and encouraging. Highlight concrete progress from the numbers and suggest one practical next step for revision. "
    f"Write the entire summary in {lang_name}. Never use emojis, bullet points, markdown headings, or harsh language. "
    "Do not assume the child's gender: refer to the child by first name, or use 'they'. Never use he, she, his or her. "
    "Use only the numbers given, exactly as given, and never combine two different numbers into one claim."
  )

  if summary_type == "mock":
    data_context = (
      f"Student: {student_name}\n"
      f"- Practice Mock Attempts: {len(analytics.get('mock_exams', []))}\n"
      f"- Questions Retried for Mastery: {len(analytics.get('retry_history', []))}\n"
      f"- Tutor Questions Asked During Practice: {analytics.get('total_tutor_uses', 0)} across {analytics.get('questions_with_tutor_count', 0)} questions"
    )
  elif summary_type == "real":
    reals = analytics.get("real_exams", [])
    best_r = max((r.get("score_pct", 0) for r in reals), default=0) if reals else 0
    data_context = (
      f"Student: {student_name}\n"
      f"- Official Real Exams Completed: {len(reals)}\n"
      f"- Best Official Exam Score: {best_r}%"
    )
  else:
    data_context = (
      f"Student: {student_name}\n"
      f"- Active Syllabus Progress: {analytics.get('completion_percent', 0)}%\n"
      f"- Total Study Time Recorded: {analytics.get('time_spent', '0h 0m')}\n"
      f"- Days In A Row With Study (current streak): {analytics.get('streak_days', 0)}\n"
      f"- Practice Mock Attempts: {len(analytics.get('mock_exams', []))}\n"
      f"- Official Real Exams Completed: {len(analytics.get('real_exams', []))}\n"
      f"- Practice Questions Retried: {len(analytics.get('retry_history', []))}"
    )

  user_prompt = (
    f"Write a clear, respectful, constructive 2-3 sentence advisor note for {student_name}'s parent in {lang_name} "
    f"based on this learning data:\n\n{data_context}\n\n"
    f"Output plain prose paragraph only (2-3 sentences, zero emojis)."
  )

  try:
    response = ai_brain.chat(
      [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_prompt},
      ],
      temperature=0.5,
      max_tokens=200,
    )
    summary = (response.choices[0].message.content or "").strip() or fallback_text
    summary_with_hash = f"{summary}\n{hash_marker}"
    cursor.execute(f"UPDATE users SET {column_name} = ? WHERE id = ?", (summary_with_hash, student_id))
    conn.commit()
    return summary
  except Exception as e:
    low = str(e).lower()
    if "insufficient_quota" in low or "credit_balance_exhausted" in low or "no credits" in low:
      _PARENT_OPENAI_COOLDOWN_UNTIL = time.monotonic() + 30.0
    print(f"Parent summary notice: {e}")
    chosen_fallback = clean_existing if (clean_existing and not is_toxic_legacy and lang_code == "en") else fallback_text
    cursor.execute(
      f"UPDATE users SET {column_name} = ? WHERE id = ?",
      (f"{chosen_fallback}\n{hash_marker}", student_id),
    )
    conn.commit()
    return chosen_fallback


def get_exam_report(conn, attempt_id: int, student_id: int):
  cursor = conn.cursor()
  q_cols = _get_table_columns(conn, "questions")
  ans_cols = _get_table_columns(conn, "answers")
  ep_cols = _get_table_columns(conn, "exam_papers")

  q_hidden_clause = "AND COALESCE(q.is_hidden, 0) = 0" if "is_hidden" in q_cols else ""
  drawing_sel = "ans.drawing_url" if "drawing_url" in ans_cols else "NULL AS drawing_url"
  target_marks_sel = "ep.target_marks," if "target_marks" in ep_cols else "NULL AS target_marks,"

  cursor.execute(
    f"""
    SELECT
      a.*,
      ep.title,
      ep.type,
      {target_marks_sel}
      c.name AS chapter_name,
      s.name AS subject_name,
      u.name AS student_name
    FROM attempts a
    JOIN exam_papers ep ON a.exam_paper_id = ep.id
    JOIN users u ON a.student_id = u.id
    LEFT JOIN chapters c ON ep.chapter_id = c.id
    LEFT JOIN subjects s ON c.subject_id = s.id
    WHERE a.id = ? AND a.student_id = ?
    """,
    (attempt_id, student_id),
  )
  attempt = cursor.fetchone()
  if not attempt:
    return None

  att_dict = dict(attempt)
  exam_paper_id = att_dict.get("exam_paper_id")

  cursor.execute(
    f"""
    SELECT
      q.id AS question_id,
      q.question_text,
      q.model_answer,
      COALESCE(q.max_marks, m.mark_value, 1) AS max_marks,
      q.media_url,
      q.answer_media_url,
      m.name AS module_name,
      ans.id AS answer_id,
      ans.answer_text,
      ans.marks_awarded AS raw_marks_awarded,
      ans.percent_correct,
      ans.ai_feedback,
      ans.submitted_at,
      {drawing_sel}
    FROM modules m
    JOIN questions q ON q.module_id = m.id
    LEFT JOIN answers ans ON ans.question_id = q.id AND ans.attempt_id = ? AND ans.is_latest = 1
    WHERE m.exam_paper_id = ? {q_hidden_clause}
    ORDER BY COALESCE(m.order_index, 0) ASC, m.id ASC, COALESCE(q.order_index, 0) ASC, q.id ASC
    """,
    (attempt_id, exam_paper_id),
  )
  raw_rows = [dict(r) for r in cursor.fetchall()]

  if not raw_rows:
    cursor.execute(
      f"""
      SELECT
        q.id AS question_id,
        q.question_text,
        q.model_answer,
        COALESCE(q.max_marks, 1) AS max_marks,
        q.media_url,
        q.answer_media_url,
        '' AS module_name,
        ans.id AS answer_id,
        ans.answer_text,
        ans.marks_awarded AS raw_marks_awarded,
        ans.percent_correct,
        ans.ai_feedback,
        ans.submitted_at,
        {drawing_sel}
      FROM answers ans
      JOIN questions q ON ans.question_id = q.id
      WHERE ans.attempt_id = ? AND ans.is_latest = 1
      ORDER BY COALESCE(q.order_index, 0) ASC, q.id ASC
      """,
      (attempt_id,),
    )
    raw_rows = [dict(r) for r in cursor.fetchall()]

  tutor_logs_by_qid = {}
  total_attempt_tutor_uses = 0
  try:
    cursor.execute(
      """
      SELECT id, question_id, question_number, asked_before_submit, user_message, ai_response, created_at
      FROM mock_exam_tutor_logs
      WHERE student_id = ? AND (attempt_id = ? OR (attempt_id IS NULL AND exam_paper_id = ?))
      ORDER BY created_at ASC, id ASC
      """,
      (student_id, attempt_id, exam_paper_id),
    )
    for r in cursor.fetchall():
      rd = dict(r)
      qid = rd["question_id"]
      tutor_logs_by_qid.setdefault(qid, []).append(rd)
      total_attempt_tutor_uses += 1
  except Exception:
    pass

  answers = []
  for r in raw_rows:
    raw_text = (r.get("answer_text") or "").strip()
    drawing_url = (r.get("drawing_url") or "").strip()
    is_unanswered = (
      r.get("answer_id") is None
      or (raw_text in ("", "No answer provided", "no answer provided") and not drawing_url)
    )
    student_answer = "" if is_unanswered else raw_text
    marks_awarded = 0 if is_unanswered else _clean_num(r.get("raw_marks_awarded") or 0)
    max_marks = _clean_num(r.get("max_marks") or 1)
    qid = r.get("question_id")
    q_logs = tutor_logs_by_qid.get(qid, [])

    answers.append({
      "id": r.get("answer_id"),
      "question_id": qid,
      "module_name": r.get("module_name") or "",
      "question_text": r.get("question_text") or "",
      "model_answer": r.get("model_answer") or "",
      "max_marks": max_marks,
      "marks_awarded": marks_awarded,
      "student_answer": student_answer,
      "answer_text": student_answer,
      "is_unanswered": bool(is_unanswered),
      "drawing_url": drawing_url or None,
      "media_url": r.get("media_url"),
      "answer_media_url": r.get("answer_media_url"),
      "ai_feedback": r.get("ai_feedback") or "",
      "submitted_at": r.get("submitted_at"),
      "tutor_logs": q_logs,
      "tutor_uses_count": len(q_logs),
      "pre_submit_tutor_uses": sum(1 for l in q_logs if l.get("asked_before_submit")),
    })

  dur_secs, dur_str = _compute_attempt_duration(att_dict)
  att_dict["time_taken_seconds"] = dur_secs
  att_dict["time_taken_str"] = dur_str
  att_dict["duration_seconds"] = dur_secs
  att_dict["duration_str"] = dur_str
  att_dict["tab_switch_count"] = int(att_dict.get("tab_switch_count") or 0)
  att_dict["total_tutor_uses"] = total_attempt_tutor_uses

  sum_q_max = sum(float(a["max_marks"] or 0) for a in answers)
  sum_q_awarded = sum(float(a["marks_awarded"] or 0) for a in answers)

  raw_tot_max = float(att_dict.get("total_max_marks") or 0)
  if raw_tot_max <= 0:
    raw_tot_max = sum_q_max or float(att_dict.get("target_marks") or 0)
  raw_tot_awarded = (
    sum_q_awarded
    if answers
    else float(att_dict.get("total_marks_awarded") or 0)
  )

  att_dict["total_max_marks"] = _clean_num(raw_tot_max)
  att_dict["total_marks_awarded"] = _clean_num(raw_tot_awarded)
  att_dict["accuracy_pct"] = (
    min(100, int(round((raw_tot_awarded / raw_tot_max) * 100))) if raw_tot_max > 0 else 0
  )
  att_dict["unanswered_count"] = sum(1 for a in answers if a["is_unanswered"])
  att_dict["needs_revision_count"] = sum(
    1 for a in answers if float(a["marks_awarded"]) < float(a["max_marks"])
  )

  return {
    "attempt": att_dict,
    "answers": answers,
  }


def update_parent_settings(
  conn,
  student_id: int,
  locked: int,
  pin: str,
  sfx_mode: int = 1,
  sfx_custom: str = "{}",
  cursor_mode: int = 0,
  cursor_effect: str = "none",
  brutality_level: int = 1,
  tts_voice: str = "af_bella",
  tts_engine: str = "en",
  tts_mode: str = "manual",
  tutor_lang: str = None,
):
  cursor = conn.cursor()
  user_cols = _get_table_columns(conn, "users")

  clean_locked = 1 if int(locked or 0) else 0
  clean_pin = (pin or "").strip()
  clean_voice = tts_voice if tts_voice in VALID_TTS_VOICES else "af_bella"
  clean_mode = tts_mode if tts_mode in VALID_TTS_MODES else "manual"

  lang_candidate = (tutor_lang or tts_engine or "en").strip().lower()
  clean_lang = lang_candidate if lang_candidate in VALID_PARENT_LANGS else "en"

  updates = {
    "parent_locked": clean_locked,
    "parent_pin": clean_pin,
    "parent_tts_voice": clean_voice,
    "parent_tts_mode": clean_mode,
  }
  if "parent_tts_engine" in user_cols:
    updates["parent_tts_engine"] = clean_lang
  if "tutor_lang" in user_cols:
    updates["tutor_lang"] = clean_lang
  if "brutality_level" in user_cols:
    updates["brutality_level"] = 1

  set_sql = ", ".join(f"{col} = ?" for col in updates.keys())
  params = list(updates.values()) + [student_id]
  cursor.execute(f"UPDATE users SET {set_sql} WHERE id = ?", params)
  conn.commit()


def get_mock_exam_analytics(conn, student_id: int):
  cursor = conn.cursor()
  att_cols = _get_table_columns(conn, "attempts")
  sub_cols = _get_table_columns(conn, "subjects")
  q_cols = _get_table_columns(conn, "questions")

  att_time_sel = "a.time_taken_seconds," if "time_taken_seconds" in att_cols else "0 AS time_taken_seconds,"
  sub_hidden_clause = "AND COALESCE(s.is_hidden, 0) = 0" if "is_hidden" in sub_cols else ""
  q_hidden_clause = "AND COALESCE(q.is_hidden, 0) = 0" if "is_hidden" in q_cols else ""

  cursor.execute(
    f"""
    SELECT
      a.id,
      a.exam_paper_id,
      a.started_at,
      {att_time_sel}
      ep.title,
      c.name AS chapter_name,
      s.name AS subject_name,
      COALESCE(SUM(ans.marks_awarded), a.total_marks_awarded, 0) as total_marks_awarded,
      COALESCE(
        NULLIF(a.total_max_marks, 0),
        (SELECT SUM(COALESCE(q.max_marks, m.mark_value, 1)) FROM questions q JOIN modules m ON q.module_id = m.id WHERE m.exam_paper_id = ep.id {q_hidden_clause}),
        ep.target_marks,
        30
      ) as total_max_marks,
      COALESCE(a.completed_at, MAX(ans.submitted_at), a.started_at) as completed_at,
      COUNT(ans.id) as questions_attempted
    FROM attempts a
    JOIN exam_papers ep ON a.exam_paper_id = ep.id
    LEFT JOIN chapters c ON ep.chapter_id = c.id
    LEFT JOIN subjects s ON c.subject_id = s.id
    LEFT JOIN answers ans ON a.id = ans.attempt_id AND ans.is_latest = 1
      AND TRIM(COALESCE(ans.answer_text, '')) NOT IN ('', 'No answer provided', 'no answer provided')
    WHERE a.student_id = ? AND ep.type = 'mock'
      AND COALESCE(c.status, 'published') = 'published'
      {sub_hidden_clause}
      AND (a.status = 'completed' OR ans.id IS NOT NULL)
    GROUP BY a.id, ep.title, a.started_at, c.name, s.name
    ORDER BY completed_at DESC, a.id DESC
    """,
    (student_id,),
  )
  mock_exams = []
  for r in cursor.fetchall():
    item = dict(r)
    dur_secs, dur_str = _compute_attempt_duration(item)
    item["duration_seconds"] = dur_secs
    item["duration_str"] = dur_str
    item["time_taken_str"] = dur_str
    aw = float(item.get("total_marks_awarded") or 0)
    mx = float(item.get("total_max_marks") or 30)
    item["total_marks_awarded"] = _clean_num(aw)
    item["total_max_marks"] = _clean_num(mx)
    item["score_pct"] = min(100, int(round((aw / mx) * 100))) if mx > 0 else 0
    mock_exams.append(item)

  tutor_logs = []
  try:
    cursor.execute(
      """
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
      """,
      (student_id,),
    )
    tutor_logs = [dict(r) for r in cursor.fetchall()]
  except Exception as e:
    print(f"Error fetching mock_exam_tutor_logs: {e}")

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
        "max_marks": _clean_num(log["max_marks"]),
        "usage_count": 0,
        "pre_submit_count": 0,
        "last_used_at": log["created_at"],
        "prompts": [],
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
      "attempt_id": log.get("attempt_id"),
    })

  tutor_by_question = list(grouped_tutor_by_q.values())
  tutor_by_question.sort(key=lambda x: x["last_used_at"] or "", reverse=True)

  for m in mock_exams:
    m["tutor_uses_count"] = tutor_count_by_attempt.get(m["id"], 0)

  cursor.execute(
    """
    SELECT ans.id, ans.question_id, q.question_text, ans.answer_text, ans.marks_awarded, ans.ai_feedback, ans.submitted_at, q.max_marks, ep.title AS exam_title, a.id AS attempt_id
    FROM answers ans
    JOIN questions q ON ans.question_id = q.id
    JOIN attempts a ON ans.attempt_id = a.id
    JOIN exam_papers ep ON a.exam_paper_id = ep.id
    WHERE a.student_id = ? AND ep.type = 'mock'
    ORDER BY ans.question_id, ans.submitted_at ASC
    """,
    (student_id,),
  )
  grouped_retries = {}
  for row in cursor.fetchall():
    qid = row["question_id"]
    if qid not in grouped_retries:
      grouped_retries[qid] = {
        "question_id": qid,
        "question_text": row["question_text"],
        "exam_title": row["exam_title"],
        "latest_attempt_id": row["attempt_id"],
        "max_marks": _clean_num(row["max_marks"]),
        "tutor_uses_count": tutor_count_by_qid.get(qid, 0),
        "attempts": [],
      }
    grouped_retries[qid]["latest_attempt_id"] = row["attempt_id"]
    grouped_retries[qid]["attempts"].append({
      "answer_text": row["answer_text"],
      "marks_awarded": _clean_num(row["marks_awarded"]),
      "ai_feedback": row["ai_feedback"],
      "submitted_at": row["submitted_at"],
      "attempt_id": row["attempt_id"],
    })

  retry_history = [v for v in grouped_retries.values() if len(v["attempts"]) > 1]
  retry_history.sort(key=lambda x: x["attempts"][-1]["submitted_at"] or "", reverse=True)

  return {
    "mock_exams": mock_exams,
    "retry_history": retry_history,
    "tutor_logs": tutor_logs,
    "tutor_by_question": tutor_by_question,
    "total_tutor_uses": len(tutor_logs),
    "pre_submit_tutor_uses": sum(1 for l in tutor_logs if l.get("asked_before_submit")),
    "questions_with_tutor_count": len({l["question_id"] for l in tutor_logs}),
  }


def get_real_exam_analytics(conn, student_id: int):
  cursor = conn.cursor()
  att_cols = _get_table_columns(conn, "attempts")
  sub_cols = _get_table_columns(conn, "subjects")
  q_cols = _get_table_columns(conn, "questions")

  att_time_sel = "a.time_taken_seconds," if "time_taken_seconds" in att_cols else "0 AS time_taken_seconds,"
  att_tab_sel = "COALESCE(a.tab_switch_count, 0) AS tab_switch_count," if "tab_switch_count" in att_cols else "0 AS tab_switch_count,"
  sub_hidden_clause = "AND COALESCE(s.is_hidden, 0) = 0" if "is_hidden" in sub_cols else ""
  q_hidden_clause = "AND COALESCE(q.is_hidden, 0) = 0" if "is_hidden" in q_cols else ""

  cursor.execute(
    f"""
    SELECT
      a.id,
      a.exam_paper_id,
      ep.title,
      c.name AS chapter_name,
      s.name AS subject_name,
      COALESCE(SUM(ans.marks_awarded), a.total_marks_awarded, 0) as total_marks_awarded,
      COALESCE(
        NULLIF(a.total_max_marks, 0),
        (SELECT SUM(COALESCE(q.max_marks, m.mark_value, 1)) FROM questions q JOIN modules m ON q.module_id = m.id WHERE m.exam_paper_id = ep.id {q_hidden_clause}),
        ep.target_marks,
        25
      ) as total_max_marks,
      a.started_at,
      {att_time_sel}
      {att_tab_sel}
      COALESCE(a.completed_at, MAX(ans.submitted_at), a.started_at) as completed_at,
      a.purchased_extra_seconds
    FROM attempts a
    JOIN exam_papers ep ON a.exam_paper_id = ep.id
    LEFT JOIN chapters c ON ep.chapter_id = c.id
    LEFT JOIN subjects s ON c.subject_id = s.id
    LEFT JOIN answers ans ON a.id = ans.attempt_id AND ans.is_latest = 1
      AND TRIM(COALESCE(ans.answer_text, '')) NOT IN ('', 'No answer provided', 'no answer provided')
    WHERE a.student_id = ? AND ep.type = 'real'
      AND COALESCE(c.status, 'published') = 'published'
      {sub_hidden_clause}
      AND (a.status = 'completed' OR ans.id IS NOT NULL)
    GROUP BY a.id, ep.title, a.started_at, a.purchased_extra_seconds, c.name, s.name
    ORDER BY completed_at DESC, a.id DESC
    """,
    (student_id,),
  )

  real_exams = []
  for row in cursor.fetchall():
    r = dict(row)
    dur_secs, dur_str = _compute_attempt_duration(r)
    r["duration_seconds"] = dur_secs
    r["duration_str"] = dur_str
    r["time_taken_str"] = dur_str
    r["tab_switch_count"] = int(r.get("tab_switch_count") or 0)
    aw = float(r.get("total_marks_awarded") or 0)
    mx = float(r.get("total_max_marks") or 25)
    r["total_marks_awarded"] = _clean_num(aw)
    r["total_max_marks"] = _clean_num(mx)
    r["score_pct"] = min(100, int(round((aw / mx) * 100))) if mx > 0 else 0
    real_exams.append(r)

  return {
    "real_exams": real_exams,
  }
