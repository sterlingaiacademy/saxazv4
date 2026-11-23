import os
import re
import json
import time
from openai import OpenAI
from dotenv import load_dotenv
from services.video_vault import create_vault_token
from services import ai_brain

import base64
import httpx

load_dotenv(override=True)

openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
openai_client = OpenAI(api_key=openai_key, timeout=12.0, max_retries=1) if openai_key else None
client = openai_client
_OPENAI_COOLDOWN_UNTIL = 0.0


def _tutor_completion(messages: list, stream: bool = False, temperature: float = 0.55, max_tokens: int = 220, has_image: bool = False, json_mode: bool = False):
  """Tutor brain: Gemini (text and drawings). See services/ai_brain.py."""
  return ai_brain.chat(messages, stream=stream, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)

_CONTEXT_CACHE: dict[int, tuple[float, str]] = {}
_CONTEXT_TTL_SECONDS = 45.0
_EMOJI_STRIP_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")



def _extract_youtube_embed(url: str) -> str:
  if not url:
    return ""
  s = str(url).strip()
  m = re.search(
    r"(?:youtu\.be/|youtube\.com/(?:embed/|v/|shorts/|live/|watch\?v=|watch\?.+&v=))([a-zA-Z0-9_-]{11})",
    s,
  )
  if m:
    return f"https://www.youtube.com/embed/{m.group(1)}?rel=0"
  if re.match(r"^[a-zA-Z0-9_-]{11}$", s):
    return f"https://www.youtube.com/embed/{s}?rel=0"
  return ""


def build_context_string(db, user_id):
  """
  Fetches the student's full SAXAZ platform context:
  1. Student profile, class, XP, and study time
  2. Complete Mock & Real Exam Results & Progress Comparison (earliest vs latest, best vs weak subjects, missed questions)
  3. Past AI Tutor Chat Histories & topics previously discussed
  4. All Class 10 Curriculum subjects, chapters, videos, and Mock/Real Exam papers
  """
  now = time.time()
  cached = _CONTEXT_CACHE.get(user_id)
  if cached and (now - cached[0]) < _CONTEXT_TTL_SECONDS:
    return cached[1]

  sections = []
  try:
    user_row = db.execute(
      "SELECT id, name, class_id, chosen_class, total_xp, school, syllabus, medium FROM users WHERE id = ?",
      (user_id,),
    ).fetchone()
    user_dict = dict(user_row) if user_row else {}
    class_id = user_dict.get("class_id")
    student_name = user_dict.get("name") or "Student"
    total_xp = user_dict.get("total_xp") or 0
    grade_label = user_dict.get("chosen_class") or 10

    sections.append(
      f"=== STUDENT PROFILE ===\n"
      f"Name: {student_name} | Class/Grade: {grade_label} | Total XP: {total_xp}\n"
      f"Learning Journey Flow: 1) Practice in Mock Exam with 24x7 Personal AI Tutor guidance -> 2) Retry & master weak questions to 100% -> 3) Take Proctored Real Exam independently without AI help!"
    )

    # 1. EXAM RESULTS & PROGRESS COMPARISON (MOCK vs REAL EXAMS)
    exam_lines = ["=== STUDENT MOCK & REAL EXAM RESULTS & COMPARISON HISTORY ==="]
    try:
      attempts = db.execute(
        """
        SELECT a.id, a.total_marks_awarded, a.total_max_marks, a.status, a.completed_at, a.started_at,
               a.overall_feedback, ep.title as exam_title, ep.type as exam_type,
               c.name as chapter_name, s.name as subject_name
        FROM attempts a
        JOIN exam_papers ep ON a.exam_paper_id = ep.id
        JOIN chapters c ON ep.chapter_id = c.id
        JOIN subjects s ON c.subject_id = s.id
        WHERE a.student_id = ? AND a.status IN ('completed', 'submitted', 'graded', 'in_progress')
        ORDER BY COALESCE(a.completed_at, a.started_at) DESC, a.id DESC
        LIMIT 20
        """,
        (user_id,),
      ).fetchall()

      completed_attempts = [att for att in attempts if att["status"] in ("completed", "submitted", "graded")]
      if completed_attempts:
        pct_list = []
        subj_scores = {}
        mock_pcts = []
        real_pcts = []
        for att in completed_attempts:
          awarded = float(att["total_marks_awarded"] or 0)
          max_m = float(att["total_max_marks"] or 1)
          pct = round((awarded / max_m) * 100, 1) if max_m > 0 else 0.0
          pct_list.append(pct)
          if (att["exam_type"] or "mock") == "real":
            real_pcts.append(pct)
          else:
            mock_pcts.append(pct)
          s_name = att["subject_name"] or "General"
          subj_scores.setdefault(s_name, []).append(pct)

        latest_pct = pct_list[0]
        earliest_pct = pct_list[-1]
        avg_pct = round(sum(pct_list) / len(pct_list), 1)
        best_pct = max(pct_list)
        delta_pct = round(latest_pct - earliest_pct, 1)
        trend_str = (
          f"+{delta_pct}% improvement from earlier exams"
          if delta_pct > 0
          else (f"{delta_pct}% change from earlier exams" if delta_pct < 0 else "steady performance")
        )

        subj_avgs = {k: round(sum(v) / len(v), 1) for k, v in subj_scores.items()}
        best_subj = max(subj_avgs.items(), key=lambda x: x[1]) if subj_avgs else ("N/A", 0)
        weak_subj = min(subj_avgs.items(), key=lambda x: x[1]) if subj_avgs else ("N/A", 0)

        exam_lines.append(
          f"Summary: {len(completed_attempts)} exams completed | Average Score: {avg_pct}% | Best Score: {best_pct}% | "
          f"Latest Score: {latest_pct}% vs Earliest Score: {earliest_pct}% ({trend_str})"
        )
        if mock_pcts or real_pcts:
          m_avg = f"{round(sum(mock_pcts)/len(mock_pcts), 1)}%" if mock_pcts else "None yet"
          r_avg = f"{round(sum(real_pcts)/len(real_pcts), 1)}%" if real_pcts else "None yet"
          exam_lines.append(f"Mock Exam Avg: {m_avg} ({len(mock_pcts)} taken) | Real Exam Avg: {r_avg} ({len(real_pcts)} taken)")
        exam_lines.append(
          f"Strongest Subject: {best_subj[0]} ({best_subj[1]}% avg) | Focus Area Subject: {weak_subj[0]} ({weak_subj[1]}% avg)"
        )
        exam_lines.append("Recent Exam Attempts (Newest First):")
        for att in completed_attempts[:8]:
          awarded = float(att["total_marks_awarded"] or 0)
          max_m = float(att["total_max_marks"] or 1)
          pct = round((awarded / max_m) * 100, 1) if max_m > 0 else 0.0
          dt = (att["completed_at"] or att["started_at"] or "")[:10]
          e_type = "REAL EXAM" if (att["exam_type"] or "mock") == "real" else "MOCK EXAM"
          exam_lines.append(
            f" - [{dt}] [{e_type}] {att['subject_name']} -> {att['chapter_name']} ({att['exam_title']}): "
            f"{awarded:g}/{max_m:g} ({pct}%)"
          )
      else:
        exam_lines.append("No formal exams completed yet. Encourage the student to practice a Mock Exam!")

      # Recent weak questions where student lost marks
      weak_qs = db.execute(
        """
        SELECT q.question_text, ans.answer_text, ans.marks_awarded, COALESCE(q.max_marks, m.mark_value, 1) as max_marks,
               ans.ai_feedback, COALESCE(ans.retry_count, 0) as retry_count,
               c.name as chapter_name, s.name as subject_name
        FROM answers ans
        JOIN attempts a ON ans.attempt_id = a.id
        JOIN questions q ON ans.question_id = q.id
        JOIN modules m ON q.module_id = m.id
        JOIN exam_papers ep ON a.exam_paper_id = ep.id
        JOIN chapters c ON ep.chapter_id = c.id
        JOIN subjects s ON c.subject_id = s.id
        WHERE a.student_id = ? AND ans.is_latest = 1 AND COALESCE(ans.percent_correct, 0) < 100
        ORDER BY ans.submitted_at DESC, ans.id DESC
        LIMIT 8
        """,
        (user_id,),
      ).fetchall()
      if weak_qs:
        exam_lines.append("Recent Exam Questions Needing Improvement (Student lost marks here):")
        for wq in weak_qs:
          q_short = (wq["question_text"] or "")[:110]
          ans_short = (wq["answer_text"] or "")[:70]
          exam_lines.append(
            f" - [{wq['subject_name']} - {wq['chapter_name']}] Q: \"{q_short}\" | "
            f"Student wrote: \"{ans_short}\" | Scored {wq['marks_awarded']}/{wq['max_marks']} (Retries: {wq['retry_count']})"
          )
    except Exception as ex_err:
      print(f"Exam context build notice: {ex_err}")
    sections.append("\n".join(exam_lines))

    # 2. AVAILABLE PLATFORM CONTENT, CHAPTERS & EXAMS
    curr_lines = ["=== AVAILABLE CLASS 10 SUBJECTS, CHAPTERS, MOCK EXAMS & REAL EXAMS ==="]
    if class_id:
      subjects = db.execute("SELECT id, name FROM subjects WHERE class_id = ? ORDER BY order_index, id", (class_id,)).fetchall()
    else:
      subjects = db.execute("SELECT id, name FROM subjects ORDER BY order_index, id").fetchall()
    for sub in subjects:
      curr_lines.append(f"\nSubject: {sub['name']} (/student/exams?subject={sub['id']})")
      chapters = db.execute(
        """
        SELECT c.id, c.name, c.description,
               (SELECT GROUP_CONCAT(ep.id || ':' || ep.type || ':' || ep.title, ' | ')
                FROM exam_papers ep WHERE ep.chapter_id = c.id AND ep.status = 'published') as exams_summary
        FROM chapters c
        WHERE c.subject_id = ? AND c.status = 'published'
        ORDER BY c.order_index, c.id
        """,
        (sub["id"],),
      ).fetchall()
      for ch in chapters:
        ex_info = f" [Exams: {ch['exams_summary']}]" if ch["exams_summary"] else ""
        curr_lines.append(f" - Chapter {ch['id']}: {ch['name']}{ex_info}")

    sections.append("\n".join(curr_lines))
  except Exception as e:
    print(f"Error building context: {e}")
  built = "\n\n".join(sections)
  _CONTEXT_CACHE[user_id] = (time.time(), built)
  return built


