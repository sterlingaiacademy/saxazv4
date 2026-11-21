from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional

from database import get_db_connection
from security import require_student, require_auth
from services import storage
import services.reward_service as reward_service

router = APIRouter(prefix="/student")
templates = Jinja2Templates(directory="templates")

import json
def parse_json_filter(value):
  if not value: return []
  try: return json.loads(value)
  except: return []
templates.env.filters['parse_json'] = parse_json_filter

from services.video_vault import (
  create_vault_token,
  resolve_vault_token,
  encode_client_payload,
  tokenize_additional_videos,
  extract_youtube_id,
)

import re as _re
def youtube_embed_filter(url: str) -> str:
  """Convert any YouTube URL to a vault token for protected playback."""
  return create_vault_token(url)
templates.env.filters['youtube_embed'] = youtube_embed_filter
templates.env.filters['video_vault_token'] = create_vault_token

import services.student_service as student_service

def _round_exam_time(total_seconds: int) -> int:
    minutes = total_seconds // 60
    if minutes < 10:
        return total_seconds
    remainder = minutes % 10
    if remainder < 5:
        rounded_minutes = minutes - remainder
    else:
        rounded_minutes = minutes + (10 - remainder)
    return rounded_minutes * 60
from fastapi.responses import JSONResponse

