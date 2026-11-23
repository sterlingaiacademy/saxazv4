import os
import json
import re
import hashlib
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
openai_client = OpenAI(api_key=openai_key, timeout=12.0, max_retries=1) if openai_key else None
client = openai_client

_OPENAI_COOLDOWN_UNTIL = 0.0
# Cache wrong-MCQ coach hints by (question_prefix, normalized_selected_option, lang_code) so repeat wrong selections spend 0 tokens
_WRONG_MCQ_HINT_CACHE: dict[tuple[str, str, str], dict] = {}
# Cache written-answer evaluations and Ask-Why explanations so duplicate/repeat requests spend 0 tokens
_WRITTEN_GRADE_CACHE: dict[tuple, dict] = {}
_ASK_WHY_CACHE: dict[tuple, dict] = {}


def _chat_json_completion(messages: list, temperature: float = 0.4, max_tokens: int = 220, has_image: bool = False):
  """Single-key OpenAI JSON completion: uses `gpt-4o` strictly for image/diagram grading and `gpt-4o-mini` for all text tasks."""
  global _OPENAI_COOLDOWN_UNTIL
  if not openai_client:
    raise RuntimeError("OPENAI_API_KEY not configured")
  if time.monotonic() < _OPENAI_COOLDOWN_UNTIL:
    raise RuntimeError("OpenAI quota cooldown active")
  oa_model = "gpt-4o" if has_image else "gpt-4o-mini"
  try:
    return openai_client.chat.completions.create(
      model=oa_model,
      messages=messages,
      response_format={"type": "json_object"},
      temperature=temperature,
      max_tokens=max_tokens,
    )
  except Exception as oa_err:
    low = str(oa_err).lower()
    if "insufficient_quota" in low or "credit_balance_exhausted" in low or "no credits" in low:
      _OPENAI_COOLDOWN_UNTIL = time.monotonic() + 30.0
    raise

_EMOJI_STRIP_RE = re.compile(
  r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]"
)

SUPPORTED_TUTOR_LANGS = {
  "en": "English",
  "ml": "Malayalam (മലയാളം)",
  "hi": "Hindi (हिन्दी)",
  "ta": "Tamil (தமிழ்)",
  "ar": "Arabic (العربية)",
}


def normalize_tutor_lang(lang: str | None) -> str:
  cleaned = (lang or "en").strip().lower()
  return cleaned if cleaned in SUPPORTED_TUTOR_LANGS else "en"


def _strip_emojis(val: str) -> str:
  if not val:
    return ""
  return _EMOJI_STRIP_RE.sub("", str(val))


_IDK_PATTERNS = re.compile(
  r"^(?:uh+|um+|hmm+|well|hey|yo|bro|man|dude|sir|miss|maam|tbh|honestly|actually|sorry|pls|please|\s|,|\.|!|\?|-)*"
  r"(?:"
  r"i\s*(?:really\s*|honestly\s*|seriously\s*|literally\s*)?(?:do\s*not|don'?t|dont|dunno)\s*know"
  r"|idk"
  r"|dunno"
  r"|dont\s*know"
  r"|don'?t\s*know"
  r"|(?:i\s*have\s*)?no\s*(?:idea|clue)"
  r"|(?:i'?m\s*|im\s*|i\s*am\s*)?not\s*sure"
  r"|i\s*(?:forgot|forget|can'?t\s*remember|cant\s*remember)"
  r"|help(?:\s*me)?"
  r"|skip|pass|nothing|idk\s*man|what\s*is\s*(?:this|it)"
  r"|ariyilla|enikk?\s*ariyilla|അറിയില്ല|എനിക്ക്\s*അറിയില്ല"
  r"|pata\s*nahi|mujhe\s*nahi\s*pata|पता\s*नहीं|मुझे\s*नहीं\s*पता"
  r"|theriyathu|தெரியாது|لا\s*أعرف"
  r")"
  r"(?:\s+(?:man|bro|dude|tbh|sir|miss|at\s*all|anything|about\s*this|this\s*one|wtf|lol|yaar|chettan|chechi))*[\s\.!\?\-]*$",
  re.IGNORECASE,
)


def _is_idk_or_unsure_answer(student_answer: str) -> bool:
  s = (student_answer or "").strip()
  if not s or len(s) > 75:
    return False
  return bool(_IDK_PATTERNS.match(s))


