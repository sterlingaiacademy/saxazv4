import asyncio
from typing import Optional
from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import get_db_connection
from security import require_parent
from services.parent_service import (
  VALID_PARENT_LANGS,
  generate_and_cache_ai_summary,
  get_chapter_milestone_summary,
  get_exam_report,
  get_mock_exam_analytics,
  get_parent_analytics,
  get_parent_lang,
  get_real_exam_analytics,
  resolve_class_display_name,
  update_parent_settings,
)
import services.student_service as student_service

router = APIRouter(
  prefix="/parent",
  tags=["parent"],
)

templates = Jinja2Templates(directory="templates")


def _prepare_user(conn, raw_user) -> dict:
  user = dict(raw_user)
  user["class_name"] = resolve_class_display_name(conn, user)
  return user


@router.api_route("/student-view", methods=["GET", "POST"])
async def switch_to_student_view(request: Request):
  return RedirectResponse(url="/auth/switch-to-student", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/dashboard", response_class=HTMLResponse)
async def parent_dashboard(request: Request):
  conn = get_db_connection()
  try:
    user = _prepare_user(conn, require_parent(request, conn))
    student_id = user["id"]
    class_id = user.get("class_id") or 1
    parent_lang = get_parent_lang(user, override_lang=request.query_params.get("lang"))

    analytics = get_parent_analytics(conn, student_id)
    stats = student_service.get_student_stats(conn, student_id)
    subjects = student_service.get_student_subjects(conn, class_id, student_id)
    chapter_milestones = get_chapter_milestone_summary(conn, student_id, class_id)

    real_scores = [
      ch["best_real_pct"] for ch in chapter_milestones if ch.get("best_real_pct") is not None
    ] + [
      e["score_pct"] for e in analytics.get("real_exams", []) if e.get("score_pct") is not None
    ]
    best_real_pct = max(real_scores) if real_scores else None

    weak_questions = []
    seen_qids = set()
    for ch in chapter_milestones:
      for wq in ch.get("weak_questions", []):
        qid = wq.get("question_id")
        if qid not in seen_qids:
          seen_qids.add(qid)
          weak_questions.append(wq)
          if len(weak_questions) >= 5:
            break
      if len(weak_questions) >= 5:
        break

    summary = await asyncio.to_thread(
      generate_and_cache_ai_summary,
      conn,
      student_id,
      user["name"],
      analytics,
      "main",
      parent_lang,
    )

    return templates.TemplateResponse(
      request=request,
      name="parent/dashboard.html",
      context={
        "request": request,
        "user": user,
        "analytics": analytics,
        "stats": stats,
        "summary": summary,
        "subjects": subjects,
        "chapter_milestones": chapter_milestones,
        "best_real_pct": best_real_pct,
        "weak_questions": weak_questions,
        "parent_lang": parent_lang,
      },
    )
  finally:
    conn.close()


@router.get("/settings", response_class=HTMLResponse)
async def parent_settings(request: Request):
  conn = get_db_connection()
  try:
    user = _prepare_user(conn, require_parent(request, conn))
    parent_lang = get_parent_lang(user)
    return templates.TemplateResponse(
      request=request,
      name="parent/settings.html",
      context={
        "request": request,
        "user": user,
        "parent_lang": parent_lang,
      },
    )
  finally:
    conn.close()


@router.post("/settings")
async def update_settings(
  request: Request,
  parent_locked: int = Form(0),
  parent_pin: str = Form(""),
  parent_tts_voice: str = Form("af_bella"),
  parent_tts_mode: str = Form("manual"),
  tutor_lang: Optional[str] = Form(None),
  parent_tts_engine: Optional[str] = Form(None),
  lang: Optional[str] = Form(None),
):
  conn = get_db_connection()
  try:
    user = _prepare_user(conn, require_parent(request, conn))
    clean_pin = (parent_pin or "").strip()

    chosen_lang = None
    for candidate in (tutor_lang, lang, parent_tts_engine):
      if candidate and str(candidate).strip().lower() in VALID_PARENT_LANGS:
        chosen_lang = str(candidate).strip().lower()
        break
    if not chosen_lang:
      chosen_lang = get_parent_lang(user)

    if parent_locked and (len(clean_pin) != 4 or not clean_pin.isdigit()):
      user["parent_locked"] = 1
      return templates.TemplateResponse(
        request=request,
        name="parent/settings.html",
        context={
          "request": request,
          "user": user,
          "parent_lang": chosen_lang,
          "error": "PIN must be exactly 4 numeric digits.",
        },
      )

    if not parent_locked and not clean_pin:
      existing_pin = str(user.get("parent_pin") or "").strip()
      clean_pin = existing_pin if (len(existing_pin) == 4 and existing_pin.isdigit()) else ""

    update_parent_settings(
      conn,
      user["id"],
      parent_locked,
      clean_pin,
      tts_voice=parent_tts_voice,
      tts_engine=chosen_lang,
      tts_mode=parent_tts_mode,
      tutor_lang=chosen_lang,
    )

    return RedirectResponse(url="/parent/settings?saved=1", status_code=status.HTTP_303_SEE_OTHER)
  finally:
    conn.close()


@router.post("/api/refresh-summary")
async def refresh_ai_summary(request: Request):
  conn = get_db_connection()
  try:
    user = _prepare_user(conn, require_parent(request, conn))
    content_type = (request.headers.get("content-type") or "").lower()
    is_json = "application/json" in content_type

    if is_json:
      data = await request.json()
      summary_type = data.get("type", "main")
      lang_override = data.get("lang")
    else:
      form = await request.form()
      summary_type = form.get("type", "main")
      lang_override = form.get("lang")

    column_name = "parent_summary"
    redirect_path = "/parent/dashboard"
    if summary_type == "mock":
      column_name = "parent_mock_summary"
      redirect_path = "/parent/mock-exams"
    elif summary_type == "real":
      column_name = "parent_real_summary"
      redirect_path = "/parent/real-exams"

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

    parent_lang = get_parent_lang(user, override_lang=lang_override)
    summary = await asyncio.to_thread(
      generate_and_cache_ai_summary,
      conn,
      student_id,
      user["name"],
      analytics,
      summary_type,
      parent_lang,
    )

    if is_json:
      return {"summary": summary}
    return RedirectResponse(url=redirect_path, status_code=status.HTTP_303_SEE_OTHER)
  except Exception as e:
    print("Error refreshing summary:", e)
    return JSONResponse(content={"error": str(e)}, status_code=500)
  finally:
    conn.close()


@router.get("/exams/{attempt_id}/report", response_class=HTMLResponse)
async def view_exam_report(request: Request, attempt_id: int):
  conn = get_db_connection()
  try:
    user = _prepare_user(conn, require_parent(request, conn))
    report = get_exam_report(conn, attempt_id, user["id"])
    if not report:
      raise HTTPException(status_code=404, detail="Exam not found")

    return templates.TemplateResponse(
      request=request,
      name="parent/exam_report.html",
      context={
        "request": request,
        "user": user,
        "report": report,
      },
    )
  finally:
    conn.close()


@router.get("/mock-exams", response_class=HTMLResponse)
async def parent_mock_exams(request: Request):
  conn = get_db_connection()
  try:
    user = _prepare_user(conn, require_parent(request, conn))
    student_id = user["id"]
    class_id = user.get("class_id") or 1
    parent_lang = get_parent_lang(user, override_lang=request.query_params.get("lang"))

    analytics = get_mock_exam_analytics(conn, student_id)
    chapter_milestones = get_chapter_milestone_summary(conn, student_id, class_id)

    return templates.TemplateResponse(
      request=request,
      name="parent/mock_exams.html",
      context={
        "request": request,
        "user": user,
        "analytics": analytics,
        "chapter_milestones": chapter_milestones,
        "parent_lang": parent_lang,
      },
    )
  finally:
    conn.close()


@router.get("/real-exams", response_class=HTMLResponse)
async def parent_real_exams(request: Request):
  conn = get_db_connection()
  try:
    user = _prepare_user(conn, require_parent(request, conn))
    student_id = user["id"]
    class_id = user.get("class_id") or 1
    parent_lang = get_parent_lang(user, override_lang=request.query_params.get("lang"))

    analytics = get_real_exam_analytics(conn, student_id)
    chapter_milestones = get_chapter_milestone_summary(conn, student_id, class_id)

    real_scores = [
      ch["best_real_pct"] for ch in chapter_milestones if ch.get("best_real_pct") is not None
    ] + [
      e["score_pct"] for e in analytics.get("real_exams", []) if e.get("score_pct") is not None
    ]
    best_real_pct = max(real_scores) if real_scores else None

    mock_scores = [
      ch["best_mock_pct"] for ch in chapter_milestones if ch.get("best_mock_pct") is not None
    ]
    best_mock_pct = max(mock_scores) if mock_scores else None
    is_real_unlocked = any(ch.get("is_real_unlocked") for ch in chapter_milestones) or bool(
      (best_mock_pct or 0) >= 80
    )

    return templates.TemplateResponse(
      request=request,
      name="parent/real_exams.html",
      context={
        "request": request,
        "user": user,
        "analytics": analytics,
        "chapter_milestones": chapter_milestones,
        "best_real_pct": best_real_pct,
        "best_mock_pct": best_mock_pct,
        "is_real_unlocked": is_real_unlocked,
        "parent_lang": parent_lang,
      },
    )
  finally:
    conn.close()
