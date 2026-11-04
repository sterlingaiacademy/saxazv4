from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional, List
import uuid
import os
import shutil
import json
import html

from database import get_db_connection
from security import require_admin
import services.admin_service as admin_service
from services import document_parser
from services import storage

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")

import json
import re
from services.video_vault import extract_youtube_id

def parse_json_filter(value):
  if not value: return []
  if isinstance(value, (list, dict)): return value
  try:
    cleaned = re.sub(r',\s*([\]}])', r'\1', str(value))
    return json.loads(cleaned)
  except: return []
templates.env.filters['parse_json'] = parse_json_filter

def _normalize_youtube_url(url: Optional[str]) -> str:
  if not url:
    return ""
  url = url.strip()
  yt_id = extract_youtube_id(url)
  if yt_id:
    return f"https://www.youtube.com/embed/{yt_id}"
  return url

@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    stats = admin_service.get_dashboard_stats(conn)
    return templates.TemplateResponse(request=request, name="admin/dashboard.html", context={"request": request, "user": user, "stats": stats})
  finally:
    conn.close()

@router.get("/curriculum", response_class=HTMLResponse)
async def curriculum_builder(request: Request):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    tree = admin_service.get_full_curriculum_tree(conn)
    return templates.TemplateResponse(request=request, name="admin/curriculum.html", context={"request": request, "user": user, "tree": tree})
  finally:
    conn.close()

# Classes
@router.post("/curriculum/classes", response_class=HTMLResponse)
async def add_class(
  request: Request, 
  name: str = Form(...),
  description: str = Form(None),
  thumbnail: UploadFile = File(None)
):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    thumbnail_url = None
    if thumbnail and thumbnail.filename:
      thumbnail_url = storage.upload_file(thumbnail, "thumbnails")
      
    try:
      class_id = admin_service.create_class(conn, name, description, thumbnail_url)
    except ValueError as e:
      return HTMLResponse(f"<script>alert('{e}');</script>")
      
    display_name = f"Grade {name.strip()}" if name.strip().isdigit() else name.strip()
    new_class = {"id": class_id, "name": display_name, "description": description, "thumbnail_url": thumbnail_url, "subjects": []}
    return templates.TemplateResponse(request=request, name="admin/partials/class_item.html", context={"request": request, "c": new_class})
  finally:
    conn.close()

# Subjects
@router.post("/curriculum/classes/{class_id}/subjects", response_class=HTMLResponse)
async def add_subject(
  request: Request, 
  class_id: int, 
  name: str = Form(...),
  description: str = Form(None),
  thumbnail: UploadFile = File(None)
):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    thumbnail_url = None
    if thumbnail and thumbnail.filename:
      thumbnail_url = storage.upload_file(thumbnail, "thumbnails")
      
    try:
      subject_id = admin_service.create_subject(conn, class_id, name, description, thumbnail_url)
    except ValueError as e:
      return HTMLResponse(f"<script>alert('{e}');</script>")
      
    new_subject = {"id": subject_id, "name": name.strip(), "description": description, "thumbnail_url": thumbnail_url, "chapters": []}
    return templates.TemplateResponse(request=request, name="admin/partials/subject_item.html", context={"request": request, "s": new_subject, "c": {"id": class_id}})
  finally:
    conn.close()

# Chapters
@router.post("/curriculum/subjects/{subject_id}/chapters", response_class=HTMLResponse)
async def add_chapter(
  request: Request, 
  subject_id: int, 
  name: str = Form(...),
  description: str = Form(None),
  thumbnail: UploadFile = File(None)
):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    thumbnail_url = None
    if thumbnail and thumbnail.filename:
      thumbnail_url = storage.upload_file(thumbnail, "thumbnails")
      
    try:
      chapter_id = admin_service.create_chapter(conn, subject_id, name, description, thumbnail_url)
    except ValueError as e:
      return HTMLResponse(f"<script>alert('{e}');</script>")
      
    new_chapter = {"id": chapter_id, "name": name.strip(), "description": description, "thumbnail_url": thumbnail_url, "status": "draft"}
    return templates.TemplateResponse(request=request, name="admin/partials/chapter_item.html", context={"request": request, "ch": new_chapter, "s": {"id": subject_id}})
  finally:
    conn.close()

def _render_node_partial(request: Request, conn, table: str, id: int, error_msg: str = None, start_open: bool = True):
  cursor = conn.cursor()
  cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (id,))
  row = cursor.fetchone()
  if not row:
    raise HTTPException(status_code=404, detail="Entity not found")
  entity = dict(row)
  ctx = {"request": request, "start_open": start_open, "rename_error": error_msg}
  if table == 'classes':
    if 'Grade ' not in entity['name'] and entity['name'].isdigit():
      entity['name'] = f"Grade {entity['name']}"
    entity['subjects'] = admin_service.get_subjects(conn, id)
    for s in entity['subjects']:
      s['chapters'] = admin_service.get_chapters(conn, s['id'])
    ctx["c"] = entity
    resp = templates.TemplateResponse(request=request, name="admin/partials/class_item.html", context=ctx)
  elif table == 'subjects':
    entity['chapters'] = admin_service.get_chapters(conn, id)
    ctx["s"] = entity
    ctx["c"] = {"id": entity["class_id"]}
    resp = templates.TemplateResponse(request=request, name="admin/partials/subject_item.html", context=ctx)
  elif table == 'chapters':
    ctx["ch"] = entity
    ctx["s"] = {"id": entity["subject_id"]}
    resp = templates.TemplateResponse(request=request, name="admin/partials/chapter_item.html", context=ctx)
  else:
    raise HTTPException(status_code=400, detail="Invalid table")

  if error_msg:
    body = resp.body.decode("utf-8") + f"<script>alert({json.dumps(error_msg)});</script>"
    return HTMLResponse(body)
  return resp

# Chapter status toggle
@router.post("/curriculum/chapters/{chapter_id}/status", response_class=HTMLResponse)
async def toggle_chapter_status(request: Request, chapter_id: int, status: str = Form(...)):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    new_status = 'published' if status == 'draft' else 'draft'
    admin_service.update_chapter_status(conn, chapter_id, new_status)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,))
    chapter = dict(cursor.fetchone())
    return templates.TemplateResponse(request=request, name="admin/partials/chapter_item.html", context={"request": request, "ch": chapter, "s": {"id": chapter["subject_id"]}})
  finally:
    conn.close()

@router.delete("/curriculum/content/{item_id}")
async def delete_content(request: Request, item_id: int):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    media_url = admin_service.delete_content_item(conn, item_id)
    # Clean up the actual file from GCS or local storage
    if media_url:
      from services import storage
      storage.delete_file(media_url)
    return HTMLResponse("")
  finally:
    conn.close()