_FAST_STRINGS = {
  "en": {
    "blank_fb": "You left this question blank — use the key scoring points below and give it a try.",
    "blank_s1": "You left this one blank — check the key scoring points right here and try again.",
    "idk_fb": "No worries if this is new — read the key scoring points below and write them in your own words.",
    "idk_s1": "No stress if you don't know it yet — read the key points here and try writing them in your own words.",
    "mcq_ok_new_fb": "Correct — {ans} is the right answer.",
    "mcq_ok_retry_fb": "Nice improvement — {ans} is the right answer.",
    "mcq_ok_new_s1": "Spot on! {ans} is right.",
    "mcq_ok_retry_s1": "Nice comeback! {ans} is right.",
    "mcq_wrong_fb": "{stu} refers to a different process than what this question asks.",
    "mcq_wrong_s1": "Not {stu} this time — check the key points below and try again.",
    "fb_easy": "{ans}",
    "fb_key": "{ans}",
    "fb_s3": "{ans}",
  },
  "ml": {
    "blank_fb": "ഇത് ഒഴിഞ്ഞുകിടക്കുകയാണല്ലോ — സാരമില്ല! താഴെയുള്ള ലളിതമായ വിശദീകരണം നോക്കി നമുക്ക് ഒരുമിച്ച് പഠിക്കാം!",
    "blank_s1": "അയ്യോ, ഇത് എഴുതിയിട്ടില്ലല്ലോ! ഒരു ടെൻഷനും വേണ്ട — നമുക്ക് വളരെ രസകരമായി ഇത് ഇപ്പോൾത്തന്നെ പഠിച്ചെടുക്കാം!",
    "idk_fb": "അറിയില്ലെന്ന് തുറന്നുപറഞ്ഞത് വളരെ നല്ല കാര്യം! ഒരു വിഷമവും വേണ്ട — നമുക്ക് ആദ്യം മുതൽ വളരെ എളുപ്പത്തിൽ ഇത് പഠിക്കാം.",
    "idk_s1": "അറിയില്ലെങ്കിൽ ഒരു കുഴപ്പവുമില്ല കൂട്ടുകാരാ! നമുക്ക് പൂജ്യത്തിൽ നിന്ന് വളരെ രസകരമായ ഒരു കഥയിലൂടെ ഇത് പഠിച്ചാലോ?",
    "mcq_ok_new_fb": "തകർത്തു! {ans} തന്നെയാണ് ശരിയായ ഉത്തരം!",
    "mcq_ok_retry_fb": "മിടുക്കൻ തിരിച്ചുവരവ്! {ans} തന്നെയാണ് ശരിയായ ഉത്തരം!",
    "mcq_ok_new_s1": "സൂപ്പർ! {ans} തന്നെയാണ് കിറുകിറുത്ത ഉത്തരം! നമുക്ക് അടുത്ത ചോദ്യത്തിലേക്ക് പോകാം!",
    "mcq_ok_retry_s1": "കൊള്ളാം, തകർപ്പൻ തിരിച്ചുവരവ്! {ans} തന്നെയാണ് ശരി! ഇനി അടുത്തതിലേക്ക് പോകാം!",
    "mcq_wrong_fb": "ഓഹോ, ചെറിയൊരു കൺഫ്യൂഷൻ പറ്റിയല്ലേ! {stu} അല്ല, {ans} ആണ് ശരിയായ ഉത്തരം. അതെങ്ങനെയെന്ന് താഴെ രസകരമായി നോക്കാം!",
    "mcq_wrong_s1": "ഓഹോ, {stu} അല്ല കേട്ടോ ഇവിടെ വരുന്നത് — {ans} ആണ് ശരിയായ ഉത്തരം! അതെങ്ങനെയെന്ന് വളരെ എളുപ്പത്തിൽ ഞാൻ പറഞ്ഞുതരാം!",
    "fb_easy": "ഇതൊരു ചെറിയ കഥയായി മനസ്സിൽ കാണൂ: {ans} ആണ് ഇവിടുത്തെ പ്രധാന താരം!",
    "fb_key": "മുഴുവൻ മാർക്കും നേടാൻ ഓർക്കേണ്ട പ്രധാന കാര്യം: {ans}",
    "fb_s3": "അപ്പോൾ ഓർത്തിരിക്കേണ്ട ഏറ്റവും പ്രധാന പോയിന്റ് ഇതാണ്: {ans}!",
  },
  "hi": {
    "blank_fb": "लगता है यह सवाल खाली रह गया — कोई बात नहीं! नीचे मज़ेदार तरीके से समझते हैं और फिर कोशिश करते हैं!",
    "blank_s1": "अरे, यह तो खाली छूट गया! कोई टेंशन नहीं — चलो इसे एक मज़ेदार ट्रिक से अभी सीख लेते हैं!",
    "idk_fb": "कोई बात नहीं दोस्त — अभी नहीं पता तो बिल्कुल टेंशन मत लो! चलो इसे बिल्कुल शुरुआत से मज़ेदार तरीके से समझते हैं।",
    "idk_s1": "अरे बिल्कुल कोई बात नहीं यार! नहीं पता तो कोई स्ट्रेस नहीं — चलो जीरो से एक मज़ेदार कहानी की तरह इसे समझते हैं!",
    "mcq_ok_new_fb": "शानदार! {ans} बिल्कुल सही जवाब है!",
    "mcq_ok_retry_fb": "क्या बात है, ज़बरदस्त वापसी! {ans} बिल्कुल सही जवाब है!",
    "mcq_ok_new_s1": "वाह, एकदम सही! {ans} बिल्कुल सटीक जवाब है! चलो अगले सवाल पर चलते हैं!",
    "mcq_ok_retry_s1": "शानदार वापसी! {ans} एकदम सही है! चलो आगे बढ़ते हैं!",
    "mcq_wrong_fb": "ओह, थोड़ा ट्रिकी था! आपने {stu} चुना, जबकि सही जवाब {ans} है। चलो नीचे आसान तरीके से समझते हैं क्यों!",
    "mcq_wrong_s1": "ओह, {stu} नहीं दोस्त — यहाँ सही जवाब {ans} है! चलो एक मज़ेदार तरीके से देखते हैं ऐसा क्यों होता है!",
    "fb_easy": "इसे एक छोटी कहानी की तरह सोचो: {ans} ही इस पूरे कॉन्सेप्ट की असली चाबी है!",
    "fb_key": "पूरे अंक पाने के लिए मुख्य बात: {ans}",
    "fb_s3": "तो याद रखने वाली सबसे खास बात यह है: {ans}!",
  },
  "ta": {
    "blank_fb": "இந்தக் கேள்வியை காலியாக விட்டுவிட்டீர்கள் — கவலையே வேண்டாம்! கீழே எளிமையாகப் புரிந்துகொண்டு மீண்டும் முயற்சிப்போம்!",
    "blank_s1": "அட, இது காலியாக இருக்கிறதே! பரவாயில்லை நண்பா — இதை ஒரு ஜாலியான கதையாக இப்போதே கற்றுக்கொள்வோம்!",
    "idk_fb": "தெரியவில்லை என்றால் எந்தக் கவலையும் வேண்டாம்! ஆரம்பத்திலிருந்து மிக எளிமையாக இதை இப்போது கற்றுக்கொள்வோம்.",
    "idk_s1": "பரவாயில்லை நண்பா, தெரியவில்லை என்றால் டென்ஷனே வேண்டாம்! வாருங்கள், பூஜ்ஜியத்திலிருந்து ஜாலியாக இதைப் புரிந்துகொள்வோம்!",
    "mcq_ok_new_fb": "அருமை! {ans} என்பது மிகச் சரியான பதில்!",
    "mcq_ok_retry_fb": "சூப்பர் முயற்சி! {ans} என்பது மிகச் சரியான பதில்!",
    "mcq_ok_new_s1": "சூப்பர் நண்பா! {ans} மிகச் சரியான பதில்! அடுத்த கேள்விக்குச் செல்வோம்!",
    "mcq_ok_retry_s1": "அசத்தல்! {ans} சரியான பதில்! அடுத்த கேள்விக்குப் போகலாம்!",
    "mcq_wrong_fb": "ஓ, சிறிய குழப்பம்! நீங்கள் {stu} தேர்வு செய்தீர்கள், ஆனால் சரியான பதில் {ans}. ஏன் என்று கீழே எளிதாகப் பார்ப்போம்!",
    "mcq_wrong_s1": "ஓ, இங்கே {stu} அல்ல நண்பா — சரியான பதில் {ans}! அது ஏன் என்று ஜாலியாகப் பார்க்கலாம்!",
    "fb_easy": "இதை ஒரு சின்னக் கதையாகக் கற்பனை செய்யுங்கள்: {ans} தான் இதன் முக்கிய நாயகன்!",
    "fb_key": "முழு மதிப்பெண் பெற முக்கியக் குறிப்பு: {ans}",
    "fb_s3": "ஆக நினைவில் வைக்க வேண்டிய முக்கிய விஷயம்: {ans}!",
  },
  "ar": {
    "blank_fb": "يبدو أنك تركت هذا السؤال فارغاً — لا تقلق أبداً! دعنا نفهمه بطريقة ممتعة وبسيطة بالأسفل!",
    "blank_s1": "يبدو أن هذا السؤال بقي فارغاً! لا تقلق يا صديقي، سنتعلم فكرته الآن بطريقة ممتعة وسهلة جداً!",
    "idk_fb": "لا بأس أبداً إن لم تكن تعرف الإجابة بعد! دعنا نبني الفكرة معاً من الصفر بطريقة ممتعة بالأسفل.",
    "idk_s1": "عادي جداً يا صديقي، لا توتر أبداً! دعنا نتعلم السر معاً من الصفر بقصة بسيطة وممتعة!",
    "mcq_ok_new_fb": "رائع! {ans} هي الإجابة الصحيحة تماماً!",
    "mcq_ok_retry_fb": "عودة ممتازة! {ans} هي الإجابة الصحيحة!",
    "mcq_ok_new_s1": "يا سلام، إجابة متقنة! {ans} صحيحة تماماً! هيا ننتقل للسؤال التالي!",
    "mcq_ok_retry_s1": "أحسنت العودة! {ans} هي الإجابة الصحيحة! لننطلق للسؤال التالي!",
    "mcq_wrong_fb": "سؤال مخادع قليلاً! اخترت {stu}، بينما الإجابة الصحيحة هي {ans}. دعنا نرى السبب بطريقة ممتعة بالأسفل!",
    "mcq_wrong_s1": "أوه، ليست {stu} هذه المرة يا بطل — الإجابة الصحيحة هي {ans}! تعال نكتشف السبب بطريقة سهلة!",
    "fb_easy": "تخيل {ans} كأنه البطل الرئيسي في هذه القصة — بمجرد تخيله ستتذكره دائماً!",
    "fb_key": "الفكرة الأساسية للعلامة الكاملة: {ans}",
    "fb_s3": "إذن النقطة الذهبية التي سنتذكرها هي: {ans}!",
  },
}


