import os
import json
import re
import urllib.request
import urllib.parse
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# We initialize the client if the key is present
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def _match_mcq_option(student_answer: str, model_answer: str):
  """
  Accurately compares a student's MCQ / Assertion-Reason selection (e.g. 'B. Chloroplast' or 'B')
  against a model answer (which may be 'B', 'B. Chloroplast', '(b)', or 'Chloroplast').
  Returns True (match), False (definite mismatch), or None (ambiguous text, use AI fallback).
  """
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

  # 1. Exact option text body match (e.g., 'B. CHLOROPLAST' vs 'CHLOROPLAST')
  if s_body and m_body and s_body == m_body:
    return True

  # 2. Both have explicit option letters (e.g., 'B. CHLOROPLAST' vs 'B' or 'B. ...')
  if s_letter and m_letter:
    return s_letter == m_letter

  # 3. Both have non-empty bodies that clearly differ (e.g., 'C. CELL WALL' vs 'CHLOROPLAST')
  if s_body and m_body and s_body != m_body:
    if s_body in m_body or m_body in s_body:
      return True
    return False

  return None


def grade_answer(question_text: str, max_marks: int, model_answer: str, student_answer: str, previous_answer: str = None, question_type: str = 'LONG_ANSWER', drawing_data_url: str = None) -> dict:
  """
  Calls the OpenAI API to evaluate a student's answer against a model answer.
  If previous_answer is provided, compares the new answer to it and generates an Improvement Guide.
  If drawing_data_url is provided, inspects the attached handwritten work/diagram using multimodal vision.
  Returns a dictionary with 'marks_awarded' (float), 'ai_feedback' (str), and 'ideal_answer' (str).
  """
  if not client:
    # Fallback if no API key is set
    return {
      "marks_awarded": 0,
      "ai_feedback": "Automated Grading unavailable. Please contact the administrator to set the OpenAI API Key."
    }
    
  # FAST-PATH FOR EMPTY ANSWERS (No drawing attached)
  s_raw = (student_answer or "").strip()
  if not s_raw or s_raw.lower() in ["no answer provided", "none", "n/a", "no answer", "blank"]:
    if not drawing_data_url or not drawing_data_url.startswith("data:image/"):
      return {
        "marks_awarded": 0,
        "ai_feedback": "No answer was provided for this question.",
        "ideal_answer": model_answer
      }

  # DETERMINISTIC FAST-PATH FOR MCQs (No AI Needed)
  if question_type in ['MCQ', 'ASSERTION_REASON']:
    is_match = _match_mcq_option(student_answer, model_answer)
    if is_match is True:
      return {
        "marks_awarded": max_marks,
        "ai_feedback": "Great job! You improved from your previous attempt by selecting the correct option." if previous_answer else "Excellent! Your answer is perfectly correct.",
        "ideal_answer": model_answer
      }
    elif is_match is False:
      return {
        "marks_awarded": 0,
        "ai_feedback": "Incorrect option selected. Review the concept and try again." if previous_answer else "Incorrect option selected.",
        "ideal_answer": model_answer
      }
      
  system_prompt = (
    "You are an expert, fair, and encouraging teacher grading a student's exam answer. "
    "You will be given the Question, the Maximum Marks possible, the Model Answer, and the Student's Answer. "
    "Your task is to assign a score and provide constructive feedback. "
  )
  
  if question_type == 'MCQ':
    system_prompt += (
      "This is a Multiple Choice Question (MCQ). "
      "Note that the Student Answer might contain the full option text (e.g., 'A. I and II') while the Model Answer might just be the letter (e.g., 'A'), or vice versa. "
      "As long as the chosen letter or the core intent matches, consider it 100% correct. "
      "Do NOT deduct marks for lack of explanation. Give full marks if correct, 0 if incorrect. "
    )
  elif question_type == 'NUMERICAL':
    system_prompt += (
      "This is a Numerical Problem. "
      "Evaluate both the step-by-step calculations and the final answer (including units). "
      "If the final answer is wrong but the steps are partially correct, award partial marks. "
    )
  elif question_type == 'ASSERTION_REASON':
    system_prompt += (
      "This is an Assertion-Reason question. "
      "Evaluate if the student correctly identified whether Assertion and Reason are true, and if Reason is the correct explanation. "
    )
  else:
    system_prompt += (
      "CRITICAL LENGTH RULE: Analyze the length based on max_marks. If the answer is too short for the marks assigned (e.g., 1 sentence for a 5-mark question), actively deduct marks and explicitly state what key points are missing. "
      "Be lenient with phrasing, but strict on having enough content to justify the marks. "
    )
    
  system_prompt += "Also, generate an 'ideal_answer' which is a perfectly phrased, concise version of the answer that the student should aim for. "
  
  if previous_answer:
    system_prompt += (
      "Since the student is retrying this question, you MUST also compare their new answer to their previous answer. "
      "Structure your feedback as an 'Improvement Guide' that explicitly states how they improved from their last attempt, what they got right, and what they still missed based on the model answer."
    )
    
  if drawing_data_url and drawing_data_url.startswith("data:image/"):
    system_prompt += (
      "\nNOTE ON ATTACHED WORK: The student has attached an image of their handwritten work, diagram, chemical structures, or calculations from their digital scratchpad. "
      "Carefully analyze and evaluate the attached image alongside any written text. Award marks for correct steps, diagrams, balancing, or derivations shown in their sketch."
    )

  system_prompt += (
    "Return the result strictly as a JSON object with three keys: 'marks_awarded' (a number between 0 and max_marks), "
    "'ai_feedback' (a string containing the feedback), and 'ideal_answer' (a string containing the perfect answer). Do not return markdown blocks.\n"
    "UNIVERSAL RULE FOR ALL QUESTION TYPES: If the student selects an option containing a letter (e.g. 'A. text' or 'C') and the model answer is just a letter (e.g. 'A') or vice versa, DO NOT mark it wrong. As long as the chosen letter matches, award full marks and treat it as fully correct."
  )
  
  user_prompt = (
    f"Question: {question_text}\n"
    f"Maximum Marks: {max_marks}\n"
    f"Model Answer: {model_answer}\n"
    f"Student Answer: {student_answer}\n"
  )
  
  if previous_answer:
    user_prompt += f"Previous Answer (for comparison): {previous_answer}\n"

  user_message_content = [{"type": "text", "text": user_prompt}]
  if drawing_data_url and drawing_data_url.startswith("data:image/"):
    user_message_content.append({
      "type": "image_url",
      "image_url": {
        "url": drawing_data_url
      }
    })

  try:
    try:
      response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": user_message_content}
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_completion_tokens=500
      )
    except Exception as primary_err:
      print(f"Primary grading model (gpt-5.4-mini) notice: {primary_err}, falling back to gpt-4o-mini...")
      response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": user_message_content}
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=500
      )
    
    raw_content = response.choices[0].message.content.strip()
    # Strip markdown fences if present (e.g. ```json ... ```)
    import re
    raw_content = re.sub(r'^```(?:json)?\s*', '', raw_content)
    raw_content = re.sub(r'\s*```$', '', raw_content)
    result = json.loads(raw_content)

    # Ensure bounds
    marks = min(max(float(result.get("marks_awarded", 0)), 0), max_marks)
    return {
      "marks_awarded": round(marks, 1),
      "ai_feedback": str(result.get("ai_feedback", "Graded successfully.")),
      "ideal_answer": str(result.get("ideal_answer", model_answer))
    }
  except Exception as e:
    print(f"Grading Error: {e}")
    return {
      "marks_awarded": 0,
      "ai_feedback": "An error occurred during grading. Please ask an instructor to review manually.",
      "ideal_answer": model_answer
    }

