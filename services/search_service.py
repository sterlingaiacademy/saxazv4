import os
import re
import json
from openai import OpenAI
from dotenv import load_dotenv
from database import get_db_connection

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None


def _clean_text(val: str) -> str:
  if not val:
    return ""
  return re.sub(r"\s+", " ", str(val)).strip()


def _truncate(val: str, max_len: int = 140) -> str:
  s = _clean_text(val)
  if len(s) <= max_len:
    return s
  return s[: max_len - 1].rstrip() + "…"


def build_search_catalog(conn, user: dict) -> dict:
  """
  Builds a comprehensive, live index of every navigable destination on the platform
  for the current student:
    - Core Website Pages & Features (Dashboard, Exams Hub, Digi-Library, AI Tutor, Past Attempts, Profile, Settings)
    - Enrolled Subjects (/student/subjects/{id})
    - Published Curriculum Chapters (/student/chapters/{id}) & Chapter Exams (/student/chapters/{id}/exams)
    - Study Materials / Videos / PDFs (/student/content/{id})
    - Practice Mock Exams (/student/exams/{id}) & Proctored Real Exams (/student/real-exams/{id}/intro)
    - Past Exam Attempt Reports (/student/attempts/{id})
    - Digi-Library Books (/student/digi-library/books/{id})
    - Digi-Library Subjects (/student/digi-library/subjects/{id})
    - Digi-Library Chapter Studios (/student/digi-library/banks/{id}) & Full Book Readers
    - Individual Digi-Library Study Questions (/student/digi-library/banks/{bank_id}?question_id={q_id}&q={idx})
    - Individual Curriculum Exam Questions (/student/exams/{exam_id}?question_id={q_id})
  """
  cursor = conn.cursor()
  user_id = user.get("id")
  class_id = user.get("class_id")

  nav_items = []
  question_items = []

  # 1. Core Platform Pages & Features
  core_pages = [
    {
      "id": "page:dashboard",
      "title": "Student Dashboard (Home)",
      "category": "Website Page",
      "badge": "Home",
      "url": "/student/dashboard",
      "description": "Main student dashboard with your Day Streak, Total XP, League tier, Subject Progress chart, Recent Exam Scores, and Activity Graph.",
      "keywords": "home dashboard main page start overview streak xp league bronze silver gold diamond progress chart activity graph"
    },
    {
      "id": "page:exams_hub",
      "title": "Subjects & Exams Hub",
      "category": "Website Page",
      "badge": "Exams & Subjects",
      "url": "/student/exams",
      "description": "Browse all your enrolled subjects (Physics, Maths, Chemistry, Biology), chapters, video lessons, practice mock exams, and real exams.",
      "keywords": "exams subjects courses curriculum syllabus test hub practice mock exam real exam chapters"
    },
    {
      "id": "page:digi_library",
      "title": "Digi-Library Bookshelf Hub",
      "category": "Website Page",
      "badge": "Digi-Library",
      "url": "/student/digi-library",
      "description": "Explore Labour India Brilliant Student digital books, subject reference content, interactive chapter study cards, full book reader, and video explanations.",
      "keywords": "digi library digital library books bookshelf labour india brilliant student question bank study studio reference"
    },
    {
      "id": "page:tutor",
      "title": "AI Tutor (Bella & Personal Guides)",
      "category": "AI Tool & Page",
      "badge": "AI Tutor",
      "url": "/student/tutor",
      "description": "Chat 1-on-1 with your interactive AI Tutor (Bella, Sarah, Adam, or Michael) with voice chat, step-by-step animated whiteboard diagrams, and digital scratchpad.",
      "keywords": "ai tutor bella sarah adam michael chat ask doubt question teacher whiteboard draw diagram sketch scratchpad help"
    },
    {
      "id": "page:attempts",
      "title": "Exam History & Past Results",
      "category": "Website Page",
      "badge": "Results & History",
      "url": "/student/attempts",
      "description": "View all your completed Mock Exam and Real Exam attempts, percentage scores, grades, and question-by-question AI evaluation reports.",
      "keywords": "exam history past attempts results scores grades report card previous exams marks review performance"
    },
    {
      "id": "page:profile",
      "title": "My Profile, Avatar & Password",
      "category": "Account Settings",
      "badge": "Profile",
      "url": "/student/profile",
      "description": "Update your student name, email address, upload or change your profile avatar picture, and change your account password.",
      "keywords": "profile account user name email avatar photo picture password change password reset password security"
    },
    {
      "id": "page:settings",
      "title": "Voice, Audio & Interface Settings",
      "category": "Account Settings",
      "badge": "Settings",
      "url": "/student/settings",
      "description": "Change your AI Tutor voice persona (Bella, Sarah, Adam, Michael), TTS engine (Kokoro AI Voice / Browser), auto/manual reading mode, sound effects (SFX), and magic cursor effects.",
      "keywords": "settings preferences configuration voice audio tts speech kokoro sarvam browser voice sound effects sfx mute cursor magic trail change tutor"
    },
  ]
  nav_items.extend(core_pages)

  # 2. Enrolled Curriculum Subjects
  try:
    if class_id:
      cursor.execute("SELECT id, name, description FROM subjects WHERE class_id = ? ORDER BY order_index, id", (class_id,))
    else:
      cursor.execute("SELECT id, name, description FROM subjects ORDER BY order_index, id")
    subjects = [dict(r) for r in cursor.fetchall()]
    for sub in subjects:
      s_name = _clean_text(sub["name"])
      s_desc = _clean_text(sub.get("description") or f"Explore {s_name} chapters, video lessons, study notes, practice mock exams, and real exams.")
      synonyms = ""
      if s_name.lower() in ("maths", "mathematics", "math"):
        synonyms = "math maths mathematics algebra geometry trigonometry arithmetic quadratic equation equations calculus"
      elif s_name.lower() == "physics":
        synonyms = "physics science optics light reflection refraction mirror lens electricity magnetic motion force"
      elif s_name.lower() == "chemistry":
        synonyms = "chemistry science chemical reactions acids bases salts metals atoms molecules carbon"
      elif s_name.lower() == "biology":
        synonyms = "biology science life processes control coordination plants animals human body heart neuron nervous endocrine"
      nav_items.append({
        "id": f"subj:{sub['id']}",
        "title": f"{s_name} — Subject Hub",
        "category": "Curriculum Subject",
        "badge": s_name,
        "url": f"/student/subjects/{sub['id']}",
        "description": s_desc,
        "keywords": f"{s_name} subject chapters exams lessons {synonyms}"
      })
  except Exception as e:
    print(f"Search catalog subjects error: {e}")

  # 3. Published Curriculum Chapters & Chapter Exams (plus draft topic awareness mapped to parent Subject)
  try:
    if class_id:
      cursor.execute("""
        SELECT c.id, c.name, c.description, c.status, c.subject_id, s.name as subject_name
        FROM chapters c
        JOIN subjects s ON c.subject_id = s.id
        WHERE s.class_id = ?
        ORDER BY s.order_index, c.order_index, c.id
      """, (class_id,))
    else:
      cursor.execute("""
        SELECT c.id, c.name, c.description, c.status, c.subject_id, s.name as subject_name
        FROM chapters c
        JOIN subjects s ON c.subject_id = s.id
        ORDER BY s.order_index, c.order_index, c.id
      """)
    for ch in [dict(r) for r in cursor.fetchall()]:
      c_name = _clean_text(ch["name"])
      s_name = _clean_text(ch["subject_name"])
      c_desc = _clean_text(ch.get("description") or f"{c_name} in {s_name}.")
      if ch.get("status") == "published":
        nav_items.append({
          "id": f"ch:{ch['id']}",
          "title": c_name,
          "category": f"{s_name} • Chapter",
          "badge": s_name,
          "url": f"/student/chapters/{ch['id']}",
          "description": c_desc,
          "keywords": f"{c_name} {s_name} chapter lesson video notes study {c_desc}"
        })
        nav_items.append({
          "id": f"ch_exams:{ch['id']}",
          "title": f"{c_name} — Chapter Exams (Mock & Real)",
          "category": f"{s_name} • Exams",
          "badge": f"{s_name} Exams",
          "url": f"/student/chapters/{ch['id']}/exams",
          "description": f"Take Practice Mock Exams or Proctored Real Exams for {c_name} ({s_name}).",
          "keywords": f"{c_name} {s_name} mock exam real exam test practice"
        })
      else:
        # Draft chapter: route student safely to its parent Subject page so they never hit a 404
        nav_items.append({
          "id": f"draft_topic:{ch['id']}",
          "title": f"{s_name}: {c_name} (Subject Hub)",
          "category": f"{s_name} • Topic",
          "badge": s_name,
          "url": f"/student/subjects/{ch['subject_id']}",
          "description": f"Open {s_name} Subject Hub for {c_name}, or practice with AI Tutor Bella.",
          "keywords": f"{c_name} {s_name} topic chapter"
        })
  except Exception as e:
    print(f"Search catalog chapters error: {e}")

  # 4. Published Study Materials / Content Items (Videos, PDFs, Notes)
  try:
    cursor.execute("""
      SELECT ci.id, ci.title, ci.type, ci.chapter_id, c.name as chapter_name, s.name as subject_name
      FROM content_items ci
      JOIN chapters c ON ci.chapter_id = c.id
      JOIN subjects s ON c.subject_id = s.id
      WHERE c.status = 'published'
      ORDER BY ci.order_index, ci.id
    """)
    for item in [dict(r) for r in cursor.fetchall()]:
      i_title = _clean_text(item["title"])
      i_type = _clean_text(item.get("type") or "resource").upper()
      c_name = _clean_text(item["chapter_name"])
      s_name = _clean_text(item["subject_name"])
      nav_items.append({
        "id": f"content:{item['id']}",
        "title": f"{i_title} ({i_type})",
        "category": f"{s_name} • Study Material",
        "badge": i_type,
        "url": f"/student/content/{item['id']}",
        "description": f"{i_type} learning material inside {c_name} ({s_name}).",
        "keywords": f"{i_title} {i_type} video youtube pdf notes study material {c_name} {s_name}"
      })
  except Exception as e:
    print(f"Search catalog content_items error: {e}")

  # 5. Published Mock Exams & Proctored Real Exams
  try:
    cursor.execute("""
      SELECT ep.id, ep.title, ep.type, ep.chapter_id, c.name as chapter_name, c.status as chapter_status, s.name as subject_name
      FROM exam_papers ep
      JOIN chapters c ON ep.chapter_id = c.id
      JOIN subjects s ON c.subject_id = s.id
      WHERE ep.status = 'published' AND c.status = 'published'
      ORDER BY ep.id
    """)
    for ep in [dict(r) for r in cursor.fetchall()]:
      e_title = _clean_text(ep["title"])
      e_type = (ep.get("type") or "mock").lower()
      c_name = _clean_text(ep["chapter_name"])
      s_name = _clean_text(ep["subject_name"])
      if e_type == "real":
        url = f"/student/real-exams/{ep['id']}/intro"
        cat = f"{s_name} • Proctored Real Exam"
        badge = "Real Exam"
        desc = f"Official Proctored Real Exam '{e_title}' for {c_name} ({s_name})."
      else:
        url = f"/student/exams/{ep['id']}"
        cat = f"{s_name} • Practice Mock Exam"
        badge = "Mock Exam"
        desc = f"Interactive Practice Mock Exam '{e_title}' for {c_name} ({s_name}) with instant AI grading and AI Tutor support."
      nav_items.append({
        "id": f"exam:{ep['id']}",
        "title": f"{e_title} — {c_name}",
        "category": cat,
        "badge": badge,
        "url": url,
        "description": desc,
        "keywords": f"{e_title} {e_type} exam test practice mock real proctored {c_name} {s_name}"
      })
  except Exception as e:
    print(f"Search catalog exam_papers error: {e}")

  # 6. Student's Recent Past Exam Attempts
  try:
    if user_id:
      cursor.execute("""
        SELECT a.id, a.completed_at, e.title as exam_title, c.name as chapter_name, s.name as subject_name
        FROM attempts a
        JOIN exam_papers e ON a.exam_paper_id = e.id
        JOIN chapters c ON e.chapter_id = c.id
        JOIN subjects s ON c.subject_id = s.id
        WHERE a.student_id = ? AND a.status = 'completed'
        ORDER BY a.id DESC
        LIMIT 8
      """, (user_id,))
      for att in [dict(r) for r in cursor.fetchall()]:
        e_title = _clean_text(att["exam_title"])
        c_name = _clean_text(att["chapter_name"])
        s_name = _clean_text(att["subject_name"])
        nav_items.append({
          "id": f"attempt:{att['id']}",
          "title": f"Graded Report: {e_title} (Attempt #{att['id']})",
          "category": "Past Exam Result",
          "badge": "Exam Report",
          "url": f"/student/attempts/{att['id']}",
          "description": f"View your graded answers, score breakdown, and AI feedback for {e_title} ({c_name}).",
          "keywords": f"attempt result report score feedback {e_title} {c_name} {s_name}"
        })
  except Exception as e:
    print(f"Search catalog attempts error: {e}")

  # 7. Digi-Library Books, Subjects & Chapter Question Banks
  try:
    if class_id:
      cursor.execute("""
        SELECT id, title, description
        FROM digi_books
        WHERE status = 'published' AND (class_id IS NULL OR class_id = ?)
        ORDER BY order_index, id DESC
      """, (class_id,))
    else:
      cursor.execute("""
        SELECT id, title, description
        FROM digi_books
        WHERE status = 'published'
        ORDER BY order_index, id DESC
      """)
    books = [dict(r) for r in cursor.fetchall()]
    for b in books:
      b_title = _clean_text(b["title"])
      b_desc = _clean_text(b.get("description") or f"Digital Book Edition '{b_title}' in Digi-Library.")
      nav_items.append({
        "id": f"digi_book:{b['id']}",
        "title": b_title,
        "category": "Digi-Library Book",
        "badge": "Digital Book",
        "url": f"/student/digi-library/books/{b['id']}",
        "description": b_desc,
        "keywords": f"{b_title} digi library digital book labour india brilliant student edition"
      })

      cursor.execute("SELECT id, name, description FROM digi_subjects WHERE book_id = ? ORDER BY order_index, id", (b["id"],))
      d_subjects = [dict(r) for r in cursor.fetchall()]
      for ds in d_subjects:
        ds_name = _clean_text(ds["name"])
        ds_desc = _clean_text(ds.get("description") or f"Browse {ds_name} chapters and study question banks in {b_title}.")
        nav_items.append({
          "id": f"digi_subj:{ds['id']}",
          "title": f"{ds_name} — Digi-Library ({b_title})",
          "category": "Digi-Library Subject",
          "badge": f"Digi • {ds_name}",
          "url": f"/student/digi-library/subjects/{ds['id']}",
          "description": ds_desc,
          "keywords": f"{ds_name} digi library subject {b_title}"
        })

        cursor.execute("""
          SELECT id, title, description
          FROM digi_question_banks
          WHERE subject_id = ? AND status = 'published'
          ORDER BY order_index, id
        """, (ds["id"],))
        banks = [dict(r) for r in cursor.fetchall()]
        for qb in banks:
          qb_title = _clean_text(qb["title"])
          qb_desc = _clean_text(qb.get("description") or f"Interactive Chapter Learning Studio for {qb_title} ({ds_name}).")
          nav_items.append({
            "id": f"digi_bank:{qb['id']}",
            "title": qb_title,
            "category": f"Digi-Library • {ds_name}",
            "badge": f"{ds_name} Studio",
            "url": f"/student/digi-library/banks/{qb['id']}",
            "description": qb_desc,
            "keywords": f"{qb_title} {ds_name} {b_title} digi library chapter learning studio question bank {qb_desc}"
          })
          nav_items.append({
            "id": f"digi_reader:{qb['id']}",
            "title": f"{qb_title} — Full Chapter Book Reader",
            "category": f"Digi-Library Reader • {ds_name}",
            "badge": "Book Reader",
            "url": f"/student/digi-library/banks/{qb['id']}?mode=book",
            "description": f"Read all ordered questions and answers of {qb_title} ({ds_name}) in continuous Full Chapter Reader mode.",
            "keywords": f"{qb_title} {ds_name} full chapter reader book view read all questions"
          })

          # Fetch ordered questions inside this Digi-Library Chapter Bank
          cursor.execute("""
            SELECT id, question_text, model_answer, question_type
            FROM digi_questions
            WHERE bank_id = ?
            ORDER BY order_index, id
          """, (qb["id"],))
          q_rows = [dict(r) for r in cursor.fetchall()]
          for idx, qr in enumerate(q_rows):
            q_num = idx + 1
            q_text = _clean_text(qr["question_text"])
            m_ans = _clean_text(qr["model_answer"])
            question_items.append({
              "id": f"digi_q:{qr['id']}",
              "title": f"Q{q_num}: {_truncate(q_text, 115)}",
              "category": f"{ds_name} • {qb_title}",
              "badge": f"Chapter Q{q_num}",
              "url": f"/student/digi-library/banks/{qb['id']}?question_id={qr['id']}&q={idx}",
              "description": f"Answer: {_truncate(m_ans, 160)}",
              "keywords": f"q{q_num} question {q_num} {qb_title} {ds_name} {q_text} {m_ans}"
            })
  except Exception as e:
    print(f"Search catalog digi_library error: {e}")

  # 8. Curriculum Exam Questions (from published Mock Exams)
  try:
    cursor.execute("""
      SELECT q.id, q.question_text, q.model_answer, ep.id as exam_id, ep.title as exam_title,
             ep.type as exam_type, c.id as chapter_id, c.name as chapter_name, s.name as subject_name
      FROM questions q
      JOIN modules m ON q.module_id = m.id
      JOIN exam_papers ep ON m.exam_paper_id = ep.id
      JOIN chapters c ON ep.chapter_id = c.id
      JOIN subjects s ON c.subject_id = s.id
      WHERE ep.status = 'published' AND c.status = 'published' AND ep.type = 'mock'
      ORDER BY ep.id, m.id, q.id
    """)
    for idx, eq in enumerate([dict(r) for r in cursor.fetchall()]):
      q_text = _clean_text(eq["question_text"])
      m_ans = _clean_text(eq["model_answer"])
      e_title = _clean_text(eq["exam_title"])
      c_name = _clean_text(eq["chapter_name"])
      s_name = _clean_text(eq["subject_name"])
      question_items.append({
        "id": f"exam_q:{eq['id']}",
        "title": f"Mock Q: {_truncate(q_text, 115)}",
        "category": f"{s_name} • {e_title} ({c_name})",
        "badge": "Exam Question",
        "url": f"/student/exams/{eq['exam_id']}?question_id={eq['id']}",
        "description": f"Practice Question in {e_title} ({c_name}) — {_truncate(m_ans, 140)}",
        "keywords": f"{q_text} {m_ans} {e_title} {c_name} {s_name} mock exam question"
      })
  except Exception as e:
    print(f"Search catalog exam questions error: {e}")

  # 9. Student's Saved AI Tutor Chat History Conversations
  try:
    if user_id:
      cursor.execute("""
        SELECT tc.id, tc.title, tc.tutor_name,
               (SELECT tm.content FROM tutor_messages tm WHERE tm.conversation_id = tc.id ORDER BY tm.id DESC LIMIT 1) as last_msg
        FROM tutor_conversations tc
        WHERE tc.student_id = ?
        ORDER BY tc.updated_at DESC, tc.id DESC
        LIMIT 12
      """, (user_id,))
      for tc in [dict(r) for r in cursor.fetchall()]:
        c_title = _clean_text(tc.get("title") or "AI Tutor Conversation")
        l_msg = _clean_text(tc.get("last_msg") or "")
        if l_msg:
          nav_items.append({
            "id": f"tutor_chat:{tc['id']}",
            "title": f"Tutor Chat: {c_title}",
            "category": "Saved AI Tutor Chat",
            "badge": "Chat History",
            "url": f"/student/tutor?chat_id={tc['id']}",
            "description": f"Continue your saved AI Tutor conversation: {_truncate(l_msg, 120)}",
            "keywords": f"tutor chat history conversation {c_title} {l_msg}"
          })
  except Exception:
    pass

  by_id = {}
  for item in nav_items:
    by_id[item["id"]] = item
  for item in question_items:
    by_id[item["id"]] = item

  return {
    "nav_items": nav_items,
    "question_items": question_items,
    "by_id": by_id
  }