def _match_mcq_option(student_answer: str, model_answer: str):
  s_clean = re.sub(r'\s+', ' ', (student_answer or "").strip()).upper()
  m_clean = re.sub(r'\s+', ' ', (model_answer or "").strip()).upper()
  if not s_clean or not m_clean:
    return False
  if s_clean == m_clean:
    return True

  prefix_re = re.compile(r'^(?:OPTION\s+|\()?([A-E1-5])(?:\s*[\.\)\:\-]\s*|\s*$)(.*)$')
  s_match = prefix_re.match(s_clean)
  m_match = prefix_re.match(m_clean)

  s_letter = s_match.group(1) if s_match else ""
  s_body = (s_match.group(2) if s_match else s_clean).strip().rstrip('.')

  m_letter = m_match.group(1) if m_match else ""
  m_body = (m_match.group(2) if m_match else m_clean).strip().rstrip('.')

  if s_body and m_body and s_body == m_body:
    return True
  if s_letter and m_letter:
    return s_letter == m_letter
  if s_body and m_body and s_body != m_body:
    if s_body in m_body or m_body in s_body:
      return True
    return False
  return None


def _extract_fallback_wiki_terms(text_a: str, text_b: str = "") -> str:
  combined = f"{text_a or ''} {text_b or ''}"
  words = re.findall(r"[A-Za-z]{4,}", combined)
  stop = {
    "what", "which", "when", "where", "there", "their", "about", "would", "could", "should",
    "these", "those", "think", "imagine", "picture", "answer", "question", "marks", "point",
    "points", "correct", "student", "explain", "because", "through", "between", "living",
    "process", "processes", "following", "statement", "option", "buddy", "remember", "concept"
  }
  picked = []
  for w in words:
    lw = w.lower()
    if lw not in stop and lw not in [p.lower() for p in picked]:
      picked.append(w.capitalize())
      if len(picked) >= 2:
        break
  return ", ".join(picked) if picked else "Science, Education"


def _build_deep_dive_html(easy_way_text: str, key_concept_text: str, wiki_terms_raw: str = "") -> str:
  raw_terms = [t.strip().replace(" ", "_").strip("[]\"'") for t in str(wiki_terms_raw or "").split(",") if t.strip()][:2]
  if not raw_terms:
    fallback_str = _extract_fallback_wiki_terms(key_concept_text, easy_way_text)
    raw_terms = [t.strip().replace(" ", "_") for t in fallback_str.split(",") if t.strip()][:2]
  clean_wiki = ", ".join(raw_terms)
  html_parts = []
  if easy_way_text:
    html_parts.append(
      "<div id='deep-dive-easy-way' class='tutor-guided-section rounded-2xl p-4 sm:p-5 mb-4 border-2 border-[#7c3aed]/25 bg-[#7c3aed]/[0.06] transition-all duration-300'>"
      "<div class='flex items-center gap-2 text-[#7c3aed] font-black text-base sm:text-lg mb-2'>"
      "<svg class='w-5 h-5 shrink-0' fill='none' stroke='currentColor' viewBox='0 0 24 24'><path stroke-linecap='round' stroke-linejoin='round' stroke-width='2.2' d='M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z'></path></svg>"
      "<span>Easy way to remember</span>"
      "<span class='ml-auto badge badge-sm bg-[#7c3aed]/15 text-[#7c3aed] border-none font-bold'>Memory Analogy</span>"
      "</div>"
      f"<p class='text-base sm:text-[1.05rem] leading-relaxed font-medium text-base-content/90'>{easy_way_text}</p>"
      "</div>"
    )
  if key_concept_text:
    html_parts.append(
      "<div id='deep-dive-key-concept' class='tutor-guided-section rounded-2xl p-4 sm:p-5 mb-4 border-2 border-[#ea580c]/25 bg-[#ea580c]/[0.06] transition-all duration-300'>"
      "<div class='flex items-center gap-2 text-[#ea580c] font-black text-base sm:text-lg mb-2'>"
      "<svg class='w-5 h-5 shrink-0' fill='none' stroke='currentColor' viewBox='0 0 24 24'><path stroke-linecap='round' stroke-linejoin='round' stroke-width='2.2' d='M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z'></path></svg>"
      "<span>Key concept</span>"
      "<span class='ml-auto badge badge-sm bg-[#ea580c]/15 text-[#ea580c] border-none font-bold'>Core Takeaway</span>"
      "</div>"
      f"<p class='text-base sm:text-[1.05rem] leading-relaxed font-medium text-base-content/90'>{key_concept_text}</p>"
      "</div>"
    )
  if clean_wiki:
    html_parts.append(
      f"<div id='deep-dive-visual' data-wiki-terms='{clean_wiki}' class='tutor-guided-section hidden rounded-2xl p-4 sm:p-5 border-2 border-[#16a34a]/25 bg-[#16a34a]/[0.06] transition-all duration-300'>"
      "<div class='flex items-center gap-2 text-[#16a34a] font-black text-base sm:text-lg mb-2'>"
      "<svg class='w-5 h-5 shrink-0' fill='none' stroke='currentColor' viewBox='0 0 24 24'><path stroke-linecap='round' stroke-linejoin='round' stroke-width='2.2' d='M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z'></path></svg>"
      "<span>Visual explanation</span>"
      "<span class='ml-auto badge badge-sm bg-[#16a34a]/15 text-[#16a34a] border-none font-bold'>Concept Diagrams</span>"
      "</div>"
      "<div class='wiki-gallery-Slot grid grid-cols-1 sm:grid-cols-2 gap-4 mt-3'></div>"
      "</div>"
    )
  return "".join(html_parts)


