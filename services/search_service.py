import os
import re
import json
from openai import OpenAI
from services import ai_brain
from dotenv import load_dotenv
from database import get_db_connection

load_dotenv(override=True)

_oa_key = (os.getenv("OPENAI_API_KEY") or "").strip()
openai_client = OpenAI(api_key=_oa_key, timeout=8.0, max_retries=0) if _oa_key else None
client = openai_client


def _clean_text(val: str) -> str:
  if not val:
    return ""
  return re.sub(r"\s+", " ", str(val)).strip()


def _truncate(val: str, max_len: int = 140) -> str:
  s = _clean_text(val)
  if len(s) <= max_len:
    return s
  return s[: max_len - 3].rstrip() + "..."


def build_search_catalog(conn, user: dict) -> dict:
  """
  Builds a comprehensive, live index of every navigable destination on the platform
  for the current student:
    - Core Website Pages & Features (Dashboard, Subjects & Exams Hub, Rewards & Shop, Past Attempts, Profile, Voice Settings)
    - Enrolled Subjects (/student/exams?subject={id})
    - Published Curriculum Chapters (/student/chapters/{id}) & Chapter Exams (/student/chapters/{id}#chapter-exams)
    - Video Lessons (/student/content/{id})
    - Practice Mock Exams (/student/exams/{id}) & Proctored Real Exams (/student/real-exams/{id}/intro)
    - Past Exam Attempt Reports (/student/attempts/{id})
    - Individual Curriculum Exam Questions (/student/exams/{exam_id}?question_id={q_id}) without answer spoilers
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
      "title": "Dashboard",
      "category": "Website Page",
      "badge": "Home",
      "url": "/student/dashboard",
      "description": "Carry on with your next lesson and see your progress.",
      "keywords": "home dashboard main page start overview resume lesson progress subjects"
    },
    {
      "id": "page:exams_hub",
      "title": "Subjects & Exams",
      "category": "Website Page",
      "badge": "Exams & Subjects",
      "url": "/student/exams",
      "description": "All your subjects, chapters, mock tests and real exams.",
      "keywords": "exams subjects courses curriculum syllabus test hub practice mock exam real exam chapters"
    },
    {
      "id": "page:shop",
      "title": "Rewards & Shop",
      "category": "Website Page",
      "badge": "Rewards & Shop",
      "url": "/student/shop",
      "description": "See your coins, how to earn more, and what you can get with them.",
      "keywords": "shop rewards coins wallet redeem voucher coupon store discount balance earn coins"
    },
    {
      "id": "page:attempts",
      "title": "Quiz Points & Results",
      "category": "Website Page",
      "badge": "Results & History",
      "url": "/student/attempts",
      "description": "Your quiz points, test scores, and feedback on every answer.",
      "keywords": "quiz points exam history past attempts results scores grades report card previous exams marks review performance xp tier bronze silver gold diamond"
    },
    {
      "id": "page:profile",
      "title": "My Profile",
      "category": "Account Settings",
      "badge": "Profile",
      "url": "/student/profile",
      "description": "Change your name, photo or password.",
      "keywords": "profile account user name email avatar photo picture password change password reset password security parent portal"
    },
    {
      "id": "page:settings",
      "title": "Teacher Voice & Language",
      "category": "Account Settings",
      "badge": "Voice Settings",
      "url": "/student/profile#voice-settings",
      "description": "Pick your teacher (Bella, Sarah, Adam or Michael) and the language they speak.",
      "keywords": "settings preferences configuration voice audio tts speech language malayalam hindi tamil arabic bella sarah adam michael mute change tutor"
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
      s_desc = f"{s_name} chapters, videos and tests."
      synonyms = ""
      if s_name.lower() in ("maths", "mathematics", "math"):
        synonyms = "math maths mathematics algebra geometry trigonometry arithmetic quadratic equation equations calculus"
      elif s_name.lower() == "physics":
        synonyms = "physics science optics light reflection refraction mirror lens electricity magnetic motion force"
      elif s_name.lower() == "chemistry":
        synonyms = "chemistry science chemical reactions acids bases salts metals atoms molecules carbon"
      elif s_name.lower() == "biology":
        synonyms = "biology science life processes control coordination plants animals human body heart kidneys nutrition respiration transportation excretion"
      nav_items.append({
        "id": f"subj:{sub['id']}",
        "title": s_name,
        "category": "Curriculum Subject",
        "badge": s_name,
        "url": f"/student/exams?subject={sub['id']}",
        "description": s_desc,
        "keywords": f"{s_name} subject chapters exams lessons {synonyms}"
      })
  except Exception as e:
    print(f"Search catalog subjects error: {e}")

  # 3. Published Curriculum Chapters & Chapter Exams
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
          "category": f"{s_name} · Chapter",
          "badge": s_name,
          "url": f"/student/chapters/{ch['id']}",
          "description": c_desc,
          "keywords": f"{c_name} {s_name} chapter lesson video notes nutshell study {c_desc}"
        })
        nav_items.append({
          "id": f"ch_exams:{ch['id']}",
          "title": f"{c_name} - Chapter Exams (Mock & Real)",
          "category": f"{s_name} · Exams",
          "badge": f"{s_name} Exams",
          "url": f"/student/chapters/{ch['id']}#chapter-exams",
          "description": f"Take Practice Mock Tests or the Official Proctored Real Exam for {c_name} ({s_name}).",
          "keywords": f"{c_name} {s_name} mock exam real exam test practice"
        })
      else:
        nav_items.append({
          "id": f"draft_topic:{ch['id']}",
          "title": f"{s_name}: {c_name} (Subject Hub)",
          "category": f"{s_name} · Topic",
          "badge": s_name,
          "url": f"/student/exams?subject={ch['subject_id']}",
          "description": f"Open {s_name} Subject Hub for {c_name}.",
          "keywords": f"{c_name} {s_name} topic chapter"
        })
  except Exception as e:
    print(f"Search catalog chapters error: {e}")

  # 4. Published Video Briefs / Content Items (Videos only)
  try:
    cursor.execute("""
      SELECT ci.id, ci.title, ci.type, ci.chapter_id, c.name as chapter_name, s.name as subject_name
      FROM content_items ci
      JOIN chapters c ON ci.chapter_id = c.id
      JOIN subjects s ON c.subject_id = s.id
      WHERE c.status = 'published' AND ci.type IN ('youtube', 'video')
      ORDER BY ci.order_index, ci.id
    """)
    for item in [dict(r) for r in cursor.fetchall()]:
      i_title = _clean_text(item["title"])
      c_name = _clean_text(item["chapter_name"])
      s_name = _clean_text(item["subject_name"])
      nav_items.append({
        "id": f"content:{item['id']}",
        "title": f"{i_title}",
        "category": f"{s_name} · Video Lesson",
        "badge": "Video Lesson",
        "url": f"/student/chapters/{item['chapter_id']}#chapter-videos",
        "description": f"Chapter Summary Video Lesson inside {c_name} ({s_name}).",
        "keywords": f"{i_title} video brief lesson summary {c_name} {s_name}"
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
        cat = f"{s_name} · Proctored Real Exam"
        badge = "Real Exam"
        desc = f"Official Proctored Real Exam '{e_title}' for {c_name} ({s_name})."
      else:
        url = f"/student/exams/{ep['id']}"
        cat = f"{s_name} · Practice Mock Exam"
        badge = "Mock Exam"
        desc = f"Practice test for {c_name} ({s_name})."
      nav_items.append({
        "id": f"exam:{ep['id']}",
        "title": f"{e_title} - {c_name}",
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
          "description": f"Your answers, marks and feedback for {e_title} ({c_name}).",
          "keywords": f"attempt result report score feedback {e_title} {c_name} {s_name}"
        })
  except Exception as e:
    print(f"Search catalog attempts error: {e}")

  # 7. Curriculum Exam Questions (from published Mock Exams — zero answer spoilers!)
  try:
    cursor.execute("""
      SELECT q.id, q.question_text, ep.id as exam_id, ep.title as exam_title,
             ep.type as exam_type, c.id as chapter_id, c.name as chapter_name, s.name as subject_name
      FROM questions q
      JOIN modules m ON q.module_id = m.id
      JOIN exam_papers ep ON m.exam_paper_id = ep.id
      JOIN chapters c ON ep.chapter_id = c.id
      JOIN subjects s ON c.subject_id = s.id
      WHERE ep.status = 'published' AND c.status = 'published' AND ep.type = 'mock'
      ORDER BY ep.id, m.id, q.id
    """)
    for eq in [dict(r) for r in cursor.fetchall()]:
      q_text = _clean_text(eq["question_text"])
      e_title = _clean_text(eq["exam_title"])
      c_name = _clean_text(eq["chapter_name"])
      s_name = _clean_text(eq["subject_name"])
      question_items.append({
        "id": f"exam_q:{eq['id']}",
        "title": f"Mock Q: {_truncate(q_text, 115)}",
        "category": f"{s_name} · {e_title} ({c_name})",
        "badge": "Exam Question",
        "url": f"/student/exams/{eq['exam_id']}?question_id={eq['id']}",
        "description": f"Question from {e_title} ({c_name}).",
        "keywords": f"{q_text} {e_title} {c_name} {s_name} mock exam question"
      })
  except Exception as e:
    print(f"Search catalog exam questions error: {e}")

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

  if q_lower in title_l:
    score += 45.0
  if q_lower in cat_l:
    score += 25.0
  if q_lower in kw_l:
    score += 20.0
  if q_lower in desc_l:
    score += 12.0

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

    if not tok_matched and len(tok) >= 4:
      stem = tok[: max(4, len(tok) - 2)]
      if stem in blob:
        score += 5.5
        tok_matched = True

    if tok_matched:
      matched_tokens += 1

  if tokens and matched_tokens == len(tokens):
    score += 18.0

  item_id = str(item.get("id", ""))
  if item_id.startswith(("page:", "subj:", "ch:", "exam:", "content:", "ch_exams:", "draft_topic:")):
    if score > 0 and (q_lower in title_l or (tokens and matched_tokens == len(tokens))):
      score += 38.0
      if q_lower in title_l or any(tok in title_l for tok in tokens):
        score += 32.0

  return score


def instant_search_suggestions(conn, user: dict, query: str, limit: int = 8) -> dict:
  """
  Fast hybrid search for the live autocomplete dropdown as the student types.
  Returns top matching pages, subjects, chapters, shop, exams, and questions.
  """
  q_clean = _clean_text(query)
  catalog = build_search_catalog(conn, user)

  if not q_clean:
    quick_ids = [
      "page:exams_hub",
      "page:shop",
      "page:attempts",
      "page:settings",
      "page:profile",
    ]
    quick_items = [catalog["by_id"][i] for i in quick_ids if i in catalog["by_id"]]
    for item in catalog["nav_items"]:
      if item["id"].startswith(("ch:", "exam:")) and len(quick_items) < 9:
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
    r"\b(?:where can i|where do i|how do i|how can i)\s+(?:change|update|edit|see|view|find|open|access|redeem)\b",
    r"^(?:settings|voice settings|profile|dashboard|home|shop|rewards|coins|redeem|exam history|quiz points|past attempts|my attempts|my profile|my settings|change password|change voice)$"
  ]
  return any(re.search(p, q) for p in nav_patterns)


_AI_SEARCH_CACHE: dict[str, dict] = {}


def ai_smart_search(conn, user: dict, query: str, prebuilt_catalog: dict = None) -> dict:
  """
  Hybrid deterministic + OpenAI (`gpt-4o-mini`) navigator:
  - Serves strong local catalog matches in 0ms for $0.00 (zero LLM tokens).
  - Invokes compact cached `gpt-4o-mini` strictly when natural-language query has weak/zero literal match.
  """
  q_clean = _clean_text(query)[:180]
  catalog = prebuilt_catalog if prebuilt_catalog is not None else build_search_catalog(conn, user)
  by_id = catalog["by_id"]

  if not q_clean:
    return {
      "query": "",
      "understood_intent": "Browse or ask anything to navigate anywhere on SAXAZ.",
      "ai_answer": "Type any topic, chapter name, practice exam, or student feature (like 'Life Processes', 'Mock Test', 'Rewards & Shop', 'Change my tutor voice', or 'Quiz points') and jump right there!",
      "auto_navigate": False,
      "primary_destination": by_id.get("page:dashboard"),
      "results": catalog["nav_items"][:10],
      "tutor_prompt": "Help me explore my subjects and chapters"
    }

  tokens = _tokenize(q_clean)

  scored_nav = []
  for item in catalog["nav_items"]:
    scored_nav.append((_score_item(item, q_clean, tokens), item))
  scored_nav.sort(key=lambda x: x[0], reverse=True)

  scored_qs = []
  for item in catalog["question_items"]:
    sc = _score_item(item, q_clean, tokens)
    scored_qs.append((sc, item))
  scored_qs.sort(key=lambda x: x[0], reverse=True)

  all_scored = sorted(scored_nav + scored_qs, key=lambda x: x[0], reverse=True)
  top_score = all_scored[0][0] if all_scored else 0.0
  fallback_matches = [item for sc, item in all_scored if sc > 0]
  fallback_primary = fallback_matches[0] if fallback_matches else by_id.get("page:exams_hub")

  # Fast 0-token deterministic path whenever local catalog has a clear match (or no AI key)
  if top_score >= 38.0 or not ai_brain.available():
    top_nav_score = scored_nav[0][0] if scored_nav else 0.0
    is_direct_nav = (_has_explicit_nav_phrase(q_clean) and bool(fallback_matches)) or top_nav_score >= 95.0
    return {
      "query": q_clean,
      "understood_intent": f"Showing matches on SAXAZ for \"{q_clean}\".",
      "ai_answer": f"Found {len(fallback_matches)} matching lessons, exams, and pages.",
      "auto_navigate": is_direct_nav,
      "primary_destination": fallback_primary,
      "results": fallback_matches[:15] if fallback_matches else catalog["nav_items"][:8],
      "tutor_prompt": q_clean
    }

  cache_key = f"{user.get('class_id') or 1}:{q_clean.lower()}"
  if cache_key in _AI_SEARCH_CACHE:
    return _AI_SEARCH_CACHE[cache_key]

  candidate_questions = [item for sc, item in scored_qs if sc > 0][:12]
  catalog_lines = ["=== PAGES, SUBJECTS, CHAPTERS & EXAMS ==="]
  for item in catalog["nav_items"][:24]:
    catalog_lines.append(
      f"- ID: {item['id']} | Title: {item['title']} | Category: {item['category']}"
    )

  if candidate_questions:
    catalog_lines.append("\n=== PRACTICE QUESTIONS ===")
    for q_item in candidate_questions:
      catalog_lines.append(
        f"- ID: {q_item['id']} | Title: {q_item['title']} | Category: {q_item['category']}"
      )

  catalog_text = "\n".join(catalog_lines)

  system_prompt = (
    "You are the Smart Website Navigator for SAXAZ. "
    "A student has typed a query into the global search bar. "
    "Your job is to:\n"
    "1. Understand what the student meant — even if they use natural conversation, typos, or synonyms (e.g., 'where can I change my voice' -> Voice Settings; 'redeem coins' -> Rewards & Shop; 'heart or kidney' -> Biology Chapter: Life Processes; 'mirror or lens' -> Physics Subject Hub).\n"
    "2. Identify the single best destination (`primary_destination_id`) and up to 12 relevant destination IDs (`matched_ids`) from the provided Platform Catalog.\n"
    "3. Decide whether `auto_navigate` should be true:\n"
    "   - Set `auto_navigate: true` ONLY when the student is clearly asking to navigate to, open, or find a specific page, setting, shop, or chapter (e.g. 'open settings', 'go to shop', 'change my password', 'where do I change voice', 'my exam history', 'life processes').\n"
    "   - Set `auto_navigate: false` when the student is searching a broad topic or asking an academic concept question where showing your brief explanation + matching chapters/questions on the results page is best. Do NOT spoil exact exam answers.\n"
    "4. Provide a concise, friendly `understood_intent` (1 sentence) and `ai_answer` (1-2 sentences) with zero emojis.\n\n"
    "Return ONLY valid JSON with this exact schema:\n"
    "{\n"
    '  "understood_intent": "string",\n'
    '  "ai_answer": "string",\n'
    '  "auto_navigate": boolean,\n'
    '  "primary_destination_id": "string (must be an exact ID from the catalog)",\n'
    '  "matched_ids": ["exact_id_1", "exact_id_2", ...],\n'
    '  "tutor_prompt": "string"\n'
    "}"
  )

  user_prompt = (
    f"Student Query: \"{q_clean}\"\n\n"
    f"Available Platform Catalog:\n{catalog_text}"
  )

  try:
    response = ai_brain.chat(
      [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
      ],
      json_mode=True,
      temperature=0.15,
      max_tokens=240
    )
    raw_json = response.choices[0].message.content or "{}"
    ai_data = json.loads(raw_json)
  except Exception as e:
    print(f"AI Smart Search notice: {e}")
    ai_data = {}

  primary_id = str(ai_data.get("primary_destination_id") or "").strip()
  primary_dest = by_id.get(primary_id) or fallback_primary or by_id.get("page:exams_hub")

  matched_ids = ai_data.get("matched_ids") or []
  results = []
  seen_urls = set()

  if primary_dest:
    results.append(primary_dest)
    seen_urls.add(primary_dest["url"])

  for mid in matched_ids:
    item = by_id.get(str(mid).strip())
    if item and item["url"] not in seen_urls:
      results.append(item)
      seen_urls.add(item["url"])

  for item in fallback_matches:
    if item["url"] not in seen_urls and len(results) < 16:
      results.append(item)
      seen_urls.add(item["url"])

  if not results:
    for item in catalog["nav_items"][:6]:
      if item["url"] not in seen_urls:
        results.append(item)
        seen_urls.add(item["url"])

  understood_intent = _clean_text(ai_data.get("understood_intent") or f"Found matches on SAXAZ for \"{q_clean}\".")
  ai_answer = _clean_text(ai_data.get("ai_answer") or "")
  tutor_prompt = _clean_text(ai_data.get("tutor_prompt") or q_clean)
  auto_nav = bool(ai_data.get("auto_navigate", False)) or _has_explicit_nav_phrase(q_clean)

  out_payload = {
    "query": q_clean,
    "understood_intent": understood_intent,
    "ai_answer": ai_answer,
    "auto_navigate": auto_nav,
    "primary_destination": primary_dest,
    "results": results,
    "tutor_prompt": tutor_prompt
  }
  if len(_AI_SEARCH_CACHE) >= 256:
    _AI_SEARCH_CACHE.pop(next(iter(_AI_SEARCH_CACHE)), None)
  _AI_SEARCH_CACHE[cache_key] = out_payload
  return out_payload


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