# Chapter Editor View
@router.get("/curriculum/chapters/{chapter_id}", response_class=HTMLResponse)
async def chapter_editor(request: Request, chapter_id: int):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    chapter = admin_service.get_chapter(conn, chapter_id)
    content_items = admin_service.get_content_items(conn, chapter_id)
    exam_papers = admin_service.get_exam_papers(conn, chapter_id)
    mock_total_marks = next((p.get('total_marks', 0) for p in exam_papers if p['type'] == 'mock'), 0)
    return templates.TemplateResponse(request=request, name="admin/chapter_edit.html", context={
      "request": request, 
      "user": user, 
      "chapter": chapter,
      "content_items": content_items,
      "exam_papers": exam_papers,
      "mock_total_marks": mock_total_marks
    })
  finally:
    conn.close()

# Update Chapter Name & Description from Chapter Editor Page
@router.post("/curriculum/chapters/{chapter_id}/update-meta", response_class=HTMLResponse)
async def update_chapter_meta(
  request: Request,
  chapter_id: int,
  name: str = Form(...),
  description: Optional[str] = Form("")
):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    admin_service.update_node_name(conn, 'chapters', chapter_id, name)
    admin_service.update_chapter_description(conn, chapter_id, description or "")
    chapter = admin_service.get_chapter(conn, chapter_id)
    return HTMLResponse(f"""
      <span id="chapter-header-title" hx-swap-oob="true" class="text-primary">{chapter['name']}</span>
      <div class='flex items-center gap-2 text-success text-sm font-bold'
           x-data='{{show:true}}' x-show='show' x-init='setTimeout(()=>show=false,3000)'>
        <svg xmlns='http://www.w3.org/2000/svg' class='h-4 w-4' viewBox='0 0 20 20' fill='currentColor'>
          <path fill-rule='evenodd' d='M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z' clip-rule='evenodd'/>
        </svg>
        Chapter details saved!
      </div>
    """)
  except Exception as e:
    return HTMLResponse(f"<div class='text-error text-sm font-bold'>Error: {html.escape(str(e))}</div>")
  finally:
    conn.close()

# Save Chapter Intro Links (video description + real life application URLs)
@router.post("/curriculum/chapters/{chapter_id}/intro-links", response_class=HTMLResponse)
async def save_chapter_intro_links(
  request: Request,
  chapter_id: int,
  video_description_url: Optional[str] = Form(None),
  real_life_url: Optional[str] = Form(None)
):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    admin_service.update_chapter_links(conn, chapter_id, (video_description_url or '').strip(), (real_life_url or '').strip())
    return HTMLResponse("""
      <div class='flex items-center gap-2 text-success text-sm font-bold' 
           x-data='{show:true}' x-show='show' x-init='setTimeout(()=>show=false,3000)'
           x-transition:leave='transition ease-in duration-300' x-transition:leave-end='opacity-0'>
        <svg xmlns='http://www.w3.org/2000/svg' class='h-4 w-4' viewBox='0 0 20 20' fill='currentColor'>
          <path fill-rule='evenodd' d='M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z' clip-rule='evenodd'/>
        </svg>
        Links saved successfully!
      </div>
    """)
  except Exception as e:
    return HTMLResponse(f"<div class='text-error text-sm font-bold'>Error: {html.escape(str(e))}</div>")
  finally:
    conn.close()

# Chunked Upload Handler
@router.post("/api/upload/chunk")
async def upload_chunk(
    request: Request,
    file_id: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    chunk: UploadFile = File(...)
):
    """Receives a 5MB chunk and appends it to a temporary file on disk."""
    conn = get_db_connection()
    try:
        user = require_admin(request, conn)
        chunk_data = await chunk.read()
        storage.append_chunk(file_id, chunk_data)
        return {"status": "ok", "chunk": chunk_index}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# Content Upload
@router.post("/curriculum/chapters/{chapter_id}/content", response_class=HTMLResponse)
async def upload_content(
  request: Request, 
  chapter_id: int, 
  title: str = Form(...),
  item_type: str = Form(...),
  file: Optional[UploadFile] = File(None),
  youtube_url: Optional[str] = Form(None),
  uploaded_file_id: Optional[str] = Form(None),
  original_filename: Optional[str] = Form(None)
):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    
    media_url = ""
    if item_type == 'youtube' and youtube_url:
      media_url = _normalize_youtube_url(youtube_url)
    elif uploaded_file_id and original_filename:
      # File was uploaded via chunks, assemble it now
      media_url = storage.finalize_chunked_upload(uploaded_file_id, original_filename, "content")
      if not media_url:
        raise Exception("Failed to assemble chunked file.")
    elif file and file.filename:
      # Fallback for standard small file upload
      media_url = storage.upload_file(file, "content")
    
    item_id = admin_service.create_content_item(conn, chapter_id, item_type, title, media_url)
    
    # Return updated content list
    content_items = admin_service.get_content_items(conn, chapter_id)
    return templates.TemplateResponse(request=request, name="admin/partials/content_list.html", context={
      "request": request, 
      "content_items": content_items
    })
  except Exception as e:
    print(f"Error uploading content: {e}")
    conn.rollback()
    return HTMLResponse(f"<div class='text-error font-bold p-4 bg-error/10 rounded-lg'>Error: {html.escape(str(e))}</div>")
  finally:
    conn.close()

# --- EXAM BUILDER ROUTES ---

@router.post("/curriculum/chapters/{chapter_id}/exams", response_class=HTMLResponse)
async def add_exam_paper(
  request: Request, 
  chapter_id: int, 
  title: str = Form(...), 
  type: str = Form(...),
  unlock_threshold_percent: str = Form(None),
  required_mock_percent: str = Form(None),
  max_attempts: str = Form(None),
  use_mock_questions: int = Form(0),
  target_marks: str = Form(None)
):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    
    # Parse fields correctly
    try:
      unlock_val = float(unlock_threshold_percent) if unlock_threshold_percent else None
      req_mock_val = float(required_mock_percent) if required_mock_percent else None
      max_att_val = int(max_attempts) if max_attempts else None
      target_val = int(target_marks) if target_marks else None
    except (ValueError, TypeError):
      return HTMLResponse("<div class='text-error text-sm p-2'>Invalid numeric value in exam fields.</div>", status_code=400)
    
    # Clear fields that don't belong to the selected type
    if type == 'real':
      unlock_val = None
    elif type == 'mock':
      req_mock_val = None
      use_mock_questions = 0
      target_val = None
    
    # Enforce 1 real exam per chapter logic
    if type == 'real':
      cursor = conn.cursor()
      cursor.execute("SELECT COUNT(*) FROM exam_papers WHERE chapter_id = ? AND type = 'real'", (chapter_id,))
      if cursor.fetchone()[0] > 0:
        return HTMLResponse("<div class='text-error text-xs'>A real exam already exists for this chapter.</div>", status_code=400)
        
    paper_id = admin_service.create_exam_paper(conn, chapter_id, type, title, unlock_val, req_mock_val, max_att_val, use_mock_questions, target_val)
    new_paper = {
      "id": paper_id, "title": title, "type": type, "status": "draft", 
      "unlock_threshold_percent": unlock_val, 
      "required_mock_percent": req_mock_val,
      "max_attempts": max_att_val,
      "use_mock_questions": use_mock_questions,
      "target_marks": target_val,
      "modules": [],
      "chapter_id": chapter_id
    }
    return templates.TemplateResponse(request=request, name="admin/partials/exam_item.html", context={"request": request, "paper": new_paper})
  finally:
    conn.close()