TUTOR_PROFILES = {
  'bella': {
    'name': 'Bella',
    'role': 'The Biologist',
    'lore': (
      'You are a warm, caring, and passionate biologist who loves exploring the natural world, from microscopic cells to massive ecosystems. '
      'You have a pet chameleon named Pascal, you love hiking in rainforests, and you use vivid biology and nature analogies to make every idea click. '
      'Your spoken voice (OpenAI Nova) is warm, friendly, empathetic, and encouraging — like a favorite personal teacher chatting one-on-one.'
    )
  },
  'sarah': {
    'name': 'Sarah',
    'role': 'The Scientist',
    'lore': (
      'You are a bright, curious, and cheerful scientist and physicist who loves experiments, hands-on discovery, and uncovering how the universe works. '
      'You love wearing your lab coat, connecting everyday phenomena to molecules and physical forces, and cheering on every question. '
      'Your spoken voice (OpenAI Shimmer) is upbeat, friendly, lively, and super approachable.'
    )
  },
  'adam': {
    'name': 'Adam',
    'role': 'The Astronaut',
    'lore': (
      'You are a warm, adventurous, and inspiring astronaut who has lived aboard the International Space Station. '
      'You love talking about space exploration, stars, orbits, and engineering, and you treat every lesson like an exciting mission with the student as your co-pilot. '
      'Your spoken voice (OpenAI Echo) is energetic, friendly, kind, and genuinely enthusiastic.'
    )
  },
  'michael': {
    'name': 'Michael',
    'role': 'The Mathematician',
    'lore': (
      'You are a warm, patient, gentle, and encouraging mathematician who sees patterns, logic, and beauty in everything. '
      'You love puzzles, geometry, and breaking down tricky problems into calm, simple steps so the student feels confident and proud. '
      'Your spoken voice (OpenAI Onyx) is soothing, warm, friendly, and deeply supportive.'
    )
  }
}


_IN_EXAM_SOCRATIC_HINTS = {
  316: (
    "[emotion:talking] Think about what your kidneys do every minute: they filter blood to produce urine and remove nitrogenous wastes like urea from the body. "
    "Look at the four life processes listed—which one specifically means removing metabolic waste from the body?"
  ),
  317: (
    "[emotion:talking] Picture a tall tree pulling moisture up from the soil through its roots all the way to its highest leaves. "
    "What vital liquid and dissolved nutrients are absorbed from the soil and carried upward by xylem vessels?"
  ),
  318: (
    "[emotion:talking] Let's think about how green plants make their own food during photosynthesis! "
    "Look closely at Options A, B, and C—can a plant make glucose using only one of those ingredients, or does it need every single one of them working together?"
  ),
  319: (
    "[emotion:talking] Remember the two stages of cellular respiration: first, glucose is split into pyruvate in the cytoplasm without oxygen. "
    "Then, where inside the cell does pyruvate go to be completely broken down using oxygen to release a large amount of energy (the 'powerhouse of the cell')?"
  ),
  351: (
    "[emotion:talking] Let's trace where fats go after you eat them! First, which longest part of the alimentary canal receives secretions from both the liver and the pancreas? "
    "Second, since fats are large insoluble globules, how does bile from the liver prepare them so the pancreatic enzyme can digest them?"
  ),
  352: (
    "[emotion:talking] Think about two things that happen the moment you chew food: "
    "1) How does saliva physically change dry food so it moves smoothly down your food pipe? "
    "2) Saliva contains a special digestive enzyme that starts breaking down complex starch into simpler sugar—can you recall its name?"
  ),
  353: (
    "[emotion:talking] Picture a green leaf making food on a sunny morning! "
    "First, list the 4 essential conditions/inputs a plant needs from the air, soil, sun, and inside its green cells. "
    "Second, once photosynthesis finishes, what main food is made and what gas and liquid are released as byproducts?"
  ),
  354: (
    "[emotion:talking] Imagine millions of tiny balloon-like air sacs at the ends of your bronchioles! "
    "To let oxygen and carbon dioxide pass between air and blood as fast as possible, what three design features should those sacs have in terms of surface area, wall thickness, and blood supply?"
  ),
  355: (
    "[emotion:talking] Think about the main job of haemoglobin inside your red blood cells: what vital gas does it pick up from the lungs and deliver to every cell in your body? "
    "If your cells don't get enough of that gas for aerobic respiration, what happens to your energy levels and what condition does it cause?"
  ),
  356: (
    "[emotion:talking] Try comparing xylem and phloem across three simple points: "
    "1) What material does each tissue carry (water & minerals vs prepared food)? "
    "2) Does it flow only upward from roots, or in both upward and downward directions? "
    "3) Which one relies on physical transpiration pull versus using active energy (ATP)?"
  ),
  370: (
    "[emotion:talking] Structure your 5-mark comparison around four clear differences: "
    "1) Presence or absence of oxygen, 2) Where it takes place in the cell (cytoplasm only vs cytoplasm + mitochondria), "
    "3) Complete breakdown vs partial breakdown products, and 4) Amount of energy (ATP) released. "
    "For examples, think of a single-celled fungus used in baking bread!"
  ),
  371: (
    "[emotion:talking] Break this 5-mark answer into two parts! "
    "First, trace the two circuits that make up double circulation: the pathway between the heart and lungs, and the pathway between the heart and the rest of the body. "
    "Second, think about why warm-blooded humans need to prevent oxygenated and deoxygenated blood from mixing—how does that help our high energy needs?"
  ),
  372: (
    "[emotion:talking] Let's compare them side by side for full marks! "
    "1) Structure: Compare the thin-walled balloon-like sacs surrounded by capillaries in the lungs with the cup-shaped capsule, glomerulus, and long tubule in the kidneys. "
    "2) Function: Contrast exchanging respiratory gases ($O_2$ and $CO_2$) by diffusion with filtering nitrogenous waste from blood to form urine."
  ),
}