def _lang_directive_for_grader(lang_code: str) -> str:
  if lang_code == "en":
    return ""
  lang_label = SUPPORTED_TUTOR_LANGS.get(lang_code, "Malayalam (മലയാളം)")
  return (
    f"\nPRIMARY TUTOR LANGUAGE PREFERENCE ({lang_label.upper()}):\n"
    f"- The student's preferred tutor language is {lang_label}. Write 'ai_feedback', 'easy_way_text', 'key_concept_text', 'spoken_1', 'spoken_2', and 'spoken_3' in warm, playful, everyday conversational {lang_label} (in its native script) so it sounds like a loving, fun native teacher talking to a child!\n"
    "- Keep key scientific terms in English in parentheses on the written cards where helpful for exams, keep 'ideal_answer' in clear exam-board English, and ALWAYS keep 'wiki_terms' in English.\n"
    "- However, if the student explicitly wrote in their answer asking to respond in English (e.g., 'explain in English'), honor their request in English.\n"
  )


def _extract_key_scoring_points(model_answer: str, max_marks: int = 2) -> list[str]:
  """The key points ARE the model answer: every sentence / line of it, in full, as its own bullet.
  Nothing is shortened or cut off, so the student sees the whole answer that scores the marks."""
  text = (model_answer or "").replace("\r", "")
  if not text.strip():
    return []
  bullets: list[str] = []
  for line in text.split("\n"):
    line = re.sub(r"\s+", " ", line).strip()
    # drop list markers like "1.", "(a)", "a)", "-", "•"
    line = re.sub(r"^(?:\(?[0-9ivxIVX]{1,4}[.)]|\(?[a-hA-H]\)|[-•*])\s+", "", line).strip()
    if not line:
      continue
    # split into sentences (never after "Dr.", "e.g.", single letters like "A." or inside decimals)
    start = 0
    for m in re.finditer(r"[.!?]\s+(?=[A-Z(])", line):
      prev_word = re.findall(r"[A-Za-z.]+$", line[start:m.start()])
      pw = prev_word[0].lower() if prev_word else ""
      if pw in _NO_SPLIT_ABBR or len(pw) == 1:
        continue
      bullets.append(line[start:m.start() + 1].strip())
      start = m.end()
    bullets.append(line[start:].strip())
  out = []
  for seg in bullets:
    if len(seg) < 2:
      continue
    # capitalise ordinary words only (keep variables / symbols like "u = -10 cm" as written)
    if re.match(r"[a-z]{2,}\b", seg):
      seg = seg[0].upper() + seg[1:]
    out.append(seg)
  return out


_NO_SPLIT_ABBR = {"dr", "mr", "mrs", "ms", "st", "sr", "jr", "no", "vs", "etc", "e.g", "i.e", "fig", "approx", "viz", "prof", "govt", "ltd"}


def _build_deterministic_memory_note(student_answer: str, model_answer: str, past_attempts: list[dict] | None, marks: float, max_marks: float = 1.0) -> str:
  if not past_attempts:
    return ""
  last = past_attempts[-1] if isinstance(past_attempts[-1], dict) else {}
  prev_ans = str(last.get("answer") or "").strip()
  prev_marks = float(last.get("marks") or 0.0)
  if not prev_ans:
    return ""
  if prev_ans.strip().lower() == (student_answer or "").strip().lower():
    return "Same answer as your previous try — use the key points above to adjust it."
  if marks > prev_marks:
    return f"Improved from your last try ({prev_marks:g} to {marks:g} marks) — add the missing point to reach full marks."
  if prev_marks >= float(max_marks or 1.0) and marks < prev_marks:
    return "You got this one right on an earlier run — review the key points above and try again."
  return "New approach compared to your last try — check the key points above to lock in full marks."


def _fallback_grade_written(question_text: str, max_marks: int, model_answer: str, student_answer: str, lang: str = "en", past_attempts: list[dict] | None = None) -> dict:
  """Deterministic keyword-overlap fallback grader when LLM API is unavailable or times out."""
  lang_code = normalize_tutor_lang(lang)
  pack = _FAST_STRINGS.get(lang_code, _FAST_STRINGS["en"])

  if _is_idk_or_unsure_answer(student_answer):
    easy = pack["fb_easy"].format(ans=model_answer)
    key = pack["fb_key"].format(ans=model_answer)
    return {
      "marks_awarded": 0.0,
      "ai_feedback": pack["idk_fb"],
      "ideal_answer": model_answer,
      "easy_way_text": easy,
      "key_concept_text": key,
      "spoken_1": pack["idk_s1"],
      "spoken_2": easy,
      "spoken_3": pack["fb_s3"].format(ans=model_answer),
      "explanation_html": _build_deep_dive_html(easy, key, _extract_fallback_wiki_terms(question_text, model_answer)),
    }

  s_clean = re.sub(r"[^a-z0-9\s]", " ", (student_answer or "").lower())
  m_clean = re.sub(r"[^a-z0-9\s]", " ", (model_answer or "").lower())
  stop_words = {
    "the", "and", "for", "that", "this", "with", "from", "are", "was", "were", "have", "has",
    "had", "not", "but", "what", "which", "when", "where", "who", "how", "why", "can", "will",
    "into", "they", "their", "them", "then", "than", "also", "such", "some", "more", "most",
    "other", "only", "very", "just", "about", "between", "through", "during", "before", "after",
    "dont", "know", "idea", "clue", "sure", "man", "bro"
  }
  m_tokens = [w for w in m_clean.split() if len(w) >= 4 and w not in stop_words]
  s_tokens = {w for w in s_clean.split() if w not in stop_words}
  if not m_tokens:
    ratio = 1.0 if len(s_clean.strip()) >= 15 else 0.0
  else:
    unique_m = set(m_tokens)
    matched = sum(1 for w in unique_m if w in s_tokens or any(sw.startswith(w[:4]) for sw in s_tokens if len(sw) >= 4))
    ratio = min(1.0, (matched / max(1, len(unique_m))) * 1.35)
    if matched == 0:
      ratio = 0.0
  raw_marks = round(float(max_marks) * ratio * 2.0) / 2.0
  marks = max(0.0, min(float(max_marks), raw_marks))
  if marks >= float(max_marks) * 0.85:
    fb = "Awesome job! You nailed the key scientific ideas clearly!"
  elif marks >= float(max_marks) * 0.5:
    fb = f"Nice work! You got part of the story right — add the remaining key points below to grab all {max_marks}/{max_marks} marks!"
  else:
    fb = "Not quite what this question is looking for yet — let's check out the fun breakdown below so it clicks right away!"
  easy = pack["fb_easy"].format(ans=model_answer)
  key = pack["fb_key"].format(ans=model_answer)
  key_pts = _extract_key_scoring_points(model_answer, max_marks)
  mem_note = _build_deterministic_memory_note(student_answer, model_answer, past_attempts, marks)
  return {
    "marks_awarded": marks,
    "ai_feedback": fb,
    "why_wrong": "" if marks >= float(max_marks) else fb,
    "key_points": [] if marks >= float(max_marks) else key_pts,
    "memory_note": mem_note,
    "spoken_short": fb,
    "ideal_answer": model_answer,
    "easy_way_text": easy,
    "key_concept_text": key,
    "spoken_1": fb,
    "spoken_2": easy,
    "spoken_3": pack["fb_s3"].format(ans=model_answer),
    "explanation_html": "",
  }


