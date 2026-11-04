from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional

from database import get_db_connection
from security import require_student, require_auth
from services import storage

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

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    class_id = user.get('class_id') or 1 # Fallback to 1 if no class assigned
    subjects = student_service.get_student_subjects(conn, class_id, user['id'])
    for s in subjects:
      s['chapters'] = student_service.get_student_chapters(conn, s['id'], user['id'])
    digi_books = student_service.get_student_digi_books(conn, user['id'])
    
    overall_progress_pct = int(sum(s.get('progress_pct', 0) for s in subjects) / len(subjects)) if subjects else 0
    total_digi_banks = sum(b.get('bank_count', 0) for b in digi_books) if digi_books else 0
    
    recent_attempts = student_service.get_recent_attempts(conn, user['id'], limit=3)
    stats = student_service.get_student_stats(conn, user['id'])
    
    import services.parent_service as parent_service
    analytics = parent_service.get_parent_analytics(conn, user['id'])
    
    return templates.TemplateResponse(request=request, name="student/dashboard.html", context={
      "request": request, 
      "user": user, 
      "subjects": subjects,
      "digi_books": digi_books,
      "overall_progress_pct": overall_progress_pct,
      "total_digi_banks": total_digi_banks,
      "recent_attempts": recent_attempts,
      "stats": stats,
      "analytics": analytics
    })
  finally:
    conn.close()

@router.get("/exams", response_class=HTMLResponse)
@router.get("/subjects", response_class=HTMLResponse)
async def exams_subjects_hub(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    class_id = user.get('class_id') or 1
    subjects = student_service.get_student_subjects(conn, class_id, user['id'])
    for s in subjects:
      s['chapters'] = student_service.get_student_chapters(conn, s['id'], user['id'])
    overall_progress_pct = int(sum(s.get('progress_pct', 0) for s in subjects) / len(subjects)) if subjects else 0
    return templates.TemplateResponse(request=request, name="student/exams_subjects.html", context={
      "request": request,
      "user": user,
      "subjects": subjects,
      "overall_progress_pct": overall_progress_pct
    })
  finally:
    conn.close()

@router.get("/subjects/{subject_id}", response_class=HTMLResponse)
async def subject_view(request: Request, subject_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    
    # Get subject details
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,))
    subject = cursor.fetchone()
    if not subject: return HTMLResponse("Subject not found", 404)
    
    chapters = student_service.get_student_chapters(conn, subject_id, user['id'])
    
    total_chapters = len(chapters)
    completed_chapters = sum(1 for ch in chapters if ch.get('state') == 'completed')
    
    # We can also compute a more granular subject progress based on the average of chapter progress
    if total_chapters > 0:
      progress_pct = int(sum(ch.get('progress_pct', 0) for ch in chapters) / total_chapters)
    else:
      progress_pct = 0
    
    return templates.TemplateResponse(request=request, name="student/subject.html", context={
      "request": request, 
      "user": user, 
      "subject": dict(subject), 
      "chapters": chapters,
      "progress_pct": progress_pct,
      "completed_chapters": completed_chapters
    })
  finally:
    conn.close()

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

    available_exams = student_service.get_available_exams(conn, chapter_id, user['id'])
    completed_content_ids = student_service.get_completed_content_ids(conn, user['id'], chapter_id)
    
    return templates.TemplateResponse(request=request, name="student/chapter.html", context={
      "request": request,
      "user": user,
      "chapter": chapter,
      "available_exams": available_exams,
      "completed_content_ids": completed_content_ids
    })
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
    
    if content_item.get('type') == 'youtube' or extract_youtube_id(content_item.get('media_url') or ''):
      content_item['media_url'] = create_vault_token(content_item.get('media_url') or '')
      content_item['type'] = 'youtube'
    if content_item.get('additional_videos'):
      content_item['additional_videos'] = tokenize_additional_videos(content_item['additional_videos'])

    # Check if already completed
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM content_progress WHERE student_id = ? AND content_item_id = ? AND completed = 1", (user['id'], content_id))
    is_completed = cursor.fetchone() is not None

    # Get prev/next items
    chapter = student_service.get_chapter_with_content(conn, content_item['chapter_id'], user['id'])
    prev_item = None
    next_item = None
    if chapter and 'content' in chapter:
      items = chapter['content']
      for i, item in enumerate(items):
        if item['id'] == content_id:
          if i > 0:
            prev_item = items[i - 1]
          if i < len(items) - 1:
            next_item = items[i + 1]
          break

    return templates.TemplateResponse(request=request, name="student/content_view.html", context={
      "request": request,
      "user": user,
      "item": content_item,
      "is_completed": is_completed,
      "prev_item": prev_item,
      "next_item": next_item
    })
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