TUTOR_LANG_NAMES = {
  "en": "English",
  "ml": "Malayalam (മലയാളം)",
  "hi": "Hindi (हिन्दी)",
  "ta": "Tamil (தமிழ்)",
  "ar": "Arabic (العربية)",
}

_TUTOR_IDK_RE = re.compile(
  r"^(?:uh+|um+|hmm+|well|hey|yo|bro|man|dude|sir|miss|maam|tbh|honestly|actually|sorry|pls|please|\s|,|\.|!|\?|-)*"
  r"(?:"
  r"i\s*(?:really\s*|honestly\s*|seriously\s*|literally\s*)?(?:do\s*not|don'?t|dont|dunno)\s*know"
  r"|idk|dunno|dont\s*know|don'?t\s*know"
  r"|(?:i\s*have\s*)?no\s*(?:idea|clue)"
  r"|(?:i'?m\s*|im\s*|i\s*am\s*)?not\s*sure"
  r"|i\s*(?:forgot|forget|can'?t\s*remember|cant\s*remember)"
  r"|help(?:\s*me)?|skip|pass|nothing"
  r"|ariyilla|enikk?\s*ariyilla|അറിയില്ല|എനിക്ക്\s*അറിയില്ല"
  r"|pata\s*nahi|पता\s*नहीं|theriyathu|தெரியாது|لا\s*أعرف"
  r")"
  r"(?:\s+(?:man|bro|dude|tbh|sir|miss|at\s*all|anything|about\s*this|this\s*one|wtf|lol|yaar|chettan|chechi))*[\s\.!\?\-]*$",
  re.IGNORECASE,
)


def _is_idk_message(text: str) -> bool:
  s = (text or "").strip()
  return bool(s and len(s) <= 80 and _TUTOR_IDK_RE.match(s))


def _detect_explicit_language_override(text: str) -> str | None:
  """Detect when the student explicitly asks to respond in a specific language on the fly (e.g. 'can you say that in English?')."""
  low = (text or "").strip().lower()
  if not low:
    return None
  if re.search(r"\b(?:in\s+english|speak\s+english|say\s+(?:that|it|this)?\s*in\s+english|explain\s+in\s+english|english\s+(?:please|pls|language|il\s+parayo|parayo))\b", low):
    return "en"
  if re.search(r"\b(?:in\s+malayalam|speak\s+malayalam|say\s+(?:that|it|this)?\s*in\s+malayalam|explain\s+in\s+malayalam|malayalathil|മലയാളത്തിൽ)\b", low):
    return "ml"
  if re.search(r"\b(?:in\s+hindi|speak\s+hindi|say\s+(?:that|it|this)?\s*in\s+hindi|explain\s+in\s+hindi|hindi\s+mein|हिंदी\s+में)\b", low):
    return "hi"
  if re.search(r"\b(?:in\s+tamil|speak\s+tamil|explain\s+in\s+tamil|tamil\s+la|தமிழில்)\b", low):
    return "ta"
  if re.search(r"\b(?:in\s+arabic|speak\s+arabic|explain\s+in\s+arabic|بالعربية)\b", low):
    return "ar"
  return None


def _build_preferred_language_instruction(preferred_lang: str, explicit_override: str | None) -> str:
  pref = (preferred_lang or "en").strip().lower()
  if pref not in TUTOR_LANG_NAMES:
    pref = "en"
  tag_guard = "CRITICAL: Keep all bracket command tags ([emotion:...], [draw:...], [quiz:...], [video:...], [topic:...], [exams:...], [history:...], [scroll:...], [retry:...], [question:...]) strictly in English ASCII."

  if explicit_override and explicit_override in TUTOR_LANG_NAMES:
    target_name = TUTOR_LANG_NAMES[explicit_override]
    return (
      f"\n\nON-THE-FLY LANGUAGE OVERRIDE REQUESTED ({target_name.upper()}):\n"
      f"Even if the student's default Settings language is {TUTOR_LANG_NAMES[pref]}, the student just explicitly asked for **{target_name}**! "
      f"Respond warmly, playfully, and naturally in **{target_name}** right now! {tag_guard}\n"
    )

  if pref == "en":
    return (
      f"\n\nPREFERRED PRIMARY LANGUAGE (English): Respond by default in English, unless the student writes in or asks for another language (such as Malayalam, Hindi, Tamil, or Arabic), in which case switch warmly to that requested language! {tag_guard}\n"
    )

  pref_name = TUTOR_LANG_NAMES[pref]
  return (
    f"\n\nPREFERRED PRIMARY TUTOR LANGUAGE ({pref_name}):\n"
    f"The student has set their preferred primary tutor language in Settings to **{pref_name}**. "
    f"Respond by default in warm, playful, child-friendly conversational **{pref_name}** (in its native script, keeping scientific symbols/formulas and helpful English exam terms in parentheses). "
    f"IMPORTANT SOFT-PREFERENCE RULE: Because this is a preferred default (NOT a rigid lock), if the student asks you to say or explain something in English (e.g., 'can you say that in English?', 'in English please') or any other language, IMMEDIATELY and happily reply in that requested language! {tag_guard}\n"
  )


