import os
import json
import logging
from io import BytesIO
from fastapi import UploadFile

from pypdf import PdfReader
from docx import Document
from openpyxl import load_workbook
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Initialize OpenAI client lazily in the function

logger = logging.getLogger(__name__)

async def extract_text_from_file(file: UploadFile) -> str:
  """Extracts raw text (and uploads any embedded .docx images) from various document formats."""
  content = await file.read()
  filename = (file.filename or "").lower()
  text = ""
  
  try:
    if filename.endswith(".pdf"):
      reader = PdfReader(BytesIO(content))
      for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text:
          text += page_text + "\n"
    
    elif filename.endswith(".docx"):
      import services.storage as storage
      doc = Document(BytesIO(content))
      rels = doc.part.rels
      uploaded_rel_urls = {}

      class _MemUpload:
        def __init__(self, fname: str, blob_bytes: bytes, ctype: str):
          self.filename = fname
          self.file = BytesIO(blob_bytes)
          self.content_type = ctype

      for para in doc.paragraphs:
        blips = para._element.xpath(".//*[local-name()='blip']")
        img_markers = []
        for b in blips:
          rid = b.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
          if rid and rid in rels:
            if rid not in uploaded_rel_urls:
              try:
                rel_part = rels[rid].target_part
                part_name = os.path.basename(str(rels[rid].target_ref)) or "image.png"
                ctype = getattr(rel_part, "content_type", "image/png")
                url = storage.upload_file(_MemUpload(part_name, rel_part.blob, ctype), "media")
                if url:
                  uploaded_rel_urls[rid] = url
              except Exception as img_err:
                logger.warning(f"Failed to upload embedded docx image {rid}: {img_err}")
            if rid in uploaded_rel_urls:
              img_markers.append(f"[IMAGE_URL: {uploaded_rel_urls[rid]}]")
        line_parts = []
        if para.text and para.text.strip():
          line_parts.append(para.text.strip())
        if img_markers:
          line_parts.extend(img_markers)
        if line_parts:
          text += " ".join(line_parts) + "\n"

      for table in doc.tables:
        for row in table.rows:
          seen_cells = set()
          cell_texts = []
          for cell in row.cells:
            if id(cell._tc) not in seen_cells:
              seen_cells.add(id(cell._tc))
              ct = (cell.text or "").strip()
              if ct:
                cell_texts.append(ct)
          if cell_texts:
            text += " | ".join(cell_texts) + "\n"
        
    elif filename.endswith(".xlsx"):
      wb = load_workbook(filename=BytesIO(content), data_only=True)
      for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
          row_text = " | ".join(str(cell) for cell in row if cell is not None)
          if row_text:
            text += row_text + "\n"
            
    elif filename.endswith(".txt") or filename.endswith(".csv"):
      text = content.decode("utf-8", errors="ignore")
      
    else:
      raise ValueError(f"Unsupported file format: {filename}")
      
  except Exception as e:
    logger.error(f"Error extracting text from {filename}: {e}")
    raise ValueError(f"Failed to read file: {str(e)}")
    
  return text

def _chunk_text_by_lines(text: str, max_chars: int = 12000) -> list[str]:
  """Splits large document text on question boundaries (or line boundaries) so numbered questions are never cut in half."""
  import re
  lines = text.splitlines(keepends=True)
  chunks = []
  current = []
  current_len = 0
  q_start_re = re.compile(r'^\s*\d+[\.\)]\s*')

  for line in lines:
    if current_len + len(line) > max_chars and current:
      # Try to split at the latest question boundary in `current` if possible
      split_idx = None
      for i in range(len(current) - 1, max(0, len(current) - 25), -1):
        if q_start_re.match(current[i]):
          split_idx = i
          break
      if split_idx and split_idx > 0:
        chunks.append("".join(current[:split_idx]))
        current = current[split_idx:] + [line]
        current_len = sum(len(x) for x in current)
      else:
        chunks.append("".join(current))
        current = [line]
        current_len = len(line)
    else:
      current.append(line)
      current_len += len(line)
  if current:
    chunks.append("".join(current))
  return chunks