@router.post("/curriculum/exams/{exam_id}/status", response_class=HTMLResponse)
async def toggle_exam_status(request: Request, exam_id: int, status: str = Form(...)):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    new_status = 'published' if status == 'draft' else 'draft'
    admin_service.update_exam_status(conn, exam_id, new_status)
    
    paper = admin_service.get_exam_paper_full(conn, exam_id)
    if not paper:
      return HTMLResponse("Exam not found", status_code=404)
    return templates.TemplateResponse(request=request, name="admin/partials/exam_item.html", context={"request": request, "paper": paper})
  finally:
    conn.close()

@router.get("/curriculum/exams/{exam_id}/preview", response_class=HTMLResponse)
async def preview_exam(request: Request, exam_id: int):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    import services.student_service as student_service
    paper = student_service.get_exam_paper_full(conn, exam_id)
    if not paper:
      return HTMLResponse("Exam not found", status_code=404)
    
    return templates.TemplateResponse(request=request, name="admin/exam_preview.html", context={
      "request": request,
      "user": user,
      "paper": paper
    })
  finally:
    conn.close()

@router.post("/curriculum/exams/{exam_id}/modules", response_class=HTMLResponse)
async def add_module(request: Request, exam_id: int, name: str = Form(...), mark_value: int = Form(...), time_limit_seconds: int = Form(60), question_type: str = Form("LONG_ANSWER")):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    module_id = admin_service.create_module(conn, exam_id, name, mark_value, time_limit_seconds, question_type)
    new_module = {"id": module_id, "name": name, "mark_value": mark_value, "time_limit_seconds": time_limit_seconds, "question_type": question_type, "questions": []}
    return templates.TemplateResponse(request=request, name="admin/partials/module_item.html", context={"request": request, "module": new_module})
  finally:
    conn.close()

@router.post("/curriculum/classes/{class_id}/description", response_class=HTMLResponse)
async def update_class_description(request: Request, class_id: int, description: str = Form("")):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    admin_service.update_class_description(conn, class_id, description)
    return _render_node_partial(request, conn, 'classes', class_id, start_open=True)
  finally:
    conn.close()

@router.post("/curriculum/subjects/{subject_id}/description", response_class=HTMLResponse)
async def update_subject_description(request: Request, subject_id: int, description: str = Form("")):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    admin_service.update_subject_description(conn, subject_id, description)
    return _render_node_partial(request, conn, 'subjects', subject_id, start_open=True)
  finally:
    conn.close()

@router.post("/curriculum/chapters/{chapter_id}/description", response_class=HTMLResponse)
async def update_chapter_description(request: Request, chapter_id: int, description: str = Form("")):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    admin_service.update_chapter_description(conn, chapter_id, description)
    return _render_node_partial(request, conn, 'chapters', chapter_id, start_open=True)
  finally:
    conn.close()

@router.post("/curriculum/modules/{module_id}/rename", response_class=HTMLResponse)
async def rename_module(
  request: Request,
  module_id: int,
  name: str = Form(...),
  mark_value: Optional[int] = Form(None),
  time_limit_seconds: Optional[int] = Form(None),
  question_type: Optional[str] = Form(None)
):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    err_msg = None
    try:
      admin_service.update_module_name(conn, module_id, name, mark_value=mark_value, time_limit_seconds=time_limit_seconds, question_type=question_type)
    except ValueError as e:
      err_msg = str(e)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM modules WHERE id = ?", (module_id,))
    row = cursor.fetchone()
    if not row:
      raise HTTPException(status_code=404, detail="Module not found")
    module = dict(row)
    cursor.execute("SELECT * FROM questions WHERE module_id = ? ORDER BY order_index, id", (module_id,))
    module['questions'] = [dict(r) for r in cursor.fetchall()]
    resp = templates.TemplateResponse(request=request, name="admin/partials/module_item.html", context={"request": request, "module": module, "start_open": True, "saved": err_msg is None})
    if err_msg:
      return HTMLResponse(resp.body.decode("utf-8") + f"<script>alert({json.dumps(err_msg)});</script>")
    return resp
  finally:
    conn.close()

@router.post("/curriculum/modules/{module_id}/questions", response_class=HTMLResponse)
async def add_question(
  request: Request, 
  module_id: int, 
  question_text: str = Form(...), 
  model_answer: str = Form(...), 
  max_marks: int = Form(...),
  options: Optional[str] = Form(None),
  media: Optional[UploadFile] = File(None),
  question_type: Optional[str] = Form(None)
):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    
    media_url = None
    if media and media.filename:
      media_url = storage.upload_file(media, "questions")
      
    q_id = admin_service.create_question(conn, module_id, question_text, model_answer, max_marks, options, media_url, question_type)
    new_q = {"id": q_id, "question_text": question_text, "model_answer": model_answer, "max_marks": max_marks, "options": options, "media_url": media_url, "question_type": question_type}
    return templates.TemplateResponse(request=request, name="admin/partials/question_item.html", context={"request": request, "q": new_q})
  finally:
    conn.close()

@router.post("/curriculum/questions/{question_id}/video", response_class=HTMLResponse)
async def attach_question_video(
  request: Request,
  question_id: int,
  video_type: str = Form(...),
  youtube_url: Optional[str] = Form(None),
  video_file: Optional[UploadFile] = File(None)
):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    
    video_url = None
    if video_type == 'youtube' and youtube_url:
      video_url = _normalize_youtube_url(youtube_url)
    elif video_type == 'upload' and video_file and video_file.filename:
      video_url = storage.upload_file(video_file, "videos")
      
    if video_url:
      admin_service.set_question_explanation_video(conn, question_id, video_url, video_type)
      
    updated_q = admin_service.get_question(conn, question_id)
    if not updated_q:
      return HTMLResponse("<div class='text-error'>Question not found</div>")
      
    return templates.TemplateResponse(request=request, name="admin/partials/question_item.html", context={"request": request, "q": updated_q})
  finally:
    conn.close()

@router.delete("/curriculum/questions/{question_id}/video", response_class=HTMLResponse)
async def remove_question_video(request: Request, question_id: int):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    admin_service.set_question_explanation_video(conn, question_id, None, None)
    
    updated_q = admin_service.get_question(conn, question_id)
    if not updated_q:
      return HTMLResponse("<div class='text-error'>Question not found</div>")
      
    return templates.TemplateResponse(request=request, name="admin/partials/question_item.html", context={"request": request, "q": updated_q})
  finally:
    conn.close()


