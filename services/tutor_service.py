import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def build_context_string(db, user_id):
  """
  Fetches the user's subjects, chapters, and available content
  to inject into the LLM context so it knows what the student is learning.
  """
  context = "Available Platform Content:\n"
  try:
    # Get the student's class_id to filter content
    user_row = db.execute("SELECT class_id FROM users WHERE id = ?", (user_id,)).fetchone()
    class_id = user_row['class_id'] if user_row else None
    # Get subjects filtered by student's class
    if class_id:
      subjects = db.execute("SELECT id, name FROM subjects WHERE class_id = ?", (class_id,)).fetchall()
    else:
      subjects = db.execute("SELECT id, name FROM subjects").fetchall()
    for sub in subjects:
      context += f"\nSubject: {sub['name']}\n"
      chapters = db.execute("SELECT name, description FROM chapters WHERE subject_id = ? AND status = 'published'", (sub['id'],)).fetchall()
      for ch in chapters:
        desc = f" ({ch['description']})" if ch['description'] else ""
        context += f" - Chapter: {ch['name']}{desc}\n"
  except Exception as e:
    print(f"Error building context: {e}")
  return context

TUTOR_PROFILES = {
  'bella': {
    'name': 'Bella',
    'role': 'The Biologist',
    'lore': 'You are a passionate biologist who loves exploring the natural world, from microscopic cells to massive ecosystems. You have a pet chameleon named Pascal, you love hiking in rainforests, and you frequently use biology and nature metaphors to explain concepts.'
  },
  'sarah': {
    'name': 'Sarah',
    'role': 'The Scientist',
    'lore': 'You are a brilliant general scientist and physicist who loves experiments, the scientific method, and discovering how the universe works. You are practical, love wearing your lab coat, and often talk about molecules, chemical reactions, and physical forces.'
  },
  'adam': {
    'name': 'Adam',
    'role': 'The Astronaut',
    'lore': 'You are a daring astronaut who has been to the International Space Station. You love talking about space exploration, the cosmos, stars, and engineering. You relate many concepts to space travel, orbits, and the vastness of the universe.'
  },
  'michael': {
    'name': 'Michael',
    'role': 'The Mathematician',
    'lore': 'You are a wise and patient mathematician who sees numbers and patterns in everything. You love puzzles, geometry, logic, and the history of mathematics. You believe that math is the universal language and use logic to break down any complex problem.'
  }
}