def parse_questions_with_ai(text: str, question_type: str = 'LONG_ANSWER') -> list[dict]:
  """
  Uses OpenAI to extract questions, model answers, embedded images, and YouTube links from raw text in exact sequential order.
  """
  if not text.strip():
    return []

  if question_type == 'CUSTOM':
    system_prompt = (
      "You are an expert educational content parser for Labour India Books & Curriculum. "
      "The user uploaded a chapter containing numbered questions and answers (which may be a mix of MCQs, Very Short Answer, Short Answer, Long Answer, Assertion-Reason, or Numerical).\n"
      "CRITICAL ORDERING & NUMBERING RULE: You MUST extract every numbered question in the EXACT sequential order it appears in the text, and preserve its leading question number (e.g. '1. ...', '2. ...') at the start of 'question_text'.\n"
      "DO NOT split a single numbered question that has sub-parts (e.g. '20. (a)... (b)...' or '71. (a)... (b)... (c)...') into separate items — keep all parts of that numbered question together under its question number so the numbering order stays 100% intact.\n"
      "CRITICAL YOUTUBE LINK RULE: If a YouTube link (e.g. https://youtu.be/... or https://www.youtube.com/...) appears after a question/answer, extract that exact URL into 'explanation_video_url' (and do NOT leave the raw URL inside 'model_answer' or 'question_text').\n"
      "CRITICAL IMAGE RULE: If an '[IMAGE_URL: /media/...]' marker appears inside the question stem, put that URL in 'media_url'. If '[IMAGE_URL: /media/...]' appears in the answer section, put that URL in 'answer_media_url' (and remove the raw '[IMAGE_URL: ...]' tag from the text).\n"
      "If a question in the text is missing an explicit answer (or references an Answer Key line like '1(c) 2(a)'), resolve and provide a clear, accurate educational model answer in 'model_answer' so no question is skipped.\n"
      "For EACH question, assign one of the following to the 'type' field: 'MCQ', 'ASSERTION_REASON', 'NUMERICAL', 'VERY_SHORT_ANSWER', 'SHORT_ANSWER', 'LONG_ANSWER'.\n"
      "If the question has multiple choice options (A, B, C, D), set type to 'MCQ' and provide the 4 options as a JSON array of strings in 'options' formatted as ['A. ...', 'B. ...', 'C. ...', 'D. ...'].\n\n"
      "Return the output STRICTLY as a JSON object containing a key called 'questions'."
    )
  else:
    system_prompt = (
      "You are an expert educational content parser. "
      f"You MUST extract questions specifically for the format: '{question_type}' in the EXACT sequential order they appear, preserving any question numbers.\n"
      "If the uploaded text clearly does NOT match this format (e.g. essay paragraphs uploaded for MCQs, with no options to extract), "
      "you MUST return an empty array for 'questions' and provide an 'error' field explaining the mismatch.\n\n"
      "Extract a list of distinct questions and their corresponding correct answers from the provided text.\n"
      "If a YouTube URL (https://youtu.be/... or https://www.youtube.com/...) appears after a question/answer, extract it into 'explanation_video_url'.\n"
      "If '[IMAGE_URL: ...]' appears in the question, put the URL in 'media_url'; if in the answer, put it in 'answer_media_url'.\n"
      "If a question is missing an explicit answer in the text, provide an accurate educational answer in 'model_answer'.\n"
      "If the question_type is 'MCQ' (Multiple Choice Questions) or 'ASSERTION_REASON', extract the 4 options as a JSON array of strings in 'options', and put the correct option text in 'model_answer'.\n\n"
      "Return the output STRICTLY as a JSON object containing a key called 'questions'."
    )

  try:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
      logger.error("OpenAI API key not found.")
      return []

    client = OpenAI(api_key=api_key)
    chunks = _chunk_text_by_lines(text.strip(), max_chars=12000)
    all_questions = []
    last_error = None

    for chunk in chunks[:8]:
      response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": f"Extract all questions, answers, images, and YouTube links in exact sequential order from this text:\n\n{chunk}"}
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=12000
      )
      result_str = response.choices[0].message.content
      data = json.loads(result_str)
      if "error" in data and not data.get("questions"):
        last_error = data["error"]
      chunk_qs = data.get("questions", [])
      if chunk_qs:
        all_questions.extend(chunk_qs)

    if not all_questions and last_error:
      raise ValueError(last_error)

    return all_questions

  except Exception as e:
    logger.error(f"OpenAI extraction failed: {e}")
    raise e