@router.get("/api/gamification", response_class=JSONResponse)
async def gamification_api(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    stats = student_service.get_student_stats(conn, user['id'])
    return {
      "streak": stats["streak_days"],
      "xp": stats["xp_earned"],
      "current_xp": stats["current_xp"],
      "league": stats["league"],
      "league_hex": stats["league_hex"],
      "league_gradient": stats["league_gradient"],
      "league_progress": stats["league_progress"],
      "next_tier_xp": stats["next_tier_xp"]
    }
  except Exception as e:
    from fastapi import HTTPException
    if not isinstance(e, HTTPException):
      print(f"Gamification API error: {e}")
    return {"streak": 0, "xp": 0}
  finally:
    conn.close()

@router.get("/api/notifications", response_class=JSONResponse)
async def get_notifications(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 20", (user['id'],))
    notifications = [dict(r) for r in cursor.fetchall()]
    unread_count = sum(1 for n in notifications if not n['is_read'])
    return {"notifications": notifications, "unreadCount": unread_count}
  except Exception as e:
    from fastapi import HTTPException
    if isinstance(e, HTTPException):
      raise
    return {"notifications": [], "unreadCount": 0}
  finally:
    conn.close()

@router.post("/api/notifications/read", response_class=JSONResponse)
async def mark_notifications_read(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (user['id'],))
    conn.commit()
    return {"success": True}
  except Exception as e:
    from fastapi import HTTPException
    if isinstance(e, HTTPException):
      raise
    return {"success": False}
  finally:
    conn.close()

@router.post("/api/track-time")
async def track_study_time_api(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    data = await request.json()
    subject_id = data.get("subject_id")
    seconds = int(data.get("seconds", 15))
    if subject_id:
      student_service.track_subject_time(conn, user['id'], int(subject_id), seconds)
    return {"success": True}
  except Exception as e:
    return {"success": False, "error": str(e)}
  finally:
    conn.close()

@router.get("/api/subject-progress")
async def get_subject_progress_live(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    class_id = user.get('class_id') or 1
    subjects = student_service.get_student_subjects(conn, class_id, user['id'])
    stats = student_service.get_student_stats(conn, user['id'])
    return {"success": True, "subjects": subjects, "stats": stats}
  except Exception as e:
    return {"success": False, "error": str(e)}
  finally:
    conn.close()

import time as _time
import base64 as _b64

def _read_continue_cookie(request: Request, user_id: int) -> dict:
  raw = request.cookies.get(f"saxaz_cont_{user_id}") or request.cookies.get("saxaz_cont")
  if not raw:
    return {}
  try:
    pad = "=" * ((4 - len(raw) % 4) % 4)
    decoded = _b64.urlsafe_b64decode((raw + pad).encode("ascii")).decode("utf-8")
    data = json.loads(decoded)
    return data if isinstance(data, dict) else {}
  except Exception:
    return {}

def _write_continue_cookie(request: Request, response, user_id: int, mode: str, entry: dict):
  try:
    state = _read_continue_cookie(request, user_id)
    prev = state.get(mode) if isinstance(state.get(mode), dict) else {}
    # If switching to a different exam or chapter without explicit question info, clear old question fields
    same_exam = prev.get("exam_id") and entry.get("exam_id") and str(prev.get("exam_id")) == str(entry.get("exam_id"))
    same_ch = prev.get("chapter_id") and entry.get("chapter_id") and str(prev.get("chapter_id")) == str(entry.get("chapter_id"))
    if same_exam or (same_ch and not entry.get("exam_id")):
      merged = {**prev, **entry, "updated_at": _time.time()}
    else:
      merged = {**entry, "updated_at": _time.time()}
    state[mode] = merged
    state["active_mode"] = mode
    encoded = _b64.urlsafe_b64encode(json.dumps(state, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("=")
    response.set_cookie(key=f"saxaz_cont_{user_id}", value=encoded, max_age=365 * 86400, path="/", samesite="lax", httponly=False)
    response.set_cookie(key="saxaz_cont", value=encoded, max_age=365 * 86400, path="/", samesite="lax", httponly=False)
  except Exception as e:
    print(f"Continue cookie write error: {e}")

@router.post("/api/continue-state")
async def update_continue_state_api(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    body = await request.json()
    mode = body.get("mode")
    if mode not in ("digi", "exam"):
      return JSONResponse({"success": False, "error": "Invalid mode"}, status_code=400)
    resp = JSONResponse({"success": True})
    _write_continue_cookie(request, resp, user["id"], mode, body)
    return resp
  except Exception as e:
    return JSONResponse({"success": False, "error": str(e)}, status_code=400)
  finally:
    conn.close()

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    class_id = user.get('class_id') or 1 # Fallback to 1 if no class assigned
    subjects = student_service.get_student_subjects(conn, class_id, user['id'])
    for s in subjects:
      s['chapters'] = student_service.get_student_chapters(conn, s['id'], user['id'])
    
    overall_progress_pct = int(sum(s.get('progress_pct', 0) for s in subjects) / len(subjects)) if subjects else 0
    
    recent_attempts = student_service.get_recent_attempts(conn, user['id'], limit=6)
    stats = student_service.get_student_stats(conn, user['id'])
    cookie_cont = _read_continue_cookie(request, user['id'])
    continue_state = student_service.get_student_continue_state(conn, user['id'], subjects, cookie_cont)
    
    return templates.TemplateResponse(request=request, name="student/dashboard.html", context={
      "request": request, 
      "user": user, 
      "subjects": subjects,
      "digi_books": [],
      "overall_progress_pct": overall_progress_pct,
      "total_digi_banks": 0,
      "recent_attempts": recent_attempts,
      "stats": stats,
      "analytics": {},
      "continue_state": continue_state
    })
  finally:
    conn.close()

@router.get("/exams", response_class=HTMLResponse)
@router.get("/subjects", response_class=HTMLResponse)
async def exams_subjects_hub(request: Request, subject: Optional[str] = None):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    class_id = user.get('class_id') or 1
    subjects = student_service.get_student_subjects(conn, class_id, user['id'])
    for s in subjects:
      s['chapters'] = student_service.get_student_chapters(conn, s['id'], user['id'])
    overall_progress_pct = int(sum(s.get('progress_pct', 0) for s in subjects) / len(subjects)) if subjects else 0
    raw_sub_param = str(subject).strip() if subject else ''
    selected_subject_id = raw_sub_param if raw_sub_param else (str(subjects[0]['id']) if subjects else '')
    valid_ids = {str(s['id']) for s in subjects}
    if selected_subject_id not in valid_ids and subjects:
      selected_subject_id = str(subjects[0]['id'])
    return templates.TemplateResponse(request=request, name="student/exams_subjects.html", context={
      "request": request,
      "user": user,
      "subjects": subjects,
      "overall_progress_pct": overall_progress_pct,
      "selected_subject_id": selected_subject_id,
      "raw_subject_query": raw_sub_param,
    })
  finally:
    conn.close()

@router.get("/subjects/{subject_id}", response_class=HTMLResponse)
async def subject_view(request: Request, subject_id: int):
  from fastapi.responses import RedirectResponse
  return RedirectResponse(url=f"/student/exams?subject={subject_id}", status_code=302)

@router.get("/chapters/{chapter_id}", response_class=HTMLResponse)
async def view_chapter(request: Request, chapter_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    chapter = student_service.get_chapter_with_content(conn, chapter_id, user['id'])
    if not chapter:
      return HTMLResponse("Chapter not found or not published", status_code=404)
    
    if chapter.get('video_description_url'):
      chapter['video_description_url'] = create_vault_token(chapter['video_description_url'])
    if chapter.get('real_life_url'):
      chapter['real_life_url'] = create_vault_token(chapter['real_life_url'])

    # Tokenize all video items for inline & dedicated playback and attach continuation metadata
    raw_items = chapter.get('content') or []
    for idx, item in enumerate(raw_items):
      m_url = item.get('media_url') or ''
      yt_id = extract_youtube_id(m_url)
      if item.get('type') in ('youtube', 'video') or yt_id:
        item['vault_token'] = create_vault_token(m_url)
      if not item.get('thumbnail_url') and yt_id:
        item['thumbnail_url'] = f"https://i.ytimg.com/vi/{yt_id}/hqdefault.jpg"
      dur_s = int(item.get('duration_seconds') or 0)
      if dur_s > 0:
        item['duration_str'] = f"{dur_s // 60}:{dur_s % 60:02d}"
      else:
        item['duration_str'] = "5:00"
      item['part_number'] = idx + 1
      if idx + 1 < len(raw_items):
        item['next_item_id'] = raw_items[idx + 1]['id']
        item['next_item_title'] = raw_items[idx + 1]['title']
        item['next_part_number'] = idx + 2
      else:
        item['next_item_id'] = None
        item['next_item_title'] = None
        item['next_part_number'] = None

    available_exams = student_service.get_available_exams(conn, chapter_id, user['id'])
    completed_content_ids = student_service.get_completed_content_ids(conn, user['id'], chapter_id)
    chapter_attempts = student_service.get_recent_attempts(conn, user['id'], limit=20, chapter_id=chapter_id)
    claimed_keys = sorted(reward_service.get_claimed_keys(conn, user['id']))
    avatar_map = {'af_bella': 'bella', 'af_sarah': 'sarah', 'am_adam': 'adam', 'am_michael': 'michael'}
    tutor_name = avatar_map.get(user.get('tts_voice') or 'af_bella', 'bella')
    
    resp = templates.TemplateResponse(request=request, name="student/chapter.html", context={
      "request": request,
      "user": user,
      "chapter": chapter,
      "available_exams": available_exams,
      "completed_content_ids": completed_content_ids,
      "chapter_attempts": chapter_attempts,
      "claimed_keys": claimed_keys,
      "tutor_name": tutor_name,
    })
    existing_cont = _read_continue_cookie(request, user['id'])
    existing_exam_cont = existing_cont.get("exam") if isinstance(existing_cont.get("exam"), dict) else {}
    if not existing_exam_cont.get("exam_id"):
      _write_continue_cookie(request, resp, user['id'], "exam", {
        "chapter_id": chapter_id,
      })
    return resp
  finally:
    conn.close()

@router.get("/content/{content_id}", response_class=HTMLResponse)
async def view_content(request: Request, content_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    content_item = student_service.get_content_item(conn, content_id)
    if not content_item:
      return HTMLResponse("Content not found", status_code=404)
    
    raw_media_url = content_item.get('media_url') or ''
    yt_id_main = extract_youtube_id(raw_media_url)
    if content_item.get('type') == 'youtube' or yt_id_main:
      content_item['media_url'] = create_vault_token(raw_media_url)
      content_item['type'] = 'youtube'
    if not content_item.get('thumbnail_url') and yt_id_main:
      content_item['thumbnail_url'] = f"https://i.ytimg.com/vi/{yt_id_main}/hqdefault.jpg"
    dur_main = int(content_item.get('duration_seconds') or 0)
    content_item['duration_str'] = f"{dur_main // 60}:{dur_main % 60:02d}" if dur_main > 0 else "5:00"

    if content_item.get('additional_videos'):
      content_item['additional_videos'] = tokenize_additional_videos(content_item['additional_videos'])

    # Check if already completed
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM content_progress WHERE student_id = ? AND content_item_id = ? AND completed = 1", (user['id'], content_id))
    is_completed = cursor.fetchone() is not None

    # Get chapter, all summary parts, prev/next items, and exams for continuation flow
    chapter_id = content_item['chapter_id']
    chapter = student_service.get_chapter_with_content(conn, chapter_id, user['id'])
    completed_content_ids = student_service.get_completed_content_ids(conn, user['id'], chapter_id)
    available_exams = student_service.get_available_exams(conn, chapter_id, user['id'])
    mock_exam = next((e for e in available_exams if e.get('type') != 'real'), available_exams[0] if available_exams else None)

    prev_item = None
    next_item = None
    current_part_idx = 1
    total_parts = 1
    chapter_videos = []
    if chapter and 'content' in chapter:
      items = chapter['content']
      total_parts = len(items)
      for i, it in enumerate(items):
        it_yt = extract_youtube_id(it.get('media_url') or '')
        if not it.get('thumbnail_url') and it_yt:
          it['thumbnail_url'] = f"https://i.ytimg.com/vi/{it_yt}/hqdefault.jpg"
        it_dur = int(it.get('duration_seconds') or 0)
        it['duration_str'] = f"{it_dur // 60}:{it_dur % 60:02d}" if it_dur > 0 else "5:00"
        it['part_number'] = i + 1
        it['is_completed'] = it['id'] in completed_content_ids
        chapter_videos.append(it)
        if it['id'] == content_id:
          current_part_idx = i + 1
          if i > 0:
            prev_item = items[i - 1]
          if i < len(items) - 1:
            next_item = items[i + 1]

    resp = templates.TemplateResponse(request=request, name="student/content_view.html", context={
      "request": request,
      "user": user,
      "item": content_item,
      "chapter": chapter,
      "chapter_videos": chapter_videos,
      "completed_content_ids": completed_content_ids,
      "available_exams": available_exams,
      "mock_exam": mock_exam,
      "current_part_idx": current_part_idx,
      "total_parts": total_parts,
      "is_completed": is_completed,
      "prev_item": prev_item,
      "next_item": next_item
    })
    _write_continue_cookie(request, resp, user['id'], "exam", {
      "chapter_id": chapter_id,
      "exam_id": mock_exam['id'] if mock_exam else None,
    })
    return resp
  finally:
    conn.close()

@router.post("/content/{content_id}/ping", response_class=JSONResponse)
async def ping_content(request: Request, content_id: int):
    conn = get_db_connection()
    try:
        user = require_student(request, conn)
        # Add 10 seconds to progress
        student_service.log_content_time(conn, user['id'], content_id, 10)
        return {"status": "ok"}
    finally:
        conn.close()

@router.post("/content/{content_id}/complete")
async def mark_content_complete(request: Request, content_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    student_service.mark_content_complete(conn, user['id'], content_id)
    ci_row = conn.execute("SELECT title FROM content_items WHERE id = ?", (content_id,)).fetchone()
    ci_title = ci_row[0] if ci_row and ci_row[0] else f"Summary Video #{content_id}"
    if "application/json" in (request.headers.get("accept") or "").lower():
      json_resp = JSONResponse({"status": "ok"})
      rw = reward_service.award_milestone_coins(
        conn, user['id'], f"video:item:{content_id}", 5, f"Watched {ci_title}", request=request, response=json_resp
      )
      json_resp.body = json.dumps({"status": "ok", "reward": rw}).encode("utf-8")
      json_resp.headers["content-length"] = str(len(json_resp.body))
      return json_resp

    html_resp = HTMLResponse("""
      <div class="w-10 h-10 rounded-full border-2 border-[#231f20] bg-[#f7b317] text-[#231f20] flex items-center justify-center" title="Completed">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
        </svg>
      </div>
    """)
    reward_service.award_milestone_coins(
      conn, user['id'], f"video:item:{content_id}", 5, f"Watched {ci_title}", request=request, response=html_resp
    )
    return html_resp
  finally:
    conn.close()

from fastapi import Form
from starlette.responses import RedirectResponse
import services.grading_service as grading_service

@router.get("/chapters/{chapter_id}/exams", response_class=HTMLResponse)
async def chapter_exams(request: Request, chapter_id: int):
  conn = get_db_connection()
  try:
    require_student(request, conn)
    return RedirectResponse(f"/student/chapters/{chapter_id}#chapter-exams", status_code=302)
  finally:
    conn.close()

@router.get("/exams/{exam_id}", response_class=HTMLResponse)
async def take_exam(request: Request, exam_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    paper = student_service.get_exam_paper_full(conn, exam_id)
    if not paper or paper['status'] != 'published':
      return HTMLResponse("Exam not available", status_code=404)

    if paper.get('chapter_id'):
      cur_meta = conn.cursor()
      cur_meta.execute(
        "SELECT c.name as chapter_name, s.name as subject_name FROM chapters c LEFT JOIN subjects s ON c.subject_id = s.id WHERE c.id = ?",
        (paper['chapter_id'],)
      )
      ch_meta = cur_meta.fetchone()
      if ch_meta:
        paper['chapter_name'] = paper.get('chapter_name') or ch_meta[0] or ''
        paper['subject_name'] = paper.get('subject_name') or ch_meta[1] or ''
      
    seen_q_objs = set()
    for mod_group_key in ('modules', 'textbook_modules', 'mark_modules'):
      for mod in paper.get(mod_group_key, []):
        for q in mod.get('questions', []):
          if id(q) in seen_q_objs:
            continue
          seen_q_objs.add(id(q))
          if q.get('explanation_video_url') and (q.get('explanation_video_type') == 'youtube' or extract_youtube_id(q.get('explanation_video_url'))):
            q['explanation_video_url'] = create_vault_token(q['explanation_video_url'])
            q['explanation_video_type'] = 'youtube'
          if q.get('additional_videos'):
            q['additional_videos'] = tokenize_additional_videos(q['additional_videos'])

    import json
    try:
      paper['speed_stats'] = student_service.get_mock_speed_stats(conn, paper['id'], user['id'])
    except Exception:
      paper['speed_stats'] = None
    paper_json = json.dumps(paper)
    
    is_fresh_run = str(request.query_params.get("fresh") or "").strip().lower() in ("1", "true", "yes")
    # Pre-initialize attempt right on GET so attemptId is never null even if student submits immediately
    try:
      initial_attempt_id = student_service.start_exam_attempt(conn, paper['id'], paper.get('version', 1), user['id'], force_new=is_fresh_run)
    except Exception:
      initial_attempt_id = None

    tts_voice = user.get('tts_voice', 'af_bella')
    avatar_map = {
      'af_bella': 'bella',
      'af_sarah': 'sarah',
      'am_adam': 'adam',
      'am_michael': 'michael'
    }
    tutor_name = avatar_map.get(tts_voice, 'bella')

    sibling_mocks = []
    real_exam_info = None
    if paper.get('chapter_id'):
      avail_exams = student_service.get_available_exams(conn, paper['chapter_id'], user['id'])
      if paper.get('type') == 'mock':
        for ex in avail_exams:
          if ex.get('type') == 'mock':
            hs = ex.get('highest_score')
            sibling_mocks.append({
              "id": ex["id"],
              "title": ex["title"],
              "best_pct": min(100, int(round(float(hs)))) if hs is not None else None,
            })
      real_ex = next((ex for ex in avail_exams if ex.get('type') == 'real'), None)
      best_mock_raw = max((float(ex.get('highest_score') or 0.0) for ex in avail_exams if ex.get('type') == 'mock'), default=0.0)
      if real_ex:
        real_exam_info = {
          "id": real_ex["id"],
          "is_locked": bool(real_ex.get("is_locked", True)),
          "best_mock_pct": min(100, int(round(best_mock_raw))) if best_mock_raw > 0 else 0,
          "subject_name": paper.get("subject_name") or "",
        }
    
    resp = templates.TemplateResponse(request=request, name="student/exam_take.html", context={
      "request": request,
      "user": user,
      "paper": paper,
      "paper_json": paper_json,
      "tutor_name": tutor_name,
      "initial_attempt_id": initial_attempt_id,
      "sibling_mocks": sibling_mocks,
      "real_exam_info": real_exam_info,
    })
    _write_continue_cookie(request, resp, user['id'], "exam", {
      "exam_id": exam_id,
      "chapter_id": paper.get('chapter_id'),
    })
    return resp
  finally:
    conn.close()

from fastapi import Form, UploadFile, File
from fastapi.responses import JSONResponse

@router.post("/exams/{exam_id}/start")
async def start_interactive_exam(request: Request, exam_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    paper = student_service.get_exam_paper_full(conn, exam_id)
    if not paper or paper.get('status') != 'published':
        return JSONResponse({"error": "Exam not available"}, status_code=404)
    
    req_body = {}
    try:
      req_body = await request.json()
    except Exception:
      req_body = {}
    is_fresh = bool(
      (isinstance(req_body, dict) and req_body.get("fresh"))
      or str(request.query_params.get("fresh") or "").strip().lower() in ("1", "true", "yes")
    )

    # Create or resume in_progress attempt
    attempt_id = student_service.start_exam_attempt(conn, paper['id'], paper.get('version', 1), user['id'], force_new=is_fresh)
    saved_answers = {} if is_fresh else student_service.get_attempt_saved_answers(conn, attempt_id)
    for _, ans_obj in saved_answers.items():
      v_url = ans_obj.get("explanation_video_url")
      v_type = ans_obj.get("explanation_video_type")
      if v_url and (v_type == "youtube" or extract_youtube_id(v_url)):
        ans_obj["explanation_video_url"] = create_vault_token(v_url)
        ans_obj["explanation_video_type"] = "youtube"
      add_v = ans_obj.get("additional_videos")
      if add_v:
        try:
          ans_obj["additional_videos"] = tokenize_additional_videos(json.loads(add_v) if isinstance(add_v, str) else add_v)
        except Exception:
          ans_obj["additional_videos"] = []
      else:
        ans_obj["additional_videos"] = []
    
    speed_stats = student_service.get_mock_speed_stats(conn, paper['id'], user['id'])
    return JSONResponse({"success": True, "attempt_id": attempt_id, "saved_answers": saved_answers, "speed_stats": speed_stats, "is_fresh": is_fresh})
  finally:
    conn.close()

@router.post("/attempts/{attempt_id}/grade/{question_id}")
async def grade_single_question(request: Request, attempt_id: str, question_id: int, answer: str = Form(""), drawing: Optional[str] = Form(None), exam_id: Optional[str] = Form(None)):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    
    raw_att_id = int(attempt_id) if str(attempt_id).strip().isdigit() else 0
    clean_exam_id = int(exam_id) if (exam_id and str(exam_id).strip().isdigit()) else None
    try:
      resolved_attempt_id = student_service.ensure_serverless_attempt(conn, raw_att_id, user['id'], exam_paper_id=clean_exam_id, question_id=question_id)
    except Exception as att_err:
      print(f"ensure_serverless_attempt notice: {att_err}")
      resolved_attempt_id = raw_att_id or 1
    attempt_id = resolved_attempt_id
    cursor = conn.cursor()
    
    # Handle drawing fallback if text answer is blank
    cleaned_answer = (answer or "").strip()
    if not cleaned_answer and drawing:
        cleaned_answer = "[Handwritten Diagram / Work Attached]"
    
    # We need to find the question details. We can query it directly.
    cursor.execute("SELECT q.id, q.module_id, q.question_text, q.model_answer, COALESCE(q.max_marks, m.mark_value, 1), COALESCE(q.question_type, m.question_type) as question_type, q.explanation_video_url, q.explanation_video_type, q.additional_videos FROM questions q JOIN modules m ON q.module_id = m.id WHERE q.id = ?", (question_id,))
    row = cursor.fetchone()
    if not row:
      return JSONResponse({"success": False, "error": "Question not found"})
    
    q_id, module_id, q_text, model_answer, max_marks, q_type, video_url, video_type, additional_videos = row
    q_type = q_type or 'LONG_ANSWER'
    
    # Fetch previous answer if it exists (in current attempt or most recent earlier attempt by this student)
    prev_row = None
    try:
      cursor.execute("SELECT answer_text, marks_awarded, COALESCE(retry_count, 0) FROM answers WHERE attempt_id = ? AND question_id = ? AND is_latest = 1", (attempt_id, question_id))
      prev_row = cursor.fetchone()
      if not prev_row:
        cursor.execute("""
          SELECT a2.answer_text, a2.marks_awarded, COALESCE(a2.retry_count, 0)
          FROM answers a2
          JOIN attempts att2 ON a2.attempt_id = att2.id
          WHERE att2.student_id = ? AND a2.question_id = ? AND a2.attempt_id != ? AND a2.is_latest = 1
          ORDER BY a2.id DESC LIMIT 1
        """, (user['id'], question_id, attempt_id))
        prev_row = cursor.fetchone()
    except Exception:
      prev_row = None

    previous_answer = prev_row[0] if prev_row else None
    previous_marks = float(prev_row[1] or 0) if prev_row else None
    is_retry = prev_row is not None
    retry_count = (int(prev_row[2] or 0) + 1) if is_retry else 0
    past_attempts = reward_service.get_past_question_attempts(conn, user['id'], question_id, current_attempt_id=attempt_id, request=request)
    if previous_answer and not past_attempts:
      past_attempts = [{"answer": previous_answer, "marks": previous_marks or 0.0}]
    
    # Call Grader (supports multimodal evaluation if drawing is provided) without blocking event loop
    import asyncio
    pref_tutor_lang = user.get("tutor_lang") or ("ml" if request.cookies.get("saxaz_lang") == "ml" else "en")
    result = await asyncio.to_thread(
      grading_service.grade_answer,
      q_text, 
      max_marks, 
      model_answer, 
      cleaned_answer,
      previous_answer,
      q_type,
      drawing,
      pref_tutor_lang,
      past_attempts
    )
    
    new_total_marks = float(result.get('marks_awarded') or 0)
    att_max_marks = float(max_marks or 1)
    try:
      cursor.execute("""
        SELECT a.status, COALESCE(a.total_max_marks, 0), COALESCE(ep.type, 'mock'), COALESCE(a.total_marks_awarded, 0)
        FROM attempts a
        LEFT JOIN exam_papers ep ON a.exam_paper_id = ep.id
        WHERE a.id = ?
      """, (attempt_id,))
      att_meta = cursor.fetchone()
      att_max_marks = float(att_meta[1] or 0) if att_meta else float(max_marks or 1)
      att_exam_type = str(att_meta[2] or 'mock') if att_meta else 'mock'
      is_completed_real = bool(att_meta and att_meta[0] == 'completed' and att_exam_type == 'real')

      if is_completed_real:
        new_total_marks = round(float(att_meta[3] or 0), 2)
      else:
        # Save answer including drawing_url if present
        student_service.save_answer(
          conn, 
          attempt_id, 
          q_id, 
          module_id, 
          cleaned_answer, 
          result['marks_awarded'], 
          max_marks, 
          result['ai_feedback'],
          drawing_url=drawing or ""
        )

        # Keep attempts.total_marks_awarded synced when re-grading questions on a completed mock attempt
        cursor.execute("""
          SELECT COALESCE(SUM(marks_awarded), 0)
          FROM answers
          WHERE attempt_id = ? AND is_latest = 1
        """, (attempt_id,))
        new_total_marks = round(float(cursor.fetchone()[0] or 0), 2)
        if att_meta and att_meta[0] == 'completed' and att_exam_type != 'real':
          cursor.execute("UPDATE attempts SET total_marks_awarded = ? WHERE id = ?", (new_total_marks, attempt_id))
          conn.commit()
    except Exception as save_err:
      print(f"Non-fatal save_answer notice on serverless instance: {save_err}")
    
    safe_video_url = video_url
    safe_video_type = video_type
    if video_url and (video_type == 'youtube' or extract_youtube_id(video_url)):
      safe_video_url = create_vault_token(video_url)
      safe_video_type = 'youtube'
    safe_add_videos = tokenize_additional_videos(json.loads(additional_videos or '[]')) if additional_videos else []

    marks_awarded = float(result['marks_awarded'] or 0)
    max_m = float(max_marks or 1)

    # Multiple choice: tell the page which option is correct so it can colour it green
    correct_option_index = None
    is_objective = str(q_type or '').upper() in ('MCQ', 'ASSERTION_REASON')
    if is_objective:
      try:
        opt_row = cursor.execute("SELECT options FROM questions WHERE id = ?", (question_id,)).fetchone()
        opts = json.loads(_re.sub(r',\s*([\]}])', r'\1', opt_row[0])) if (opt_row and opt_row[0]) else []
        for oi, ov in enumerate(opts if isinstance(opts, list) else []):
          opt_body = _re.sub(r'^(?:[A-Ea-e][.):]|\([A-Ea-e]\))\s*', '', str(ov).strip())
          cand = f"{chr(65 + oi)}. {opt_body}"
          if grading_service._match_mcq_option(cand, model_answer) is True:
            correct_option_index = oi
            break
      except Exception as opt_err:
        print(f"correct option lookup notice: {opt_err}")
    # Written answers: friendly note when the answer is clearly too short for its marks
    length_note = ""
    if not is_objective and not drawing and marks_awarded < max_m:
      length_note = grading_service.answer_length_note(cleaned_answer, max_marks)

    improvement_delta = round(marks_awarded - previous_marks, 2) if previous_marks is not None else 0.0
    improvement_pct = round(((marks_awarded - previous_marks) / max_m) * 100.0, 1) if (previous_marks is not None and max_m > 0) else 0.0

    json_resp = JSONResponse({
      "success": True, 
      "attempt_id": attempt_id,
      "marks": marks_awarded,
      "max_marks": max_m,
      "feedback": result['ai_feedback'],
      "why_wrong": result.get('why_wrong', ''),
      "key_points": result.get('key_points', []),
      "memory_note": result.get('memory_note', ''),
      "spoken_short": result.get('spoken_short', result.get('spoken_1', '')),
      "ideal_answer": result.get('ideal_answer', model_answer),
      "explanation": "",
      "easy_way_text": "",
      "key_concept_text": result.get('key_concept_text', ''),
      "spoken_1": result.get('spoken_short', result.get('spoken_1', '')),
      "spoken_2": "",
      "spoken_3": "",
      "is_correct": marks_awarded >= (max_m * 0.5),
      "correct_option_index": correct_option_index,
      "length_note": length_note,
      "is_retry": is_retry or bool(past_attempts),
      "retry_count": retry_count or len(past_attempts),
      "previous_marks": previous_marks,
      "previous_answer": previous_answer or (past_attempts[-1]["answer"] if past_attempts else ""),
      "improvement_delta": improvement_delta,
      "improvement_pct": improvement_pct,
      "attempt_total_marks": new_total_marks,
      "attempt_max_marks": att_max_marks,
      "explanation_video_url": safe_video_url,
      "explanation_video_type": safe_video_type,
      "additional_videos": safe_add_videos
    })
    reward_service.record_question_attempt_in_wallet(
      conn, user['id'], question_id, cleaned_answer, marks_awarded, request=request, response=json_resp
    )
    return json_resp
  except HTTPException:
    raise
  except Exception as e:
    print(f"grade_single_question error: {e}")
    return JSONResponse({"success": False, "error": f"Unable to grade right now ({e}). Please try again."}, status_code=200)
  finally:
    conn.close()

@router.post("/questions/{question_id}/why")
async def explain_question_answer(request: Request, question_id: int, chosen: str = Form("")):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    row = conn.execute(
      """SELECT q.question_text, q.model_answer, q.options, COALESCE(q.question_type, m.question_type), ep.type
         FROM questions q JOIN modules m ON q.module_id = m.id JOIN exam_papers ep ON m.exam_paper_id = ep.id
         WHERE q.id = ?""", (question_id,)
    ).fetchone()
    if not row:
      return JSONResponse({"success": False, "error": "Question not found"}, status_code=404)
    q_text, model_answer, options_raw, q_type, paper_type = row
    if str(paper_type or '').lower() == 'real' or str(q_type or '').upper() not in ('MCQ', 'ASSERTION_REASON'):
      return JSONResponse({"success": False, "error": "Not available for this question"}, status_code=400)
    try:
      opts = json.loads(_re.sub(r',\s*([\]}])', r'\1', options_raw)) if options_raw else []
    except Exception:
      opts = []
    import asyncio
    lang = user.get("tutor_lang") or "en"
    why = await asyncio.to_thread(grading_service.explain_mcq_answer, q_text, opts, model_answer, chosen, lang)
    return JSONResponse({"success": True, "why": why})
  finally:
    conn.close()


@router.post("/attempts/{attempt_id}/finish")
async def finish_interactive_exam(request: Request, attempt_id: str):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    payload = {}
    try:
      payload = await request.json()
    except Exception:
      payload = {}
    exam_id = payload.get("exam_id") if isinstance(payload, dict) else None
    feedbacks = (payload.get("feedbacks") or {}) if isinstance(payload, dict) else {}

    raw_att_id = int(attempt_id) if str(attempt_id).strip().isdigit() else 0
    attempt_id = student_service.ensure_serverless_attempt(conn, raw_att_id, user['id'], exam_paper_id=exam_id)
    cursor = conn.cursor()
    if feedbacks and isinstance(feedbacks, dict):
      for q_id_str, fb in feedbacks.items():
        try:
          qid = int(q_id_str)
        except Exception:
          continue
        cursor.execute("SELECT id FROM answers WHERE attempt_id = ? AND question_id = ? AND is_latest = 1", (attempt_id, qid))
        if not cursor.fetchone() and isinstance(fb, dict):
          cursor.execute("SELECT module_id, COALESCE(max_marks, 1) FROM questions WHERE id = ?", (qid,))
          q_meta = cursor.fetchone()
          if q_meta:
            student_service.save_answer(
              conn,
              attempt_id,
              qid,
              q_meta[0],
              fb.get("_savedAnswerText") or "",
              float(fb.get("marks") or 0),
              float(fb.get("max_marks") or q_meta[1] or 1),
              fb.get("feedback") or "",
              drawing_url=fb.get("_savedAttachedDrawing") or "",
              notify_xp=False
            )

    time_taken_seconds = payload.get("time_taken_seconds") if isinstance(payload, dict) else None
    student_service.complete_attempt(conn, attempt_id, time_taken_seconds=time_taken_seconds)

    att_info = conn.execute(
      """
      SELECT a.exam_paper_id, a.status, COALESCE(a.total_marks_awarded, 0), COALESCE(a.total_max_marks, 1),
             COALESCE(ep.type, 'mock'), COALESCE(ep.title, 'Mock Exam')
      FROM attempts a
      LEFT JOIN exam_papers ep ON a.exam_paper_id = ep.id
      WHERE a.id = ?
      """,
      (attempt_id,),
    ).fetchone()
    fin_resp = JSONResponse({"success": True, "redirect": f"/student/attempts/{attempt_id}"})
    if att_info and att_info[0]:
      pct_sc = (float(att_info[2]) / max(1.0, float(att_info[3]))) * 100.0
      rw = reward_service.award_exam_completion_coins(
        conn, user['id'], int(att_info[0]), str(att_info[4]), pct_sc, status=str(att_info[1]),
        paper_title=str(att_info[5]), request=request, response=fin_resp
      )
      redir = f"/student/attempts/{attempt_id}"
      if rw.get("coins_added", 0) > 0:
        redir += f"?coins_added={rw['coins_added']}"
      fin_resp.body = json.dumps({"success": True, "redirect": redir, "reward": rw}).encode("utf-8")
      fin_resp.headers["content-length"] = str(len(fin_resp.body))
    return fin_resp
  finally:
    conn.close()

@router.post("/exams/{exam_id}/submit")
async def submit_exam(request: Request, exam_id: int):
  import asyncio
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    paper = student_service.get_exam_paper_full(conn, exam_id)
    if not paper or paper.get('status') != 'published':
        return JSONResponse({"error": "Exam not available"}, status_code=404)
    
    # parse form data
    form_data = await request.form()
    
    # Create attempt
    attempt_id = student_service.start_exam_attempt(conn, paper['id'], paper.get('version', 1), user['id'])
    
    # Grade each answer
    for module in paper['modules']:
      for q in module['questions']:
        answer_key = f"q_{q['id']}"
        student_ans = form_data.get(answer_key, "")
        
        # Call Grader in threadpool
        q_type = q.get('question_type') or module.get('question_type', 'LONG_ANSWER')
        result = await asyncio.to_thread(
          grading_service.grade_answer,
          q['question_text'], 
          q['max_marks'], 
          q['model_answer'], 
          student_ans,
          None,
          q_type
        )
        
        # Save answer
        student_service.save_answer(
          conn, 
          attempt_id, 
          q['id'], 
          module['id'], 
          student_ans, 
          result['marks_awarded'], 
          q['max_marks'], 
          result['ai_feedback']
        )
        
    # Finalize attempt
    student_service.complete_attempt(conn, attempt_id)
    
    # Redirect to results
    return RedirectResponse(url=f"/student/attempts/{attempt_id}", status_code=303)
  finally:
    conn.close()

# --- REAL EXAM ROUTES ---

@router.get("/real-exams/caught", response_class=HTMLResponse)
async def cheat_caught_page(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    raw_ch = request.query_params.get("chapter_id") or ""
    raw_ex = request.query_params.get("exam_id") or ""
    chapter_id = int(raw_ch) if raw_ch.isdigit() else None
    exam_id = int(raw_ex) if raw_ex.isdigit() else None
    cursor = conn.cursor()
    if exam_id and not chapter_id:
      r_ch = cursor.execute("SELECT chapter_id FROM exam_papers WHERE id = ?", (exam_id,)).fetchone()
      if r_ch:
        chapter_id = r_ch[0]
    if chapter_id and not exam_id:
      r_ex = cursor.execute("SELECT id FROM exam_papers WHERE chapter_id = ? AND type = 'real' AND status = 'published' ORDER BY id LIMIT 1", (chapter_id,)).fetchone()
      if r_ex:
        exam_id = r_ex[0]
    if not chapter_id:
      chapter_id = 3
    if not exam_id:
      exam_id = 14
    return templates.TemplateResponse(request=request, name="student/cheat_caught.html", context={
      "request": request,
      "user": user,
      "chapter_id": chapter_id,
      "exam_id": exam_id,
    })
  finally:
    conn.close()

@router.get("/real-exams/{exam_id}/intro", response_class=HTMLResponse)
async def real_exam_intro(request: Request, exam_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    paper = student_service.get_exam_paper_full(conn, exam_id)
    if not paper or paper['status'] != 'published' or paper['type'] != 'real':
      return HTMLResponse("Real Exam not available", status_code=404)

    cursor = conn.cursor()
    if paper.get('chapter_id'):
      ch_row = cursor.execute(
        "SELECT c.name, s.name FROM chapters c LEFT JOIN subjects s ON c.subject_id = s.id WHERE c.id = ?",
        (paper['chapter_id'],)
      ).fetchone()
      if ch_row:
        paper['chapter_name'] = paper.get('chapter_name') or ch_row[0] or ''
        paper['subject_name'] = paper.get('subject_name') or ch_row[1] or ''
      
    total_minutes = int(paper.get('time_limit_minutes') or 60)
    total_seconds = total_minutes * 60
    total_questions = sum([len(m.get('questions', [])) for m in paper.get('modules', [])]) or 12
    
    # Check if max attempts reached again just in case (only count completed attempts)
    max_att = paper.get('max_attempts')
    if max_att is not None:
      cursor.execute("SELECT COUNT(*) FROM attempts WHERE student_id = ? AND exam_paper_id = ? AND status = 'completed'", (user['id'], exam_id))
      if cursor.fetchone()[0] >= max_att:
        return HTMLResponse("Max attempts reached for this exam.", status_code=403)

    is_locked = False
    best_mock_pct = 0
    first_mock_id = None
    required_mock_pct = int(round(float(paper.get('required_mock_percent') or 80)))
    if paper.get('chapter_id'):
      avail_exams = student_service.get_available_exams(conn, paper['chapter_id'], user['id'])
      mock_list = [ex for ex in avail_exams if ex.get('type') == 'mock']
      if mock_list:
        first_mock_id = mock_list[0]['id']
        best_raw = max((float(m.get('highest_score') or 0.0) for m in mock_list), default=0.0)
        best_mock_pct = min(100, int(round(best_raw))) if best_raw > 0 else 0
      real_ex = next((ex for ex in avail_exams if ex['id'] == exam_id), None)
      if real_ex:
        is_locked = bool(real_ex.get('is_locked', False))
        if real_ex.get('required_mock_percent'):
          required_mock_pct = int(round(float(real_ex['required_mock_percent'])))
      # If an in_progress attempt already exists for this student & exam, allow continuing it
      in_prog = cursor.execute(
        "SELECT id FROM attempts WHERE student_id = ? AND exam_paper_id = ? AND status = 'in_progress' LIMIT 1",
        (user['id'], exam_id)
      ).fetchone()
      if in_prog:
        is_locked = False
        
    return templates.TemplateResponse(request=request, name="student/real_exam_intro.html", context={
      "request": request,
      "user": user,
      "paper": paper,
      "total_questions": total_questions,
      "total_minutes": total_minutes,
      "total_seconds": total_seconds,
      "is_locked": is_locked,
      "best_mock_pct": best_mock_pct,
      "first_mock_id": first_mock_id,
      "required_mock_pct": required_mock_pct,
    })
  finally:
    conn.close()

@router.post("/real-exams/{exam_id}/start")
async def start_real_exam(request: Request, exam_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    paper = student_service.get_exam_paper_full(conn, exam_id)
    if not paper or paper.get('status') != 'published':
        return JSONResponse({"error": "Exam not available"}, status_code=404)
    
    cursor = conn.cursor()
    # Resume an existing in_progress attempt if one exists
    cursor.execute(
      "SELECT id FROM attempts WHERE student_id = ? AND exam_paper_id = ? AND status = 'in_progress' ORDER BY id DESC LIMIT 1",
      (user['id'], exam_id)
    )
    existing = cursor.fetchone()
    if existing:
      return RedirectResponse(url=f"/student/real-exams/attempts/{existing[0]}/take", status_code=303)

    # Enforce 80% Mock Exam unlock gate unless an attempt already exists
    if paper.get('chapter_id'):
      avail_exams = student_service.get_available_exams(conn, paper['chapter_id'], user['id'])
      real_ex = next((ex for ex in avail_exams if ex['id'] == exam_id), None)
      if real_ex and real_ex.get('is_locked'):
        return RedirectResponse(url=f"/student/real-exams/{exam_id}/intro?locked=1", status_code=303)

    # Check completed attempts against max_attempts
    max_att = paper.get('max_attempts')
    if max_att is not None:
      cursor.execute("SELECT COUNT(*) FROM attempts WHERE student_id = ? AND exam_paper_id = ? AND status = 'completed'", (user['id'], exam_id))
      if cursor.fetchone()[0] >= max_att:
        return RedirectResponse(url=f"/student/chapters/{paper['chapter_id']}", status_code=303)
        
    # Create attempt
    attempt_id = student_service.start_exam_attempt(conn, paper['id'], paper.get('version', 1), user['id'])
    
    return RedirectResponse(url=f"/student/real-exams/attempts/{attempt_id}/take", status_code=303)
  finally:
    conn.close()

@router.get("/real-exams/attempts/{attempt_id}/take", response_class=HTMLResponse)
async def take_real_exam(request: Request, attempt_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    attempt_id = student_service.ensure_serverless_attempt(conn, attempt_id, user['id'])
    attempt = student_service.get_attempt_full(conn, attempt_id)
    if not attempt or attempt['student_id'] != user['id']:
      return HTMLResponse("Unauthorized", status_code=403)
    if attempt['status'] == 'completed':
      return RedirectResponse(url=f"/student/attempts/{attempt_id}", status_code=303)
      
    paper = student_service.get_exam_paper_full(conn, attempt['exam_paper_id'], seed_id=attempt_id)
    cursor = conn.cursor()
    if paper.get('chapter_id'):
      ch_row = cursor.execute(
        "SELECT c.name, s.name FROM chapters c LEFT JOIN subjects s ON c.subject_id = s.id WHERE c.id = ?",
        (paper['chapter_id'],)
      ).fetchone()
      if ch_row:
        paper['chapter_name'] = paper.get('chapter_name') or ch_row[0] or ''
        paper['subject_name'] = paper.get('subject_name') or ch_row[1] or ''
    
    total_minutes = int(paper.get('time_limit_minutes') or 60)
    total_seconds = total_minutes * 60
    total_questions = sum([len(m['questions']) for m in paper['modules']])

    import json
    paper_json = json.dumps(paper)
    
    return templates.TemplateResponse(request=request, name="student/real_exam.html", context={
      "request": request,
      "user": user,
      "paper": paper,
      "paper_json": paper_json,
      "attempt": attempt,
      "total_seconds": total_seconds,
      "total_questions": total_questions,
      "current_xp": 0,
      "has_purchased": False
    })
  finally:
    conn.close()

@router.post("/real-exams/attempts/{attempt_id}/buy-time")
async def buy_time(request: Request, attempt_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    attempt_id = student_service.ensure_serverless_attempt(conn, attempt_id, user['id'])
    cursor = conn.cursor()
    
    # Ensure attempt belongs to user
    cursor.execute("SELECT student_id, purchased_extra_seconds FROM attempts WHERE id = ?", (attempt_id,))
    row = cursor.fetchone()
    if not row or row[0] != user['id']:
      return JSONResponse({"success": False, "error": "Unauthorized"})
      
    if row[1] > 0:
      return JSONResponse({"success": False, "error": "Already purchased time for this exam."})
      
    # Check XP
    cursor.execute("SELECT total_xp, spent_xp FROM users WHERE id = ?", (user['id'],))
    row = cursor.fetchone()
    total_xp = row[0] if row and row[0] else 0
    spent_xp = row[1] if row and row[1] else 0
    current_xp = max(0, total_xp - spent_xp)
    
    if current_xp < 10:
      return JSONResponse({"success": False, "error": "Not enough XP."})
      
    # Deduct XP and add time
    conn.execute("UPDATE users SET spent_xp = spent_xp + 10 WHERE id = ?", (user['id'],))
    conn.execute("UPDATE attempts SET purchased_extra_seconds = 300 WHERE id = ?", (attempt_id,)) # 5 mins
    conn.commit()
    
    return JSONResponse({"success": True, "added_seconds": 300, "new_xp": current_xp - 10})
  finally:
    conn.close()

@router.post("/real-exams/attempts/{attempt_id}/cheat_fail")
async def cheat_fail(request: Request, attempt_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    attempt_id = student_service.ensure_serverless_attempt(conn, attempt_id, user['id'])
    attempt = student_service.get_attempt_full(conn, attempt_id)
    if not attempt or attempt['student_id'] != user['id'] or attempt['status'] == 'completed':
      return JSONResponse({"success": False, "error": "Unauthorized or already completed"})
      
    # Get max attempts and target_marks to record voided attempt cleanly
    cursor = conn.cursor()
    cursor.execute("SELECT max_attempts, COALESCE(target_marks, 31) FROM exam_papers WHERE id = ?", (attempt['exam_paper_id'],))
    row = cursor.fetchone()
    max_att = row[0] if row and row[0] else 1
    target_m = float(row[1] if row and row[1] else 31)
    
    # Mark as failed due to cheating
    conn.execute(
      "UPDATE attempts SET status = 'completed', completed_at = CURRENT_TIMESTAMP, total_marks_awarded = 0, total_max_marks = ?, tab_switch_count = 99, overall_feedback = ? WHERE id = ?",
      (target_m, "**[EXAM FAILED: CHEATING DETECTED]** Tab switching or window blur detected. This attempt is void.", attempt_id)
    )
    conn.commit()
    return JSONResponse({"success": True})
  finally:
    conn.close()

@router.post("/real-exams/attempts/{attempt_id}/submit")
async def submit_real_exam(request: Request, attempt_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    attempt_id = student_service.ensure_serverless_attempt(conn, attempt_id, user['id'])
    attempt = student_service.get_attempt_full(conn, attempt_id)
    if not attempt or attempt['student_id'] != user['id'] or attempt['status'] == 'completed':
      return HTMLResponse("Unauthorized or already completed", status_code=403)
      
    paper = student_service.get_exam_paper_full(conn, attempt['exam_paper_id'], seed_id=attempt_id)
    
    form_data = await request.form()
    
    # Parse cheated questions array and tab_switch_count
    cheated_questions = form_data.get("cheated_questions", "")
    tab_switches = int(form_data.get("tab_switch_count") or 0)
    
    cheated_q_ids = []
    if cheated_questions:
      try:
        import json
        cheated_q_ids = json.loads(cheated_questions)
      except:
        pass
        
    # Update attempt tab switches
    conn.execute("UPDATE attempts SET tab_switch_count = ? WHERE id = ?", (tab_switches, attempt_id))
    
    penalty_active = tab_switches > 3

    # Prepare all questions for concurrent grading (including previous attempt answers for improvement calculation)
    cursor = conn.cursor()
    questions_to_grade = []
    modules_for_grading = paper.get('mark_modules') or paper['modules']
    for module in modules_for_grading:
      for q in module['questions']:
        answer_key = f"q_{q['id']}"
        student_ans = (form_data.get(answer_key) or "").strip()
        drawing_data = form_data.get(f"drawing_{q['id']}")
        if not student_ans and drawing_data:
          student_ans = "[Handwritten Diagram / Work Attached]"
        elif not student_ans:
          student_ans = "No answer provided"
        
        cursor.execute("""
          SELECT a2.answer_text
          FROM answers a2
          JOIN attempts att2 ON a2.attempt_id = att2.id
          WHERE att2.student_id = ? AND a2.question_id = ? AND a2.attempt_id != ? AND a2.is_latest = 1
          ORDER BY a2.id DESC LIMIT 1
        """, (user['id'], q['id'], attempt_id))
        prev_r = cursor.fetchone()
        prev_ans_text = prev_r[0] if prev_r else None

        questions_to_grade.append({
          "question": q,
          "module": module,
          "student_ans": student_ans,
          "drawing_data": drawing_data,
          "previous_ans": prev_ans_text
        })

    import asyncio

    async def grade_single_item(item):
      q = item["question"]
      mod = item["module"]
      ans_text = item["student_ans"]
      drawing_url = item["drawing_data"]
      prev_ans = item.get("previous_ans")
      
      if penalty_active:
        return {
          "marks": 0,
          "feedback": "**[EXAM FAILED: ANTI-CHEAT VIOLATION]** You exceeded the maximum allowed tab switches or minimized the window too many times. All answers receive 0 marks."
        }
      
      q_type = q.get('question_type') or mod.get('question_type', 'LONG_ANSWER')
      q_max = float(q.get('max_marks') or mod.get('mark_value') or 1)
      res = await asyncio.to_thread(
        grading_service.grade_answer,
        q['question_text'],
        q_max,
        q['model_answer'],
        ans_text,
        prev_ans,
        q_type,
        drawing_url
      )
      return {
        "marks": res.get('marks_awarded', 0),
        "feedback": res.get('ai_feedback', '')
      }

    # Run grading tasks concurrently for speed
    graded_results = await asyncio.gather(*[grade_single_item(item) for item in questions_to_grade])

    # Save all graded answers sequentially into the DB (defer XP notification until all questions are saved)
    for item, grade in zip(questions_to_grade, graded_results):
      q = item["question"]
      mod = item["module"]
      q_max = float(q.get('max_marks') or mod.get('mark_value') or 1)
      mod_id = q.get('original_module_id') or mod['id']
      student_service.save_answer(
        conn,
        attempt_id,
        q['id'],
        mod_id,
        item["student_ans"],
        grade["marks"],
        q_max,
        grade["feedback"],
        drawing_url=item["drawing_data"] or "",
        notify_xp=False
      )
        
    raw_time_taken = form_data.get("time_taken_seconds")
    try:
      time_taken_seconds = int(raw_time_taken) if raw_time_taken is not None else None
    except Exception:
      time_taken_seconds = None
    student_service.recalculate_user_xp(conn, user['id'], notify=True)
    student_service.complete_attempt(conn, attempt_id, time_taken_seconds=time_taken_seconds)

    redir_url = f"/student/attempts/{attempt_id}"
    redir_resp = RedirectResponse(url=redir_url, status_code=303)
    if not penalty_active:
      att_row = conn.execute(
        "SELECT COALESCE(total_marks_awarded, 0), COALESCE(total_max_marks, 1) FROM attempts WHERE id = ?",
        (attempt_id,),
      ).fetchone()
      if att_row:
        pct_real = (float(att_row[0]) / max(1.0, float(att_row[1]))) * 100.0
        rw_real = reward_service.award_exam_completion_coins(
          conn, user['id'], int(paper['id']), "real", pct_real, status="completed",
          paper_title=str(paper.get('title') or 'Official Real Exam'), request=request, response=redir_resp
        )
        if rw_real.get("coins_added", 0) > 0:
          redir_resp.headers["location"] = f"/student/attempts/{attempt_id}?coins_added={rw_real['coins_added']}"
    return redir_resp
  finally:
    conn.close()

@router.get("/attempts", response_class=HTMLResponse)
async def list_attempts(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    attempts = student_service.get_recent_attempts(conn, user['id'], limit=100)
    stats = student_service.get_student_stats(conn, user['id'])
    class_id = user.get('class_id') or 1
    subjects = student_service.get_student_subjects(conn, class_id, user['id'])
    total_videos = sum(int(s.get('total_content') or 0) for s in subjects) if subjects else 4
    watched_videos = sum(int(s.get('completed_content') or 0) for s in subjects) if subjects else 0
    if not subjects:
      completed_ch3 = student_service.get_completed_content_ids(conn, user['id'], 3)
      watched_videos = len(completed_ch3 or [])
    return templates.TemplateResponse(request=request, name="student/attempts_list.html", context={
      "request": request, 
      "user": user,
      "attempts": attempts,
      "stats": stats,
      "subjects": subjects,
      "videos_watched_count": watched_videos,
      "total_videos_count": max(1, total_videos),
    })
  finally:
    conn.close()

@router.get("/attempts/{attempt_id}", response_class=HTMLResponse)
@router.get("/attempts/{attempt_id}/review", response_class=HTMLResponse)
async def view_attempt(request: Request, attempt_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    attempt = student_service.get_attempt_full(conn, attempt_id)
    if not attempt:
      return HTMLResponse("Attempt not found", status_code=404)
    
    # Verify ownership
    if attempt['student_id'] != user['id']:
      return HTMLResponse("Unauthorized", status_code=403)
      
    for ans in attempt.get('answers', []):
      if ans.get('explanation_video_url') and (ans.get('explanation_video_type') == 'youtube' or extract_youtube_id(ans.get('explanation_video_url'))):
        ans['explanation_video_url'] = create_vault_token(ans['explanation_video_url'])
        ans['explanation_video_type'] = 'youtube'

    sibling_mocks = []
    real_exam_info = None
    if attempt.get('chapter_id'):
      avail_exams = student_service.get_available_exams(conn, attempt['chapter_id'], user['id'])
      for ex in avail_exams:
        if ex.get('type') == 'mock':
          hs = ex.get('highest_score')
          sibling_mocks.append({
            "id": ex["id"],
            "title": ex["title"],
            "best_pct": min(100, int(round(float(hs)))) if hs is not None else None,
          })
      real_ex = next((ex for ex in avail_exams if ex.get('type') == 'real'), None)
      best_mock_raw = max((float(ex.get('highest_score') or 0.0) for ex in avail_exams if ex.get('type') == 'mock'), default=0.0)
      if real_ex:
        real_exam_info = {
          "id": real_ex["id"],
          "is_locked": bool(real_ex.get("is_locked", True)),
          "best_mock_pct": min(100, int(round(best_mock_raw))) if best_mock_raw > 0 else 0,
        }

    return templates.TemplateResponse(request=request, name="student/exam_results.html", context={
      "request": request,
      "user": user,
      "attempt": attempt,
      "sibling_mocks": sibling_mocks,
      "real_exam_info": real_exam_info,
    })
  finally:
    conn.close()


class VideoVaultResolveRequest(BaseModel):
  token: str

@router.post("/api/video-vault/resolve", response_class=JSONResponse)
async def resolve_video_vault(req: VideoVaultResolveRequest, request: Request):
  if request.headers.get("X-Requested-With") != "SAXAZ-Vault":
    return JSONResponse({"error": "Forbidden"}, status_code=403)
  conn = get_db_connection()
  try:
    require_auth(request, conn)
  finally:
    conn.close()
  yt_id = resolve_vault_token(req.token)
  if not yt_id:
    return JSONResponse({"error": "Invalid token"}, status_code=404)
  return JSONResponse(encode_client_payload(yt_id))
from fastapi import UploadFile, File, Form
import os
import shutil
import uuid
from security import verify_password, get_password_hash

@router.get("/profile", response_class=HTMLResponse)
async def view_profile(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    class_id = user.get('class_id') or 1
    subjects = student_service.get_student_subjects(conn, class_id, user['id'])
    return templates.TemplateResponse(request=request, name="student/profile.html", context={
      "request": request,
      "user": user,
      "subjects": subjects
    })
  finally:
    conn.close()

@router.post("/profile/update", response_class=HTMLResponse)
async def update_profile(
  request: Request,
  name: str = Form(...),
  email: str = Form(...),
  profile_picture: UploadFile = File(None)
):
  import sqlite3
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    clean_name = (name or "").strip()
    clean_email = (email or "").strip()
    
    pic_url = None
    if profile_picture and profile_picture.filename:
      pic_url = storage.upload_file(profile_picture, "profiles")
      
    try:
      if pic_url:
        conn.execute("UPDATE users SET name = ?, email = ?, profile_picture = ? WHERE id = ?", 
               (clean_name, clean_email, pic_url, user['id']))
      else:
        conn.execute("UPDATE users SET name = ?, email = ? WHERE id = ?", 
               (clean_name, clean_email, user['id']))
      conn.commit()
    except sqlite3.IntegrityError:
      return RedirectResponse(url="/student/profile?error=email_taken", status_code=303)
    
    return RedirectResponse(url="/student/profile?success=profile_updated", status_code=303)
  finally:
    conn.close()

@router.post("/profile/password", response_class=HTMLResponse)
async def update_password(
  request: Request,
  old_password: str = Form(...),
  new_password: str = Form(...),
  confirm_password: Optional[str] = Form(None)
):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    
    if not verify_password(old_password, user['password_hash']):
      return RedirectResponse(url="/student/profile?error=invalid_old_password", status_code=303)

    if (confirm_password is not None and new_password != confirm_password) or len(new_password or "") < 6:
      return RedirectResponse(url="/student/profile?error=password_mismatch", status_code=303)
      
    new_hash = get_password_hash(new_password)
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user['id']))
    conn.commit()
    
    return RedirectResponse(url="/student/profile?success=password_updated", status_code=303)
  finally:
    conn.close()


from fastapi import Form
from fastapi.responses import RedirectResponse

@router.get('/settings', response_class=HTMLResponse)
async def settings(request: Request):
  conn = get_db_connection()
  try:
    require_student(request, conn)
    return RedirectResponse("/student/profile#voice-settings", status_code=302)
  finally:
    conn.close()

@router.post('/settings')
async def save_settings(
  request: Request, 
  tts_voice: str = Form(...), 
  tts_engine: str = Form(default="gemini"), 
  tts_mode: str = Form(default="auto"), 
  tutor_lang: str = Form(default="en"),
  sfx_mode: int = Form(default=1),
  sfx_custom: str = Form(default="{}"),
  cursor_mode: int = Form(default=0),
  cursor_effect: str = Form(default="magic"),
  subject_intro_mode: int = Form(default=0),
  game_prompt_mode: Optional[str] = Form(default=None),
  redirect_to: str = Form(default="")
):
  from security import set_prefs_cookie
  clean_lang = grading_service.normalize_tutor_lang(tutor_lang)
  tts_engine = "gemini"
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    # Game invite preference: always / once / never (keep the current value when the form does not send it)
    gp_mode = (game_prompt_mode or user.get('game_prompt_mode') or 'always').strip().lower()
    if gp_mode not in ('always', 'once', 'never'):
      gp_mode = 'always'
    conn.execute(
      'UPDATE users SET tts_voice = ?, tts_engine = ?, tts_mode = ?, tutor_lang = ?, sfx_mode = ?, sfx_custom = ?, cursor_mode = ?, cursor_effect = ?, subject_intro_mode = ?, game_prompt_mode = ? WHERE id = ?', 
      (tts_voice, tts_engine, tts_mode, clean_lang, sfx_mode, sfx_custom, cursor_mode, cursor_effect, subject_intro_mode, gp_mode, user['id'])
    )
    conn.commit()
    target_url = '/student/profile?success=voice_updated#voice-settings'
    resp = RedirectResponse(url=target_url, status_code=303)
    set_prefs_cookie(resp, user['id'], {
      'tts_voice': tts_voice,
      'tts_engine': tts_engine,
      'tts_mode': tts_mode,
      'tutor_lang': clean_lang,
      'sfx_mode': sfx_mode,
      'sfx_custom': sfx_custom,
      'cursor_mode': cursor_mode,
      'cursor_effect': cursor_effect,
      'subject_intro_mode': subject_intro_mode,
      'game_prompt_mode': gp_mode,
    })
    return resp
  finally:
    conn.close()

import services.search_service as search_service

@router.get("/api/search-suggest", response_class=JSONResponse)
async def search_suggest_api(request: Request, q: str = ""):
    import asyncio
    conn = get_db_connection()
    try:
        user = dict(require_student(request, conn))
    finally:
        conn.close()
    try:
        data = await asyncio.to_thread(search_service.run_instant_suggestions, user, q, 8)
        return JSONResponse(data)
    except Exception as e:
        print(f"Search suggest error: {e}")
        return JSONResponse({"query": q, "suggestions": []})


@router.get("/api/ai-search", response_class=JSONResponse)
async def ai_search_api(request: Request, q: str = ""):
    import asyncio
    conn = get_db_connection()
    try:
        user = dict(require_student(request, conn))
    finally:
        conn.close()
    try:
        data = await asyncio.to_thread(search_service.run_ai_smart_search, user, q)
        return JSONResponse(data)
    except Exception as e:
        print(f"AI search API error: {e}")
        return JSONResponse({"query": q, "results": [], "auto_navigate": False})


@router.get("/search", response_class=HTMLResponse)
async def search_content(request: Request, q: str = "", stay: str = "0"):
    import asyncio
    conn = get_db_connection()
    try:
        user = dict(require_student(request, conn))
    finally:
        conn.close()

    ai_data = await asyncio.to_thread(search_service.run_ai_smart_search, user, q)
    primary_dest = ai_data.get("primary_destination")

    # If the AI determined the user wants to navigate directly to a specific page/section
    # (and the user didn't explicitly request to stay on the search page via ?stay=1), redirect directly!
    if q.strip() and ai_data.get("auto_navigate") and str(stay) != "1" and primary_dest and primary_dest.get("url"):
        return RedirectResponse(url=primary_dest["url"], status_code=303)

    raw_results = ai_data.get("results") or []
    results = []
    for r in raw_results:
        results.append({
            "id": r.get("id", ""),
            "name": r.get("title", ""),
            "title": r.get("title", ""),
            "description": r.get("description", ""),
            "chapter": r.get("category", ""),
            "category": r.get("category", ""),
            "badge": r.get("badge", "Destination"),
            "link": r.get("url", "/student/dashboard"),
            "url": r.get("url", "/student/dashboard"),
        })

    return templates.TemplateResponse(request=request, name="student/search.html", context={
        "request": request,
        "user": user,
        "query": q,
        "results": results,
        "understood_intent": ai_data.get("understood_intent", ""),
        "ai_answer": ai_data.get("ai_answer", ""),
        "primary_destination": primary_dest,
        "tutor_prompt": ai_data.get("tutor_prompt", q),
    })

class AskWhyRequest(BaseModel):
  question_text: str
  student_answer: str
  correct_answer: str
  marks_awarded: Optional[float] = 0.0
  max_marks: Optional[float] = 1.0
  is_retry: Optional[bool] = False

@router.post("/exams/ask_why")
async def ask_why(req: AskWhyRequest, request: Request):
  import asyncio
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
  finally:
    conn.close()
  try:
    from services.grading_service import explain_answer_structured
    pref_tutor_lang = user.get("tutor_lang") or ("ml" if request.cookies.get("saxaz_lang") == "ml" else "en")
    res = await asyncio.to_thread(
      explain_answer_structured,
      req.question_text,
      req.student_answer,
      req.correct_answer,
      float(req.marks_awarded or 0.0),
      float(req.max_marks or 1.0),
      bool(req.is_retry),
      pref_tutor_lang
    )
    return {
      "explanation": res.get("html", ""),
      "easy_way_text": res.get("easy_way_text", ""),
      "key_concept_text": res.get("key_concept_text", ""),
      "spoken_2": res.get("spoken_2", ""),
      "spoken_3": res.get("spoken_3", ""),
      "how_to_improve_text": res.get("how_to_improve_text", "")
    }
  except Exception as e:
    print(f"ask_why error: {e}")
    return {
      "explanation": "Let's review the correct answer above and focus on the key terms.",
      "easy_way_text": "Let's review the correct answer above and focus on the key terms.",
      "key_concept_text": "",
      "how_to_improve_text": ""
    }

from fastapi.responses import StreamingResponse
import services.tutor_service as tutor_service

@router.get("/tutor", response_class=HTMLResponse)
async def ai_tutor_ui(request: Request):
  return RedirectResponse(url="/student/dashboard", status_code=302)


class TutorChatRequest(BaseModel):
    messages: list
    exam_context: Optional[dict] = None


@router.post("/tutor/chat")
async def tutor_chat_stream(req: TutorChatRequest, request: Request):
    conn = get_db_connection()
    log_id = None
    try:
        user = require_student(request, conn)

        # Build context (skip heavy full-platform DB query when inside a live exam unless asking for score comparisons)
        if req.exam_context and isinstance(req.exam_context, dict):
            u_msg_low = str(req.exam_context.get("user_message") or "").lower()
            if "compare" in u_msg_low or "score" in u_msg_low or "history" in u_msg_low:
                context_str = tutor_service.build_context_string(conn, user['id'])
            else:
                context_str = f"Student Name: {user.get('name', 'Student')}"
        else:
            context_str = tutor_service.build_context_string(conn, user['id'])

        # If the student is chatting inside a live Mock Exam, inject the full live screen state into context_str
        if req.exam_context and isinstance(req.exam_context, dict):
            ec = req.exam_context
            live_lines = ["\n\n=== LIVE CURRENT EXAM SCREEN CONTEXT (WHAT THE STUDENT IS LOOKING AT RIGHT NOW) ==="]
            if ec.get("exam_title"):
                live_lines.append(f"Active Exam: {ec.get('exam_title')} (Module: {ec.get('module_name') or 'General'})")
            if ec.get("question_number") or ec.get("total_questions"):
                live_lines.append(f"Current Question Number: Q{ec.get('question_number') or 1} of {ec.get('total_questions') or '?'}")
            if ec.get("question_text"):
                live_lines.append(f"Question Text: {ec.get('question_text')}")
            if ec.get("options"):
                live_lines.append(f"Options: {ec.get('options')}")
            if ec.get("student_answer"):
                live_lines.append(f"Student's Current Answer: {ec.get('student_answer')}")
            if ec.get("has_submitted"):
                live_lines.append(
                    f"Graded Result: Scored {ec.get('marks_awarded', 0)}/{ec.get('max_marks', 1)} marks "
                    f"(Retry Count: {ec.get('retry_count', 0)})"
                )
                if ec.get("ai_feedback"):
                    live_lines.append(f"Grader Feedback: {ec.get('ai_feedback')}")
                if ec.get("ideal_answer"):
                    live_lines.append(f"Ideal Correct Answer: {ec.get('ideal_answer')}")
                if ec.get("easy_way_text"):
                    live_lines.append(f"Easy Way to Remember Shown on Screen: {ec.get('easy_way_text')}")
                if ec.get("key_concept_text"):
                    live_lines.append(f"Key Concept Shown on Screen: {ec.get('key_concept_text')}")
            else:
                live_lines.append("Status: Student has not submitted this question yet (guide them Socratically without giving away the exact answer verbatim!).")
            context_str = context_str + "\n" + "\n".join(live_lines)

        tts_voice = user.get('tts_voice', 'af_bella')
        avatar_map = {
            'af_bella': 'bella',
            'af_sarah': 'sarah',
            'am_adam': 'adam',
            'am_michael': 'michael'
        }
        tutor_name = avatar_map.get(tts_voice, 'bella')

        # Record Mock Exam AI Tutor usage if triggered inside a Mock Exam
        is_mock_exam = bool(req.exam_context and req.exam_context.get("is_mock_exam"))
        if is_mock_exam:
            try:
                exam_paper_id = int(req.exam_context.get("exam_paper_id") or 0)
                question_id = int(req.exam_context.get("question_id") or 0)
                attempt_id_raw = req.exam_context.get("attempt_id")
                attempt_id = int(attempt_id_raw) if attempt_id_raw else None
                question_number = int(req.exam_context.get("question_number") or 1)
                module_name = str(req.exam_context.get("module_name") or "").strip()
                asked_before_submit = 1 if req.exam_context.get("asked_before_submit", 1) else 0
                user_msg = str(req.exam_context.get("user_message") or "").strip()
                if not user_msg and req.messages:
                    last_msg = req.messages[-1]
                    user_msg = str(last_msg.get("content") if isinstance(last_msg, dict) else "").strip()

                if exam_paper_id > 0 and question_id > 0 and user_msg:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO mock_exam_tutor_logs
                          (student_id, exam_paper_id, attempt_id, question_id, question_number, module_name, asked_before_submit, user_message, ai_response)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')
                        """,
                        (user['id'], exam_paper_id, attempt_id, question_id, question_number, module_name, asked_before_submit, user_msg)
                    )
                    log_id = cur.lastrowid
                    conn.commit()
            except Exception as log_err:
                print(f"Error logging mock exam tutor usage: {log_err}")
    finally:
        conn.close()

    saved_tutor_lang = (user.get("tutor_lang") or "").strip().lower()
    if saved_tutor_lang and saved_tutor_lang != "en":
        lang_mode = saved_tutor_lang
    elif request.cookies.get("saxaz_prefs"):
        lang_mode = saved_tutor_lang or "en"
    else:
        lang_mode = "ml" if request.cookies.get("saxaz_lang") == "ml" else "en"

    async def _logged_stream():
        collected = []
        try:
            async for chunk in tutor_service.stream_tutor_response(req.messages, context_str, tutor_id=tutor_name, lang=lang_mode, exam_context=req.exam_context):
                if chunk:
                    collected.append(chunk)
                yield chunk
        except Exception as stream_err:
            print(f"Error in tutor stream wrapper: {stream_err}")
            yield "I'm sorry, I encountered an error while thinking about that."
        finally:
            if collected and log_id:
                import re
                full_reply = "".join(collected)
                clean_reply = re.sub(r'\[\s*(?:e*mot+ions?|draw|quiz|video|topic|exams|history|scroll|retry|question|navigate)\s*:[^\]]*\]', '', full_reply, flags=re.IGNORECASE).strip()
                try:
                    c2 = get_db_connection()
                    try:
                        c2.execute("UPDATE mock_exam_tutor_logs SET ai_response = ? WHERE id = ?", (clean_reply, log_id))
                        c2.commit()
                    finally:
                        c2.close()
                except Exception as e:
                    print(f"Error updating mock tutor log response: {e}")

    # Stream response (after closing DB connection so connection isn't held open during stream)
    return StreamingResponse(
        _logged_stream(),
        media_type="text/plain"
    )

class TutorDrawingRequest(BaseModel):
  prompt: str

@router.post("/tutor/generate-drawing")
async def tutor_generate_drawing(req: TutorDrawingRequest, request: Request):
  import asyncio
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
  finally:
    conn.close()
  try:
    prompt = req.prompt.strip()
    if not prompt:
      return JSONResponse({"title": "Drawing", "steps": []})
    
    drawing_data = await asyncio.to_thread(tutor_service.generate_drawing_steps, prompt)
    return JSONResponse(drawing_data)
  except Exception as e:
    print(f"Generate drawing route error: {e}")
    return JSONResponse({"title": req.prompt, "steps": []}, status_code=500)


@router.post("/tutor/transcribe", response_class=JSONResponse)
async def tutor_transcribe_audio_api(request: Request, audio: UploadFile = File(...)):
  import asyncio
  conn = get_db_connection()
  try:
    require_student(request, conn)
  finally:
    conn.close()
  try:
    audio_bytes = await audio.read()
    filename = audio.filename or "speech.webm"
    content_type = audio.content_type or "audio/webm"
    text = await asyncio.to_thread(
      tutor_service.transcribe_student_audio,
      audio_bytes,
      filename,
      content_type
    )
    return JSONResponse({"text": text})
  except Exception as e:
    print(f"Tutor transcribe route error: {e}")
    return JSONResponse({"text": ""}, status_code=200)


# ==========================================
# DIGI LIBRARY STUDENT ROUTES (Redirected to Exams Hub in v4 Exams-Only Edition)
# ==========================================

@router.get("/digi-library", response_class=HTMLResponse)
async def student_digi_library(request: Request):
  return RedirectResponse(url="/student/exams", status_code=302)


@router.get("/digi-library/books/{book_id}", response_class=HTMLResponse)
async def student_digi_book_view(request: Request, book_id: int):
  return RedirectResponse(url="/student/exams", status_code=302)


@router.get("/digi-library/subjects/{subject_id}", response_class=HTMLResponse)
async def student_digi_subject_view(request: Request, subject_id: int):
  return RedirectResponse(url="/student/exams", status_code=302)


@router.get("/digi-library/banks/{bank_id}", response_class=HTMLResponse)
async def student_digi_bank_take(request: Request, bank_id: int):
  return RedirectResponse(url="/student/exams", status_code=302)


@router.post("/digi-library/study-progress")
async def record_digi_study_progress(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    data = await request.json()
    studied = bool(data.get("studied", True))
    if studied:
      student_service.record_daily_activity(conn, user['id'], problems_delta=1, modules_delta=0, notify_streak=True)
    return JSONResponse({"success": True})
  except Exception as e:
    return JSONResponse({"success": False, "error": str(e)})
  finally:
    conn.close()


@router.post("/digi-library/banks/{bank_id}/start")
async def start_digi_bank_attempt(request: Request, bank_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    paper = student_service.get_digi_bank_for_practice(conn, bank_id)
    if not paper:
      raise HTTPException(status_code=404, detail="Question Bank not found")
    attempt_id = student_service.start_digi_attempt(conn, bank_id, user['id'])
    return JSONResponse({"success": True, "attempt_id": attempt_id})
  finally:
    conn.close()


@router.post("/digi-library/attempts/{attempt_id}/grade/{question_id}")
async def grade_digi_question_attempt(
  request: Request,
  attempt_id: int,
  question_id: int,
  answer: str = Form(""),
  answer_text: str = Form(""),
  drawing: str = Form(None),
  drawing_data: str = Form(None)
):
  import asyncio, json
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    cursor = conn.cursor()
    cursor.execute("SELECT student_id FROM digi_attempts WHERE id = ?", (attempt_id,))
    att_row = cursor.fetchone()
    if not att_row or att_row['student_id'] != user['id']:
      raise HTTPException(status_code=403, detail="Unauthorized attempt access")

    cursor.execute("SELECT * FROM digi_questions WHERE id = ?", (question_id,))
    q_row = cursor.fetchone()
    if not q_row:
      raise HTTPException(status_code=404, detail="Question not found")
    question = dict(q_row)
    q_type = question.get('question_type') or 'CUSTOM'

    # Check if student has a previous answer in this attempt for retry comparison
    cursor.execute(
      "SELECT answer_text FROM digi_answers WHERE attempt_id = ? AND question_id = ? AND is_latest = 1",
      (attempt_id, question_id)
    )
    prev_row = cursor.fetchone()
    previous_answer = prev_row['answer_text'] if prev_row else None
  finally:
    conn.close()

  raw_drawing = drawing or drawing_data
  saved_drawing_url = ""
  if raw_drawing and raw_drawing.startswith("data:image/"):
    try:
      import base64, uuid, os
      from main import MEDIA_DIR
      header, b64_str = raw_drawing.split(",", 1)
      img_bytes = base64.b64decode(b64_str)
      drawings_dir = os.path.join(MEDIA_DIR, "drawings")
      os.makedirs(drawings_dir, exist_ok=True)
      fname = f"digi_drawing_{attempt_id}_{question_id}_{uuid.uuid4().hex[:8]}.png"
      fpath = os.path.join(drawings_dir, fname)
      with open(fpath, "wb") as f:
        f.write(img_bytes)
      saved_drawing_url = f"/media/drawings/{fname}"
    except Exception as e:
      print(f"Error saving digi drawing image: {e}")

  effective_answer = (answer or answer_text or "").strip()
  if not effective_answer and raw_drawing and raw_drawing.startswith("data:image/"):
    effective_answer = "[Handwritten Diagram / Work Attached]"

  grade_result = await asyncio.to_thread(
    grading_service.grade_digi_answer,
    question_text=question['question_text'],
    model_answer=question['model_answer'],
    student_answer=effective_answer,
    previous_answer=previous_answer if previous_answer and previous_answer.strip() else None,
    question_type=q_type,
    drawing_data_url=raw_drawing if (raw_drawing and raw_drawing.startswith("data:image/")) else None
  )

  is_correct = bool(grade_result.get('is_correct', False))
  feedback = grade_result.get('ai_feedback', '')
  ideal_answer = grade_result.get('ideal_answer', question['model_answer'])

  conn2 = get_db_connection()
  try:
    student_service.save_digi_answer(
      conn2,
      attempt_id=attempt_id,
      question_id=question_id,
      answer_text=effective_answer,
      is_correct=is_correct,
      feedback=feedback,
      drawing_url=saved_drawing_url or (raw_drawing if raw_drawing else "")
    )
  finally:
    conn2.close()

  video_url = question.get('explanation_video_url')
  video_type = question.get('explanation_video_type')
  additional_videos = question.get('additional_videos')
  safe_video_url = video_url
  safe_video_type = video_type
  if video_url and (video_type == 'youtube' or extract_youtube_id(video_url)):
    safe_video_url = create_vault_token(video_url)
    safe_video_type = 'youtube'
  safe_add_videos = tokenize_additional_videos(json.loads(additional_videos or '[]')) if additional_videos else []

  return JSONResponse({
    "success": True,
    "is_correct": is_correct,
    "marks": 1 if is_correct else 0,
    "max_marks": 1,
    "feedback": feedback,
    "ideal_answer": ideal_answer,
    "answer_media_url": question.get('answer_media_url') or "",
    "explanation_video_url": safe_video_url,
    "explanation_video_type": safe_video_type,
    "additional_videos": safe_add_videos,
    "drawing_url": saved_drawing_url
  })


@router.post("/digi-library/attempts/{attempt_id}/finish")
async def finish_digi_attempt(request: Request, attempt_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    cursor = conn.cursor()
    cursor.execute("SELECT student_id FROM digi_attempts WHERE id = ?", (attempt_id,))
    att_row = cursor.fetchone()
    if not att_row or att_row['student_id'] != user['id']:
      raise HTTPException(status_code=403, detail="Unauthorized attempt access")
    student_service.complete_digi_attempt(conn, attempt_id)
    return JSONResponse({"success": True, "redirect": f"/student/digi-library/attempts/{attempt_id}"})
  finally:
    conn.close()


@router.get("/digi-library/attempts/{attempt_id}", response_class=HTMLResponse)
async def view_digi_attempt_results(request: Request, attempt_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    attempt = student_service.get_digi_attempt_full(conn, attempt_id)
    if not attempt or attempt['student_id'] != user['id']:
      raise HTTPException(status_code=404, detail="Attempt not found")
    for ans in attempt.get('answers', []):
      if ans.get('explanation_video_url') and (ans.get('explanation_video_type') == 'youtube' or extract_youtube_id(ans.get('explanation_video_url'))):
        ans['explanation_video_url'] = create_vault_token(ans['explanation_video_url'])
        ans['explanation_video_type'] = 'youtube'
      if ans.get('additional_videos'):
        ans['additional_videos'] = tokenize_additional_videos(ans['additional_videos'])
    return templates.TemplateResponse(
      request=request,
      name="student/digi_results.html",
      context={"request": request, "user": user, "attempt": attempt}
    )
  finally:
    conn.close()


# ==============================================================================
# REWARDS WALLET, SHOP & CHAPTER SOCRATIC "LET'S DISCUSS" ENDPOINTS
# ==============================================================================

class MilestoneClaimRequest(BaseModel):
  reward_key: str


@router.post("/rewards/claim", response_class=JSONResponse)
async def claim_reward_milestone(req: MilestoneClaimRequest, request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    resp = JSONResponse({"success": True})
    rw = reward_service.claim_whitelisted_milestone(
      conn, user['id'], req.reward_key, request=request, response=resp
    )
    payload = {"success": "error" not in rw, **rw}
    resp.body = json.dumps(payload).encode("utf-8")
    resp.headers["content-length"] = str(len(resp.body))
    return resp
  finally:
    conn.close()


_DISCUSS_REPLY_CACHE: dict[tuple, dict] = {}


class ChapterDiscussRequest(BaseModel):
  prompt_idx: int = 1
  question: str = ""
  student_reply: str = ""


@router.post("/chapters/{chapter_id}/discuss", response_class=JSONResponse)
async def chapter_lets_discuss(chapter_id: int, req: ChapterDiscussRequest, request: Request):
  import asyncio
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    first_name = (user.get("name") or "Friend").strip().split(" ")[0]
    p_idx = 1 if int(req.prompt_idx or 1) <= 1 else 2
    stu_txt = (req.student_reply or "").strip()[:400]
    q_txt = (req.question or "Why does the human heart have four separate chambers?").strip()[:240]
    pref_lang = grading_service.normalize_tutor_lang(user.get("tutor_lang") or "en")

    is_unsure = (not stu_txt) or len(stu_txt) < 3 or grading_service._is_idk_or_unsure_answer(stu_txt)

    def _run_discuss_llm() -> dict:
      if is_unsure:
        if p_idx == 1:
          return {
            "reply": f"No worries, {first_name}! Picture two pipes — one carrying fresh oxygen-rich blood and one carrying used carbon-dioxide blood. What would happen if those two pipes mixed inside one big room?",
            "emotion": "thinking",
            "heart_mood": "curious",
            "can_claim": False,
          }
        return {
          "reply": f"Totally okay, {first_name}! Think about sprinting in a race — your leg muscles burn way more energy. Why does Lub-Dub the Heart beat faster to help them?",
          "emotion": "thinking",
          "heart_mood": "curious",
          "can_claim": False,
        }

      cache_k = (chapter_id, p_idx, stu_txt.lower(), pref_lang, first_name.lower())
      if cache_k in _DISCUSS_REPLY_CACHE:
        return dict(_DISCUSS_REPLY_CACHE[cache_k])

      if grading_service.client:
        try:
          sys_p = (
            f"You are a warm, playful science tutor chatting one-on-one with {first_name} alongside 'Lub-Dub', a friendly living animated Heart character! "
            "Respond in 2 short, exciting sentences MAX (under 32 words total, NO emojis, NO markdown asterisks). "
            "If the student's thought makes biological sense or shows genuine reasoning, set 'can_claim': true, 'emotion': 'laughing', 'heart_mood': 'excited', and cheer their insight! "
            "If their answer is completely off-topic or nonsense, set 'can_claim': false, 'emotion': 'talking', 'heart_mood': 'curious', and give one playful hint. "
            + grading_service._lang_directive_for_grader(pref_lang)
            + "\nReturn JSON: {'reply': string, 'emotion': 'laughing'|'talking'|'thinking', 'heart_mood': 'excited'|'pumping'|'curious', 'can_claim': boolean}"
          )
          usr_p = f"Discussion Question: {q_txt}\nStudent Answer: {stu_txt}"
          comp = grading_service._chat_json_completion(
            messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
            temperature=0.5,
            max_tokens=160,
          )
          raw = comp.choices[0].message.content.strip()
          raw = _re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
          parsed = json.loads(raw)
          out_disc = {
            "reply": grading_service._strip_emojis(parsed.get("reply") or "").strip() or f"Awesome thinking, {first_name}! Keeping oxygen-rich and oxygen-poor blood separate gives our body super-high energy!",
            "emotion": parsed.get("emotion") if parsed.get("emotion") in ("laughing", "talking", "thinking", "serious") else "laughing",
            "heart_mood": parsed.get("heart_mood") if parsed.get("heart_mood") in ("excited", "pumping", "curious") else "excited",
            "can_claim": bool(parsed.get("can_claim", True)),
          }
          if len(_DISCUSS_REPLY_CACHE) >= 128:
            _DISCUSS_REPLY_CACHE.pop(next(iter(_DISCUSS_REPLY_CACHE)), None)
          _DISCUSS_REPLY_CACHE[cache_k] = dict(out_disc)
          return out_disc
        except Exception:
          pass

      return {
        "reply": f"Spot on, {first_name}! Lub-Dub is pumping happily — keeping oxygen-rich and oxygen-poor blood separate gives warm-blooded humans non-stop energy!",
        "emotion": "laughing",
        "heart_mood": "excited",
        "can_claim": True,
      }

    ai_out = await asyncio.to_thread(_run_discuss_llm)

    resp = JSONResponse({"success": True})
    rw = {"awarded": False, "coins_added": 0, "coin_balance": user.get("coin_balance") or 0}
    if ai_out.get("can_claim"):
      rw = reward_service.claim_whitelisted_milestone(
        conn, user['id'], f"discuss:ch:{chapter_id}:q{p_idx}", request=request, response=resp
      )
    payload = {"success": True, **ai_out, "reward": rw}
    resp.body = json.dumps(payload).encode("utf-8")
    resp.headers["content-length"] = str(len(resp.body))
    return resp
  finally:
    conn.close()


@router.get("/shop", response_class=HTMLResponse)
async def student_rewards_shop(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    wallet = reward_service.get_wallet_details(conn, user['id'])
    user['coin_balance'] = wallet['coin_balance']
    user['coin_inr'] = wallet['inr_value']
    return templates.TemplateResponse(
      request=request,
      name="student/shop.html",
      context={
        "request": request,
        "user": user,
        "wallet": wallet,
      },
    )
  finally:
    conn.close()


@router.post("/shop/redeem")
async def redeem_from_shop(request: Request, item_code: str = Form(...)):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    if "application/json" in (request.headers.get("accept") or "").lower():
      resp = JSONResponse({"success": True})
      out = reward_service.redeem_shop_item(conn, user['id'], item_code, request=request, response=resp)
      resp.body = json.dumps(out).encode("utf-8")
      resp.headers["content-length"] = str(len(resp.body))
      return resp

    redir = RedirectResponse(url="/student/shop", status_code=303)
    out = reward_service.redeem_shop_item(conn, user['id'], item_code, request=request, response=redir)
    if out.get("success"):
      redir.headers["location"] = f"/student/shop?redeemed={out['coupon_code']}"
    else:
      from urllib.parse import quote
      redir.headers["location"] = f"/student/shop?error={quote(out.get('error') or 'Unable to redeem')}"
    return redir
  finally:
    conn.close()