@router.post("/curriculum/modules/{module_id}/upload-questions", response_class=HTMLResponse)
async def upload_questions(request: Request, module_id: int, file: UploadFile = File(...)):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    
    # 1. Extract text from file
    text = await document_parser.extract_text_from_file(file)
    
    # 3. Get module mark_value and question_type
    cursor = conn.cursor()
    cursor.execute("SELECT mark_value, question_type FROM modules WHERE id = ?", (module_id,))
    row = cursor.fetchone()
    mark_value = row['mark_value'] if row else 1
    question_type = row['question_type'] if row and 'question_type' in row.keys() else 'LONG_ANSWER'
    
    # 2. Parse text with AI without blocking the event loop
    import asyncio
    questions = await asyncio.to_thread(document_parser.parse_questions_with_ai, text, question_type)
    
    # 4. Insert each question and render HTML
    html_responses = []
    for q in questions:
      q_text = q.get("question_text", "")
      m_answer = q.get("model_answer", "")
      opts = q.get("options", None)
      
      # If returned a specific type for this question, use it, else fallback to module type
      q_type = q.get("type", question_type)
      
      if q_text and m_answer:
        opts_json = json.dumps(opts) if isinstance(opts, list) else opts
        q_id = admin_service.create_question(conn, module_id, q_text, m_answer, mark_value, opts_json, None, q_type)
        new_q = {"id": q_id, "question_text": q_text, "model_answer": m_answer, "max_marks": mark_value, "options": opts_json, "question_type": q_type}
        html_res = templates.TemplateResponse(request=request, name="admin/partials/question_item.html", context={"request": request, "q": new_q}).body.decode('utf-8')
        html_responses.append(html_res)
        
    if not html_responses:
      return HTMLResponse("<div class='text-error mt-4 font-bold'>Failed to parse any questions from the document. Please ensure it has clear questions and answers.</div>")
      
    return HTMLResponse("".join(html_responses))
  except Exception as e:
    print(f"Error uploading content: {e}")
    conn.rollback()
    return HTMLResponse(f"<div class='text-error font-bold p-4 bg-error/10 rounded-lg'>Error: {html.escape(str(e))}</div>")
  finally:
    conn.close()

@router.delete("/curriculum/exam_node/{table}/{id}")
async def delete_exam_node(request: Request, table: str, id: int):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    admin_service.delete_exam_node(conn, table, id)
    return HTMLResponse("")
  finally:
    conn.close()

# --- ANALYTICS ROUTES ---

@router.get("/analytics", response_class=HTMLResponse)
async def analytics_dashboard(request: Request):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    students = admin_service.get_students_analytics(conn)
    return templates.TemplateResponse(request=request, name="admin/analytics.html", context={
      "request": request,
      "user": user,
      "students": students
    })
  finally:
    conn.close()

@router.get("/analytics/attempts/{attempt_id}", response_class=HTMLResponse)
async def review_attempt(request: Request, attempt_id: int):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    attempt = admin_service.get_attempt_review(conn, attempt_id)
    if not attempt:
      return HTMLResponse("Attempt not found", status_code=404)
    return templates.TemplateResponse(request=request, name="admin/attempt_review.html", context={
      "request": request,
      "user": user,
      "attempt": attempt
    })
  finally:
    conn.close()

@router.get('/settings', response_class=HTMLResponse)
async def settings(request: Request):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    return templates.TemplateResponse(request=request, name='admin/settings.html', context={
      'request': request,
      'user': user
    })
  finally:
    conn.close()

@router.post('/settings')
async def save_settings(
  request: Request, 
  sfx_mode: int = Form(default=1),
  sfx_custom: str = Form(default="{}"),
  cursor_mode: int = Form(default=0),
  cursor_effect: str = Form(default="magic")
):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    conn.execute(
      'UPDATE users SET sfx_mode = ?, sfx_custom = ?, cursor_mode = ?, cursor_effect = ? WHERE id = ?', 
      (sfx_mode, sfx_custom, cursor_mode, cursor_effect, user['id'])
    )
    conn.commit()
    return RedirectResponse(url='/admin/settings?success=1', status_code=303)
  finally:
    conn.close()




@router.post("/curriculum/chapters/{chapter_id}/content/reorder")
async def reorder_content(request: Request, chapter_id: int):
  import json
  body = await request.body()
  try:
      item_ids = json.loads(body)
      if not isinstance(item_ids, list):
          raise ValueError("Expected a list")
  except Exception:
      return JSONResponse({"error": "Invalid request body"}, status_code=400)

  conn = get_db_connection()
  try:
    require_admin(request, conn)
    cursor = conn.cursor()
    for index, item_id in enumerate(item_ids):
      cursor.execute("UPDATE content_items SET order_index = ? WHERE id = ? AND chapter_id = ?", (index, int(item_id), chapter_id))
    conn.commit()
    return {"status": "success"}
  finally:
    conn.close()