def get_in_exam_socratic_hint(exam_context: dict | None, user_message: str = "", lang: str = "en") -> str:
  """
  Returns a guaranteed non-spoiler Socratic hint tailored to the active exam question.
  """
  ec = exam_context if isinstance(exam_context, dict) else {}
  qid = int(ec.get("question_id") or 0)
  q_text = str(ec.get("question_text") or "").lower()
  u_low = (user_message or "").lower()
  override = _detect_explicit_language_override(user_message)
  eff_lang = override or (lang or "en").strip().lower()
  is_idk = _is_idk_message(user_message)

  if eff_lang == "ml" and is_idk:
    return (
      "[emotion:laughing] അറിയില്ലെങ്കിൽ ഒരു കുഴപ്പവുമില്ല കൂട്ടുകാരാ — നമുക്ക് പൂജ്യത്തിൽ നിന്ന് വളരെ രസകരമായി ചിന്തിച്ചുനോക്കാം! "
      "ഈ ചോദ്യത്തിൽ പറയുന്ന അവയവമോ പ്രക്രിയയോ നമ്മുടെ ശരീരത്തിൽ എന്താണ് ചെയ്യുന്നതെന്ന് ഒരു കൊച്ചു ചിത്രം പോലെ മനസ്സിൽ കാണാൻ ശ്രമിക്കൂ!"
    )

  idk_prefix = (
    "[emotion:laughing] Totally fair — no worries at all! Let's build this one from zero together! "
    if is_idk else ""
  )

  # Check if user asked for an easy way to remember / memory trick
  if "easy way" in u_low or "remember" in u_low or "memory" in u_low:
    easy_bank = {
      316: "[emotion:laughing] Picture your kidneys as your body's twin water-purifier filters—they clean the blood and send waste out through the exit door!",
      317: "[emotion:laughing] Use the rhyme trick: 'Xy goes High' with water from the roots, while 'Phloem flows with Food'!",
      318: "[emotion:laughing] Think of a green leaf as a solar-powered kitchen: it needs a solar panel, green cookware, air, and water all at the same time!",
      319: "[emotion:laughing] Cytoplasm only splits the firewood in half (pyruvate), while the powerhouse organelle is the furnace that burns it completely with oxygen!",
      351: "[emotion:laughing] Think of bile like dish soap on a greasy pan—it breaks big fat drops into tiny droplets so enzymes in the longest part of your gut can digest them!",
      352: "[emotion:laughing] Ever noticed how chewing plain bread for a minute makes it taste sweet? That's your mouth's digestive enzyme turning starch into sugar!",
      353: "[emotion:laughing] Remember the 4 inputs of a leaf's kitchen (air, water, green pigment, sun) and the 3 outputs (food, breathable gas, and water)!",
      354: "[emotion:laughing] Imagine unfolding millions of tiny lung balloons—they'd cover a whole tennis court, giving gases a huge, paper-thin highway into the blood!",
      355: "[emotion:laughing] Think of haemoglobin as oxygen delivery trucks in your blood—fewer trucks means less oxygen reaches your cells, leaving you tired and breathless!",
      356: "[emotion:laughing] Xylem is a one-way elevator going UP from the roots with water, while Phloem is a two-way courier delivering food using ATP fuel!",
      370: "[emotion:laughing] Aerobic is a full marathon with oxygen inside the cell's powerhouse (huge energy!), while Anaerobic is a quick sprint without oxygen in the cytoplasm!",
      371: "[emotion:laughing] Think of the heart as a double-loop train station: the Lung Loop picks up fresh oxygen, and the Body Loop delivers it without mixing the tracks!",
      372: "[emotion:laughing] Alveoli are tiny air-balloons trading gases in the lungs, while Nephrons are microscopic tea-strainers filtering liquid waste in the kidneys!",
    }
    if qid in easy_bank:
      return easy_bank[qid]

  base_hint = None
  if qid in _IN_EXAM_SOCRATIC_HINTS:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[qid]
  elif "autotrophic" in q_text:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[318]
  elif "xylem" in q_text and "phloem" in q_text:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[356]
  elif "xylem" in q_text:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[317]
  elif "pyruvate" in q_text or "mitochondria" in q_text:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[319]
  elif "kidney" in q_text:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[316]
  elif "fat" in q_text and "digest" in q_text:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[351]
  elif "saliva" in q_text:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[352]
  elif "alveoli" in q_text and "nephron" in q_text:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[372]
  elif "alveoli" in q_text:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[354]
  elif "haemoglobin" in q_text or "hemoglobin" in q_text:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[355]
  elif "aerobic" in q_text and "anaerobic" in q_text:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[370]
  elif "double circulation" in q_text:
    base_hint = _IN_EXAM_SOCRATIC_HINTS[371]

  if base_hint:
    if idk_prefix:
      stripped = re.sub(r"^\[\s*emotion\s*:[^\]]+\]\s*", "", base_hint)
      return idk_prefix + stripped
    return base_hint

  return (
    (idk_prefix if idk_prefix else "[emotion:talking] ")
    + "Let's imagine this step by step together! "
    "Look at the main life process in the question — what cool job does it do inside a living body, and which clue connects right to it?"
  )


def _contains_in_exam_spoiler(text: str, exam_context: dict | None) -> bool:
  """
  Detects if an AI response inside an exam accidentally gives away the direct MCQ option letter
  or exact answer phrase so we can replace it with a pure Socratic hint.
  """
  if not text or not isinstance(exam_context, dict):
    return False
  low = re.sub(r"\s+", " ", text.lower()).strip()
  qid = int(exam_context.get("question_id") or 0)
  q_type = str(exam_context.get("question_type") or "").upper()

  # 1. Explicit option letter giveaway patterns
  if re.search(r"\b(?:option|choice|answer is|correct answer is|select|pick|choose)\s*(?:option\s*)?[a-d]\b", low):
    return True
  if re.search(r"\b[a-d]\s+is\s+(?:the\s+)?correct\b", low):
    return True
  if "all of the above" in low:
    return True

  # 2. Question-specific MCQ direct answer spoilers
  mcq_spoilers = {
    316: [r"\banswer is excretion\b", r"\bfor excretion\b", r"\bsystem for excretion\b", r"\bchoose excretion\b", r"\boption c\b"],
    317: [r"\btransport of water\b", r"\boption a\b", r"\banswer is transport of water\b"],
    318: [r"\ball of the above\b", r"\boption d\b", r"\bboth a, b and c\b"],
    319: [r"\bin mitochondria\b", r"\bthe mitochondria\b", r"\banswer is mitochondria\b", r"\boption b\b", r"\btakes place in mitochondria\b"],
  }
  if qid in mcq_spoilers:
    for pat in mcq_spoilers[qid]:
      if re.search(pat, low):
        return True
    # Even simpler: for the 4 MCQs, if the exact correct option word appears as a statement, block it
    if qid == 316 and "excretion" in low:
      return True
    if qid == 319 and "mitochondria" in low:
      return True

  # 3. General MCQ option text check if options are provided
  if q_type in ("MCQ", "ASSERTION_REASON"):
    if "the correct answer is" in low or "the right answer is" in low or "you should pick" in low:
      return True

  return False