@router.post("/content/{content_id}/complete", response_class=HTMLResponse)
async def mark_content_complete(request: Request, content_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    student_service.mark_content_complete(conn, user['id'], content_id)
    # Return the success badge HTML directly to replace the button via HTMX
    return HTMLResponse("""
      <div class="w-10 h-10 rounded-full border-2 border-success bg-success text-white shadow-[0_0_15px_rgba(54,211,153,0.4)] flex items-center justify-center transition-all duration-500 scale-100 animate-in zoom-in" title="Completed">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
        </svg>
      </div>
    """)
  finally:
    conn.close()

from fastapi import Form
from starlette.responses import RedirectResponse
import services.grading_service as grading_service

@router.get("/chapters/{chapter_id}/exams", response_class=HTMLResponse)
async def chapter_exams(request: Request, chapter_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    
    # Get chapter details
    cursor = conn.cursor()
    cursor.execute("SELECT c.*, s.name as subject_name FROM chapters c JOIN subjects s ON c.subject_id = s.id WHERE c.id = ?", (chapter_id,))
    row = cursor.fetchone()
    if not row: return HTMLResponse("Chapter not found", 404)
    chapter = dict(row)
    
    available_exams = student_service.get_available_exams(conn, chapter_id, user['id'])
    
    return templates.TemplateResponse(request=request, name="student/chapter_exams.html", context={
      "request": request,
      "user": user,
      "chapter": chapter,
      "available_exams": available_exams
    })
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
      
    for mod in paper.get('modules', []):
      for q in mod.get('questions', []):
        if q.get('explanation_video_url') and (q.get('explanation_video_type') == 'youtube' or extract_youtube_id(q.get('explanation_video_url'))):
          q['explanation_video_url'] = create_vault_token(q['explanation_video_url'])
          q['explanation_video_type'] = 'youtube'
        if q.get('additional_videos'):
          q['additional_videos'] = tokenize_additional_videos(q['additional_videos'])

    import json
    paper_json = json.dumps(paper)
    
    tts_voice = user.get('tts_voice', 'af_bella')
    avatar_map = {
      'af_bella': 'bella',
      'af_sarah': 'sarah',
      'am_adam': 'adam',
      'am_michael': 'michael'
    }
    tutor_name = avatar_map.get(tts_voice, 'bella')
    
    return templates.TemplateResponse(request=request, name="student/exam_take.html", context={
      "request": request,
      "user": user,
      "paper": paper,
      "paper_json": paper_json,
      "tutor_name": tutor_name
    })
  finally:
    conn.close()

from fastapi import Form
from fastapi.responses import JSONResponse

@router.post("/exams/{exam_id}/start")
async def start_interactive_exam(request: Request, exam_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    paper = student_service.get_exam_paper_full(conn, exam_id)
    if not paper or paper.get('status') != 'published':
        return JSONResponse({"error": "Exam not available"}, status_code=404)
    
    # Create attempt
    attempt_id = student_service.start_exam_attempt(conn, paper['id'], paper.get('version', 1), user['id'])
    
    return JSONResponse({"success": True, "attempt_id": attempt_id})
  finally:
    conn.close()

@router.post("/attempts/{attempt_id}/grade/{question_id}")
async def grade_single_question(request: Request, attempt_id: int, question_id: int, answer: str = Form(""), drawing: Optional[str] = Form(None)):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    
    # Verify attempt ownership
    cursor = conn.cursor()
    cursor.execute("SELECT student_id FROM attempts WHERE id = ?", (attempt_id,))
    own = cursor.fetchone()
    if not own or own[0] != user['id']:
        return JSONResponse({"error": "Unauthorized"}, status_code=403)
    
    # Handle drawing fallback if text answer is blank
    cleaned_answer = (answer or "").strip()
    if not cleaned_answer and drawing:
        cleaned_answer = "[Handwritten Diagram / Work Attached]"
    
    # We need to find the question details. We can query it directly.
    cursor = conn.cursor()
    cursor.execute("SELECT q.id, q.module_id, q.question_text, q.model_answer, m.mark_value, COALESCE(q.question_type, m.question_type) as question_type, q.explanation_video_url, q.explanation_video_type, q.additional_videos FROM questions q JOIN modules m ON q.module_id = m.id WHERE q.id = ?", (question_id,))
    row = cursor.fetchone()
    if not row:
      return JSONResponse({"success": False, "error": "Question not found"})
    
    q_id, module_id, q_text, model_answer, max_marks, q_type, video_url, video_type, additional_videos = row
    q_type = q_type or 'LONG_ANSWER'
    
    # Fetch previous answer if it exists
    cursor.execute("SELECT answer_text FROM answers WHERE attempt_id = ? AND question_id = ? AND is_latest = 1", (attempt_id, question_id))
    prev_row = cursor.fetchone()
    previous_answer = prev_row[0] if prev_row else None
    
    # Call Grader (supports multimodal evaluation if drawing is provided) without blocking event loop
    import asyncio
    result = await asyncio.to_thread(
      grading_service.grade_answer,
      q_text, 
      max_marks, 
      model_answer, 
      cleaned_answer,
      previous_answer,
      q_type,
      drawing
    )
    
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
    
    safe_video_url = video_url
    safe_video_type = video_type
    if video_url and (video_type == 'youtube' or extract_youtube_id(video_url)):
      safe_video_url = create_vault_token(video_url)
      safe_video_type = 'youtube'
    safe_add_videos = tokenize_additional_videos(json.loads(additional_videos or '[]')) if additional_videos else []

    return JSONResponse({
      "success": True, 
      "marks": result['marks_awarded'],
      "max_marks": max_marks,
      "feedback": result['ai_feedback'],
      "ideal_answer": result.get('ideal_answer', model_answer),
      "is_correct": result['marks_awarded'] >= (max_marks * 0.5),
      "explanation_video_url": safe_video_url,
      "explanation_video_type": safe_video_type,
      "additional_videos": safe_add_videos
    })
  finally:
    conn.close()

@router.post("/attempts/{attempt_id}/finish")
async def finish_interactive_exam(request: Request, attempt_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)

    # Verify attempt ownership
    cursor = conn.cursor()
    cursor.execute("SELECT student_id FROM attempts WHERE id = ?", (attempt_id,))
    own = cursor.fetchone()
    if not own or own[0] != user['id']:
        return JSONResponse({"error": "Unauthorized"}, status_code=403)

    student_service.complete_attempt(conn, attempt_id)
    return JSONResponse({"success": True, "redirect": f"/student/attempts/{attempt_id}"})
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
    return templates.TemplateResponse(request=request, name="student/cheat_caught.html", context={
      "request": request,
      "user": user
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
      
    # Calculate total exam time and round it
    total_seconds = sum([m.get('time_limit_seconds', 60) * len(m['questions']) for m in paper['modules']])
    total_seconds = _round_exam_time(total_seconds)
    total_minutes = total_seconds // 60
    
    # Check if max attempts reached again just in case (only count completed attempts)
    max_att = paper.get('max_attempts')
    if max_att is not None:
      cursor = conn.cursor()
      cursor.execute("SELECT COUNT(*) FROM attempts WHERE student_id = ? AND exam_paper_id = ? AND status = 'completed'", (user['id'], exam_id))
      if cursor.fetchone()[0] >= max_att:
        return HTMLResponse("Max attempts reached for this exam.", status_code=403)
        
    return templates.TemplateResponse(request=request, name="student/real_exam_intro.html", context={
      "request": request,
      "user": user,
      "paper": paper,
      "total_minutes": total_minutes,
      "total_seconds": total_seconds
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
    attempt = student_service.get_attempt_full(conn, attempt_id)
    if not attempt or attempt['student_id'] != user['id']:
      return HTMLResponse("Unauthorized", status_code=403)
    if attempt['status'] == 'completed':
      return RedirectResponse(url=f"/student/attempts/{attempt_id}", status_code=303)
      
    paper = student_service.get_exam_paper_full(conn, attempt['exam_paper_id'], seed_id=attempt_id)
    
    total_seconds = sum([m.get('time_limit_seconds', 60) * len(m['questions']) for m in paper['modules']])
    total_seconds = _round_exam_time(total_seconds)
    total_questions = sum([len(m['questions']) for m in paper['modules']])
    
    # Check if already purchased time in this attempt
    cursor = conn.cursor()
    cursor.execute("SELECT purchased_extra_seconds FROM attempts WHERE id = ?", (attempt_id,))
    purchased_time = cursor.fetchone()[0] or 0
    has_purchased = purchased_time > 0
    total_seconds += purchased_time
    
    # Get current XP
    cursor.execute("SELECT total_xp, spent_xp FROM users WHERE id = ?", (user['id'],))
    row = cursor.fetchone()
    total_xp = row[0] if row and row[0] else 0
    spent_xp = row[1] if row and row[1] else 0
    current_xp = max(0, total_xp - spent_xp)

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
      "current_xp": current_xp,
      "has_purchased": has_purchased
    })
  finally:
    conn.close()

@router.post("/real-exams/attempts/{attempt_id}/buy-time")
async def buy_time(request: Request, attempt_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
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
    attempt = student_service.get_attempt_full(conn, attempt_id)
    if not attempt or attempt['student_id'] != user['id'] or attempt['status'] == 'completed':
      return JSONResponse({"success": False, "error": "Unauthorized or already completed"})
      
    # Get max attempts to max out tab_switch_count
    cursor = conn.cursor()
    cursor.execute("SELECT max_attempts FROM exam_papers WHERE id = ?", (attempt['exam_paper_id'],))
    row = cursor.fetchone()
    max_att = row[0] if row and row[0] else 1
    
    # Mark as failed due to cheating
    conn.execute(
      "UPDATE attempts SET status = 'completed', completed_at = CURRENT_TIMESTAMP, total_marks_awarded = 0, total_max_marks = 0, tab_switch_count = 99, overall_feedback = ? WHERE id = ?",
      ("**[EXAM FAILED: CHEATING DETECTED]** Tab switching or window blur detected. This attempt is void.", attempt_id)
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

    # Prepare all questions for concurrent grading
    questions_to_grade = []
    for module in paper['modules']:
      for q in module['questions']:
        answer_key = f"q_{q['id']}"
        student_ans = (form_data.get(answer_key) or "").strip()
        drawing_data = form_data.get(f"drawing_{q['id']}")
        if not student_ans and drawing_data:
          student_ans = "[Handwritten Diagram / Work Attached]"
        elif not student_ans:
          student_ans = "No answer provided"
        
        questions_to_grade.append({
          "question": q,
          "module": module,
          "student_ans": student_ans,
          "drawing_data": drawing_data
        })

    import asyncio

    async def grade_single_item(item):
      q = item["question"]
      mod = item["module"]
      ans_text = item["student_ans"]
      drawing_url = item["drawing_data"]
      
      if penalty_active:
        return {
          "marks": 0,
          "feedback": "**[EXAM FAILED: ANTI-CHEAT VIOLATION]** You exceeded the maximum allowed tab switches or minimized the window too many times. All answers receive 0 marks."
        }
      
      q_type = q.get('question_type') or mod.get('question_type', 'LONG_ANSWER')
      res = await asyncio.to_thread(
        grading_service.grade_answer,
        q['question_text'],
        q['max_marks'],
        q['model_answer'],
        ans_text,
        None,
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
      student_service.save_answer(
        conn,
        attempt_id,
        q['id'],
        mod['id'],
        item["student_ans"],
        grade["marks"],
        q['max_marks'],
        grade["feedback"],
        drawing_url=item["drawing_data"] or "",
        notify_xp=False
      )
        
    student_service.recalculate_user_xp(conn, user['id'], notify=True)
    student_service.complete_attempt(conn, attempt_id)
    return RedirectResponse(url=f"/student/attempts/{attempt_id}", status_code=303)
  finally:
    conn.close()

@router.get("/attempts", response_class=HTMLResponse)
async def list_attempts(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    attempts = student_service.get_recent_attempts(conn, user['id'], limit=100)
    return templates.TemplateResponse(request=request, name="student/attempts_list.html", context={
      "request": request, 
      "user": user,
      "attempts": attempts
    })
  finally:
    conn.close()

@router.get("/attempts/{attempt_id}", response_class=HTMLResponse)
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

    return templates.TemplateResponse(request=request, name="student/exam_results.html", context={
      "request": request,
      "user": user,
      "attempt": attempt
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
    return templates.TemplateResponse(request=request, name="student/profile.html", context={
      "request": request,
      "user": user
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
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    
    pic_url = None
    if profile_picture and profile_picture.filename:
      # Upload using storage service
      pic_url = storage.upload_file(profile_picture, "profiles")
      
    # Update database
    if pic_url:
      conn.execute("UPDATE users SET name = ?, email = ?, profile_picture = ? WHERE id = ?", 
             (name, email, pic_url, user['id']))
    else:
      conn.execute("UPDATE users SET name = ?, email = ? WHERE id = ?", 
             (name, email, user['id']))
    conn.commit()
    
    # We can just redirect back to profile with a query param or set a flash message
    # For simplicity, returning a redirect
    return RedirectResponse(url="/student/profile?success=profile_updated", status_code=303)
  finally:
    conn.close()

@router.post("/profile/password", response_class=HTMLResponse)
async def update_password(
  request: Request,
  old_password: str = Form(...),
  new_password: str = Form(...)
):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    
    # Verify old password
    if not verify_password(old_password, user['password_hash']):
      # For simplicity, returning a redirect with an error param
      return RedirectResponse(url="/student/profile?error=invalid_old_password", status_code=303)
      
    # Hash new password and update
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
    user = require_student(request, conn)
    return templates.TemplateResponse(request=request, name='student/settings.html', context={
      'request': request,
      'user': user
    })
  finally:
    conn.close()

@router.post('/settings')
async def save_settings(
  request: Request, 
  tts_voice: str = Form(...), 
  tts_engine: str = Form(default="kokoro"), 
  tts_mode: str = Form(default="auto"), 
  sfx_mode: int = Form(default=1),
  sfx_custom: str = Form(default="{}"),
  cursor_mode: int = Form(default=0),
  cursor_effect: str = Form(default="magic"),
  subject_intro_mode: int = Form(default=0)
):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    conn.execute(
      'UPDATE users SET tts_voice = ?, tts_engine = ?, tts_mode = ?, sfx_mode = ?, sfx_custom = ?, cursor_mode = ?, cursor_effect = ?, subject_intro_mode = ? WHERE id = ?', 
      (tts_voice, tts_engine, tts_mode, sfx_mode, sfx_custom, cursor_mode, cursor_effect, subject_intro_mode, user['id'])
    )
    conn.commit()
    return RedirectResponse(url='/student/settings?success=1', status_code=303)
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

@router.post("/exams/ask_why")
async def ask_why(req: AskWhyRequest, request: Request):
  import asyncio
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
  finally:
    conn.close()
  try:
    from services.grading_service import explain_answer
    explanation = await asyncio.to_thread(explain_answer, req.question_text, req.student_answer, req.correct_answer)
    return {"explanation": explanation}
  except Exception as e:
    return {"explanation": "An error occurred. Please try again."}

from fastapi.responses import StreamingResponse
import services.tutor_service as tutor_service

@router.get("/tutor", response_class=HTMLResponse)
async def ai_tutor_ui(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    # Determine the user's tutor avatar based on their TTS voice
    tts_voice = user.get('tts_voice', 'af_bella')
    avatar_map = {
      'af_bella': 'bella',
      'af_sarah': 'sarah',
      'am_adam': 'adam',
      'am_michael': 'michael'
    }
    tutor_name = avatar_map.get(tts_voice, 'bella')
    
    return templates.TemplateResponse(request=request, name="student/tutor.html", context={
      "request": request,
      "user": user,
      "tutor_name": tutor_name
    })
  finally:
    conn.close()

class TutorChatRequest(BaseModel):
    messages: list
    exam_context: Optional[dict] = None
    conversation_id: Optional[int] = None
    save_history: Optional[bool] = True


def _make_chat_title(raw_text: str, has_drawing: bool = False) -> str:
    import re
    s = (raw_text or "").strip()
    s = re.sub(r'^(?:can you help explain this question\s*:\s*|can you please\s+|could you please\s+|please\s+)', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s+', ' ', s)
    if not s:
        return "Scratchpad Diagram Review" if has_drawing else "Study Conversation"
    if len(s) > 54:
        cut = s[:54].rsplit(' ', 1)[0]
        s = (cut if len(cut) >= 18 else s[:54]).rstrip('.,;:!?') + "…"
    return s[0].upper() + s[1:] if s else "Study Conversation"


@router.get("/tutor/history", response_class=JSONResponse)
async def list_tutor_conversations(request: Request):
    conn = get_db_connection()
    try:
        user = require_student(request, conn)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT tc.id, tc.title, tc.tutor_name, tc.created_at, tc.updated_at,
                   (SELECT COUNT(*) FROM tutor_messages tm WHERE tm.conversation_id = tc.id) as message_count,
                   (SELECT tm2.content FROM tutor_messages tm2 WHERE tm2.conversation_id = tc.id ORDER BY tm2.id DESC LIMIT 1) as last_message
            FROM tutor_conversations tc
            WHERE tc.student_id = ?
            ORDER BY tc.updated_at DESC, tc.id DESC
            LIMIT 100
            """,
            (user['id'],)
        )
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            if (d.get("message_count") or 0) > 0:
                rows.append(d)
        return JSONResponse({"conversations": rows})
    except Exception as e:
        print(f"Error listing tutor history: {e}")
        return JSONResponse({"conversations": []})
    finally:
        conn.close()


@router.get("/tutor/history/{conversation_id}", response_class=JSONResponse)
async def get_tutor_conversation_detail(conversation_id: int, request: Request):
    conn = get_db_connection()
    try:
        user = require_student(request, conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM tutor_conversations WHERE id = ? AND student_id = ?",
            (conversation_id, user['id'])
        )
        conv = cur.fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        cur.execute(
            "SELECT * FROM tutor_messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,)
        )
        messages = []
        for m in cur.fetchall():
            md = dict(m)
            meta_obj = None
            if md.get("scratchpad_meta"):
                try:
                    parsed_meta = json.loads(md["scratchpad_meta"])
                    if parsed_meta:
                        meta_obj = parsed_meta
                except Exception:
                    meta_obj = None
            messages.append({
                "id": md["id"],
                "role": md["role"],
                "content": md["content"],
                "emotion": md.get("emotion") or "talking",
                "image": md.get("image_url") or None,
                "scratchpadMeta": meta_obj,
                "diagram": md.get("diagram_key") or None,
                "diagramTitle": md.get("diagram_title") or None,
                "created_at": md.get("created_at")
            })
        return JSONResponse({
            "conversation": dict(conv),
            "messages": messages
        })
    finally:
        conn.close()


class RenameTutorChatRequest(BaseModel):
    title: str


@router.post("/tutor/history/{conversation_id}/rename", response_class=JSONResponse)
async def rename_tutor_conversation(conversation_id: int, req: RenameTutorChatRequest, request: Request):
    conn = get_db_connection()
    try:
        user = require_student(request, conn)
        new_title = (req.title or "").strip()[:80]
        if not new_title:
            return JSONResponse({"success": False, "error": "Title cannot be empty"}, status_code=400)
        cur = conn.cursor()
        cur.execute(
            "UPDATE tutor_conversations SET title = ? WHERE id = ? AND student_id = ?",
            (new_title, conversation_id, user['id'])
        )
        conn.commit()
        return JSONResponse({"success": True, "title": new_title})
    finally:
        conn.close()


@router.delete("/tutor/history/{conversation_id}", response_class=JSONResponse)
async def delete_tutor_conversation(conversation_id: int, request: Request):
    conn = get_db_connection()
    try:
        user = require_student(request, conn)
        cur = conn.cursor()
        cur.execute("DELETE FROM tutor_messages WHERE conversation_id IN (SELECT id FROM tutor_conversations WHERE id = ? AND student_id = ?)", (conversation_id, user['id']))
        cur.execute("DELETE FROM tutor_conversations WHERE id = ? AND student_id = ?", (conversation_id, user['id']))
        conn.commit()
        return JSONResponse({"success": True})
    finally:
        conn.close()


@router.post("/tutor/chat")
async def tutor_chat_stream(req: TutorChatRequest, request: Request):
    conn = get_db_connection()
    log_id = None
    active_conv_id = None
    user_had_drawing = False
    try:
        user = require_student(request, conn)

        # Build context
        context_str = tutor_service.build_context_string(conn, user['id'])

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

        # Persist conversation & user message for ChatGPT-style Tutor History
        should_save_history = bool(req.save_history) and not is_mock_exam
        if should_save_history and req.messages:
            try:
                last_msg = req.messages[-1] if isinstance(req.messages[-1], dict) else {}
                u_content = str(last_msg.get("content") or "").strip()
                raw_img = str(last_msg.get("image") or last_msg.get("image_url") or "").strip()
                meta_dict = last_msg.get("scratchpad_meta") or last_msg.get("scratchpadMeta") or {}
                user_had_drawing = bool(raw_img)

                saved_img_url = ""
                if raw_img.startswith("data:image/"):
                    try:
                        import base64, uuid, os
                        from main import MEDIA_DIR
                        _, b64_str = raw_img.split(",", 1)
                        img_bytes = base64.b64decode(b64_str)
                        drawings_dir = os.path.join(MEDIA_DIR, "drawings")
                        os.makedirs(drawings_dir, exist_ok=True)
                        fname = f"tutor_chat_{user['id']}_{uuid.uuid4().hex[:8]}.png"
                        fpath = os.path.join(drawings_dir, fname)
                        with open(fpath, "wb") as f_img:
                            f_img.write(img_bytes)
                        saved_img_url = f"/media/drawings/{fname}"
                    except Exception as img_err:
                        print(f"Error saving tutor chat image: {img_err}")
                elif raw_img.startswith("/media/") or raw_img.startswith("http"):
                    saved_img_url = raw_img

                cur = conn.cursor()
                if req.conversation_id:
                    cur.execute(
                        "SELECT id FROM tutor_conversations WHERE id = ? AND student_id = ?",
                        (req.conversation_id, user['id'])
                    )
                    row_c = cur.fetchone()
                    if row_c:
                        active_conv_id = int(row_c["id"])

                if not active_conv_id:
                    chat_title = _make_chat_title(u_content, has_drawing=bool(saved_img_url))
                    cur.execute(
                        "INSERT INTO tutor_conversations (student_id, tutor_name, title) VALUES (?, ?, ?)",
                        (user['id'], tutor_name, chat_title)
                    )
                    active_conv_id = cur.lastrowid

                cur.execute(
                    """
                    INSERT INTO tutor_messages
                      (conversation_id, role, content, emotion, image_url, scratchpad_meta)
                    VALUES (?, 'user', ?, 'base', ?, ?)
                    """,
                    (active_conv_id, u_content, saved_img_url, json.dumps(meta_dict or {}))
                )
                cur.execute(
                    "UPDATE tutor_conversations SET updated_at = CURRENT_TIMESTAMP, tutor_name = ? WHERE id = ?",
                    (tutor_name, active_conv_id)
                )
                conn.commit()
            except Exception as hist_err:
                print(f"Error saving tutor user message history: {hist_err}")
    finally:
        conn.close()

    async def _logged_stream():
        collected = []
        try:
            async for chunk in tutor_service.stream_tutor_response(req.messages, context_str, tutor_id=tutor_name):
                if chunk:
                    collected.append(chunk)
                yield chunk
        except Exception as stream_err:
            print(f"Error in tutor stream wrapper: {stream_err}")
            yield "I'm sorry, I encountered an error while thinking about that."
        finally:
            if collected:
                import re
                full_reply = "".join(collected)
                clean_reply = re.sub(r'\[\s*(?:emotion|draw)\s*:[^\]]*\]', '', full_reply, flags=re.IGNORECASE).strip()

                if log_id:
                    try:
                        c2 = get_db_connection()
                        try:
                            c2.execute("UPDATE mock_exam_tutor_logs SET ai_response = ? WHERE id = ?", (clean_reply, log_id))
                            c2.commit()
                        finally:
                            c2.close()
                    except Exception as e:
                        print(f"Error updating mock tutor log response: {e}")

                if active_conv_id and clean_reply:
                    try:
                        emo_matches = re.findall(r'\[\s*emotion\s*:\s*([a-zA-Z_]+)\s*\]', full_reply, flags=re.IGNORECASE)
                        final_emo = emo_matches[-1].lower().strip() if emo_matches else "talking"
                        if final_emo not in ("base", "thinking", "talking", "laughing", "serious", "angry"):
                            final_emo = "talking"

                        diag_key = ""
                        diag_title = ""
                        if not user_had_drawing:
                            draw_matches = re.findall(r'\[\s*draw\s*:\s*([^\]]+)\]', full_reply, flags=re.IGNORECASE)
                            if draw_matches:
                                raw_topic = draw_matches[0].strip()
                                diag_key = re.sub(r'[\s-]+', '_', raw_topic.lower())
                                diag_title = raw_topic.replace('_', ' ').title()

                        c3 = get_db_connection()
                        try:
                            c3.execute(
                                """
                                INSERT INTO tutor_messages
                                  (conversation_id, role, content, emotion, diagram_key, diagram_title)
                                VALUES (?, 'assistant', ?, ?, ?, ?)
                                """,
                                (active_conv_id, clean_reply, final_emo, diag_key, diag_title)
                            )
                            c3.execute(
                                "UPDATE tutor_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (active_conv_id,)
                            )
                            c3.commit()
                        finally:
                            c3.close()
                    except Exception as hist_save_err:
                        print(f"Error saving assistant tutor message history: {hist_save_err}")

    headers = {}
    if active_conv_id:
        headers["X-Tutor-Conversation-Id"] = str(active_conv_id)

    # Stream response (after closing DB connection so connection isn't held open during stream)
    return StreamingResponse(
        _logged_stream(),
        media_type="text/plain",
        headers=headers
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


# ==========================================
# DIGI LIBRARY STUDENT ROUTES (Markless)
# ==========================================

@router.get("/digi-library", response_class=HTMLResponse)
async def student_digi_library(request: Request):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    books = student_service.get_student_digi_books(conn, user['id'])
    return templates.TemplateResponse(
      request=request,
      name="student/digi_library.html",
      context={"request": request, "user": user, "books": books}
    )
  finally:
    conn.close()


@router.get("/digi-library/books/{book_id}", response_class=HTMLResponse)
async def student_digi_book_view(request: Request, book_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    book = student_service.get_student_digi_book_details(conn, book_id, user['id'])
    if not book:
      raise HTTPException(status_code=404, detail="Book not found")
    return templates.TemplateResponse(
      request=request,
      name="student/digi_book.html",
      context={"request": request, "user": user, "book": book}
    )
  finally:
    conn.close()


@router.get("/digi-library/subjects/{subject_id}", response_class=HTMLResponse)
async def student_digi_subject_view(request: Request, subject_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    subject = student_service.get_student_digi_subject_details(conn, subject_id, user['id'])
    if not subject:
      raise HTTPException(status_code=404, detail="Subject not found")
    return templates.TemplateResponse(
      request=request,
      name="student/digi_subject.html",
      context={"request": request, "user": user, "subject": subject}
    )
  finally:
    conn.close()


@router.get("/digi-library/banks/{bank_id}", response_class=HTMLResponse)
async def student_digi_bank_take(request: Request, bank_id: int):
  conn = get_db_connection()
  try:
    user = require_student(request, conn)
    paper = student_service.get_digi_bank_for_practice(conn, bank_id)
    if not paper:
      raise HTTPException(status_code=404, detail="Question Bank not found")

    for mod in paper.get('modules', []):
      for q in mod.get('questions', []):
        if q.get('explanation_video_url') and (q.get('explanation_video_type') == 'youtube' or extract_youtube_id(q.get('explanation_video_url'))):
          q['explanation_video_url'] = create_vault_token(q['explanation_video_url'])
          q['explanation_video_type'] = 'youtube'
        if q.get('additional_videos'):
          q['additional_videos'] = tokenize_additional_videos(q['additional_videos'])

    tts_voice = user.get('tts_voice', 'af_bella')
    avatar_map = {
      'af_bella': 'bella',
      'af_sarah': 'sarah',
      'am_adam': 'adam',
      'am_michael': 'michael'
    }
    tutor_name = avatar_map.get(tts_voice, 'bella')

    import json
    return templates.TemplateResponse(
      request=request,
      name="student/digi_chapter_study.html",
      context={
        "request": request,
        "user": user,
        "paper": paper,
        "paper_json": json.dumps(paper),
        "tutor_name": tutor_name,
        "is_digi_library": True
      }
    )
  finally:
    conn.close()


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