STOP_WORDS = {
  "a", "an", "the", "to", "in", "on", "of", "for", "and", "or", "is", "are", "was",
  "were", "be", "can", "you", "i", "me", "my", "we", "please", "pls", "take", "go",
  "open", "show", "find", "search", "where", "what", "how", "do", "does", "want",
  "need", "navigate", "page", "section", "website", "site", "about", "from", "with"
}


def _tokenize(text: str) -> list[str]:
  words = re.findall(r"[a-z0-9]+", (text or "").lower())
  tokens = [w for w in words if w not in STOP_WORDS and len(w) >= 2]
  if not tokens and words:
    tokens = words
  return tokens


def _score_item(item: dict, raw_query: str, tokens: list[str]) -> float:
  q_lower = raw_query.lower().strip()
  title_l = (item.get("title") or "").lower()
  cat_l = (item.get("category") or "").lower()
  desc_l = (item.get("description") or "").lower()
  kw_l = (item.get("keywords") or "").lower()
  blob = f"{title_l} {cat_l} {desc_l} {kw_l}"

  score = 0.0
  if not q_lower:
    return 0.0

  # Exact substring matches
  if q_lower in title_l:
    score += 45.0
  if q_lower in cat_l:
    score += 25.0
  if q_lower in kw_l:
    score += 20.0
  if q_lower in desc_l:
    score += 12.0

  # Token-level scoring + prefix/stem matching
  matched_tokens = 0
  for tok in tokens:
    tok_matched = False
    if tok in title_l:
      score += 14.0
      tok_matched = True
    if tok in cat_l:
      score += 8.0
      tok_matched = True
    if tok in kw_l:
      score += 7.0
      tok_matched = True
    if tok in desc_l:
      score += 4.0
      tok_matched = True

    # Prefix / stem match (e.g. "reflect" -> "reflection", "coord" -> "coordination", "quad" -> "quadratic")
    if not tok_matched and len(tok) >= 4:
      stem = tok[: max(4, len(tok) - 2)]
      if stem in blob:
        score += 5.5
        tok_matched = True

    if tok_matched:
      matched_tokens += 1

  if tokens and matched_tokens == len(tokens):
    score += 18.0

  # Boost top-level navigation pages, subjects, chapters, Digi-Library studios, content & exams
  # above individual questions when the top-level destination matches the full query or title
  item_id = str(item.get("id", ""))
  if item_id.startswith(("page:", "subj:", "ch:", "digi_bank:", "digi_book:", "digi_subj:", "exam:", "content:", "ch_exams:", "draft_topic:")):
    if score > 0 and (q_lower in title_l or (tokens and matched_tokens == len(tokens))):
      score += 38.0
      if q_lower in title_l or any(tok in title_l for tok in tokens):
        score += 32.0

  return score