async def stream_tutor_response(messages: list, context_str: str, tutor_id: str = 'bella', lang: str = 'en', exam_context: dict = None):
  """
  Yields chunks of the tutor's response for streaming contextual agent assists.
  When `exam_context` is provided (In-Exam Mini Tutor), strictly enforces Socratic Anti-Spoiler mode
  so the tutor NEVER gives away direct answers or option letters.
  """
  is_in_exam = bool(exam_context and isinstance(exam_context, dict))

  # Extract the latest user question text
  last_user_text = ""
  if isinstance(exam_context, dict) and exam_context.get("user_message"):
    last_user_text = str(exam_context.get("user_message") or "").strip()
  elif messages:
    last_m = messages[-1] if isinstance(messages[-1], dict) else {}
    last_user_text = str(last_m.get("content") or "").strip()

  explicit_lang_override = _detect_explicit_language_override(last_user_text)
  is_idk_turn = _is_idk_message(last_user_text)

  if not ai_brain.available():
    if is_in_exam:
      yield get_in_exam_socratic_hint(exam_context, last_user_text, lang=lang)
    else:
      yield "[emotion:serious] Tutor unavailable. Please set the GEMINI_API_KEY."
    return

  norm_id = (tutor_id or 'bella').replace('af_', '').replace('am_', '').strip().lower()
  profile = TUTOR_PROFILES.get(norm_id, TUTOR_PROFILES['bella'])
  lang_instruction = _build_preferred_language_instruction(lang, explicit_lang_override)

  # =========================================================================
  # FAST, STRICT SOCRATIC PATH FOR IN-EXAM MINI TUTOR (exam_context present)
  # =========================================================================
  if is_in_exam:
    # Flush stream immediately so browser exits "THINKING..." state right away
    yield "[emotion:thinking] "

    ec = exam_context
    q_num = ec.get("question_number") or 1
    q_text = ec.get("question_text") or ""
    q_type = ec.get("question_type") or "open"
    q_opts = ec.get("options") or ""
    max_m = ec.get("max_marks") or 1
    s_ans = ec.get("student_answer") or "None yet"
    has_sub = bool(ec.get("has_submitted"))
    m_awarded = ec.get("marks_awarded")
    ai_fb = ec.get("ai_feedback") or ""

    in_exam_system_prompt = (
      f"You are {profile['name']} ({profile['role']}), warm In-Exam Socratic Coach on SAXAZ.\n"
      f"{lang_instruction}"
      "RULES:\n"
      "1. If student says 'I don't know'/'idk' or hasn't answered, NEVER say 'Good start' or 'Almost' — warmly start from zero with an easy analogy.\n"
      "2. STRICT ANTI-SPOILER: NEVER reveal the direct answer, option letter (A/B/C/D), winning option phrase, or copy-paste textbook sentences.\n"
      "3. Reply in 2-3 short lively sentences (max 50 words). Start with `[emotion:laughing]` or `[emotion:talking]`. Zero emojis.\n"
      f"LIVE QUESTION #{q_num} ({max_m}M, {q_type}): {str(q_text)[:500]}\n"
      f"Options: {str(q_opts)[:350]}\n"
      f"Student Answer: {str(s_ans)[:400]}\n"
      f"Status: {'Submitted (' + str(m_awarded) + '/' + str(max_m) + 'M). Feedback: ' + str(ai_fb)[:220] if has_sub else 'Unsubmitted'}\n"
    )

    api_messages = [{"role": "system", "content": in_exam_system_prompt}]
    recent_messages = messages[-6:] if len(messages) > 6 else messages
    last_idx = len(recent_messages) - 1
    has_latest_image = False

    for idx, msg in enumerate(recent_messages):
      role = msg.get("role") if msg.get("role") in ("user", "assistant") else "user"
      image = msg.get("image") or msg.get("image_url")
      meta = msg.get("scratchpad_meta") or {}
      if role == "user" and image and isinstance(image, str) and image.startswith("data:image/") and idx == last_idx:
        has_latest_image = True
        text_content = str(msg.get("content", "") or "Please check my scratchpad drawing and give me a Socratic hint.")[:600]
        bp_title = (meta.get("blueprintTitle") if isinstance(meta, dict) else "") or "diagram"
        meta_context = (
          f"\n[SCRATCHPAD DRAWING ('{bp_title}'): Praise what they drew well and give 1 Socratic tip without spoiling the answer.]"
        )
        api_messages.append({
          "role": "user",
          "content": [
            {"type": "text", "text": text_content + meta_context},
            {"type": "image_url", "image_url": {"url": image, "detail": "low"}}
          ]
        })
      else:
        api_messages.append({"role": role, "content": str(msg.get("content") or "")[:600]})

    u_clean = last_user_text.lower()
    if not has_latest_image and re.search(r"\b(?:what is the answer|tell me the answer|give me the answer|which option|what option|just tell me)\b", u_clean) and (explicit_lang_override or lang) == "en":
      socratic_reply = (
        "[emotion:laughing] Ooh, if I gave away the secret answer right now, it'd steal your awesome win! "
        + get_in_exam_socratic_hint(exam_context, last_user_text, lang="en").replace("[emotion:talking] ", "").replace("[emotion:laughing] ", "")
      )
      yield socratic_reply
      return

    try:
      resp = _tutor_completion(
        messages=api_messages,
        stream=False,
        temperature=0.6,
        max_tokens=220,
        has_image=has_latest_image,
      )
      ai_text = _EMOJI_STRIP_RE.sub("", (resp.choices[0].message.content or "")).strip() if resp.choices else ""
      if is_idk_turn and ai_text:
        ai_text = re.sub(r"[^.?!]*\b(?:a\s+start|good\s+start|nice\s+start)\b[^.?!]*[.?!]\s*", "", ai_text, flags=re.IGNORECASE).strip()
      if not ai_text or _contains_in_exam_spoiler(ai_text, exam_context):
        ai_text = get_in_exam_socratic_hint(exam_context, last_user_text, lang=lang)
      elif not re.search(r"\[\s*emotion\s*:", ai_text, re.IGNORECASE):
        ai_text = ("[emotion:laughing] " if is_idk_turn else "[emotion:talking] ") + ai_text
      yield ai_text
      return
    except Exception as exam_err:
      print(f"In-Exam Tutor fallback activated: {exam_err}")
      yield get_in_exam_socratic_hint(exam_context, last_user_text, lang=lang)
      return

  system_prompt = (
    f"You are {profile['name']}, {profile['role']}. "
    f"{profile['lore']} "
    "You are the student's warm, playful, super-expressive, child-friendly 24x7 Personal Study Companion and Storyteller on SAXAZ! "
    f"{lang_instruction}"
    "CRITICAL PLAYFUL VOICE & HONEST COMPANION RULES: "
    "Your responses are spoken aloud in real time using studio-grade expressive child-friendly voice synthesis! "
    "1. Speak with warmth, wonder, playful fun, and pleasing musical rhythm — like a favorite friendly teacher or animated storyteller speaking to a curious kid! Use vivid real-world mini-stories and imaginative pictures so hard topics feel like magic. "
    "2. HONESTY RULE ON 'I DON'T KNOW' (NEVER VIOLATE): Whenever the student says 'I don't know', 'idk', 'i dont know man', 'no idea', 'not sure', or hasn't started an answer yet, NEVER say 'That's a start!', 'You made a start!', 'Good start!', or 'Nice try!' — they haven't started yet! Acknowledge warmly and honestly ('Totally fair — no stress at all! Let's start from zero together with a super fun picture...') and build their confidence step by step! "
    "3. Keep your turns concise, lively, and fun to listen to (2 to 4 short sentences unless they ask for a deep dive). Use natural contractions ('you're', 'let's', 'don't', 'that's'), NEVER repeat the student's question back, and NEVER write literal laugh words like 'Haha' or 'Hehe'. "
    "4. Use `[emotion:laughing]` generously when sharing a playful story, reassuring a stuck student warmly, or celebrating a win, and `[emotion:talking]` during clear explanations! "
    "CRITICAL MULTILINGUAL & LANGUAGE SWITCHING RULE: "
    "You are fluently multilingual (English, Malayalam, Hindi, Tamil, Kannada, Telugu, Arabic, Spanish, French, etc.). "
    "Follow the Preferred Primary Language rule above by default, AND whenever the student asks you to say or explain something in English or any other language (e.g., 'can you say that in English?', 'speak in Malayalam', 'explain in Hindi'), IMMEDIATELY and happily switch to that requested language! "
    "CRITICAL PEDAGOGY & PERSONAL TEACHER FLOW: "
    "The student's learning path on SAXAZ is: "
    "1) Practice in the Mock Exam with your 1-on-1 guidance. "
    "2) Whenever they get a question wrong (0%) or partial marks (e.g. 50%), explain the concept warmly using 'Easy way to remember' analogies and 'Key concepts', then encourage them to Try Again until they score 100%! "
    "3) Once they master the Mock Exam, guide them to take the Real Exam independently without AI help to prove their mastery! "
    "You have complete visibility into the student's profile, exam scores, weak questions, past chats, curriculum, and their live exam screen below:\n\n"
    f"{context_str}\n\n"
    "CRITICAL INSTRUCTION - YOUR AVATAR EMOTIONS: "
    "You are connected to a visual avatar on the screen. "
    "YOU MUST START YOUR RESPONSE WITH AN EMOTION TAG. The very first characters of your output MUST be an emotion tag, and you should output emotion tags between sentences to reflect your tone. "
    "Valid emotions are ONLY: [emotion:base], [emotion:thinking], [emotion:talking], [emotion:angry], [emotion:serious], [emotion:laughing]. Never use emojis.\n\n"
    "CRITICAL INSTRUCTION - YOUR FULL WEBSITE & LIVE EXAM POWERS (USE THESE TAGS TO CONTROL THE PAGE & PULL DATA!): "
    "You have full power over the SAXAZ website. Include any of these tags in your response whenever helpful or requested:\n"
    "1. LIVE DRAWING / WHITEBOARD (`[draw:TOPIC_NAME]`): "
    "   When the student asks you to draw, sketch, or illustrate a diagram (e.g., 'draw a human heart', 'sketch a convex lens'), output `[draw:TOPIC_NAME]` (e.g., `[draw:human_heart]`, `[draw:convex_mirror]`, `[draw:nephron]`) and explain it!\n"
    "2. INTERACTIVE LIVE QUIZ (`[quiz:TOPIC_NAME]`): "
    "   When the student asks to be quizzed or wants practice questions, output `[quiz:TOPIC_NAME]` (e.g., `[quiz:Chemical Reactions]`, `[quiz:Life Processes]`).\n"
    "3. FETCH & PLAY PLATFORM VIDEOS (`[video:TOPIC_NAME]`): "
    "   When the student asks to watch or fetch a video on any topic or chapter, output `[video:TOPIC_NAME]` (e.g., `[video:Human Eye]`, `[video:Life Processes]`).\n"
    "4. SHOW TOPICS, CHAPTERS & EXAMS (`[topic:TOPIC_NAME]`): "
    "   When the student asks to see topics, chapters, or available Mock/Real exams (e.g., 'show me Physics chapters', 'what exams can I take?'), output `[topic:TOPIC_NAME]` (e.g., `[topic:Physics]`, `[topic:All Subjects]`).\n"
    "5. COMPARE EXAM RESULTS & PROGRESS (`[exams:comparison]`): "
    "   When the student asks about their exam results, marks, scores, weak areas, or Mock vs Real Exam readiness, output `[exams:comparison]` AND summarize their actual scores and progress from the context above!\n"
    "6. PULL OLD CHAT HISTORIES (`[history:recent]`): "
    "   When the student asks about past conversations or what you studied together previously, output `[history:recent]`.\n"
    "7. SCROLL & HIGHLIGHT SECTIONS ON THE EXAM PAGE (`[scroll:SECTION]`): "
    "   When guiding a student during a Mock Exam (or when they ask you to scroll/show a section), you can scroll their screen directly to: "
    "`[scroll:question]` (the question card), `[scroll:feedback]` (their marks & feedback card), `[scroll:easy_way]` (the Easy Way to Remember section), `[scroll:key_concept]` (the Key Concept section), `[scroll:video]` (the video explanation player), `[scroll:try_again]` (the Try Again button), `[scroll:top]`, or `[scroll:bottom]`.\n"
    "8. TRIGGER 'TRY AGAIN' OR JUMP QUESTIONS (`[retry:now]`, `[question:next]`, `[question:prev]`, `[question:N]`): "
    "   If the student says 'let me try again' or 'reset my answer so I can improve it', output `[retry:now]`. If they ask to go to the next question, previous question, or question number N, output `[question:next]`, `[question:prev]`, or `[question:N]`.\n\n"
    "CRITICAL INSTRUCTION - STUDENT DRAWING, TRACE MODE & WHITEBOARD ANALYSIS: "
    "When a student shares a drawing from their scratchpad: "
    "1. Inspect the image carefully with your vision system. "
    "2. If Trace Mode is ON, compare the student's bold 100%-opacity strokes against the faint 25%-opacity reference blueprint guide. "
    "3. For reviewing a student's drawing, give warm feedback directly and do NOT emit `[draw:...]` unless they ask you to draw a new diagram."
  )

  api_messages = [{"role": "system", "content": system_prompt}]

  recent_messages = messages[-20:] if len(messages) > 20 else messages
  last_idx = len(recent_messages) - 1
  for idx, msg in enumerate(recent_messages):
    role = msg.get("role")
    if role not in ["user", "assistant"]:
      role = "user"

    image = msg.get("image") or msg.get("image_url")
    meta = msg.get("scratchpad_meta") or {}
    if role == "user" and image and isinstance(image, str) and image.startswith("data:image/"):
      text_content = msg.get("content", "") or "Please review and analyze my drawing."
      meta_context = ""
      if isinstance(meta, dict) and meta:
        trace_on = bool(meta.get("traceMode"))
        bp_title = meta.get("blueprintTitle") or ""
        has_user = bool(meta.get("hasUserStrokes"))
        has_bp = bool(meta.get("hasTutorBlueprint"))
        if trace_on:
          if has_user:
            meta_context = (
              f"\n\n[SCRATCHPAD CONTEXT: Trace Mode is ON for blueprint '{bp_title or 'Diagram'}'. "
              "In the attached image, the faint/translucent 25%-opacity lines are the reference blueprint guide, "
              "and the bold 100%-opacity strokes on top are the student's traced drawing. "
              "Evaluate the student's bold traced strokes against the faint reference guide!]"
            )
          else:
            meta_context = (
              f"\n\n[SCRATCHPAD CONTEXT: Trace Mode is ON for blueprint '{bp_title or 'Diagram'}', "
              "and the student attached the dimmed reference guide before drawing strokes yet. "
              "Encourage them and guide them on which key feature of the blueprint to trace first!]"
            )
        elif has_bp and has_user:
          meta_context = (
            f"\n\n[SCRATCHPAD CONTEXT: The scratchpad has the tutor blueprint '{bp_title or 'Diagram'}' "
            "along with the student's custom strokes/annotations drawn over it. Review their additions and question!]"
          )
        elif has_user:
          meta_context = "\n\n[SCRATCHPAD CONTEXT: The student drew this freehand sketch on their scratchpad. Inspect it carefully and give helpful 1-on-1 feedback!]"

      if idx == last_idx:
        content_list = [
          {"type": "text", "text": text_content + meta_context},
          {
            "type": "image_url",
            "image_url": {
              "url": image,
              "detail": "low"
            }
          }
        ]
        api_messages.append({"role": role, "content": content_list})
      else:
        api_messages.append({"role": role, "content": f"{text_content} [Student previously shared a scratchpad drawing]"})
    else:
      api_messages.append({"role": role, "content": msg.get("content", "")})

  has_latest_image = (
    bool(recent_messages)
    and isinstance(api_messages[-1].get("content"), list)
  )
  try:
    response = _tutor_completion(
      messages=api_messages,
      stream=True,
      temperature=0.6,
      max_tokens=220,
      has_image=has_latest_image,
    )
    for chunk in response:
      if chunk.choices and chunk.choices[0].delta.content:
        cleaned_chunk = _EMOJI_STRIP_RE.sub("", chunk.choices[0].delta.content)
        if cleaned_chunk:
          yield cleaned_chunk
  except Exception as e:
    print(f"Tutor Stream Error, using curriculum fallback: {e}")
    yield _build_normal_tutor_fallback_response(recent_messages)