def grade_digi_answer(question_text: str, model_answer: str, student_answer: str, previous_answer: str = None, question_type: str = 'CUSTOM', drawing_data_url: str = None) -> dict:
  """
  Evaluates a student's answer for Digi Library Question Banks WITHOUT marks distribution.
  Determines purely if the answer is Correct (is_correct=True) or Wrong (is_correct=False),
  along with constructive AI feedback and an ideal answer.
  """
  s_raw = (student_answer or "").strip()
  if not s_raw or s_raw.lower() in ["no answer provided", "none", "n/a", "no answer", "blank"]:
    if not drawing_data_url or not drawing_data_url.startswith("data:image/"):
      return {
        "is_correct": False,
        "marks_awarded": 0,
        "ai_feedback": "No answer was provided for this question.",
        "ideal_answer": model_answer
      }

  # Deterministic fast-path for MCQs and Assertion-Reason
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
    "You are an expert, fair, and encouraging teacher evaluating a student's practice question answer in a Question Bank. "
    "IMPORTANT: There are NO marks or points for this question. Do NOT mention marks, scores, or points anywhere in your feedback. "
    "Your task is to determine whether the student's answer is conceptually CORRECT or WRONG compared to the Model Answer, and provide clear, constructive feedback. "
    "Focus on conceptual accuracy and understanding rather than strict word count or length. If the student captures the core concept or correct final value/meaning, mark it as Correct (is_correct: true). "
    "Also generate an 'ideal_answer' which is a clear, concise version of the correct answer."
  )

  if previous_answer:
    system_prompt += (
      " Since the student is retrying this question, compare their new answer to their previous answer and explain how they improved and what (if anything) is still missing."
    )

  if drawing_data_url and drawing_data_url.startswith("data:image/"):
    system_prompt += (
      "\nNOTE ON ATTACHED WORK: The student has attached an image of their handwritten work, diagram, or calculations. "
      "Carefully inspect the attached image alongside any written text to judge whether their solution is correct."
    )

  system_prompt += (
    "\nReturn the result strictly as a JSON object with three keys: "
    "'is_correct' (boolean true or false), "
    "'ai_feedback' (string with constructive feedback—never mention marks or points), and "
    "'ideal_answer' (string containing the ideal answer). Do not return markdown blocks.\n"
    "UNIVERSAL RULE: If the student selects an option letter (e.g. 'A. text' or 'A') and the model answer matches that letter or option text, treat it as 100% correct (is_correct: true)."
  )

  user_prompt = (
    f"Question: {question_text}\n"
    f"Model Answer: {model_answer}\n"
    f"Student Answer: {student_answer}\n"
  )
  if previous_answer:
    user_prompt += f"Previous Answer (for comparison): {previous_answer}\n"

  user_message_content = [{"type": "text", "text": user_prompt}]
  if drawing_data_url and drawing_data_url.startswith("data:image/"):
    user_message_content.append({
      "type": "image_url",
      "image_url": {"url": drawing_data_url}
    })

  try:
    try:
      response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": user_message_content}
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_completion_tokens=500
      )
    except Exception as primary_err:
      print(f"Primary digi grading model (gpt-5.4-mini) notice: {primary_err}, falling back to gpt-4o-mini...")
      response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": user_message_content}
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=500
      )
    raw_content = response.choices[0].message.content.strip()
    raw_content = re.sub(r'^```(?:json)?\s*', '', raw_content)
    raw_content = re.sub(r'\s*```$', '', raw_content)
    result = json.loads(raw_content)

    is_corr = bool(result.get("is_correct", False))
    return {
      "is_correct": is_corr,
      "marks_awarded": 1 if is_corr else 0,
      "ai_feedback": str(result.get("ai_feedback", "Correct!" if is_corr else "Wrong. Please review the ideal answer.")),
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

def explain_answer(question_text: str, student_answer: str, correct_answer: str) -> str:
  """
  Calls the OpenAI API to provide a detailed, step-by-step 'Why?' explanation
  comparing the student's answer to the correct answer.
  """
  if not client:
    return "Explanation unavailable. Please contact the administrator to set the OpenAI API Key."
    
  system_prompt = (
    "You are an expert tutor. The student wants to know WHY their answer is incorrect or how the correct answer was derived.\n"
    "You MUST respond EXACTLY in the following format. DO NOT use ANY markdown symbols like asterisks (**), hashes (##), or backticks. Just use plain text.\n\n"
    "[EASY_WAY]\n"
    "[Provide a simple analogy or memory trick here]\n\n"
    "[KEY_CONCEPT]\n"
    "[Provide one important takeaway the student should remember]\n\n"
    "[VISUAL_EXPLANATION]\n"
    "WIKIPEDIA_SEARCH: [Provide 1-3 EXACT Wikipedia page titles separated by commas that directly represent the core specific subjects (e.g. Vyankoji_Bhosale, Thanjavur_Maratha_Palace). DO NOT use generic terms like 'India' or 'Empire'.]\n\n"
    "[LEARN_MORE]\n"
    "<ul><li><a href='https://en.wikipedia.org/wiki/Exact_Page_Title' target='_blank' class='text-primary underline'>Topic Name</a></li></ul>"
  )
  
  user_prompt = (
    f"Question: {question_text}\n"
    f"Correct Answer: {correct_answer}\n"
    f"Student Answer: {student_answer}\n"
    "Explain in detail why the correct answer is what it is, and where my understanding might have gone wrong."
  )
  
  try:
    try:
      response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,
        max_completion_tokens=600
      )
    except Exception as primary_err:
      print(f"Primary explain model (gpt-5.4-mini) notice: {primary_err}, falling back to gpt-4o-mini...")
      response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,
        max_tokens=600
      )
    content = response.choices[0].message.content
    
    # Inject SVGs for headers
    content = content.replace(
      "[EASY_WAY]",
      "<div class='flex items-center gap-2 text-[#9b59b6] font-bold mt-4 mb-1'><svg class='w-5 h-5' fill='none' stroke='currentColor' viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'><path stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z'></path></svg> Easy way to remember</div>"
    )
    content = content.replace(
      "[KEY_CONCEPT]",
      "<div class='flex items-center gap-2 text-[#e74c3c] font-bold mt-4 mb-1'><svg class='w-5 h-5' fill='none' stroke='currentColor' viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'><path stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z'></path></svg> Key concept</div>"
    )
    content = content.replace(
      "[VISUAL_EXPLANATION]",
      "<div class='flex items-center gap-2 text-[#2ecc71] font-bold mt-4 mb-1'><svg class='w-5 h-5' fill='none' stroke='currentColor' viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'><path stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z'></path></svg> Visual explanation</div>"
    )
    content = content.replace(
      "[LEARN_MORE]",
      "<div class='flex items-center gap-2 text-[#3498db] font-bold mt-4 mb-1'><svg class='w-5 h-5' fill='none' stroke='currentColor' viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'><path stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253'></path></svg> Labour India Digital Library</div>"
    )
    
    # Inject Wikipedia Image Gallery
    match = re.search(r'WIKIPEDIA_SEARCH:\s*([^\n]+)', content)
    if match:
      search_terms = match.group(1).split(',')
      img_tags = []
      for term in search_terms:
        term = term.strip().replace(' ', '_').strip('[]')
        if not term: continue
        try:
          url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(term)}"
          req = urllib.request.Request(url, headers={'User-Agent': 'EduSafariTutor/1.0'})
          resp = urllib.request.urlopen(req, timeout=3)
          data = json.loads(resp.read().decode())
          img_url = data.get('thumbnail', {}).get('source')
          if img_url:
            img_tags.append(f"<img src='{img_url}' alt='{term.replace('_', ' ')}' class='w-full object-cover rounded-xl shadow-md aspect-square border border-base-content/10' />")
        except Exception as e:
          print(f"Wikipedia fetch error for {term}: {e}")
      
      if img_tags:
        grid_cols = 'grid-cols-2' if len(img_tags) > 1 else 'grid-cols-1 max-w-sm'
        gallery_html = f"<div class='grid {grid_cols} gap-4 my-4'>{''.join(img_tags)}</div>"
        content = content.replace(match.group(0), gallery_html)
      else:
        content = content.replace(match.group(0), "")
        
    return content
  except Exception as e:
    print(f"Explanation Error: {e}")
    return "An error occurred while generating the explanation. Please try again later."