# Expected written-answer length by marks (CBSE board-style guidance)
_EXPECTED_WORDS = {2: (30, 50), 3: (50, 80), 4: (70, 100), 5: (80, 120)}


def expected_answer_words(max_marks) -> tuple[int, int] | None:
  try:
    m = int(round(float(max_marks or 0)))
  except (TypeError, ValueError):
    return None
  if m < 2:
    return None
  return _EXPECTED_WORDS.get(m, (80, 120) if m > 5 else None)


def answer_length_note(student_answer: str, max_marks) -> str:
  """Friendly note when a written answer is clearly too short for its marks (empty string otherwise)."""
  exp = expected_answer_words(max_marks)
  if not exp:
    return ""
  words = len(re.findall(r"[A-Za-z0-9\u0D00-\u0D7F\u0900-\u097F\u0B80-\u0BFF\u0600-\u06FF]+", student_answer or ""))
  if words == 0 or words >= int(exp[0] * 0.6):
    return ""
  m = int(round(float(max_marks)))
  return f"Too short for {m} marks: you wrote {words} words. Aim for about {exp[0]}-{exp[1]} words."


_MCQ_WHY_CACHE: dict[tuple, str] = {}


def mcq_why_key(question_text: str, model_answer: str, chosen: str = "", lang: str = "en") -> str:
  """Stable id for one explanation: question + correct answer + (wrong) choice + language."""
  lang_code = normalize_tutor_lang(lang)
  ans_parts = [ln.strip() for ln in (model_answer or "").splitlines() if ln.strip()]
  short_ans = ans_parts[0] if ans_parts else (model_answer or "").strip()
  chosen_clean = re.sub(r'^[A-Ea-e][\.\)\s:-]+', '', (chosen or "").strip()).strip()
  picked_right = bool(chosen) and _match_mcq_option(chosen, model_answer) is True
  raw = "|".join([(question_text or "").strip()[:200], short_ans.lower(), "" if picked_right else chosen_clean.lower(), lang_code])
  return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def explain_mcq_answer(question_text: str, options: list, model_answer: str, chosen: str = "", lang: str = "en", with_source: bool = False):
  """A very short, kid-friendly reason why the correct option is right (cached per question + choice).
  with_source=True returns (why, came_from_ai)."""
  lang_code = normalize_tutor_lang(lang)
  ans_parts = [ln.strip() for ln in (model_answer or "").splitlines() if ln.strip()]
  short_ans = ans_parts[0] if ans_parts else (model_answer or "").strip()
  chosen_clean = re.sub(r'^[A-Ea-e][\.\)\s:-]+', '', (chosen or "").strip()).strip()
  picked_right = bool(chosen) and _match_mcq_option(chosen, model_answer) is True
  key = (question_text.strip()[:200], short_ans.lower(), "" if picked_right else chosen_clean.lower(), lang_code)
  if key in _MCQ_WHY_CACHE:
    return (_MCQ_WHY_CACHE[key], True) if with_source else _MCQ_WHY_CACHE[key]
  why = ""
  if client:
    try:
      sys_msg = (
        "You are a friendly Class 10 science tutor. In at most 2 short sentences (under 40 words total), "
        "explain simply why the correct option is right. If the student picked a different option, "
        "add a few words on why that one does not fit. Plain words a 15-year-old understands. No emojis. "
        "Return JSON: {'why': '...'}" + _lang_directive_for_grader(lang_code)
      )
      opts_txt = " | ".join(f"{chr(65 + i)}. {str(o).strip()}" for i, o in enumerate(options or []))
      usr = f"Question: {question_text}\nOptions: {opts_txt}\nCorrect: {short_ans}\n"
      if chosen_clean and not picked_right:
        usr += f"Student picked: {chosen_clean}\n"
      r = _chat_json_completion(
        messages=[{"role": "system", "content": sys_msg}, {"role": "user", "content": usr}],
        temperature=0.3,
        max_tokens=120,
      )
      raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", (r.choices[0].message.content or "{}").strip())
      why = _strip_emojis(str(json.loads(raw).get("why") or "")).strip()
    except Exception as e:
      print(f"MCQ why notice: {e}")
  from_ai = bool(why)
  if not why:
    extra = " ".join(ans_parts[1:]).strip()
    why = extra or f"The correct answer is {short_ans}."
  if from_ai:
    _MCQ_WHY_CACHE[key] = why
  return (why, from_ai) if with_source else why