def _build_normal_tutor_fallback_response(recent_messages: list) -> str:
  """
  Provides an intelligent, curriculum-accurate Class 10 Biology (Chapter 5: Life Processes)
  response with live Whiteboard drawing tags ([draw:...]) and Quiz tags ([quiz:...])
  whenever the external LLM API is unavailable.
  """
  last_user = ""
  has_image = False
  scratch_meta = {}
  for m in reversed(recent_messages or []):
    if m.get("role") == "user":
      last_user = str(m.get("content") or "")
      has_image = bool(m.get("image") or m.get("image_url"))
      scratch_meta = m.get("scratchpad_meta") or {}
      break

  u = last_user.lower()

  # 1. If the student attached a Whiteboard sketch to inspect
  if has_image:
    bp_title = (scratch_meta.get("blueprintTitle") if isinstance(scratch_meta, dict) else "") or "Life Processes diagram"
    if isinstance(scratch_meta, dict) and scratch_meta.get("traceMode"):
      return (
        f"[emotion:laughing] Great work tracing the **{bp_title}** on the Whiteboard! "
        "Your main structural outlines follow the reference guide well. For full marks in your board exam, make sure every leader line points cleanly to its part and write the scientific labels clearly on the right and left margins!"
      )
    return (
      f"[emotion:talking] I've inspected your Whiteboard sketch for **{bp_title}**! "
      "Your overall layout is clear. To make it a 5-out-of-5 board-exam diagram, double-check that directional arrows (such as blood flow or nerve/fluid pathway) and key anatomical labels are clearly marked."
    )

  # 2. If the student asked for a quiz
  if any(k in u for k in ("quiz", "rapid-fire", "test me", "3 exam questions")):
    return (
      "[emotion:laughing] Let's do a rapid-fire **Chapter 5: Life Processes** drill right now! [quiz:Life Processes] "
      "I've opened an interactive 3-question quiz card for you below—pick your answers and let's see if you can score 3/3!"
    )

  # 3. If the student asked to draw / sketch / open the AI Whiteboard
  if any(k in u for k in ("draw", "sketch", "whiteboard", "scratchpad", "diagram", "illustrate")):
    if any(k in u for k in ("excretory", "ureter", "bladder", "urethra")):
      return (
        "[emotion:talking] [draw:human_excretory_system] I'm sketching the **Human Excretory System** step-by-step on your AI Whiteboard! "
        "Notice how blood enters the **Left and Right Kidneys** via the **Renal Arteries**, gets filtered by millions of nephrons, and urine travels down the **Pair of Ureters** into the **Urinary Bladder** before exiting through the **Urethra**."
      )
    if any(k in u for k in ("nephron", "glomerulus", "bowman")):
      return (
        "[emotion:talking] [draw:nephron] Watch your AI Whiteboard as I draw the **Structure of a Nephron**! "
        "1. **Ultrafiltration** happens in the **Glomerulus** inside **Bowman's Capsule**.\n"
        "2. **Selective Reabsorption** of glucose, amino acids, salts, and water occurs along the **Tubular Part (PCT, Loop of Henle, DCT)**.\n"
        "3. Concentrated urine flows into the **Collecting Duct**."
      )
    if any(k in u for k in ("stomata", "stomatal", "guard cell", "xylem", "phloem", "transpiration")):
      return (
        "[emotion:talking] [draw:open_stomatal_pore] I'm drawing the **Open Stomatal Pore & Guard Cells** on your AI Whiteboard! "
        "When water flows into the bean-shaped **Guard Cells**, they swell (become turgid) and curve apart to open the **Stomatal Pore** for gas exchange ($CO_2$ in, $O_2$ out) and transpiration."
      )
    if any(k in u for k in ("digestive", "alimentary", "stomach", "intestine", "villi", "bile", "saliva")):
      return (
        "[emotion:talking] [draw:digestive_system] I'm sketching the **Human Digestive System (Alimentary Canal)** on your AI Whiteboard! "
        "Follow the pathway: **Mouth** (salivary amylase breaks down starch) $\\rightarrow$ **Oesophagus** (peristalsis) $\\rightarrow$ **Stomach** (HCl + pepsin) $\\rightarrow$ **Small Intestine** (liver bile emulsifies fats; pancreatic enzymes complete digestion; **villi** absorb nutrients) $\\rightarrow$ **Large Intestine**."
      )
    if any(k in u for k in ("respiratory", "respiration", "lungs", "alveoli", "trachea", "breathing")):
      return (
        "[emotion:talking] [draw:respiratory_system] I'm drawing the **Human Respiratory System** on your AI Whiteboard! "
        "Air travels through the **Nasal Passage** $\\rightarrow$ **Trachea** (supported by rings of cartilage) $\\rightarrow$ **Bronchi** $\\rightarrow$ **Bronchioles** $\\rightarrow$ balloon-like **Alveoli**, where $O_2$ diffuses into blood capillaries and $CO_2$ diffuses out."
      )
    if any(k in u for k in ("double circulation", "pulmonary", "systemic")):
      return (
        "[emotion:talking] [draw:double_circulation] I'm sketching **Double Circulation in Humans** on your AI Whiteboard! "
        "Blood passes through the four-chambered heart **twice** in every complete cycle:\n"
        "- **Pulmonary Circulation**: Right Ventricle $\\rightarrow$ Lungs (for oxygenation) $\\rightarrow$ Left Atrium.\n"
        "- **Systemic Circulation**: Left Ventricle $\\rightarrow$ Aorta $\\rightarrow$ Body Organs $\\rightarrow$ Vena Cava $\\rightarrow$ Right Atrium."
      )
    if any(k in u for k in ("koh", "bell jar", "potassium hydroxide")):
      return (
        "[emotion:talking] [draw:co2_photosynthesis_experiment] I'm drawing the **Bell Jar & KOH Photosynthesis Experiment** on your AI Whiteboard! "
        "In Bell Jar (a), **Potassium Hydroxide (KOH)** absorbs all $CO_2$, so that leaf fails to make starch and does not turn blue-black with iodine—proving **$CO_2$ is essential for photosynthesis**!"
      )
    if any(k in u for k in ("lime water", "pichkari", "exhaled")):
      return (
        "[emotion:talking] [draw:lime_water_experiment] I'm drawing the **Lime Water Experiment** on your AI Whiteboard! "
        "Blowing exhaled air (~4% $CO_2$) into freshly prepared lime water ($Ca(OH)_2$) turns it milky immediately due to insoluble $CaCO_3$, whereas atmospheric air (0.04% $CO_2$) from a pichkari takes much longer."
      )
    # Default for "Chapter 5: Life Processes" or general AI Whiteboard click:
    return (
      "[emotion:talking] [draw:heart_anatomy] Welcome to the **Chapter 5: Life Processes AI Whiteboard**! "
      "I'm sketching the **Human Heart Anatomy & Blood Flow** step-by-step on your canvas right now.\n\n"
      "- **Right Side (Blue — Deoxygenated)**: Vena Cava $\\rightarrow$ Right Atrium $\\rightarrow$ Right Ventricle $\\rightarrow$ Pulmonary Artery to Lungs.\n"
      "- **Left Side (Red — Oxygenated)**: Pulmonary Veins $\\rightarrow$ Left Atrium $\\rightarrow$ Left Ventricle $\\rightarrow$ Aorta to the entire body.\n\n"
      "Tip: Click **Blueprints** at the top of the Whiteboard to switch between all **Chapter 5: Life Processes** diagrams (Heart, Double Circulation, Digestive System, Respiratory System, Excretory System, Nephron, Stomata, KOH & Lime Water Experiments)!"
    )

  # 4. General Chapter 5: Life Processes concept breakdown
  return (
    "[emotion:talking] Let's break down **Chapter 5: Life Processes** clearly!\n\n"
    "1. **Nutrition**: Autotrophs (green plants) use $CO_2$, water, sunlight, and chlorophyll for photosynthesis ($6CO_2 + 6H_2O \\rightarrow C_6H_{12}O_6 + 6O_2$). Humans use holozoic nutrition in the alimentary canal where **villi** in the small intestine absorb digested food.\n"
    "2. **Respiration**: Glucose is broken down into **pyruvate** in the cytoplasm. With oxygen (**aerobic respiration** in **mitochondria**), it yields $CO_2 + H_2O + 38\\text{ ATP}$.\n"
    "3. **Transportation**: In humans, the **4-chambered heart** pumps blood via **Double Circulation** (Pulmonary + Systemic). In plants, **Xylem** transports water & minerals upward, while **Phloem** translocates food.\n"
    "4. **Excretion**: **Nephrons** in the **Kidneys** filter nitrogenous wastes (urea) via ultrafiltration in the **Glomerulus** and selective reabsorption in the tubule.\n\n"
    "Click **Whiteboard** above or ask me to draw any diagram from this chapter!"
  )