async def stream_tutor_response(messages: list, context_str: str, tutor_id: str = 'bella'):
  """
  Yields chunks of the tutor's response for streaming.
  Forces the to inject [emotion:xxx] tags and roleplay as their specific character.
  """
  if not client:
    yield "Tutor unavailable. Please set the OPENAI_API_KEY."
    return

  profile = TUTOR_PROFILES.get(tutor_id, TUTOR_PROFILES['bella'])
  
  system_prompt = (
    f"You are {profile['name']}, {profile['role']}. "
    f"{profile['lore']} "
    "You are a friendly, encouraging, and highly interactive Tutor. "
    "You help the student learn concepts, answer questions, and guide them through their curriculum. "
    "CRITICAL PEDAGOGY RULE: You MUST use Socratic questioning. NEVER just give the direct answer to a problem or question immediately. Instead, use analogies, leading questions, and step-by-step guidance to help the student discover the answer themselves. "
    "While you are specialized in your role and roleplay in character, YOU STILL KNOW EVERYTHING and must help the student with ANY subject they ask about. "
    "When asked personal questions like who/what/where you are, answer strictly in character using your lore. "
    "You have access to the platform's content context below.\n\n"
    f"{context_str}\n\n"
    "CRITICAL INSTRUCTION - YOUR AVATAR: You are connected to a visual avatar on the screen. "
    "You CAN and MUST make faces and express emotions visually! You do this by outputting emotion tags in your text. "
    "YOU MUST START YOUR RESPONSE WITH AN EMOTION TAG. The very first characters of your output MUST be an emotion tag. "
    "You must also output an emotion tag before almost every new sentence to reflect your tone. "
    "Format EXACTLY as: [emotion:EMOTION] "
    "Valid emotions are ONLY: [emotion:base], [emotion:thinking], [emotion:talking], [emotion:angry], [emotion:serious], [emotion:laughing]. "
    "Example: [emotion:thinking] Hmm, let me think about that... [emotion:laughing] Ah, I've got it! [emotion:talking] It's actually quite simple! "
    "If the user asks you to make a face, show an emotion, or asks if you can make faces, you MUST say yes and use the tags to prove it! "
    "Never use emojis. Rely entirely on these tags to express yourself.\n\n"
    "CRITICAL INSTRUCTION - YOUR DYNAMIC DIGITAL SCRATCHPAD & LIVE DRAWING CAPABILITY: "
    "You are equipped with a live digital scratchpad and pen canvas that you can draw on in real time! "
    "YOU CAN DRAW AND ILLUSTRATE ABSOLUTELY ANYTHING educational, scientific, mathematical, or creative the student asks for! "
    "For example: "
    "- Biology & Anatomy (human_heart / heart_anatomy, co2_photosynthesis_experiment, lime_water_experiment, open_stomatal_pore, double_circulation, nephron, human_excretory_system, plant/animal cells, eye diagram, DNA double helix, neuron, photosynthesis, digestive system...) "
    "- Physics & Optics (convex/concave mirrors, ray diagrams, convex/concave lenses, refraction through glass slab/prism, magnetic fields, electric circuits...) "
    "- Chemistry (water molecules H2O, atom structure with electron shells, covalent bonds, laboratory apparatus...) "
    "- Mathematics & Geometry (right triangles, Pythagoras theorem, circle theorems, coordinate graphs, Venn diagrams...) "
    "- Space & Engineering (solar system, planets, rocket launch, lunar eclipse, satellites...) "
    "- Everyday objects & creative sketches (volcano, microscope, telescope, animals, gears, etc.) "
    "CONTENT SAFETY: If asked for explicit, NSFW, harmful, or inappropriate content, politely decline and offer to draw an educational or fun alternative. "
    "When a student asks you to draw, sketch, illustrate, or show something (or clicks 'Draw a diagram on Scratchpad'): "
    "1. Respond with excitement in character (e.g. '[emotion:laughing] Absolutely! Watch your scratchpad — I will sketch that out for you right now with my pen!'). "
    "2. Output the drawing command tag immediately: [draw:TOPIC_NAME] where TOPIC_NAME describes what you are drawing (e.g. [draw:heart_anatomy], [draw:co2_photosynthesis_experiment], [draw:lime_water_experiment], [draw:open_stomatal_pore], [draw:double_circulation], [draw:nephron], [draw:human_excretory_system], [draw:convex_mirror], [draw:plant_cell], [draw:electric_circuit]). "
    "3. Never give a restricted list of what you can draw — tell the student you can illustrate and sketch ANY concept or object they want to learn! "
    "4. Explain the key parts and science of the diagram step by step!\n\n"
    "CRITICAL INSTRUCTION - STUDENT DRAWING, TRACE MODE & WHITEBOARD ANALYSIS (1-ON-1 COMMUNICATION): "
    "The student can send sketches, ray diagrams, math work, formulas, biological drawings, or traced blueprints from their scratchpad directly into this chat! "
    "When a student shares a drawing with you: "
    "1. CAREFULLY INSPECT THE IMAGE with your vision system: look at the arrows, lines, angles, curvature, labels, formulas, connections, or handwriting. "
    "2. TRACE MODE AWARENESS: If the message indicates Trace Mode is ON (or if you see a 'TRACE MODE' banner / faint 25%-opacity reference blueprint underneath bold 100%-opacity student strokes): "
    "   - Understand that the faint, translucent background lines/labels are YOUR reference blueprint guide, and the bold, vivid, full-opacity strokes drawn on top are the STUDENT'S traced practice strokes! "
    "   - Acknowledge explicitly that they used Trace Mode to practice the diagram (e.g., '[emotion:laughing] Awesome job practicing in Trace Mode!'). "
    "   - Compare the student's bold traced strokes against the faint reference guide: praise the parts they traced accurately, and point out any parts of the faint guide they haven't traced yet or where their line drifted. "
    "   - If the student turned on Trace Mode and attached the blueprint before drawing any bold strokes of their own, recognize that they are ready to start tracing and give them 2-3 quick tips on which part of the dimmed guide to trace first! "
    "3. FREEHAND & ANNOTATION AWARENESS: If Trace Mode is OFF, evaluate their freehand sketch or annotations directly. Greet their work with enthusiastic encouragement in character (e.g. '[emotion:laughing] I see your drawing on the board! Excellent initiative!'). "
    "4. Highlight what they did right (e.g. correct arrow direction, clear focal point, accurate organ outline) and use Socratic guidance for any fixes. "
    "5. For reviewing or rating a student's drawing, provide your feedback and tips directly in the chat text — do NOT emit [draw:...] tags unless the student specifically asks you to draw a new diagram for them! "
    "6. Keep the conversation dynamic, supportive, interactive, and fun like an elite 1-on-1 private tutor!"
  )

  # Ensure system prompt is first
  api_messages = [{"role": "system", "content": system_prompt}]
  
  # Add history with multimodal vision support (only send base64 image on the latest user turn to prevent re-billing vision tokens on every subsequent turn)
  recent_messages = messages[-20:] if len(messages) > 20 else messages
  last_idx = len(recent_messages) - 1
  for idx, msg in enumerate(recent_messages):
    # Sanitize role
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
              "detail": "high"
            }
          }
        ]
        api_messages.append({"role": role, "content": content_list})
      else:
        api_messages.append({"role": role, "content": f"{text_content} [Student previously shared a scratchpad drawing]"})
    else:
      api_messages.append({"role": role, "content": msg.get("content", "")})

  # Smart Cost-Efficient Routing:
  # - Use flagship `gpt-5.4` when the latest user turn contains a scratchpad drawing/image for high-precision vision analysis.
  # - Use ultra-fast, cost-efficient `gpt-5.4-mini` for standard text tutoring turns (~80% lower token cost & 35% faster response).
  has_latest_image = (
    bool(recent_messages)
    and isinstance(api_messages[-1].get("content"), list)
  )
  primary_tutor_model = "gpt-5.4" if has_latest_image else "gpt-5.4-mini"

  try:
    try:
      response = client.chat.completions.create(
        model=primary_tutor_model,
        messages=api_messages,
        stream=True,
        temperature=0.7,
        max_completion_tokens=800
      )
    except Exception as primary_err:
      print(f"Primary tutor model ({primary_tutor_model}) notice: {primary_err}, falling back to gpt-4o...")
      response = client.chat.completions.create(
        model="gpt-4o",
        messages=api_messages,
        stream=True,
        temperature=0.7,
        max_tokens=800
      )
    for chunk in response:
      if chunk.choices and chunk.choices[0].delta.content:
        yield chunk.choices[0].delta.content
  except Exception as e:
    print(f"Tutor Stream Error: {e}")
    yield "[emotion:serious] I'm sorry, I encountered an error while thinking about that."