def grade_answer(
  question_text: str,
  max_marks: int,
  model_answer: str,
  student_answer: str,
  previous_answer: str = None,
  question_type: str = 'LONG_ANSWER',
  drawing_data_url: str = None,
  lang: str = "en",
  past_attempts: list[dict] | None = None,
) -> dict:
  """
  Evaluates a student's answer with instantaneous (<10ms) deterministic fast-paths for Blank, "I don't know", and MCQs,
  plus concise kid-friendly grading with Key Mark-Scoring Points and Adaptive Past-Answer Memory.
  """
  lang_code = normalize_tutor_lang(lang)
  pack = _FAST_STRINGS.get(lang_code, _FAST_STRINGS["en"])
  has_drawing = bool(drawing_data_url and drawing_data_url.startswith("data:image/"))
  s_raw = (student_answer or "").strip()[:1500]
  student_answer = s_raw
  history_list = list(past_attempts or [])
  if not history_list and previous_answer:
    history_list = [{"answer": str(previous_answer)[:600], "marks": 0.0}]

  # 1. FAST-PATH FOR EMPTY ANSWERS (0ms)
  if not s_raw or s_raw.lower() in ["no answer provided", "none", "n/a", "no answer", "blank"]:
    if not has_drawing:
      key_pts = _extract_key_scoring_points(model_answer, max_marks)
      return {
        "marks_awarded": 0,
        "ai_feedback": pack["blank_fb"],
        "why_wrong": pack["blank_fb"],
        "key_points": key_pts,
        "memory_note": _build_deterministic_memory_note(s_raw, model_answer, history_list, 0.0),
        "spoken_short": pack["blank_s1"],
        "ideal_answer": model_answer,
        "easy_way_text": "",
        "key_concept_text": "; ".join(key_pts),
        "spoken_1": pack["blank_s1"],
        "spoken_2": "",
        "spoken_3": "",
        "explanation_html": "",
      }

  # 2. HONEST, WARM FAST-PATH FOR "I DON'T KNOW" / "IDK MAN" / "NO IDEA" (NEVER says "That's a start"!)
  if not has_drawing and _is_idk_or_unsure_answer(s_raw):
    key_pts = _extract_key_scoring_points(model_answer, max_marks)
    return {
      "marks_awarded": 0,
      "ai_feedback": pack["idk_fb"],
      "why_wrong": pack["idk_fb"],
      "key_points": key_pts,
      "memory_note": _build_deterministic_memory_note(s_raw, model_answer, history_list, 0.0),
      "spoken_short": pack["idk_s1"],
      "ideal_answer": model_answer,
      "easy_way_text": "",
      "key_concept_text": "; ".join(key_pts),
      "spoken_1": pack["idk_s1"],
      "spoken_2": "",
      "spoken_3": "",
      "explanation_html": "",
    }

  # 3. DETERMINISTIC GRADING + CACHED WRONG-OPTION COACHING FOR MCQs
  if question_type in ['MCQ', 'ASSERTION_REASON']:
    is_match = _match_mcq_option(student_answer, model_answer)
    if is_match is True:
      ans_parts = [ln.strip() for ln in (model_answer or "").splitlines() if ln.strip()]
      short_ans = ans_parts[0] if ans_parts else model_answer
      extra_ans = " ".join(ans_parts[1:]).strip()
      fb_msg = (pack["mcq_ok_retry_fb"] if history_list else pack["mcq_ok_new_fb"]).format(ans=short_ans)
      if extra_ans:
        fb_msg = f"{fb_msg} {extra_ans}"
      spoken_msg = (pack["mcq_ok_retry_s1"] if history_list else pack["mcq_ok_new_s1"]).format(ans=short_ans)
      mem_ok = "Awesome comeback — you switched from your previous choice to the exact right option!" if history_list else ""
      return {
        "marks_awarded": max_marks,
        "ai_feedback": fb_msg,
        "why_wrong": "",
        "key_points": [],
        "memory_note": mem_ok,
        "spoken_short": spoken_msg,
        "ideal_answer": model_answer,
        "easy_way_text": "",
        "key_concept_text": "",
        "spoken_1": spoken_msg,
        "spoken_2": "",
        "spoken_3": "",
        "explanation_html": "",
      }
    elif is_match is False:
      ans_parts = [ln.strip() for ln in (model_answer or "").splitlines() if ln.strip()]
      short_ans = ans_parts[0] if ans_parts else (model_answer or "").strip()
      plain = f"The correct answer is {short_ans}."
      return {
        "marks_awarded": 0,
        "ai_feedback": plain,
        "why_wrong": plain,
        "key_points": [],
        "memory_note": "",
        "spoken_short": plain,
        "ideal_answer": model_answer,
        "easy_way_text": "",
        "key_concept_text": "",
        "spoken_1": plain,
        "spoken_2": "",
        "spoken_3": "",
        "explanation_html": "",
      }

  if not client:
    return _fallback_grade_written(question_text, max_marks, model_answer, student_answer, lang=lang_code, past_attempts=history_list)

  prev_sig = "|".join(f"{str(h.get('answer') or '').strip().lower()[:80]}:{float(h.get('marks') or 0):g}" for h in history_list[-2:])
  written_cache_k = (question_text.strip()[:140], s_raw.lower(), prev_sig, float(max_marks), lang_code)
  if not has_drawing and written_cache_k in _WRITTEN_GRADE_CACHE:
    return dict(_WRITTEN_GRADE_CACHE[written_cache_k])

  is_wrong_mcq = False

  system_prompt = (
    "Concise science examiner & tutor. Rules: "
    "If marks_awarded==0, NEVER say 'Good start' or 'Almost'. No filler, no emojis. "
    "Scale marks fairly vs Model Answer."
    + _lang_directive_for_grader(lang_code)
  )
  if history_list:
    system_prompt += " Set 'memory_note' (max 14 words) comparing this try to Past Attempts."
  if has_drawing:
    system_prompt += " Grade attached handwritten diagram alongside text."

  system_prompt += (
    "\nReturn JSON: {'marks_awarded': number, 'ai_feedback': '<1 short sentence>', "
    "'why_wrong': '<empty if full marks, else max 20 words>', "
    "'key_points': ['<4-8 word missing point>'], "
    "'memory_note': '<empty if no history>', "
    "'spoken_short': '<12-18 word warm spoken line>'}"
  )

  user_prompt = (
    f"Q ({max_marks}M): {question_text}\n"
    f"Model: {model_answer}\n"
    f"Student: {student_answer}\n"
  )
  exp_len = expected_answer_words(max_marks)
  if exp_len and not has_drawing:
    n_words = len(re.findall(r"[A-Za-z0-9\u0D00-\u0D7F\u0900-\u097F\u0B80-\u0BFF\u0600-\u06FF]+", student_answer or ""))
    user_prompt += (
      f"Length: a {max_marks}-mark answer should be about {exp_len[0]}-{exp_len[1]} words; the student wrote {n_words}. "
      "An answer far shorter than expected usually misses scoring points: do not give full marks unless it still covers every point.\n"
    )
  if history_list:
    hist_lines = [f"Try#{i+1}({float(h.get('marks') or 0):g}/{max_marks}): {str(h.get('answer') or '')[:90]}" for i, h in enumerate(history_list[-2:])]
    user_prompt += "Past: " + " | ".join(hist_lines) + "\n"

  user_message_content = [{"type": "text", "text": user_prompt}]
  if has_drawing:
    user_message_content.append({
      "type": "image_url",
      "image_url": {"url": drawing_data_url, "detail": "low"}
    })

  try:
    response = _chat_json_completion(
      messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message_content}
      ],
      temperature=0.35,
      max_tokens=220,
      has_image=has_drawing,
    )

    raw_content = response.choices[0].message.content.strip()
    raw_content = re.sub(r'^```(?:json)?\s*', '', raw_content)
    raw_content = re.sub(r'\s*```$', '', raw_content)
    result = json.loads(raw_content)

    marks = 0.0 if is_wrong_mcq else round(min(max(float(result.get("marks_awarded", 0)), 0), max_marks), 1)
    ideal_ans = _strip_emojis(result.get("ideal_answer") or model_answer)
    ai_fb = _strip_emojis(result.get("ai_feedback") or "Reviewed!").strip()
    why_wrong = _strip_emojis(result.get("why_wrong") or "").strip()
    raw_kp = result.get("key_points")
    if isinstance(raw_kp, list):
      key_points = [_strip_emojis(str(x)).strip(" •-*") for x in raw_kp if str(x).strip()][:3]
    else:
      key_points = []
    memory_note = _strip_emojis(result.get("memory_note") or "").strip()
    spoken_short = _strip_emojis(result.get("spoken_short") or result.get("spoken_1") or "").strip()

    # Safety scrub: never allow "a start" / "good start" when marks == 0
    if marks == 0:
      for bad_phrase in ("a start", "good start", "nice start"):
        if bad_phrase in ai_fb.lower():
          ai_fb = pack["idk_fb"]
        if bad_phrase in why_wrong.lower():
          why_wrong = pack["idk_fb"]
        if bad_phrase in spoken_short.lower():
          spoken_short = pack["idk_s1"]

    if history_list and not memory_note:
      memory_note = _build_deterministic_memory_note(student_answer, model_answer, history_list, marks, max_marks)

    if marks >= max_marks:
      why_wrong = ""
      key_points = []
      if not spoken_short:
        spoken_short = ai_fb or pack["mcq_ok_new_s1"].format(ans=ideal_ans)
    else:
      if not why_wrong:
        why_wrong = ai_fb
      # Key points always come straight from the model answer (the AI's short paraphrases were not helpful)
      key_points = _extract_key_scoring_points(model_answer, max_marks) or key_points
      if not spoken_short:
        spoken_short = why_wrong

    out_grade = {
      "marks_awarded": marks,
      "ai_feedback": ai_fb,
      "why_wrong": why_wrong,
      "key_points": key_points,
      "memory_note": memory_note,
      "spoken_short": spoken_short,
      "ideal_answer": ideal_ans,
      "easy_way_text": "",
      "key_concept_text": "; ".join(key_points),
      "spoken_1": spoken_short,
      "spoken_2": "",
      "spoken_3": "",
      "explanation_html": "",
    }
    if not has_drawing:
      if len(_WRITTEN_GRADE_CACHE) >= 256:
        _WRITTEN_GRADE_CACHE.pop(next(iter(_WRITTEN_GRADE_CACHE)), None)
      _WRITTEN_GRADE_CACHE[written_cache_k] = dict(out_grade)
    return out_grade
  except Exception as e:
    print(f"Grading Error (using fallback grader): {e}")
    if is_wrong_mcq:
      stu_clean = re.sub(r'^[A-Da-d][\.\)\s:-]+', '', s_raw).strip() or s_raw
      why_msg = f"'{stu_clean}' describes a different process than the specific function asked in this question."
      stem_clean = re.split(r'\([A-Da-d]\)|\b[A-D]\.', question_text)[0].strip().rstrip(':?- ')
      clues = [
        f"Focus on the exact organ or mechanism mentioned: {stem_clean[:95]}",
        "Match that biological function to the system responsible for carrying it out",
      ]
      mem_msg = _build_deterministic_memory_note(student_answer, model_answer, history_list, 0.0, max_marks)
      return {
        "marks_awarded": 0,
        "ai_feedback": why_msg,
        "why_wrong": why_msg,
        "key_points": clues,
        "memory_note": mem_msg,
        "spoken_short": why_msg,
        "ideal_answer": model_answer,
        "easy_way_text": "",
        "key_concept_text": "; ".join(clues),
        "spoken_1": why_msg,
        "spoken_2": "",
        "spoken_3": "",
        "explanation_html": "",
      }
    return _fallback_grade_written(question_text, max_marks, model_answer, student_answer, lang=lang_code, past_attempts=history_list)