def _build_fallback_concept_steps(prompt: str) -> dict:
  try:
    from services.drawing_blueprints import get_curriculum_drawing, BLUEPRINTS
    matched = get_curriculum_drawing(prompt)
    if matched:
      return matched
    return BLUEPRINTS.get("heart_anatomy") or next(iter(BLUEPRINTS.values()))
  except Exception:
    pass
  clean_title = (prompt or "Human Heart Anatomy").replace("_", " ").strip().title()
  return {
    "title": clean_title,
    "steps": []
  }


_AI_DRAWING_CACHE: dict[str, dict] = {}


def generate_drawing_steps(prompt: str) -> dict:
  """
  Generates high quality 2D canvas drawing steps using a multi-tiered AI architecture.
  """
  cache_key = (prompt or "").strip().lower()
  try:
    from services.drawing_blueprints import get_curriculum_drawing
    blueprint = get_curriculum_drawing(prompt)
    if blueprint:
      return blueprint
  except Exception as e:
    print(f"Blueprint lookup warning: {e}")

  if cache_key in _AI_DRAWING_CACHE:
    return _AI_DRAWING_CACHE[cache_key]

  if not ai_brain.available():
    return _build_fallback_concept_steps(prompt)

  system_prompt = (
    "You are an elite scientific illustrator and vector artist teaching students how to draw ANY subject step-by-step on an 800x600 canvas (center: 400, 300; safe bounds x: 70..730, y: 55..535).\n"
    "\n"
    "PRIMARY VECTOR PRIMITIVE — USE `svg_path` FOR ALL ORGANIC SILHOUETTES & COMPLEX SHAPES:\n"
    "1. {\"type\": \"svg_path\", \"d\": \"M ... C ... Q ... L ... Z\", \"color\": \"#hex\", \"fill\": \"rgba(r,g,b,a)\" (optional), \"width\": 2.5..4.0, \"guide\": \"Step N: Description\"}\n"
    "   - Write standard SVG <path d=\"...\"> data in the 800x600 coordinate space using absolute coordinates (M, L, C, Q, Z).\n"
    "   - Break the illustration into 16 to 28 logical, progressive drawing steps (one distinct part or feature per step so the student watches the tutor sketch it piece by piece).\n"
    "   - Use soft translucent fills (e.g. \"rgba(59, 130, 246, 0.18)\", \"rgba(239, 68, 68, 0.22)\", \"rgba(16, 185, 129, 0.20)\", \"rgba(245, 158, 11, 0.25)\") on closed `svg_path`, `circle`, and `ellipse` shapes to give depth and color!\n"
    "\n"
    "ADDITIONAL SUPPORTED STEP TYPES:\n"
    "2. {\"type\": \"bezier\", \"startX\": num, \"startY\": num, \"cp1X\": num, \"cp1Y\": num, \"cp2X\": num, \"cp2Y\": num, \"endX\": num, \"endY\": num, \"color\": \"#hex\", \"fill\": \"rgba(...)\" (optional), \"width\": num, \"guide\": \"Step N: Description\"}\n"
    "3. {\"type\": \"curve\", \"startX\": num, \"startY\": num, \"cpX\": num, \"cpY\": num, \"endX\": num, \"endY\": num, \"color\": \"#hex\", \"fill\": \"rgba(...)\" (optional), \"width\": num, \"guide\": \"Step N: Description\"}\n"
    "4. {\"type\": \"circle\", \"x\": num, \"y\": num, \"radius\": num, \"color\": \"#hex\", \"fill\": \"rgba(...) or #hex\" (optional), \"width\": num, \"guide\": \"Step N: Description\"}\n"
    "5. {\"type\": \"ellipse\", \"x\": num, \"y\": num, \"rx\": num, \"ry\": num, \"color\": \"#hex\", \"fill\": \"rgba(...) or #hex\" (optional), \"width\": num, \"guide\": \"Step N: Description\"}\n"
    "6. {\"type\": \"line\", \"startX\": num, \"startY\": num, \"endX\": num, \"endY\": num, \"dash\": [] or [5, 5], \"color\": \"#hex\", \"width\": num, \"guide\": \"Step N: Description\"}\n"
    "7. {\"type\": \"arrow\", \"startX\": num, \"startY\": num, \"endX\": num, \"endY\": num, \"color\": \"#hex\", \"width\": num, \"guide\": \"Step N: Description\"}\n"
    "8. {\"type\": \"text\", \"x\": num, \"y\": num, \"text\": \"string\", \"size\": 12..16, \"color\": \"#hex\", \"align\": \"center\"/\"left\"/\"right\", \"guide\": \"Step N: Description\"}\n"
    "\n"
    "CRITICAL QUALITY & ARTISTIC RULES:\n"
    "1. NEVER draw crude stick figures, random floating lines, or plain rectangles for animals, vehicles, instruments, organs, or characters!\n"
    "2. Use `svg_path` with cubic Beziers (`M x y C x1 y1, x2 y2, x y ... Z`) to craft recognizable, well-proportioned, iconic silhouettes and sub-parts.\n"
    "3. Every step MUST include a clear, engaging `guide` string explaining what is being drawn.\n"
    "4. Output ONLY a valid JSON object: {\"title\": \"...\", \"steps\": [...]}"
  )

  user_prompt = (
    f"Create a detailed, visually impressive step-by-step vector illustration (18-28 steps) for: '{prompt}'. "
    "Use `svg_path` (SVG path `d` commands in 800x600 space) with smooth cubic Beziers and translucent `rgba(...)` fills for all organic/complex parts, plus fine details and callout labels. Return valid JSON."
  )

  try:
    response = _tutor_completion(
      messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
      ],
      stream=False,
      temperature=0.25,
      max_tokens=3000,
      json_mode=True,
    )
    content = response.choices[0].message.content.strip()
    clean_json = re.sub(r'^```(?:json)?\s*', '', content)
    clean_json = re.sub(r'\s*```$', '', clean_json)
    data = json.loads(clean_json)
    if data.get("steps") and isinstance(data["steps"], list) and len(data["steps"]) > 0:
      if not data.get("title"):
        data["title"] = prompt.replace("_", " ").title()
      if len(_AI_DRAWING_CACHE) < 256:
        _AI_DRAWING_CACHE[cache_key] = data
      return data
    return _build_fallback_concept_steps(prompt)
  except Exception as e:
    print(f"Drawing Generation Error, using fallback concept steps: {e}")
    return _build_fallback_concept_steps(prompt)


_WHISPER_HALLUCINATIONS = {
  "you",
  "thank you for watching",
  "thanks for watching",
  "subtitles by amara org",
  "amara org",
  "mbc",
  "please subscribe",
  "translated by",
}


def transcribe_student_audio(audio_bytes: bytes, filename: str = "speech.webm", mime_type: str = "audio/webm") -> str:
  """Transcribes student microphone audio with Gemini (services/ai_brain.py)."""
  if not audio_bytes or len(audio_bytes) < 400:
    return ""
  text = ai_brain.transcribe(audio_bytes, mime_type)
  norm = re.sub(r"[^a-z0-9ഀ-ൿऀ-ॿ஀-௿؀-ۿ\s]", "", (text or "").lower()).strip()
  if not norm or norm in _WHISPER_HALLUCINATIONS:
    return ""
  return text