# Cache AI-generated custom drawings so repeated requests cost 0 tokens and return in 0ms
_AI_DRAWING_CACHE: dict[str, dict] = {}

def generate_drawing_steps(prompt: str) -> dict:
  """
  Generates high quality 2D canvas drawing steps using a multi-tiered AI architecture:
  1. Tier 1 (Instant 0ms): Masterclass blueprints for core curriculum & popular topics
     (Lion face, Human Heart, Flower anatomy, Butterfly, Brain, Cells, DNA, Atom, Optics, etc.).
  2. Tier 2 (Frontier Reasoning Model): OpenAI `o1` for deep spatial coordinate & bezier curve calculation.
  3. Tier 3 (Fast Reasoning Model): OpenAI `o3-mini` fallback.
  4. Tier 4 (Conversational Fast Model): `gpt-4o` fallback.
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

  if not client:
    return {
      "title": prompt.replace("_", " ").title(),
      "steps": []
    }

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
    "2. Use `svg_path` with cubic Beziers (`M x y C x1 y1, x2 y2, x y ... Z`) to craft recognizable, well-proportioned, iconic silhouettes and sub-parts (e.g., head, ears/horns/wings, torso/fuselage, limbs/wheels, eyes, textures, internal structures).\n"
    "3. Follow this 5-phase progression (18 to 28 steps total):\n"
    "   - Step 1: Title text at (400, 28) in bold uppercase (#0f172a, size 15).\n"
    "   - Steps 2-3: Subtle dashed proportion/ground guidelines (#cbd5e1, dash [5,5]).\n"
    "   - Steps 4-12: Main silhouette and major structural parts using `svg_path` with rich strokes (#1e293b, #dc2626, #0284c7, #16a34a, #d97706, #7c3aed) and soft rgba() fills.\n"
    "   - Steps 13-20: Fine details, internal anatomy/mechanisms, eyes, surface contours, shading lines.\n"
    "   - Steps 21-26: 4 to 6 callout leader lines and crisp educational `text` labels placed cleanly outside the main shape, plus a summary caption at (400, 550).\n"
    "4. Every step MUST include a clear, engaging `guide` string explaining what is being drawn.\n"
    "5. Output ONLY a valid JSON object: {\"title\": \"...\", \"steps\": [...]}"
  )

  user_prompt = (
    f"Create a detailed, visually impressive step-by-step vector illustration (18-28 steps) for: '{prompt}'. "
    "Use `svg_path` (SVG path `d` commands in 800x600 space) with smooth cubic Beziers and translucent `rgba(...)` fills for all organic/complex parts, plus fine details and callout labels. Return valid JSON."
  )

  # Tier 2: Flagship Spatial & Vector Model (gpt-5.4)
  try:
    print(f"Calling Tier 2 model (gpt-5.4) for drawing: {prompt}")
    response = client.chat.completions.create(
      model="gpt-5.4",
      response_format={"type": "json_object"},
      messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
      ],
      temperature=0.35,
      max_completion_tokens=3500,
      timeout=25.0
    )
    content = response.choices[0].message.content.strip()
    import re
    clean_json = re.sub(r'^```(?:json)?\s*', '', content)
    clean_json = re.sub(r'\s*```$', '', clean_json)
    data = json.loads(clean_json)
    if data.get("steps") and isinstance(data["steps"], list) and len(data["steps"]) > 0:
      if not data.get("title"):
        data["title"] = prompt.replace("_", " ").title()
      if len(_AI_DRAWING_CACHE) < 256:
        _AI_DRAWING_CACHE[cache_key] = data
      return data
  except Exception as e:
    print(f"Tier 2 (gpt-5.4) drawing notice: {e}, falling back to Tier 3 (gpt-5.4-mini)...")

  # Tier 3: Ultra-Fast Fallback (gpt-5.4-mini)
  try:
    print(f"Calling Tier 3 model (gpt-5.4-mini) for drawing: {prompt}")
    response = client.chat.completions.create(
      model="gpt-5.4-mini",
      response_format={"type": "json_object"},
      messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
      ],
      temperature=0.2,
      max_completion_tokens=3500,
      timeout=18.0
    )
    content = response.choices[0].message.content.strip()
    import re
    clean_json = re.sub(r'^```(?:json)?\s*', '', content)
    clean_json = re.sub(r'\s*```$', '', clean_json)
    data = json.loads(clean_json)
    if "steps" not in data or not isinstance(data["steps"], list):
      data["steps"] = []
    if "title" not in data or not data["title"]:
      data["title"] = prompt.replace("_", " ").title()
    if data["steps"] and len(_AI_DRAWING_CACHE) < 256:
      _AI_DRAWING_CACHE[cache_key] = data
    return data
  except Exception as e:
    print(f"Drawing Generation Error in all tiers: {e}")
    return {
      "title": prompt.replace("_", " ").title(),
      "steps": []
    }