@router.post("/curriculum/content-items/{item_id}/edit", response_class=HTMLResponse)
async def edit_content_item(
  request: Request,
  item_id: int,
  title: str = Form(...),
  item_type: str = Form(...),
  youtube_url: Optional[str] = Form(None),
  file: Optional[UploadFile] = File(None),
  uploaded_file_id: Optional[str] = Form(None),
  original_filename: Optional[str] = Form(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    
    cursor = conn.cursor()
    cursor.execute("SELECT media_url FROM content_items WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    if not row:
        return HTMLResponse("Item not found", status_code=404)
        
    media_url = row['media_url']
    
    if item_type == 'youtube' and youtube_url and youtube_url.strip():
      media_url = _normalize_youtube_url(youtube_url)
    elif item_type != 'youtube' and uploaded_file_id and original_filename:
      assembled_url = storage.finalize_chunked_upload(uploaded_file_id, original_filename, "content")
      if assembled_url:
        media_url = assembled_url
    elif item_type != 'youtube' and file and file.filename:
      media_url = storage.upload_file(file, "content")
      
    cursor.execute(
      "UPDATE content_items SET title = ?, type = ?, media_url = ? WHERE id = ?",
      (title.strip(), item_type, media_url, item_id)
    )
    conn.commit()
    
    cursor.execute("SELECT * FROM content_items WHERE id = ?", (item_id,))
    item_row = cursor.fetchone()
    item = dict(item_row) if item_row else {}
    
    return templates.TemplateResponse(request=request, name="admin/partials/content_item_partial.html", context={"request": request, "item": item, "saved": True})
  finally:
    conn.close()


@router.post("/curriculum/content-items/{item_id}/alternative-videos", response_class=HTMLResponse)
async def add_alt_video_content(
  request: Request,
  item_id: int,
  category: str = Form(...),
  label: str = Form(...),
  video_type: str = Form(...),
  youtube_url: Optional[str] = Form(None),
  file: Optional[UploadFile] = File(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    url = ""
    if video_type == "youtube" and youtube_url:
      url = _normalize_youtube_url(youtube_url)
    elif video_type == "upload" and file and file.filename:
      url = storage.upload_file(file, "videos")
      
    if url:
      admin_service.add_video_attachment(conn, "content_item", item_id, category, label.strip(), url, video_type)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM content_items WHERE id = ?", (item_id,))
    item_row = cursor.fetchone()
    item = dict(item_row) if item_row else {}
    return templates.TemplateResponse(request=request, name="admin/partials/content_item_partial.html", context={"request": request, "item": item})
  finally:
    conn.close()

@router.delete("/curriculum/content-items/{item_id}/alternative-videos/{video_id}", response_class=HTMLResponse)
async def delete_alt_video_content(request: Request, item_id: int, video_id: str):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    admin_service.delete_additional_video(conn, "content_item", item_id, video_id)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM content_items WHERE id = ?", (item_id,))
    item_row = cursor.fetchone()
    item = dict(item_row) if item_row else {}
    return templates.TemplateResponse(request=request, name="admin/partials/content_item_partial.html", context={"request": request, "item": item})
  finally:
    conn.close()

@router.post("/curriculum/questions/{question_id}/alternative-videos", response_class=HTMLResponse)
async def add_alt_video_question(
  request: Request,
  question_id: int,
  category: str = Form(...),
  label: str = Form(...),
  video_type: str = Form(...),
  youtube_url: Optional[str] = Form(None),
  file: Optional[UploadFile] = File(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    url = ""
    if video_type == "youtube" and youtube_url:
      url = _normalize_youtube_url(youtube_url)
    elif video_type == "upload" and file and file.filename:
      url = storage.upload_file(file, "videos")
      
    if url:
      admin_service.add_video_attachment(conn, "question", question_id, category, label.strip(), url, video_type)
    q = admin_service.get_question(conn, question_id)
    return templates.TemplateResponse(request=request, name="admin/partials/question_item.html", context={"request": request, "q": q})
  finally:
    conn.close()

@router.delete("/curriculum/questions/{question_id}/alternative-videos/{video_id}", response_class=HTMLResponse)
async def delete_alt_video_question(request: Request, question_id: int, video_id: str):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    admin_service.delete_additional_video(conn, "question", question_id, video_id)
    q = admin_service.get_question(conn, question_id)
    return templates.TemplateResponse(request=request, name="admin/partials/question_item.html", context={"request": request, "q": q})
  finally:
    conn.close()


@router.post("/curriculum/exams/{exam_id}/rename", response_class=HTMLResponse)
async def rename_exam(
    request: Request,
    exam_id: int,
    title: str = Form(...),
    unlock_threshold_percent: Optional[str] = Form(None),
    required_mock_percent: Optional[str] = Form(None),
    max_attempts: Optional[str] = Form(None),
    use_mock_questions: Optional[int] = Form(0),
    target_marks: Optional[str] = Form(None),
    update_settings: Optional[str] = Form(None)
):
    conn = get_db_connection()
    try:
        require_admin(request, conn)
        utp = float(unlock_threshold_percent) if unlock_threshold_percent and unlock_threshold_percent.strip() != '' else None
        rmp = float(required_mock_percent) if required_mock_percent and required_mock_percent.strip() != '' else None
        ma = int(max_attempts) if max_attempts and max_attempts.strip() != '' else None
        tm = int(target_marks) if target_marks and target_marks.strip() != '' else None
        do_settings = update_settings == "1"
        try:
            admin_service.update_exam_title(
                conn,
                exam_id,
                title,
                unlock_threshold_percent=utp,
                required_mock_percent=rmp,
                max_attempts=ma,
                use_mock_questions=use_mock_questions or 0,
                target_marks=tm,
                update_settings=do_settings
            )
        except ValueError as e:
            paper = admin_service.get_exam_paper_full(conn, exam_id)
            if not paper:
                return HTMLResponse("Exam not found", status_code=404)
            return templates.TemplateResponse(request=request, name="admin/partials/exam_item.html", context={"request": request, "paper": paper, "rename_error": str(e), "start_open": True})
        paper = admin_service.get_exam_paper_full(conn, exam_id)
        if not paper:
            return HTMLResponse("Exam not found", status_code=404)
        return templates.TemplateResponse(request=request, name="admin/partials/exam_item.html", context={"request": request, "paper": paper, "start_open": True, "saved": True})
    finally:
        conn.close()


@router.post("/curriculum/questions/{question_id}/edit", response_class=HTMLResponse)
async def edit_question(
    request: Request,
    question_id: int,
    question_text: str = Form(...),
    model_answer: str = Form(""),
    options: str = Form(""),
    question_type: Optional[str] = Form(None),
    max_marks: Optional[str] = Form(None),
    question_image: Optional[UploadFile] = File(None),
    answer_image: Optional[UploadFile] = File(None),
    question_image_url: Optional[str] = Form(None),
    answer_image_url: Optional[str] = Form(None),
    remove_question_image: Optional[str] = Form(None),
    remove_answer_image: Optional[str] = Form(None)
):
    conn = get_db_connection()
    try:
        require_admin(request, conn)
        q = admin_service.get_question(conn, question_id)
        if not q:
            return HTMLResponse("Question not found", status_code=404)
        
        media_url = q.get('media_url') or ""
        if remove_question_image == "1":
            media_url = ""
        elif question_image and question_image.filename:
            media_url = storage.upload_file(question_image, "media")
        elif question_image_url is not None:
            media_url = question_image_url.strip()

        answer_media_url = q.get('answer_media_url') or ""
        if remove_answer_image == "1":
            answer_media_url = ""
        elif answer_image and answer_image.filename:
            answer_media_url = storage.upload_file(answer_image, "media")
        elif answer_image_url is not None:
            answer_media_url = answer_image_url.strip()

        parsed_max_marks = int(max_marks) if max_marks and max_marks.strip() != '' else None

        admin_service.update_question_details(
            conn, question_id, question_text, model_answer, options,
            media_url=media_url, answer_media_url=answer_media_url,
            question_type=question_type, max_marks=parsed_max_marks
        )
        updated_q = admin_service.get_question(conn, question_id)
        return templates.TemplateResponse(request=request, name="admin/partials/question_item.html", context={"request": request, "q": updated_q, "saved": True})
    finally:
        conn.close()


# Generic Rename (placed after specific module/exam rename routes so {table} does not shadow them)
@router.post("/curriculum/{table}/{id}/rename", response_class=HTMLResponse)
async def rename_node(request: Request, table: str, id: int, name: str = Form(...)):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    if table not in ['classes', 'subjects', 'chapters']:
      raise HTTPException(status_code=400, detail="Invalid table")
      
    admin_service.update_node_name(conn, table, id, name)
    return _render_node_partial(request, conn, table, id, start_open=True)
  except ValueError as e:
    return _render_node_partial(request, conn, table, id, error_msg=str(e), start_open=True)
  finally:
    conn.close()


# Generic Thumbnail Update
@router.post("/curriculum/{table}/{id}/thumbnail", response_class=HTMLResponse)
async def update_thumbnail(request: Request, table: str, id: int, thumbnail: Optional[UploadFile] = File(None)):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    if table not in ['classes', 'subjects', 'chapters']:
      raise HTTPException(status_code=400, detail="Invalid table")
      
    if thumbnail and thumbnail.filename:
      thumbnail_url = storage.upload_file(thumbnail, "thumbnails")
      admin_service.update_node_thumbnail(conn, table, id, thumbnail_url)
    
    return _render_node_partial(request, conn, table, id, start_open=True)
  except ValueError as e:
    return _render_node_partial(request, conn, table, id, error_msg=str(e), start_open=True)
  finally:
    conn.close()


# Generic Delete
@router.delete("/curriculum/{table}/{id}")
async def delete_node(request: Request, table: str, id: int):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    admin_service.delete_node(conn, table, id)
    return HTMLResponse("")
  finally:
    conn.close()


# ==========================================
# DIGI LIBRARY ADMIN ROUTES (Markless)
# ==========================================

@router.get("/digi-library", response_class=HTMLResponse)
async def digi_library_admin(request: Request):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    books = admin_service.get_digi_library_tree(conn)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM classes ORDER BY order_index, id")
    classes = [dict(r) for r in cursor.fetchall()]
    return templates.TemplateResponse(
      request=request,
      name="admin/digi_library.html",
      context={"request": request, "user": user, "books": books, "classes": classes}
    )
  finally:
    conn.close()


@router.post("/digi-library/books", response_class=HTMLResponse)
async def create_digi_book_route(
  request: Request,
  title: str = Form(...),
  description: str = Form(""),
  class_id: Optional[str] = Form(None),
  thumbnail: Optional[UploadFile] = File(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    thumbnail_url = ""
    if thumbnail and thumbnail.filename:
      thumbnail_url = storage.upload_file(thumbnail, "thumbnails")
    parsed_class_id = int(class_id) if class_id and class_id.strip().isdigit() else None
    book = admin_service.create_digi_book(conn, title, description, thumbnail_url, parsed_class_id)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM classes ORDER BY order_index, id")
    classes = [dict(r) for r in cursor.fetchall()]
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_book_item.html",
      context={"request": request, "book": book, "classes": classes, "start_open": True}
    )
  except ValueError as e:
    return HTMLResponse(f"<div class='alert alert-error text-sm mb-3'>{str(e)}</div>", status_code=400)
  finally:
    conn.close()


@router.post("/digi-library/books/{book_id}/edit", response_class=HTMLResponse)
async def edit_digi_book_route(
  request: Request,
  book_id: int,
  title: str = Form(...),
  description: str = Form(""),
  class_id: Optional[str] = Form(None),
  thumbnail: Optional[UploadFile] = File(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    thumbnail_url = None
    if thumbnail and thumbnail.filename:
      thumbnail_url = storage.upload_file(thumbnail, "thumbnails")
    parsed_class_id = int(class_id) if class_id and class_id.strip().isdigit() else None
    book = admin_service.update_digi_book(conn, book_id, title, description, thumbnail_url, parsed_class_id, update_class=True)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM classes ORDER BY order_index, id")
    classes = [dict(r) for r in cursor.fetchall()]
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_book_item.html",
      context={"request": request, "book": book, "classes": classes, "start_open": True}
    )
  finally:
    conn.close()


@router.post("/digi-library/books/{book_id}/toggle-status", response_class=HTMLResponse)
async def toggle_digi_book_status_route(request: Request, book_id: int):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    book = admin_service.toggle_digi_book_status(conn, book_id)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM classes ORDER BY order_index, id")
    classes = [dict(r) for r in cursor.fetchall()]
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_book_item.html",
      context={"request": request, "book": book, "classes": classes, "start_open": True}
    )
  finally:
    conn.close()


@router.delete("/digi-library/books/{book_id}")
async def delete_digi_book_route(request: Request, book_id: int):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    admin_service.delete_digi_book(conn, book_id)
    return HTMLResponse("")
  finally:
    conn.close()


@router.post("/digi-library/books/{book_id}/subjects", response_class=HTMLResponse)
async def create_digi_subject_route(
  request: Request,
  book_id: int,
  name: str = Form(...),
  description: str = Form(""),
  thumbnail: Optional[UploadFile] = File(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    thumbnail_url = ""
    if thumbnail and thumbnail.filename:
      thumbnail_url = storage.upload_file(thumbnail, "thumbnails")
    subject = admin_service.create_digi_subject(conn, book_id, name, description, thumbnail_url)
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_subject_item.html",
      context={"request": request, "subject": subject, "start_open": True}
    )
  finally:
    conn.close()


@router.post("/digi-library/subjects/{subject_id}/edit", response_class=HTMLResponse)
async def edit_digi_subject_route(
  request: Request,
  subject_id: int,
  name: str = Form(...),
  description: str = Form(""),
  thumbnail: Optional[UploadFile] = File(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    thumbnail_url = None
    if thumbnail and thumbnail.filename:
      thumbnail_url = storage.upload_file(thumbnail, "thumbnails")
    subject = admin_service.update_digi_subject(conn, subject_id, name, description, thumbnail_url)
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_subject_item.html",
      context={"request": request, "subject": subject, "start_open": True}
    )
  finally:
    conn.close()


@router.post("/digi-library/subjects/{subject_id}/move", response_class=HTMLResponse)
async def move_digi_subject_route(
  request: Request,
  subject_id: int,
  direction: str = Form("up")
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    book = admin_service.move_digi_subject(conn, subject_id, direction)
    if not book:
      return HTMLResponse("Subject not found", status_code=404)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM classes ORDER BY order_index, id")
    classes = [dict(r) for r in cursor.fetchall()]
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_book_item.html",
      context={"request": request, "book": book, "classes": classes, "start_open": True}
    )
  finally:
    conn.close()


@router.delete("/digi-library/subjects/{subject_id}")
async def delete_digi_subject_route(request: Request, subject_id: int):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    admin_service.delete_digi_subject(conn, subject_id)
    return HTMLResponse("")
  finally:
    conn.close()


@router.post("/digi-library/subjects/{subject_id}/banks", response_class=HTMLResponse)
async def create_digi_bank_route(
  request: Request,
  subject_id: int,
  title: str = Form(...),
  description: str = Form(""),
  question_type: str = Form("CUSTOM"),
  raw_text: Optional[str] = Form(None),
  file: Optional[UploadFile] = File(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    bank = admin_service.create_digi_bank(conn, subject_id, title, description)

    # Optional: Bulk extract and insert ordered questions & answers right during Chapter creation
    extracted_text = ""
    if file and file.filename:
      extracted_text = await document_parser.extract_text_from_file(file)
    elif raw_text and raw_text.strip():
      extracted_text = raw_text.strip()

    if extracted_text:
      import asyncio
      questions = await asyncio.to_thread(document_parser.parse_questions_with_ai, extracted_text, question_type or "CUSTOM")
      for q in questions:
        q_text = (q.get("question_text") or "").strip()
        m_answer = (q.get("model_answer") or "").strip()
        opts = q.get("options", None)
        q_type = q.get("type", question_type or "CUSTOM")
        if q_text and m_answer:
          opts_json = json.dumps(opts) if isinstance(opts, list) else opts
          admin_service.create_digi_question(
            conn,
            bank_id=bank["id"],
            question_text=q_text,
            model_answer=m_answer,
            options=opts_json,
            question_type=q_type
          )
      bank = admin_service.get_digi_bank(conn, bank["id"])

    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_bank_item.html",
      context={"request": request, "bank": bank}
    )
  finally:
    conn.close()


@router.post("/digi-library/banks/{bank_id}/move", response_class=HTMLResponse)
async def move_digi_bank_route(
  request: Request,
  bank_id: int,
  direction: str = Form("up")
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    subject = admin_service.move_digi_bank(conn, bank_id, direction)
    if not subject:
      return HTMLResponse("Chapter not found", status_code=404)
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_subject_item.html",
      context={"request": request, "subject": subject, "start_open": True}
    )
  finally:
    conn.close()


@router.post("/digi-library/banks/{bank_id}/edit", response_class=HTMLResponse)
async def edit_digi_bank_route(
  request: Request,
  bank_id: int,
  title: str = Form(...),
  description: str = Form("")
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    bank = admin_service.update_digi_bank(conn, bank_id, title, description)
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_bank_item.html",
      context={"request": request, "bank": bank}
    )
  finally:
    conn.close()


@router.post("/digi-library/banks/{bank_id}/toggle-status", response_class=HTMLResponse)
async def toggle_digi_bank_status_route(request: Request, bank_id: int):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    bank = admin_service.toggle_digi_bank_status(conn, bank_id)
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_bank_item.html",
      context={"request": request, "bank": bank}
    )
  finally:
    conn.close()


@router.delete("/digi-library/banks/{bank_id}")
async def delete_digi_bank_route(request: Request, bank_id: int):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    admin_service.delete_digi_bank(conn, bank_id)
    return HTMLResponse("")
  finally:
    conn.close()


@router.get("/digi-library/banks/{bank_id}", response_class=HTMLResponse)
async def digi_bank_manage_page(request: Request, bank_id: int):
  conn = get_db_connection()
  try:
    user = require_admin(request, conn)
    bank = admin_service.get_digi_bank(conn, bank_id)
    if not bank:
      raise HTTPException(status_code=404, detail="Chapter not found")
    return templates.TemplateResponse(
      request=request,
      name="admin/digi_bank_edit.html",
      context={"request": request, "user": user, "bank": bank}
    )
  finally:
    conn.close()


@router.post("/digi-library/banks/{bank_id}/questions", response_class=HTMLResponse)
async def create_digi_question_route(
  request: Request,
  bank_id: int,
  question_text: str = Form(...),
  model_answer: str = Form(...),
  question_type: str = Form("CUSTOM"),
  options: Optional[str] = Form(None),
  option_a: Optional[str] = Form(None),
  option_b: Optional[str] = Form(None),
  option_c: Optional[str] = Form(None),
  option_d: Optional[str] = Form(None),
  image: Optional[UploadFile] = File(None),
  image_url: Optional[str] = Form(None),
  answer_image: Optional[UploadFile] = File(None),
  answer_image_url: Optional[str] = Form(None),
  video_source: Optional[str] = Form("none"),
  video_url: Optional[str] = Form(None),
  video_file: Optional[UploadFile] = File(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    media_url = None
    if image and image.filename:
      media_url = storage.upload_file(image, "media")
    elif image_url and image_url.strip():
      media_url = image_url.strip()

    ans_media_url = ""
    if answer_image and answer_image.filename:
      ans_media_url = storage.upload_file(answer_image, "media")
    elif answer_image_url and answer_image_url.strip():
      ans_media_url = answer_image_url.strip()

    final_options = options
    if question_type == "MCQ" and any([option_a, option_b, option_c, option_d]):
      opts_list = []
      if option_a and option_a.strip(): opts_list.append(f"A. {option_a.strip()}")
      if option_b and option_b.strip(): opts_list.append(f"B. {option_b.strip()}")
      if option_c and option_c.strip(): opts_list.append(f"C. {option_c.strip()}")
      if option_d and option_d.strip(): opts_list.append(f"D. {option_d.strip()}")
      if opts_list:
        final_options = json.dumps(opts_list)

    exp_video_url = None
    exp_video_type = None
    if video_source == "youtube" and video_url and video_url.strip():
      exp_video_url = video_url.strip()
      exp_video_type = "youtube"
    elif video_source == "upload" and video_file and video_file.filename:
      exp_video_url = storage.upload_file(video_file, "media")
      exp_video_type = "video"

    q = admin_service.create_digi_question(
      conn,
      bank_id=bank_id,
      question_text=question_text,
      model_answer=model_answer,
      options=final_options,
      question_type=question_type,
      media_url=media_url,
      answer_media_url=ans_media_url,
      explanation_video_url=exp_video_url,
      explanation_video_type=exp_video_type
    )
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_question_item.html",
      context={"request": request, "q": q}
    )
  except ValueError as e:
    return HTMLResponse(f"<div class='text-error text-sm font-bold p-2'>{html.escape(str(e))}</div>", status_code=400)
  finally:
    conn.close()


@router.post("/digi-library/banks/{bank_id}/upload-questions", response_class=HTMLResponse)
async def upload_digi_questions_route(
  request: Request,
  bank_id: int,
  question_type: str = Form("CUSTOM"),
  raw_text: Optional[str] = Form(None),
  return_card: Optional[str] = Form(None),
  file: Optional[UploadFile] = File(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    text = ""
    if file and file.filename:
      text = await document_parser.extract_text_from_file(file)
    elif raw_text and raw_text.strip():
      text = raw_text.strip()
    else:
      if return_card == "1":
        bank = admin_service.get_digi_bank(conn, bank_id)
        return templates.TemplateResponse(
          request=request,
          name="admin/partials/digi_bank_item.html",
          context={"request": request, "bank": bank}
        )
      return HTMLResponse("<div class='text-error mt-4 font-bold'>Please select a document (.pdf, .docx, .xlsx, .txt) or paste question & answer text.</div>")

    import asyncio
    questions = await asyncio.to_thread(document_parser.parse_questions_with_ai, text, question_type)

    html_responses = []
    for q in questions:
      q_text = q.get("question_text", "")
      m_answer = q.get("model_answer", "")
      opts = q.get("options", None)
      q_type = q.get("type", question_type)
      q_media = (q.get("media_url") or "").strip() or None
      a_media = (q.get("answer_media_url") or "").strip()
      v_url = (q.get("explanation_video_url") or q.get("youtube_url") or q.get("video_url") or "").strip() or None
      v_type = "youtube" if v_url else None
      if q_text and m_answer:
        opts_json = json.dumps(opts) if isinstance(opts, list) else opts
        new_q = admin_service.create_digi_question(
          conn,
          bank_id=bank_id,
          question_text=q_text,
          model_answer=m_answer,
          options=opts_json,
          question_type=q_type,
          media_url=q_media,
          answer_media_url=a_media,
          explanation_video_url=v_url,
          explanation_video_type=v_type
        )
        html_res = templates.TemplateResponse(
          request=request,
          name="admin/partials/digi_question_item.html",
          context={"request": request, "q": new_q}
        ).body.decode("utf-8")
        html_responses.append(html_res)

    if return_card == "1":
      bank = admin_service.get_digi_bank(conn, bank_id)
      return templates.TemplateResponse(
        request=request,
        name="admin/partials/digi_bank_item.html",
        context={"request": request, "bank": bank, "bulk_uploaded_count": len(html_responses)}
      )

    if not html_responses:
      return HTMLResponse("<div class='text-error mt-4 font-bold'>Failed to parse any questions from the input. Please ensure it has clear questions and answers.</div>")
    return HTMLResponse("".join(html_responses))
  except Exception as e:
    conn.rollback()
    return HTMLResponse(f"<div class='text-error font-bold p-4 bg-error/10 rounded-lg'>Error: {html.escape(str(e))}</div>")
  finally:
    conn.close()


@router.post("/digi-library/questions/{question_id}/move", response_class=HTMLResponse)
async def move_digi_question_route(
  request: Request,
  question_id: int,
  direction: str = Form("up")
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    bank = admin_service.move_digi_question(conn, question_id, direction)
    if not bank:
      return HTMLResponse("Question not found", status_code=404)
    html_responses = []
    for q in bank["questions"]:
      html_res = templates.TemplateResponse(
        request=request,
        name="admin/partials/digi_question_item.html",
        context={"request": request, "q": q}
      ).body.decode("utf-8")
      html_responses.append(html_res)
    return HTMLResponse("".join(html_responses))
  finally:
    conn.close()



@router.post("/digi-library/questions/{question_id}/edit", response_class=HTMLResponse)
async def edit_digi_question_route(
  request: Request,
  question_id: int,
  question_text: str = Form(...),
  model_answer: str = Form(...),
  options: str = Form(""),
  question_type: Optional[str] = Form(None),
  question_image: Optional[UploadFile] = File(None),
  answer_image: Optional[UploadFile] = File(None),
  question_image_url: Optional[str] = Form(None),
  answer_image_url: Optional[str] = Form(None),
  remove_question_image: Optional[str] = Form(None),
  remove_answer_image: Optional[str] = Form(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    q = admin_service.get_digi_question(conn, question_id)
    if not q:
      return HTMLResponse("Question not found", status_code=404)

    media_url = q.get("media_url") or ""
    if remove_question_image == "1":
      media_url = ""
    elif question_image and question_image.filename:
      media_url = storage.upload_file(question_image, "media")
    elif question_image_url is not None and question_image_url.strip():
      media_url = question_image_url.strip()

    answer_media_url = q.get("answer_media_url") or ""
    if remove_answer_image == "1":
      answer_media_url = ""
    elif answer_image and answer_image.filename:
      answer_media_url = storage.upload_file(answer_image, "media")
    elif answer_image_url is not None and answer_image_url.strip():
      answer_media_url = answer_image_url.strip()

    updated_q = admin_service.update_digi_question(
      conn,
      question_id=question_id,
      question_text=question_text,
      model_answer=model_answer,
      options=options,
      question_type=question_type,
      media_url=media_url,
      answer_media_url=answer_media_url
    )
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_question_item.html",
      context={"request": request, "q": updated_q, "saved": True}
    )
  finally:
    conn.close()


@router.post("/digi-library/questions/{question_id}/video", response_class=HTMLResponse)
async def add_digi_question_video_route(
  request: Request,
  question_id: int,
  video_source: str = Form(...),
  video_url: Optional[str] = Form(None),
  file: Optional[UploadFile] = File(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    if video_source == "youtube":
      if not video_url or not video_url.strip():
        return HTMLResponse("<div class='text-error'>YouTube URL is required</div>")
      admin_service.update_digi_question_explanation_video(conn, question_id, video_url.strip(), "youtube")
    elif video_source == "upload":
      if not file or not file.filename:
        return HTMLResponse("<div class='text-error'>Video file is required</div>")
      media_url = storage.upload_file(file, "media")
      admin_service.update_digi_question_explanation_video(conn, question_id, media_url, "video")
    updated_q = admin_service.get_digi_question(conn, question_id)
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_question_item.html",
      context={"request": request, "q": updated_q}
    )
  finally:
    conn.close()


@router.delete("/digi-library/questions/{question_id}/video", response_class=HTMLResponse)
async def remove_digi_question_video_route(request: Request, question_id: int):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    updated_q = admin_service.update_digi_question_explanation_video(conn, question_id, None, None)
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_question_item.html",
      context={"request": request, "q": updated_q}
    )
  finally:
    conn.close()


@router.post("/digi-library/questions/{question_id}/additional-videos", response_class=HTMLResponse)
async def add_digi_question_additional_video_route(
  request: Request,
  question_id: int,
  category: str = Form("teacher"),
  label: str = Form(...),
  video_source: str = Form("youtube"),
  url: Optional[str] = Form(None),
  video_file: Optional[UploadFile] = File(None)
):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    final_url = ""
    final_type = "youtube"
    if video_source == "upload" and video_file and video_file.filename:
      final_url = storage.upload_file(video_file, "media")
      final_type = "video"
    elif url and url.strip():
      final_url = url.strip()
      final_type = "youtube"
    if final_url:
      admin_service.add_video_attachment(conn, "digi_question", question_id, category, label.strip(), final_url, final_type)
    updated_q = admin_service.get_digi_question(conn, question_id)
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_question_item.html",
      context={"request": request, "q": updated_q}
    )
  finally:
    conn.close()


@router.delete("/digi-library/questions/{question_id}/additional-videos/{video_id}", response_class=HTMLResponse)
async def delete_digi_question_additional_video_route(request: Request, question_id: int, video_id: str):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    admin_service.delete_additional_video(conn, "digi_question", question_id, video_id)
    updated_q = admin_service.get_digi_question(conn, question_id)
    return templates.TemplateResponse(
      request=request,
      name="admin/partials/digi_question_item.html",
      context={"request": request, "q": updated_q}
    )
  finally:
    conn.close()


@router.delete("/digi-library/questions/{question_id}")
async def delete_digi_question_route(request: Request, question_id: int):
  conn = get_db_connection()
  try:
    require_admin(request, conn)
    admin_service.delete_digi_question(conn, question_id)
    return HTMLResponse("")
  finally:
    conn.close()