def instant_search_suggestions(conn, user: dict, query: str, limit: int = 8) -> dict:
  """
  Fast hybrid search for the live autocomplete dropdown as the student types.
  Returns top matching pages, subjects, chapters, Digi-Library studios, exams, and questions.
  """
  q_clean = _clean_text(query)
  catalog = build_search_catalog(conn, user)

  if not q_clean:
    # Return default curated quick-navigation destinations across the platform
    quick_ids = [
      "page:digi_library",
      "page:exams_hub",
      "page:tutor",
      "page:attempts",
      "page:settings",
      "page:profile",
    ]
    quick_items = [catalog["by_id"][i] for i in quick_ids if i in catalog["by_id"]]
    # Also append up to 3 published chapters / Digi-Library chapter banks
    for item in catalog["nav_items"]:
      if item["id"].startswith(("digi_bank:", "ch:")) and len(quick_items) < 9:
        quick_items.append(item)
    return {
      "query": "",
      "suggestions": quick_items[:limit]
    }

  tokens = _tokenize(q_clean)
  scored = []
  for item in catalog["nav_items"] + catalog["question_items"]:
    sc = _score_item(item, q_clean, tokens)
    if sc > 0:
      scored.append((sc, item))

  scored.sort(key=lambda x: x[0], reverse=True)
  top_items = [item for _, item in scored[:limit]]

  return {
    "query": q_clean,
    "suggestions": top_items
  }


