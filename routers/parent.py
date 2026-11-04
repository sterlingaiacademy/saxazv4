from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import get_db_connection
from security import require_parent
from services.parent_service import get_parent_analytics, generate_and_cache_ai_summary, get_exam_report, update_parent_settings, get_mock_exam_analytics, get_real_exam_analytics
import services.student_service as student_service

router = APIRouter(
  prefix="/parent",
  tags=["parent"]
)

templates = Jinja2Templates(directory="templates")

@router.get("/dashboard", response_class=HTMLResponse)
async def parent_dashboard(request: Request):
  import asyncio
  conn = get_db_connection()
  try:
    user = require_parent(request, conn)
    student_id = user["id"]
    
    analytics = get_parent_analytics(conn, student_id)
    stats = student_service.get_student_stats(conn, student_id)
    summary = await asyncio.to_thread(generate_and_cache_ai_summary, conn, student_id, user["name"], analytics)
    class_id = user.get('class_id') or 1
    subjects = student_service.get_student_subjects(conn, class_id, student_id)
    
    return templates.TemplateResponse(request=request, name="parent/dashboard.html", context={
      "request": request,
      "user": user,
      "analytics": analytics,
      "stats": stats,
      "summary": summary,
      "subjects": subjects
    })
  finally:
    conn.close()

@router.get("/settings", response_class=HTMLResponse)
async def parent_settings(request: Request):
  conn = get_db_connection()
  try:
    user = require_parent(request, conn)
    return templates.TemplateResponse(request=request, name="parent/settings.html", context={"request": request, "user": user})
  finally:
    conn.close()

@router.post("/settings")
async def update_settings(
  request: Request,
  parent_locked: int = Form(0),
  parent_pin: str = Form(""),
  sfx_mode: int = Form(default=1),
  sfx_custom: str = Form(default="{}"),
  cursor_mode: int = Form(default=0),
  cursor_effect: str = Form(default="magic"),
  brutality_level: int = Form(default=1),
  parent_tts_voice: str = Form(default="af_bella"),
  parent_tts_engine: str = Form(default="kokoro"),
  parent_tts_mode: str = Form(default="manual")
):
  conn = get_db_connection()
  try:
    user = require_parent(request, conn)
    parent_pin = (parent_pin or "").strip()
    if parent_locked and (len(parent_pin) != 4 or not parent_pin.isdigit()):
      return templates.TemplateResponse(request=request, name="parent/settings.html", context={
        "request": request, 
        "user": user,
        "error": "PIN must be exactly 4 numeric digits."
      })
      
    update_parent_settings(conn, user["id"], parent_locked, parent_pin, sfx_mode, sfx_custom, cursor_mode, cursor_effect, brutality_level, parent_tts_voice, parent_tts_engine, parent_tts_mode)
    
    # update local user object so template renders correct state if needed, or redirect
    return RedirectResponse(url="/parent/settings?success=1", status_code=status.HTTP_302_FOUND)
  finally:
    conn.close()

@router.post("/api/refresh-summary")
async def refresh_ai_summary(request: Request):
  import asyncio
  conn = get_db_connection()
  try:
    user = require_parent(request, conn)
    data = await request.json()
    summary_type = data.get("type", "main")
    
    column_name = "parent_summary"
    if summary_type == "mock":
      column_name = "parent_mock_summary"
    elif summary_type == "real":
      column_name = "parent_real_summary"
      
    cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET {column_name} = NULL WHERE id = ?", (user["id"],))
    conn.commit()
    
    student_id = user["id"]
    if summary_type == "mock":
      analytics = get_mock_exam_analytics(conn, student_id)
    elif summary_type == "real":
      analytics = get_real_exam_analytics(conn, student_id)
    else:
      analytics = get_parent_analytics(conn, student_id)
      
    summary = await asyncio.to_thread(generate_and_cache_ai_summary, conn, student_id, user["name"], analytics, summary_type)
    return {"summary": summary}
  except Exception as e:
    print("Error refreshing summary:", e)
    from fastapi.responses import JSONResponse
    return JSONResponse(content={"error": str(e)}, status_code=500)
  finally:
    conn.close()

@router.get("/exams/{attempt_id}/report", response_class=HTMLResponse)
async def view_exam_report(request: Request, attempt_id: int):
  conn = get_db_connection()
  try:
    user = require_parent(request, conn)
    report = get_exam_report(conn, attempt_id, user["id"])
    
    if not report:
      raise HTTPException(status_code=404, detail="Exam not found")
      
    return templates.TemplateResponse(request=request, name="parent/exam_report.html", context={
      "request": request,
      "user": user,
      "report": report
    })
  finally:
    conn.close()

@router.get("/mock-exams", response_class=HTMLResponse)
async def parent_mock_exams(request: Request):
  import asyncio
  conn = get_db_connection()
  try:
    user = require_parent(request, conn)
    student_id = user["id"]
    
    analytics = get_mock_exam_analytics(conn, student_id)
    summary = await asyncio.to_thread(generate_and_cache_ai_summary, conn, student_id, user["name"], analytics, summary_type="mock")
    
    return templates.TemplateResponse(request=request, name="parent/mock_exams.html", context={
      "request": request,
      "user": user,
      "analytics": analytics,
      "summary": summary
    })
  finally:
    conn.close()

@router.get("/real-exams", response_class=HTMLResponse)
async def parent_real_exams(request: Request):
  import asyncio
  conn = get_db_connection()
  try:
    user = require_parent(request, conn)
    student_id = user["id"]
    
    analytics = get_real_exam_analytics(conn, student_id)
    summary = await asyncio.to_thread(generate_and_cache_ai_summary, conn, student_id, user["name"], analytics, summary_type="real")
    
    return templates.TemplateResponse(request=request, name="parent/real_exams.html", context={
      "request": request,
      "user": user,
      "analytics": analytics,
      "summary": summary
    })
  finally:
    conn.close()