def grade_digi_answer(question_text: str, model_answer: str, student_answer: str, previous_answer: str = None, question_type: str = 'CUSTOM', drawing_data_url: str = None) -> dict:
  s_raw = (student_answer or "").strip()
  if not s_raw or s_raw.lower() in ["no answer provided", "none", "n/a", "no answer", "blank"]:
    if not drawing_data_url or not drawing_data_url.startswith("data:image/"):
      return {
        "is_correct": False,
        "marks_awarded": 0,
        "ai_feedback": "No answer was provided for this question.",
        "ideal_answer": model_answer
      }

  if question_type in ['MCQ', 'ASSERTION_REASON']:
    is_match = _match_mcq_option(student_answer, model_answer)
    if is_match is True:
      return {
        "is_correct": True,
        "marks_awarded": 1,
        "ai_feedback": "Great job! You improved from your previous attempt by selecting the correct option." if previous_answer else "Correct! You selected the right option.",
        "ideal_answer": model_answer
      }
    elif is_match is False:
      return {
        "is_correct": False,
        "marks_awarded": 0,
        "ai_feedback": "Wrong option selected. Review the concept and try again." if previous_answer else "Wrong option selected.",
        "ideal_answer": model_answer
      }

  if not client:
    return {
      "is_correct": False,
      "marks_awarded": 0,
      "ai_feedback": "Automated evaluation unavailable. Please contact the administrator to set the OpenAI API Key.",
      "ideal_answer": model_answer
    }

  system_prompt = (
    "You are a warm, encouraging teacher evaluating a student's practice question answer in a Question Bank. "
    "IMPORTANT: Do NOT mention marks, scores, or points anywhere in your feedback. "
    "Determine whether the student's answer is conceptually CORRECT or WRONG compared to the Model Answer, and provide clear, friendly feedback. "
    "If the student says 'I don't know', never call it 'a start' — kindly explain the idea from scratch."
  )
  if previous_answer:
    system_prompt += " Compare their new answer to their previous answer and explain how they improved."
  if drawing_data_url and drawing_data_url.startswith("data:image/"):
    system_prompt += "\nInspect the attached image of their handwritten work alongside any text."

  system_prompt += (
    "\nReturn strictly a JSON object with keys: 'is_correct' (boolean), 'ai_feedback' (string), and 'ideal_answer' (string)."
  )

  user_prompt = f"Question: {question_text}\nModel Answer: {model_answer}\nStudent Answer: {student_answer}\n"
  if previous_answer:
    user_prompt += f"Previous Answer: {previous_answer}\n"

  user_message_content = [{"type": "text", "text": user_prompt}]
  if drawing_data_url and drawing_data_url.startswith("data:image/"):
    user_message_content.append({"type": "image_url", "image_url": {"url": drawing_data_url}})

  try:
    response = _chat_json_completion(
      messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message_content}
      ],
      temperature=0.3,
      max_tokens=220,
      has_image=bool(drawing_data_url and drawing_data_url.startswith("data:image/")),
    )
    raw_content = response.choices[0].message.content.strip()
    raw_content = re.sub(r'^```(?:json)?\s*', '', raw_content)
    raw_content = re.sub(r'\s*```$', '', raw_content)
    result = json.loads(raw_content)

    is_corr = bool(result.get("is_correct", False))
    return {
      "is_correct": is_corr,
      "marks_awarded": 1 if is_corr else 0,
      "ai_feedback": str(result.get("ai_feedback", "Correct!" if is_corr else "Let's review the ideal answer.")),
      "ideal_answer": str(result.get("ideal_answer", model_answer))
    }
  except Exception as e:
    print(f"Digi Library Grading Error: {e}")
    return {
      "is_correct": False,
      "marks_awarded": 0,
      "ai_feedback": "An error occurred during evaluation. Please try again.",
      "ideal_answer": model_answer
    }