def _has_explicit_nav_phrase(query: str) -> bool:
  q = (query or "").lower().strip()
  nav_patterns = [
    r"^(?:go to|take me to|open|navigate to|visit|launch|bring me to|head to)\b",
    r"\b(?:where can i|where do i|how do i|how can i)\s+(?:change|update|edit|see|view|find|open|access)\b",
    r"^(?:settings|profile|dashboard|home|digi library|digi-library|digital library|tutor|ai tutor|bella|exam history|past attempts|my attempts|my profile|my settings|change password|change voice)$"
  ]
  return any(re.search(p, q) for p in nav_patterns)


def ai_smart_search(conn, user: dict, query: str, prebuilt_catalog: dict = None) -> dict:
  """
  Uses OpenAI (OPENAI_API_KEY) as the core brain to understand the student's natural-language
  request, answer their question or explain the match, and identify the exact website
  destination(s) to navigate them to.
  """
  q_clean = _clean_text(query)
  catalog = prebuilt_catalog if prebuilt_catalog is not None else build_search_catalog(conn, user)
  by_id = catalog["by_id"]

  if not q_clean:
    return {
      "query": "",
      "understood_intent": "Browse or ask anything to navigate anywhere on SAXAZ.",
      "ai_answer": "Type any topic, question, chapter name, or website feature (like 'Digi-Library', 'Chapter 6 Control and Coordination', 'Neuron diagram', 'Change my tutor voice', or 'Past exam results') and I will take you right there!",
      "auto_navigate": False,
      "primary_destination": by_id.get("page:dashboard"),
      "results": catalog["nav_items"][:10],
      "tutor_prompt": "Help me explore my subjects and chapters"
    }

  tokens = _tokenize(q_clean)

  # Score all nav_items and question_items
  scored_nav = []
  for item in catalog["nav_items"]:
    scored_nav.append((_score_item(item, q_clean, tokens), item))
  scored_nav.sort(key=lambda x: x[0], reverse=True)

  scored_qs = []
  for item in catalog["question_items"]:
    sc = _score_item(item, q_clean, tokens)
    scored_qs.append((sc, item))
  scored_qs.sort(key=lambda x: x[0], reverse=True)

  # Build compact catalog context for OpenAI:
  # 1. Include ALL navigation items (Pages, Subjects, Chapters, Content, Exams, Digi-Library Books/Subjects/Banks)
  # 2. Include top 40 candidate questions (or representative questions across banks if lexical score is 0)
  candidate_questions = [item for sc, item in scored_qs if sc > 0][:40]
  if len(candidate_questions) < 25:
    seen_q_ids = {q["id"] for q in candidate_questions}
    for _, q_item in scored_qs:
      if q_item["id"] not in seen_q_ids:
        candidate_questions.append(q_item)
        seen_q_ids.add(q_item["id"])
      if len(candidate_questions) >= 35:
        break

  catalog_lines = []
  catalog_lines.append("=== WEBSITE PAGES, SUBJECTS, CHAPTERS, EXAMS & DIGI-LIBRARY STUDIOS ===")
  for item in catalog["nav_items"]:
    catalog_lines.append(
      f"- ID: {item['id']} | Title: {item['title']} | Category: {item['category']} | URL: {item['url']} | Info: {_truncate(item['description'], 110)}"
    )

  if candidate_questions:
    catalog_lines.append("\n=== STUDY & EXAM QUESTIONS (DEEP-LINKED TO EXACT QUESTION) ===")
    for q_item in candidate_questions:
      catalog_lines.append(
        f"- ID: {q_item['id']} | Title: {q_item['title']} | Category: {q_item['category']} | URL: {q_item['url']} | { _truncate(q_item['description'], 100) }"
      )

  catalog_text = "\n".join(catalog_lines)

  # Deterministic fallback in case OpenAI is unavailable
  fallback_matches = [item for sc, item in (scored_nav + scored_qs) if sc > 0]
  fallback_matches.sort(key=lambda it: _score_item(it, q_clean, tokens), reverse=True)
  fallback_primary = fallback_matches[0] if fallback_matches else by_id.get("page:tutor")

  if not client:
    return {
      "query": q_clean,
      "understood_intent": f"Showing website destinations and learning resources matching \"{q_clean}\".",
      "ai_answer": f"Found {len(fallback_matches)} matching destinations on SAXAZ.",
      "auto_navigate": _has_explicit_nav_phrase(q_clean) and bool(fallback_matches),
      "primary_destination": fallback_primary,
      "results": fallback_matches[:15] if fallback_matches else catalog["nav_items"][:8],
      "tutor_prompt": q_clean
    }

  system_prompt = (
    "You are the Core AI Brain and Smart Website Navigator for SAXAZ (Labour India Educational Platform). "
    "A student has typed a query into the global search/ask bar. "
    "Your job is to:\n"
    "1. Understand what the student actually meant — even if they use natural conversation, indirect descriptions, typos, synonyms, or ask a question (e.g., 'where can I change my voice' -> Settings page; 'nervous system' or 'how plants move' -> Digi-Library Chapter 6: Control and Coordination; 'heart or kidney' -> Digi-Library Chapter 5: Life Processes; 'mirror or lens' -> Physics Chapter 9: Light Reflection & Refraction; 'quadratic' -> Maths Subject Hub + AI Tutor).\n"
    "2. Identify the single best destination (`primary_destination_id`) and up to 12 relevant destination IDs (`matched_ids`) from the provided Platform Catalog.\n"
    "3. Decide whether `auto_navigate` should be true:\n"
    "   - Set `auto_navigate: true` ONLY when the student is clearly asking to navigate to, open, or find a specific page/setting/chapter/feature (e.g. 'go to digi library', 'open settings', 'take me to chapter 6', 'change my password', 'where do I change voice', 'open tutor', 'my exam history', 'settings', 'profile', 'digi library', 'control and coordination', 'life processes').\n"
    "   - Set `auto_navigate: false` when the student is searching a broad topic or asking an academic concept question (e.g. 'light', 'biology', 'neuron', 'what is photosynthesis', 'quadratic equation', 'physics') where showing your helpful AI explanation + the primary button + all related questions/chapters on the results page is best.\n"
    "4. Provide a concise, friendly `understood_intent` (1 sentence) and `ai_answer` (1-3 sentences). If they asked an academic question, give a clear, accurate mini-explanation and tell them which chapter/question covers it!\n\n"
    "Return ONLY valid JSON with this exact schema:\n"
    "{\n"
    '  "understood_intent": "string",\n'
    '  "ai_answer": "string",\n'
    '  "auto_navigate": boolean,\n'
    '  "primary_destination_id": "string (must be an exact ID from the catalog)",\n'
    '  "matched_ids": ["exact_id_1", "exact_id_2", ...],\n'
    '  "tutor_prompt": "string (a helpful prompt the student can send to AI Tutor Bella with 1 click)"\n'
    "}"
  )

  user_prompt = (
    f"Student Query: \"{q_clean}\"\n\n"
    f"Available Platform Catalog:\n{catalog_text}"
  )

  try:
    try:
      response = client.chat.completions.create(
        model="gpt-5.4-nano",
        response_format={"type": "json_object"},
        messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": user_prompt}
        ],
        temperature=0.15,
        max_completion_tokens=650
      )
    except Exception as primary_err:
      print(f"Primary search model (gpt-5.4-nano) notice: {primary_err}, falling back to gpt-5.4-mini...")
      response = client.chat.completions.create(
        model="gpt-5.4-mini",
        response_format={"type": "json_object"},
        messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": user_prompt}
        ],
        temperature=0.15,
        max_completion_tokens=650
      )
    raw_json = response.choices[0].message.content or "{}"
    ai_data = json.loads(raw_json)
  except Exception as e:
    print(f"AI Smart Search OpenAI error: {e}")
    ai_data = {}

  primary_id = str(ai_data.get("primary_destination_id") or "").strip()
  primary_dest = by_id.get(primary_id) or fallback_primary or by_id.get("page:tutor")

  matched_ids = ai_data.get("matched_ids") or []
  results = []
  seen_urls = set()

  # Ensure primary destination is first in results
  if primary_dest:
    results.append(primary_dest)
    seen_urls.add(primary_dest["url"])

  for mid in matched_ids:
    item = by_id.get(str(mid).strip())
    if item and item["url"] not in seen_urls:
      results.append(item)
      seen_urls.add(item["url"])

  # Append any strong lexical matches that OpenAI didn't include so no relevant question/chapter is missed
  for item in fallback_matches:
    if item["url"] not in seen_urls and len(results) < 16:
      results.append(item)
      seen_urls.add(item["url"])

  # If still empty, provide core helpful destinations
  if not results:
    for item in catalog["nav_items"][:6]:
      if item["url"] not in seen_urls:
        results.append(item)
        seen_urls.add(item["url"])

  understood_intent = _clean_text(ai_data.get("understood_intent") or f"Found matches on SAXAZ for \"{q_clean}\".")
  ai_answer = _clean_text(ai_data.get("ai_answer") or "")
  tutor_prompt = _clean_text(ai_data.get("tutor_prompt") or q_clean)
  auto_nav = bool(ai_data.get("auto_navigate", False)) or _has_explicit_nav_phrase(q_clean)

  return {
    "query": q_clean,
    "understood_intent": understood_intent,
    "ai_answer": ai_answer,
    "auto_navigate": auto_nav,
    "primary_destination": primary_dest,
    "results": results,
    "tutor_prompt": tutor_prompt
  }


def run_instant_suggestions(user: dict, query: str, limit: int = 8) -> dict:
  conn = get_db_connection()
  try:
    return instant_search_suggestions(conn, user, query, limit=limit)
  finally:
    conn.close()


def run_ai_smart_search(user: dict, query: str) -> dict:
  conn = get_db_connection()
  try:
    catalog = build_search_catalog(conn, user)
  finally:
    conn.close()
  return ai_smart_search(None, user, query, prebuilt_catalog=catalog)