def explain_answer_structured(
  question_text: str,
  student_answer: str,
  correct_answer: str,
  marks_awarded: float = 0.0,
  max_marks: float = 1.0,
  is_retry: bool = False,
  lang: str = "en",
  is_idk: bool = False,
) -> dict:
  """
  Provides a playful, child-friendly storytelling explanation in the student's preferred language (`lang`),
  with separate spoken lines ('spoken_2', 'spoken_3') and HTML sections (#deep-dive-easy-way, #deep-dive-key-concept, #deep-dive-visual).
  """
  lang_code = normalize_tutor_lang(lang)
  pack = _FAST_STRINGS.get(lang_code, _FAST_STRINGS["en"])
  question_text = (question_text or "").strip()[:800]
  student_answer = (student_answer or "").strip()[:1000]
  correct_answer = (correct_answer or "").strip()[:1000]
  ask_cache_k = (question_text[:140], student_answer.lower()[:200], float(marks_awarded or 0), float(max_marks or 1), bool(is_retry), lang_code)
  if ask_cache_k in _ASK_WHY_CACHE:
    return dict(_ASK_WHY_CACHE[ask_cache_k])

  if not client:
    easy_fb = pack["fb_easy"].format(ans=correct_answer)
    key_fb = pack["fb_key"].format(ans=correct_answer)
    return {
      "html": _build_deep_dive_html(easy_fb, key_fb, _extract_fallback_wiki_terms(question_text, correct_answer)),
      "easy_way_text": easy_fb,
      "key_concept_text": key_fb,
      "spoken_2": easy_fb,
      "spoken_3": pack["fb_s3"].format(ans=correct_answer),
      "how_to_improve_text": key_fb,
    }

  score_ratio = (float(marks_awarded or 0) / float(max_marks or 1)) if float(max_marks or 1) > 0 else 0.0
  idk_flag = is_idk or _is_idk_or_unsure_answer(student_answer)
  context_hint = (
    "The student honestly said they don't know yet — teach it warmly from zero like an exciting children's discovery story!"
    if idk_flag
    else (
      f"The student scored {marks_awarded:g} out of {max_marks:g} ({int(round(score_ratio * 100))}%)."
      + (" This was a retry attempt." if is_retry else "")
    )
  )

  lang_note = ""
  if lang_code != "en":
    lang_label = SUPPORTED_TUTOR_LANGS.get(lang_code, "Malayalam (മലയാളം)")
    lang_note = (
      f"\nLANGUAGE RULE: Write 'easy_way_text', 'key_concept_text', 'spoken_2', and 'spoken_3' in warm, playful, everyday conversational {lang_label} (in its native script, keeping key English science terms in parentheses on written cards when helpful). ALWAYS keep 'wiki_terms' in English!\n"
    )

  system_prompt = (
    "You are a warm, playful, expressive storyteller and mentor explaining science to a curious kid! "
    "Respond strictly as a JSON object with 5 keys (NO markdown symbols like ** or ##, NO emojis, NEVER write literal 'Haha' or 'Hehe'):\n"
    "1. 'easy_way_text': Written card text (2 short, vivid, playful sentences) giving a fun real-life analogy a child can picture immediately.\n"
    "2. 'key_concept_text': Written card text (2 short, crystal-clear sentences) explaining the magic scientific takeaway.\n"
    "3. 'wiki_terms': 2 specific English Wikipedia article titles separated by commas (ALWAYS in English, e.g. 'Human_eye, Retina' or 'Nephron, Kidney').\n"
    "4. 'spoken_2': (16-24 words MAX) How you excitedly tell the fun story/analogy out loud with warmth and wonder — WITHOUT saying robotic headers like 'Here is a memory trick'.\n"
    "5. 'spoken_3': (14-20 words MAX) How you warmly wrap up the main scientific secret out loud — without repeating spoken_2 and without saying 'try again' yet."
    + lang_note
  )

  user_prompt = (
    f"Question: {question_text}\n"
    f"Correct Answer: {correct_answer}\n"
    f"Student Answer: {student_answer}\n"
    f"Context: {context_hint}\n"
  )

  try:
    response = _chat_json_completion(
      messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
      ],
      temperature=0.5,
      max_tokens=220,
      has_image=False,
    )
    raw_content = (response.choices[0].message.content or "{}").strip()
    raw_content = re.sub(r'^```(?:json)?\s*', '', raw_content)
    raw_content = re.sub(r'\s*```$', '', raw_content)
    parsed = json.loads(raw_content)

    easy_way_text = re.sub(r"\s+", " ", _strip_emojis(parsed.get("easy_way_text") or "").strip())
    key_concept_text = re.sub(r"\s+", " ", _strip_emojis(parsed.get("key_concept_text") or "").strip())
    wiki_terms = str(parsed.get("wiki_terms") or "").strip()
    spoken_2 = re.sub(r"\s+", " ", _strip_emojis(parsed.get("spoken_2") or "").strip())
    spoken_3 = re.sub(r"\s+", " ", _strip_emojis(parsed.get("spoken_3") or "").strip())

    if not easy_way_text:
      easy_way_text = pack["fb_easy"].format(ans=correct_answer)
    if not key_concept_text:
      key_concept_text = pack["fb_key"].format(ans=correct_answer)
    if not wiki_terms:
      wiki_terms = _extract_fallback_wiki_terms(question_text, correct_answer)
    if not spoken_2:
      spoken_2 = easy_way_text
    if not spoken_3:
      spoken_3 = key_concept_text or pack["fb_s3"].format(ans=correct_answer)

    final_html = _build_deep_dive_html(easy_way_text, key_concept_text, wiki_terms)
    out_why = {
      "html": final_html,
      "easy_way_text": easy_way_text,
      "key_concept_text": key_concept_text,
      "spoken_2": spoken_2,
      "spoken_3": spoken_3,
      "how_to_improve_text": key_concept_text,
    }
    if len(_ASK_WHY_CACHE) >= 256:
      _ASK_WHY_CACHE.pop(next(iter(_ASK_WHY_CACHE)), None)
    _ASK_WHY_CACHE[ask_cache_k] = dict(out_why)
    return out_why
  except Exception as e:
    print(f"Explanation Error: {e}")
    easy_fb = pack["fb_easy"].format(ans=correct_answer)
    key_fb = pack["fb_key"].format(ans=correct_answer)
    return {
      "html": _build_deep_dive_html(easy_fb, key_fb, _extract_fallback_wiki_terms(question_text, correct_answer)),
      "easy_way_text": easy_fb,
      "key_concept_text": key_fb,
      "spoken_2": easy_fb,
      "spoken_3": pack["fb_s3"].format(ans=correct_answer),
      "how_to_improve_text": key_fb,
    }


def explain_answer(question_text: str, student_answer: str, correct_answer: str) -> str:
  res = explain_answer_structured(question_text, student_answer, correct_answer)
  return res.get("html", "")
