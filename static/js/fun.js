/* SAXAZ Sunny v3 - Confetti, Bilingual EN/Malayalam Engine & Client Account Vault Sync */
(function () {
  var COLORS = ['#f7b317', '#231f20', '#ffffff'];

  window.saxazConfetti = function (x, y, count) {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    var n = count || 28;
    var cx = typeof x === 'number' ? x : window.innerWidth / 2;
    var cy = typeof y === 'number' ? y : window.innerHeight / 3;
    for (var i = 0; i < n; i++) {
      var el = document.createElement('div');
      el.className = 'sx-confetti-bit';
      var s = 6 + Math.random() * 8;
      el.style.width = s + 'px';
      el.style.height = (Math.random() > 0.5 ? s : s * 0.45) + 'px';
      el.style.left = cx + 'px';
      el.style.top = cy + 'px';
      el.style.background = COLORS[i % COLORS.length];
      document.body.appendChild(el);
      var angle = Math.random() * Math.PI * 2;
      var dist = 70 + Math.random() * 150;
      var dx = Math.cos(angle) * dist;
      var dy = Math.sin(angle) * dist - 60;
      var rot = (Math.random() - 0.5) * 900;
      var anim = el.animate([
        { transform: 'translate(0,0) rotate(0deg)', opacity: 1 },
        { transform: 'translate(' + dx + 'px,' + dy + 'px) rotate(' + rot / 2 + 'deg)', opacity: 1, offset: 0.55 },
        { transform: 'translate(' + dx * 1.15 + 'px,' + (dy + 190) + 'px) rotate(' + rot + 'deg)', opacity: 0 }
      ], { duration: 1100 + Math.random() * 500, easing: 'cubic-bezier(.2,.7,.3,1)' });
      anim.onfinish = (function (node) { return function () { node.remove(); }; })(el);
    }
  };

  document.addEventListener('click', function (e) {
    var t = e.target.closest && e.target.closest('[data-confetti]');
    if (t) window.saxazConfetti(e.clientX, e.clientY, 26);
  });

  /* --------------------------------------------------------------------------
     Client-Side Account Vault Sync (mirrors signed saxaz_vault cookie <-> localStorage)
     -------------------------------------------------------------------------- */
  function readCookie(name) {
    var parts = document.cookie.split('; ');
    for (var i = 0; i < parts.length; i++) {
      if (parts[i].indexOf(name + '=') === 0) {
        return decodeURIComponent(parts[i].substring(name.length + 1));
      }
    }
    return '';
  }

  function syncVaultStorage() {
    try {
      var cookieVal = readCookie('saxaz_vault');
      var localVal = localStorage.getItem('saxaz_vault_token') || '';
      if (cookieVal && cookieVal.indexOf('v1.') === 0) {
        localStorage.setItem('saxaz_vault_token', cookieVal);
      } else if (localVal && localVal.indexOf('v1.') === 0) {
        document.cookie = 'saxaz_vault=' + localVal + ';path=/;max-age=31536000;SameSite=Lax';
      }
    } catch (e) {}
  }

  window.getSaxazVaultToken = function () {
    syncVaultStorage();
    try {
      return readCookie('saxaz_vault') || localStorage.getItem('saxaz_vault_token') || '';
    } catch (e) {
      return '';
    }
  };
  syncVaultStorage();

  /* --------------------------------------------------------------------------
     Bilingual English / Malayalam (EN / മലയാളം) Translation Engine
     -------------------------------------------------------------------------- */
  var DICT = {
    // Navigation & Global
    'Today': 'ഇന്ന്',
    'Learn': 'പഠനം',
    'Library': 'ലൈബ്രറി',
    'Tutor': 'ട്യൂട്ടർ',
    'Settings': 'ക്രമീകരണങ്ങൾ',
    'Overview': 'അവലോകനം',
    'Mock exams': 'മാതൃകാ പരീക്ഷകൾ',
    'Mock Exams': 'മാതൃകാ പരീക്ഷകൾ',
    'Real exams': 'യഥാർഥ പരീക്ഷകൾ',
    'Real Exams': 'യഥാർഥ പരീക്ഷകൾ',
    'Dashboard': 'ഡാഷ്‌ബോർഡ്',
    'Curriculum': 'പാഠ്യപദ്ധതി',
    'Digi-Library': 'ഡിജി-ലൈബ്രറി',
    'Analytics': 'വിശകലനം',
    'Search': 'തിരയുക',
    'Home': 'ഹോം',
    'Back to home': 'ഹോമിലേക്ക്',
    'My profile': 'എന്റെ പ്രൊഫൈൽ',
    'Install app': 'ആപ്പ് ഇൻസ്റ്റാൾ ചെയ്യുക',
    'Log out': 'ലോഗ് ഔട്ട്',
    'Log in': 'ലോഗിൻ',
    'Start free': 'സൗജന്യമായി തുടങ്ങൂ',
    'Create account': 'അക്കൗണ്ട് ഉണ്ടാക്കുക',
    'Create an account': 'അക്കൗണ്ട് ഉണ്ടാക്കുക',
    'Create free account': 'സൗജന്യ അക്കൗണ്ട് ഉണ്ടാക്കൂ',
    'Open my dashboard': 'ഡാഷ്‌ബോർഡ് തുറക്കുക',
    'Start learning free': 'സൗജന്യമായി പഠനം തുടങ്ങൂ',
    'I already have an account': 'എനിക്ക് അക്കൗണ്ട് ഉണ്ട്',
    'What you get': 'പ്രത്യേകതകൾ',
    'How it works': 'പ്രവർത്തന രീതി',
    'For parents': 'രക്ഷിതാക്കൾക്ക്',

    // Subjects
    'Physics': 'ഭൗതികശാസ്ത്രം',
    'PHYSICS': 'ഭൗതികശാസ്ത്രം',
    'Maths': 'ഗണിതം',
    'MATHS': 'ഗണിതം',
    'Mathematics': 'ഗണിതം',
    'MATHEMATICS': 'ഗണിതം',
    'Chemistry': 'രസതന്ത്രം',
    'CHEMISTRY': 'രസതന്ത്രം',
    'Biology': 'ജീവശാസ്ത്രം',
    'BIOLOGY': 'ജീവശാസ്ത്രം',
    'Science': 'ശാസ്ത്രം',
    'Social Science': 'സാമൂഹ്യശാസ്ത്രം',
    'English': 'ഇംഗ്ലീഷ്',
    'Malayalam': 'മലയാളം',
    'Hindi': 'ഹിന്ദി',
    'IT': 'ഐ.ടി.',

    // Greetings & Dashboard
    'Good morning': 'സുപ്രഭാതം',
    'Good afternoon': 'ശുഭ മദ്ധ്യാഹ്നം',
    'Good evening': 'ശുഭ സായാഹ്നം',
    'Welcome back': 'വീണ്ടും സ്വാഗതം',
    'Ask AI Tutor': 'AI ട്യൂട്ടറോട് ചോദിക്കുക',
    'Quick Search': 'വേഗത്തിൽ തിരയുക',
    'Whiteboard': 'വൈറ്റ്ബോർഡ്',
    'Interactive Whiteboard': 'ഇന്ററാക്ടീവ് വൈറ്റ്ബോർഡ്',
    'Unlock Issue': 'മാഗസിൻ അൺലോക്ക് ചെയ്യുക',
    'Where your next +15 marks are': 'അടുത്ത +15 മാർക്ക് നേടാൻ',
    'Practice on Whiteboard': 'വൈറ്റ്ബോർഡിൽ പരിശീലിക്കുക',
    'Story & Word of the Day': 'ഇന്നത്തെ കഥയും വാക്കും',
    'Listen Aloud': 'ശബ്ദത്തിൽ കേൾക്കുക',
    'Daily 3-Step Curiosity Quest': 'ഇന്നത്തെ 3-ഘട്ട പഠന ദൗത്യം',
    'Exam & Entrance Pulse': 'പരീക്ഷാ പരിശീലന കേന്ദ്രം',
    'Review Mistakes on Whiteboard': 'തെറ്റുകൾ വൈറ്റ്ബോർഡിൽ തിരുത്താം',
    'Start a streak today. One small session is all it takes.': 'ഇന്ന് തന്നെ സ്ട്രീക്ക് തുടങ്ങൂ. ഒരു ചെറിയ പഠന സെഷൻ മതി.',
    'League': 'ലീഗ്',
    'Bronze': 'വെങ്കലം',
    'Silver': 'വെള്ളി',
    'Gold': 'സ്വർണ്ണം',
    'Diamond': 'ഡയമണ്ട്',
    'Continue where you left off': 'നിർത്തിയിടത്തു നിന്ന് തുടരാം',
    'All caught up': 'എല്ലാം പൂർത്തിയായി',
    'Every chapter is done. Time to test yourself.': 'എല്ലാ അധ്യായങ്ങളും പൂർത്തിയായി. ഇനി സ്വയം പരീക്ഷിച്ചു നോക്കാം.',
    'Try a practice quiz or ask your tutor for a harder challenge.': 'ഒരു പരിശീലന ക്വിസ് എഴുതുക അല്ലെങ്കിൽ ട്യൂട്ടറോട് ചോദിക്കുക.',
    'Open learning path': 'പഠന പാത തുറക്കുക',
    'Talk to tutor': 'ട്യൂട്ടറോട് സംസാരിക്കാം',
    'Resume': 'തുടരുക',
    'Practice quiz': 'പരിശീലന ക്വിസ്',
    'Ask tutor': 'ട്യൂട്ടറോട് ചോദിക്കുക',
    'Focus timer': 'ഫോക്കസ് ടൈമർ',
    'Focus': 'ഫോക്കസ്',
    'Break': 'ഇടവേള',
    'Ready': 'തയ്യാർ',
    'Stay with it': 'ശ്രദ്ധയോടെ തുടരൂ',
    'Rest up': 'വിശ്രമിക്കൂ',
    'Start': 'തുടങ്ങുക',
    'Pause': 'നിർത്തുക',
    'Reset': 'പുനഃസജ്ജമാക്കുക',
    'Your class': 'നിങ്ങളുടെ ക്ലാസ്',
    'Subjects': 'വിഷയങ്ങൾ',
    'Learning path': 'പഠന പാത',
    'This week': 'ഈ ആഴ്ച',
    'Words of great minds': 'മഹാന്മാരുടെ വാക്കുകൾ',
    'Great minds': 'മഹാന്മാർ',
    'Learners online now': 'വിദ്യാർഥികൾ ഓൺലൈനിൽ',
    'AI tutor': 'AI ട്യൂട്ടർ',
    'Stuck? Start with one of these': 'സംശയമുണ്ടോ? ഇതിലൊന്ന് പരീക്ഷിക്കൂ',
    'Explain my next chapter simply': 'അടുത്ത അധ്യായം ലളിതമായി വിവരിക്കുക',
    'Quiz me with 3 quick questions': '3 ചെറിയ ചോദ്യങ്ങൾ ചോദിക്കുക',
    'Plan my revision for this week': 'ഈ ആഴ്ചയിലെ റിവിഷൻ പ്ലാൻ തയ്യാറാക്കുക',
    'Study buddy': 'പഠനക്കൂട്ടുകാരൻ',
    'Tap for a new tip': 'പുതിയ അറിവിനായി തൊടുക',
    'Go': 'പോകാം',

    // Learn & Library
    'Full roadmap': 'പൂർണ്ണ രൂപരേഖ',
    'Completed': 'പൂർത്തിയായി',
    'Up next': 'അടുത്തത്',
    'In progress': 'പുരോഗമിക്കുന്നു',
    'Notes & videos': 'നോട്ടുകളും വീഡിയോകളും',
    'Your shelf is empty, for now': 'നിങ്ങളുടെ ഷെൽഫ് ഇപ്പോൾ ശൂന്യമാണ്',
    'When your class digital editions are published, they will stand right here.': 'നിങ്ങളുടെ ക്ലാസിലെ ഡിജിറ്റൽ പതിപ്പുകൾ പ്രസിദ്ധീകരിക്കുമ്പോൾ ഇവിടെ കാണാം.',
    'Explore the learning path': 'പഠന പാതയിലൂടെ പോവുക',

    // Login & Signup
    'Log in to pick up right where you left off.': 'നിർത്തിയിടത്തു നിന്ന് തുടരാൻ ലോഗിൻ ചെയ്യുക.',
    'Email or phone number': 'ഇമെയിൽ അല്ലെങ്കിൽ ഫോൺ നമ്പർ',
    'Password': 'പാസ്‌വേഡ്',
    'Forgot?': 'മറന്നോ?',
    'Keep me signed in on this device': 'ഈ ഉപകരണത്തിൽ ലോഗിൻ തുടരുക',
    'New to SAXAZ?': 'സാക്സാസിൽ പുതിയതാണോ?',
    'Every class gets its own SAXAZ.': 'ഓരോ ക്ലാസിനും സ്വന്തം സാക്സാസ്.',
    'Pick your class and syllabus—your subjects, interactive lessons, and study buddy adapt right away.': 'ക്ലാസും സിലബസും തിരഞ്ഞെടുക്കൂ — നിങ്ങളുടെ വിഷയങ്ങളും പാഠങ്ങളും ഉടൻ ക്രമീകരിക്കപ്പെടും.',
    'Student': 'വിദ്യാർഥി',
    'Parent': 'രക്ഷിതാവ്',
    'Login': 'ലോഗിൻ',
    'Student name': 'വിദ്യാർഥിയുടെ പേര്',
    'Class': 'ക്ലാസ്',
    'Stream': 'സ്ട്രീം',
    'Syllabus': 'സിലബസ്',
    'Medium': 'മീഡിയം',
    'Next': 'അടുത്തത്',
    'Back': 'തിരികെ',
    'Parent or guardian name': 'രക്ഷിതാവിന്റെ പേര്',
    'Relationship (optional)': 'ബന്ധം (ഐച്ഛികം)',
    'Parent contact number': 'രക്ഷിതാവിന്റെ ഫോൺ നമ്പർ',
    'Parent email (recommended)': 'രക്ഷിതാവിന്റെ ഇമെയിൽ',
    'Place and school (optional)': 'സ്ഥലവും സ്കൂളും (ഐച്ഛികം)',
    'Country': 'രാജ്യം',
    'State': 'സംസ്ഥാനം',
    'District': 'ജില്ല',
    'School name': 'സ്കൂളിന്റെ പേര്',
    'I am the parent or guardian, and I agree to this student using SAXAZ.': 'ഞാൻ രക്ഷിതാവാണ്, ഈ വിദ്യാർഥി സാക്സാസ് ഉപയോഗിക്കുന്നതിന് സമ്മതിക്കുന്നു.',
    'Phone number or email (your login ID)': 'ഫോൺ നമ്പർ അല്ലെങ്കിൽ ഇമെയിൽ (ലോഗിൻ ID)',
    'Password (at least 8 characters)': 'പാസ്‌വേഡ് (കുറഞ്ഞത് 8 അക്ഷരം)',
    'Confirm password': 'പാസ്‌വേഡ് സ്ഥിരീകരിക്കുക',
    'Already have an account?': 'അക്കൗണ്ട് ഉണ്ടോ?'
  };

  var PLACEHOLDERS = {
    'Search a chapter, formula or ask anything...': 'ഏത് അധ്യായവും ഫോർമുലയും തിരയൂ, അല്ലെങ്കിൽ AI-യോട് ചോദിക്കൂ...',
    'Find a chapter in this subject...': 'ഈ വിഷയത്തിലെ അധ്യായം തിരയുക...',
    'Search editions or books...': 'പുസ്തകങ്ങളും പതിപ്പുകളും തിരയുക...',
    'Search lessons, subjects, books, or ask AI...': 'പാഠങ്ങൾ, വിഷയങ്ങൾ, പുസ്തകങ്ങൾ തിരയുക...',
    'Enter student full name': 'വിദ്യാർഥിയുടെ മുഴുവൻ പേര് നൽകുക',
    'Parent full name': 'രക്ഷിതാവിന്റെ പേര് നൽകുക',
    'Your password': 'നിങ്ങളുടെ പാസ്‌വേഡ്',
    'At least 8 characters': 'കുറഞ്ഞത് 8 അക്ഷരം',
    'Re-enter your password': 'പാസ്‌വേഡ് വീണ്ടും നൽകുക'
  };

  function translateDynamic(str) {
    if (DICT[str]) return DICT[str];
    var m;
    if ((m = str.match(/^(Good morning|Good afternoon|Good evening|Welcome back),\s*(.+)$/i))) {
      var gMap = { 'good morning': 'സുപ്രഭാതം', 'good afternoon': 'ശുഭ മദ്ധ്യാഹ്നം', 'good evening': 'ശുഭ സായാഹ്നം', 'welcome back': 'വീണ്ടും സ്വാഗതം' };
      return (gMap[m[1].toLowerCase()] || m[1]) + ', ' + m[2];
    }
    if ((m = str.match(/^(\d+)-day streak\s*·\s*One small session keeps it alive\.?$/i))) return m[1] + ' ദിവസത്തെ സ്ട്രീക്ക് · ഈ തുടർച്ച നിലനിർത്താം.';
    if ((m = str.match(/^(\d+)\s+chapters$/i))) return m[1] + ' അധ്യായങ്ങൾ';
    if ((m = str.match(/^(\d+)\/(\d+)\s+chapters$/i))) return m[2] + '-ൽ ' + m[1] + ' അധ്യായങ്ങൾ';
    if ((m = str.match(/^(\d+)\s+of\s+(\d+)\s+chapters\s+complete$/i))) return m[2] + '-ൽ ' + m[1] + ' അധ്യായങ്ങൾ പൂർത്തിയായി';
    if ((m = str.match(/^(\d+)\s+day\s+streak$/i))) return m[1] + ' ദിവസത്തെ സ്ട്രീക്ക്';
    if ((m = str.match(/^(\d+)-day\s+streak$/i))) return m[1] + ' ദിവസത്തെ സ്ട്രീക്ക്';
    if ((m = str.match(/^(\d+)\s+days?\s+in\s+a\s+row$/i))) return 'തുടർച്ചയായി ' + m[1] + ' ദിവസം';
    if ((m = str.match(/^(\d+)%\s+to\s+next\s+tier$/i))) return 'അടുത്ത ഘട്ടത്തിലേക്ക് ' + m[1] + '%';
    if ((m = str.match(/^(\d+)%\s+of\s+(.+)\s+done$/i))) return m[2] + ' — ' + m[1] + '% പൂർത്തിയായി';
    if ((m = str.match(/^Subject\s+(\d+)$/i))) return 'വിഷയം ' + m[1];
    if ((m = str.match(/^Class\s+(\d+)$/i))) return 'ക്ലാസ് ' + m[1];
    if ((m = str.match(/^Grade\s+(\d+)$/i))) return 'ക്ലാസ് ' + m[1];
    return null;
  }

  window.getSaxazLang = function () {
    try {
      var saved = localStorage.getItem('saxaz_lang') || readCookie('saxaz_lang') || 'en';
      return saved === 'ml' ? 'ml' : 'en';
    } catch (e) {
      return 'en';
    }
  };

  function walkAndTranslate(lang) {
    if (!document.body) return;
    document.documentElement.lang = lang;

    // 1. Input placeholders
    var inputs = document.querySelectorAll('input[placeholder]');
    for (var i = 0; i < inputs.length; i++) {
      var inp = inputs[i];
      if (!inp.hasAttribute('data-sx-ph-en')) {
        inp.setAttribute('data-sx-ph-en', inp.getAttribute('placeholder') || '');
      }
      var origPh = inp.getAttribute('data-sx-ph-en');
      if (lang === 'ml' && PLACEHOLDERS[origPh]) {
        inp.setAttribute('placeholder', PLACEHOLDERS[origPh]);
      } else if (lang === 'en' && origPh) {
        inp.setAttribute('placeholder', origPh);
      }
    }

    // 2. Leaf text nodes inside elements
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    var node;
    while ((node = walker.nextNode())) {
      var parent = node.parentElement;
      if (!parent) continue;
      var tag = parent.tagName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT' || tag === 'TEXTAREA' || tag === 'CODE' || tag === 'KBD') continue;
      if (parent.classList && (parent.classList.contains('material-symbols-outlined') || parent.classList.contains('sx-lang-btn'))) continue;

      var raw = node.nodeValue || '';
      var trimmed = raw.trim();
      if (!trimmed) continue;

      if (lang === 'ml') {
        var tr = translateDynamic(trimmed);
        if (tr) {
          if (!node._sxEn) node._sxEn = raw;
          node.nodeValue = raw.replace(trimmed, tr);
        }
      } else if (lang === 'en' && node._sxEn) {
        node.nodeValue = node._sxEn;
      }
    }
  }

  window.applySaxazLang = function (lang) {
    var clean = lang === 'ml' ? 'ml' : 'en';
    try {
      localStorage.setItem('saxaz_lang', clean);
      document.cookie = 'saxaz_lang=' + clean + ';path=/;max-age=31536000;SameSite=Lax';
    } catch (e) {}
    document.documentElement.lang = clean;
    walkAndTranslate(clean);
    window.dispatchEvent(new CustomEvent('saxaz-lang-change', { detail: { lang: clean } }));
    return clean;
  };

  window.toggleSaxazLang = function () {
    var next = window.getSaxazLang() === 'en' ? 'ml' : 'en';
    return window.applySaxazLang(next);
  };

  function initLang() {
    var cur = window.getSaxazLang();
    document.documentElement.lang = cur;
    if (cur === 'ml') {
      walkAndTranslate('ml');
      setTimeout(function () { walkAndTranslate('ml'); }, 180);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLang);
  } else {
    initLang();
  }
  document.addEventListener('htmx:afterSwap', function () {
    if (window.getSaxazLang() === 'ml') walkAndTranslate('ml');
  });

  /* --------------------------------------------------------------------------
     Universal Sunny v3 Button Hover Tooltip Controller
     Replaces ugly native browser tooltips & describes every button cleanly
     -------------------------------------------------------------------------- */
  var ACTION_TIPS = {
    'today': 'Go to your daily study dashboard & streak',
    'exams': 'Browse subjects, chapters, Mock & Real Exams',
    'tutor': 'Open your 1-on-1 AI Personal Study Tutor',
    'overview': 'View your child\'s overall progress & study activity',
    'mock exams': 'View practice Mock Exam scores & attempts',
    'real exams': 'View official proctored Real Exam reports',
    'dashboard': 'Open Admin overview & platform metrics',
    'curriculum': 'Manage classes, subjects, chapters & exams',
    'analytics': 'View student performance & engagement insights',
    'settings': 'Customize voice, theme, sound & preferences',
    'aa': 'Adjust reading text size (100% – 135%)',
    'a-': 'Decrease reading text size',
    'a+': 'Increase reading text size',
    'sessions': 'View or switch between saved AI Tutor chats',
    'whiteboard': 'Open interactive Whiteboard & diagram studio',
    'ai whiteboard': 'Draw diagrams & get AI visual feedback on Whiteboard',
    'open whiteboard': 'Open interactive Whiteboard & diagram studio',
    'practice on whiteboard': 'Practice tricky concepts & diagrams on Whiteboard',
    'formulas': 'Open Math & Science symbols and formula toolkit',
    'voice': 'Toggle AI Tutor spoken voice responses on or off',
    'stop voice': 'Stop current AI Tutor voice playback',
    'send': 'Send your message to the AI Tutor',
    'chapter summary': 'Watch the animated chapter summary videos',
    'chapter introduction': 'Watch the animated chapter summary videos',
    'watch summary': 'Watch the animated chapter summary lesson',
    '1. mock exam': 'Practice with stopwatch, AI Tutor & video hints',
    '2. real exam': 'Take the timed, proctored chapter Real Exam',
    'continue / practice': 'Open Mock Exam practice with AI Tutor & stopwatch',
    'take real exam': 'Start the official timed chapter Real Exam',
    'attend real exam': 'Start the official timed chapter Real Exam',
    'retake real exam': 'Start a fresh official Real Exam attempt',
    'new timed run': 'Restart Mock Exam stopwatch at 00:00 for a speed run',
    'finish run': 'Save this timed run and view your Exam Report',
    'ask ai tutor': 'Open 1-on-1 AI Tutor for step-by-step guidance',
    'ask tutor': 'Ask your AI Tutor for step-by-step guidance',
    'textbook order': 'Display questions in original textbook sequence',
    'by marks (1m–5m)': 'Group questions by mark weight (1M to 5M)',
    'by marks (1m-5m)': 'Group questions by mark weight (1M to 5M)',
    'submit answer': 'Submit your answer for instant AI grading',
    'submit exam': 'Finish and submit all answers for final grading',
    'mark for review': 'Flag this question to revisit before submitting',
    'marked for review': 'Unflag this question from your review list',
    'prev': 'Go to the previous question',
    'previous': 'Go to the previous question',
    'next': 'Move to the next question',
    'next question': 'Move to the next question',
    'prev page': 'Turn to the previous book page',
    'next page': 'Turn to the next book page',
    'back': 'Go back to the previous page',
    'back to chapter': 'Return to chapter overview & study steps',
    'exam history': 'View all your past Real & Mock exam attempts',
    'expand all': 'Expand details for every question on this page',
    'collapse all': 'Collapse all expanded question cards',
    'video solution': 'Watch the animated video solution for this question',
    'hide video': 'Close the video solution player',
    'why this score?': 'See step-by-step reasoning behind your marks',
    'why?': 'See step-by-step reasoning behind your marks',
    'cancel': 'Cancel and close without saving changes',
    'close': 'Close this panel',
    'clear': 'Clear current input or canvas',
    'save': 'Save your changes',
    'save preferences': 'Save your updated personal preferences',
    'save all preferences': 'Save all your updated preferences',
    'print / save pdf': 'Print this official report or save as PDF',
    'log in': 'Sign in to your SAXAZ account',
    'log out': 'Sign out of your SAXAZ account',
    'start free': 'Create your free SAXAZ student account'
  };

  var BTN_SELECTOR = [
    '[data-tip]',
    '[title]',
    'button',
    'a.sx-btn',
    'a.sx-pill',
    'a.sx-brand',
    'a.sx-link',
    'a.btn',
    '.sx-seg-btn',
    '.sx-ico-btn',
    '.sx-icon-btn',
    '.sx-search-btn',
    '.sx-lang-btn',
    '.sx-avatar-btn',
    '.sx-mock-ctrl-btn',
    '.sx-mock-real-cta',
    '.sx-qpill',
    '[role="tab"]'
  ].join(',');

  function isCoarseTouch() {
    return !!(window.matchMedia && window.matchMedia('(hover: none), (pointer: coarse)').matches);
  }

  function stripNativeTitles(startEl) {
    var cur = startEl;
    while (cur && cur !== document.body && cur.nodeType === 1) {
      var t = cur.getAttribute('title');
      if (t !== null) {
        if (t.trim()) cur.setAttribute('data-sx-orig-title', t.trim());
        cur.removeAttribute('title');
      }
      cur = cur.parentElement;
    }
  }

  function cleanVisibleLabel(el) {
    if (!el) return '';
    var clone = el.cloneNode(true);
    var icons = clone.querySelectorAll('.material-symbols-outlined, svg, kbd, script, style, .sr-only');
    for (var i = 0; i < icons.length; i++) icons[i].remove();
    return (clone.textContent || '').replace(/[→←↑↓•·]/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function resolveButtonTip(el) {
    if (!el || el.hasAttribute('data-no-tip')) return '';

    var explicit = (el.getAttribute('data-tip') || '').trim();
    if (explicit) return explicit;

    var freshTitle = (el.getAttribute('title') || '').trim();
    if (freshTitle) {
      el.setAttribute('data-sx-orig-title', freshTitle);
      el.removeAttribute('title');
    }
    var origTitle = (el.getAttribute('data-sx-orig-title') || '').trim();
    if (origTitle && origTitle.toLowerCase() !== 'text size') {
      return origTitle;
    }

    if (el.classList.contains('sx-brand')) return 'Go to SAXAZ Home';
    if (el.classList.contains('sx-aa')) return 'Adjust reading text size (100% – 135%)';
    if (el.classList.contains('sx-lang-btn')) {
      var ltxt = (el.textContent || '').trim();
      return ltxt === 'EN' ? 'Switch interface language to English' : 'Switch interface language to Malayalam';
    }
    if (el.classList.contains('sx-avatar-btn')) return 'Open profile, settings & account menu';
    if (el.classList.contains('sx-search-btn')) return 'Quick-search lessons, exams & AI Tutor (Ctrl+K)';

    var label = cleanVisibleLabel(el);
    var lower = label.toLowerCase();

    if (ACTION_TIPS[lower]) return ACTION_TIPS[lower];

    // Segmented filter tabs vs preference radio pills
    if (el.classList.contains('sx-seg-btn') || el.getAttribute('role') === 'tab') {
      var baseSeg = lower.replace(/\(\d+\)/g, '').trim();
      if (ACTION_TIPS[baseSeg]) return ACTION_TIPS[baseSeg];
      if (el.querySelector && el.querySelector('input[type="radio"]')) {
        if (label) return 'Set preference to ' + label;
      }
      if (label) return 'Switch view to ' + label;
    }

    // Question strip number pills ("1", "2", "H1", "P1")
    if (el.classList.contains('sx-qpill') || /^[0-9]{1,2}$/.test(label)) {
      return 'Jump to Question ' + label;
    }

    var aria = (el.getAttribute('aria-label') || '').trim();
    if (aria) {
      var ariaLow = aria.toLowerCase();
      if (ACTION_TIPS[ariaLow]) return ACTION_TIPS[ariaLow];
      return aria;
    }

    if (origTitle) return origTitle;

    if (!label || label.length > 44) return '';
    if (label === '\u00d7' || label === '\u2715') return 'Close';

    if (el.tagName === 'A' && el.getAttribute('href')) {
      if (/^(open|view|watch|start|take|attend|go|back|return|try|ask|review|practice|retake|sign|log)\b/i.test(label)) {
        return label;
      }
      return 'Open ' + label;
    }

    if (/^(open|view|watch|start|take|save|submit|retry|grade|check|play|pause|resume|replay|reset|clear|close|cancel|delete|remove|edit|add|create|unlock|print|download|copy|listen|read|hide|show|expand|collapse|finish|new|switch|select|choose)\b/i.test(label)) {
      return label;
    }

    return 'Click: ' + label;
  }

  function initTooltips() {
    if (!document.body || document.getElementById('saxaz-tooltip-pop')) return;

    var pop = document.createElement('div');
    pop.id = 'saxaz-tooltip-pop';
    pop.className = 'sx-tooltip-pop';
    pop.setAttribute('role', 'tooltip');
    pop.setAttribute('aria-hidden', 'true');
    pop.innerHTML = '<i></i><span></span>';
    document.body.appendChild(pop);

    var textSpan = pop.querySelector('span');
    var activeEl = null;
    var showTimer = null;
    var warmUntil = 0;

    function positionTooltip(target) {
      if (!target || !target.isConnected) return hideTooltip();
      var rect = target.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return hideTooltip();

      var popRect = pop.getBoundingClientRect();
      var pw = popRect.width || 160;
      var ph = popRect.height || 34;
      var gap = 9;
      var vw = window.innerWidth;
      var vh = window.innerHeight;

      // Prefer below for topbar items or near top of viewport; otherwise prefer above
      var preferBottom = rect.top < 84 || (rect.top - ph - gap < 8);
      var place = preferBottom ? 'bottom' : 'top';
      if (place === 'bottom' && rect.bottom + ph + gap > vh - 8 && rect.top - ph - gap > 8) {
        place = 'top';
      }

      var top = place === 'bottom' ? (rect.bottom + gap) : (rect.top - ph - gap);
      var centerX = rect.left + rect.width / 2;
      var left = Math.max(10, Math.min(vw - pw - 10, centerX - pw / 2));
      var arrowX = Math.max(14, Math.min(pw - 14, centerX - left));

      pop.setAttribute('data-place', place);
      pop.style.setProperty('--tip-x', Math.round(left) + 'px');
      pop.style.setProperty('--tip-y', Math.round(top) + 'px');
      pop.style.setProperty('--tip-arrow-x', Math.round(arrowX) + 'px');
    }

    function showTooltip(target, text) {
      if (isCoarseTouch() || !target || !text) return;
      activeEl = target;
      textSpan.textContent = text;
      pop.classList.remove('is-visible');
      pop.style.setProperty('--tip-x', '-9999px');
      pop.style.setProperty('--tip-y', '-9999px');
      requestAnimationFrame(function () {
        if (activeEl !== target) return;
        positionTooltip(target);
        pop.classList.add('is-visible');
        pop.setAttribute('aria-hidden', 'false');
      });
    }

    function hideTooltip() {
      if (showTimer) {
        clearTimeout(showTimer);
        showTimer = null;
      }
      if (activeEl) {
        warmUntil = Date.now() + 350;
      }
      activeEl = null;
      pop.classList.remove('is-visible');
      pop.setAttribute('aria-hidden', 'true');
    }

    document.addEventListener('mouseover', function (e) {
      if (isCoarseTouch()) return;
      var raw = e.target;
      if (!raw || raw.nodeType !== 1) return;
      stripNativeTitles(raw);

      var btn = raw.closest(BTN_SELECTOR);
      if (!btn || btn.disabled || btn.getAttribute('aria-disabled') === 'true') {
        if (activeEl) hideTooltip();
        return;
      }
      // Avoid showing generic auto-tips on giant full-card wrappers, surf badge cards, or wide accordion headers unless explicitly tagged with data-tip
      if (btn.classList.contains('sx-qreview-head') || btn.hasAttribute('data-sx-surf-badge')) {
        if (activeEl) hideTooltip();
        return;
      }
      if (activeEl === btn) return;

      var tip = resolveButtonTip(btn);
      if (!tip) {
        if (activeEl) hideTooltip();
        return;
      }

      if (showTimer) clearTimeout(showTimer);
      var delay = Date.now() < warmUntil ? 45 : 140;
      showTimer = setTimeout(function () {
        showTooltip(btn, tip);
      }, delay);
    }, true);

    document.addEventListener('mouseout', function (e) {
      if (!activeEl && !showTimer) return;
      var rel = e.relatedTarget;
      if (activeEl && rel && activeEl.contains(rel)) return;
      var fromBtn = e.target && e.target.closest ? e.target.closest(BTN_SELECTOR) : null;
      if (fromBtn && rel && fromBtn.contains(rel)) return;
      hideTooltip();
    }, true);

    document.addEventListener('pointerdown', hideTooltip, true);
    document.addEventListener('scroll', hideTooltip, true);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') hideTooltip();
    }, true);
    window.addEventListener('blur', hideTooltip);
  }

  /* --------------------------------------------------------------------------
     Always-Moving 3D RGBA Sprite Badges + Hover Straight Pop-Up (NO Tilt)
     -------------------------------------------------------------------------- */
  var __sxBadgeWakeFns = [];
  var __sxIllusWakeFns = [];

  function initSurfBadges() {
    var reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var cards = document.querySelectorAll('[data-sx-surf-badge]');
    if (!cards.length) return;

    var COLS = 8;
    var TOTAL_FRAMES = 48;
    var CELL = 340;
    var sheetCache = {};

    function loadSheet(url, onReady) {
      if (!url) return;
      var entry = sheetCache[url];
      if (!entry) {
        var im = new Image();
        im.decoding = 'async';
        entry = { img: im, ready: false, waiters: [] };
        sheetCache[url] = entry;
        im.onload = function () {
          entry.ready = true;
          var list = entry.waiters.slice();
          entry.waiters.length = 0;
          list.forEach(function (fn) { fn(im); });
        };
        im.src = url;
      }
      if (entry.ready) {
        onReady(entry.img);
      } else {
        entry.waiters.push(onReady);
      }
    }

    cards.forEach(function (card, cardIdx) {
      if (card.__sxSurfBound) return;
      card.__sxSurfBound = true;

      var stage = card.querySelector('.sx-badge-stage');
      var canvas = card.querySelector('.sx-badge-canvas');
      var ctx = canvas && canvas.getContext ? canvas.getContext('2d') : null;
      var sheetUrl = canvas ? canvas.getAttribute('data-sx-sheet') : '';
      var cardCols = (canvas && parseInt(canvas.getAttribute('data-sx-cols') || '', 10)) || COLS;
      var cardTotal = (canvas && parseInt(canvas.getAttribute('data-sx-frames') || '', 10)) || TOTAL_FRAMES;
      var cellW = (canvas && parseInt(canvas.getAttribute('width') || '', 10)) || CELL;
      var cellH = (canvas && parseInt(canvas.getAttribute('height') || '', 10)) || cellW;
      var sheetImg = null;

      var state = {
        hovered: false,
        inView: true,
        scale: 1, vScale: 0,
        stageScale: 1, vStageScale: 0,
        lift: 0, vLift: 0,
        framePos: (cardIdx * 11) % cardTotal,
        drawnIdx: -1,
        raf: 0,
        lastTs: 0
      };

      function drawFrame(idx) {
        if (!ctx || !sheetImg) return;
        var clamped = ((idx % cardTotal) + cardTotal) % cardTotal;
        if (state.drawnIdx === clamped) return;
        state.drawnIdx = clamped;
        var col = clamped % cardCols;
        var row = Math.floor(clamped / cardCols);
        ctx.clearRect(0, 0, cellW, cellH);
        ctx.drawImage(sheetImg, col * cellW, row * cellH, cellW, cellH, 0, 0, cellW, cellH);
      }

      function stepPhysicsAndSprite(dt) {
        var k = 260;
        var d = 22;

        // Clean straight-up Pop-Up ONLY on hover — zero tilt / zero rotation
        var tScale = state.hovered ? 1.065 : 1;
        var tStage = state.hovered ? 1.075 : 1;
        var tLift = state.hovered ? -8 : 0;

        state.vScale += ((tScale - state.scale) * k - state.vScale * d) * dt;
        state.scale += state.vScale * dt;

        state.vStageScale += ((tStage - state.stageScale) * k - state.vStageScale * d) * dt;
        state.stageScale += state.vStageScale * dt;

        state.vLift += ((tLift - state.lift) * k - state.vLift * d) * dt;
        state.lift += state.vLift * dt;

        var springSettled =
          Math.abs(tScale - state.scale) < 0.0008 &&
          Math.abs(state.vScale) < 0.002 &&
          Math.abs(tLift - state.lift) < 0.04;

        if (!springSettled || state.hovered) {
          card.style.transform =
            'translate3d(0,' + state.lift.toFixed(2) + 'px,0) ' +
            'scale3d(' + state.scale.toFixed(4) + ',' + state.scale.toFixed(4) + ',1)';
          if (stage) {
            stage.style.transform =
              'scale3d(' + state.stageScale.toFixed(4) + ',' + state.stageScale.toFixed(4) + ',1)';
          }
        } else {
          card.style.transform = '';
          if (stage) stage.style.transform = '';
        }

        // Always-moving continuous sprite loop whenever visible in viewport
        var spriteAnimating = false;
        if (sheetImg && !reducedMotion && state.inView && !document.hidden) {
          var fps = state.hovered ? 20.5 : 16.5;
          state.framePos = (state.framePos + dt * fps) % cardTotal;
          drawFrame(Math.floor(state.framePos));
          card.classList.add('is-sprite-active');
          spriteAnimating = true;
        }

        return springSettled && !state.hovered && !spriteAnimating;
      }

      function tick(ts) {
        if (document.hidden) {
          state.raf = 0;
          state.lastTs = 0;
          return;
        }
        if (!state.lastTs) state.lastTs = ts;
        var dt = Math.min(0.032, Math.max(0.004, (ts - state.lastTs) / 1000));
        state.lastTs = ts;
        if (stepPhysicsAndSprite(dt)) {
          card.style.transform = '';
          if (stage) stage.style.transform = '';
          state.raf = 0;
          state.lastTs = 0;
          return;
        }
        state.raf = requestAnimationFrame(tick);
      }

      function wakeSpring() {
        if (reducedMotion || document.hidden) return;
        if (!state.raf) {
          state.lastTs = 0;
          state.raf = requestAnimationFrame(tick);
        }
      }
      __sxBadgeWakeFns.push(wakeSpring);

      // Locked ("coming soon") subject tiles stay as a still picture: no big sprite sheet download.
      var staticBadge = card.classList.contains('is-soon') || card.hasAttribute('data-sx-static');
      var sheetRequested = false;
      function ensureSheet() {
        if (sheetRequested || !sheetUrl || reducedMotion || staticBadge) return;
        sheetRequested = true;
        loadSheet(sheetUrl, function (im) {
          sheetImg = im;
          drawFrame(Math.floor(state.framePos));
          card.classList.add('is-sprite-active');
          wakeSpring();
        });
      }

      if (!reducedMotion && 'IntersectionObserver' in window) {
        // The sprite sheet is fetched only when the badge is on (or near) the screen.
        var badgeIo = new IntersectionObserver(function (entries) {
          entries.forEach(function (ent) {
            state.inView = ent.isIntersecting;
            if (ent.isIntersecting) { ensureSheet(); wakeSpring(); }
          });
        }, { rootMargin: '360px' });
        badgeIo.observe(card);
      } else {
        ensureSheet();
      }

      function startSurf() {
        state.hovered = true;
        card.classList.add('is-surfing');
        wakeSpring();
      }

      function endSurf() {
        state.hovered = false;
        card.classList.remove('is-surfing');
        wakeSpring();
      }

      card.addEventListener('pointerenter', function (e) {
        if (e.pointerType === 'touch') return;
        startSurf();
      });
      card.addEventListener('pointerleave', function (e) {
        if (e.pointerType === 'touch') return;
        endSurf();
      });
      card.addEventListener('focus', function () { startSurf(); });
      card.addEventListener('blur', function () { endSurf(); });
    });
  }

  /* --------------------------------------------------------------------------
     Always-Moving Syllabus Illustrations Engine (True Looping RGBA Sprite Sheets)
     Continuously animates without needing cursor hover (Pop-Up on hover, Zero Tilt)
     -------------------------------------------------------------------------- */
  var __sxIllusSheetCache = {};

  function initLivingIllustrations() {
    var reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var items = document.querySelectorAll('[data-sx-pop-illus]');
    if (!items.length) return;

    function loadIllusSheet(url, onReady) {
      if (!url) return;
      var entry = __sxIllusSheetCache[url];
      if (!entry) {
        var im = new Image();
        im.decoding = 'async';
        entry = { img: im, ready: false, waiters: [] };
        __sxIllusSheetCache[url] = entry;
        im.onload = function () {
          entry.ready = true;
          var list = entry.waiters.slice();
          entry.waiters.length = 0;
          list.forEach(function (fn) { fn(im); });
        };
        im.src = url;
      }
      if (entry.ready) {
        onReady(entry.img);
      } else {
        entry.waiters.push(onReady);
      }
    }

    items.forEach(function (box, illusIdx) {
      if (box.__sxIllusBound) return;
      box.__sxIllusBound = true;

      var img = box.querySelector('.sx-illus-img');
      var canvas = box.querySelector('.sx-illus-canvas');
      var ctx = canvas && canvas.getContext ? canvas.getContext('2d') : null;
      if (!img || !canvas || !ctx) return;

      var sheetUrl = canvas.getAttribute('data-sx-sheet') || '';
      var cols = parseInt(canvas.getAttribute('data-sx-cols') || '6', 10) || 6;
      var totalFrames = parseInt(canvas.getAttribute('data-sx-frames') || '36', 10) || 36;
      var cellW = parseInt(canvas.getAttribute('width') || '360', 10) || 360;
      var cellH = parseInt(canvas.getAttribute('height') || '360', 10) || 360;
      var sheetImg = null;

      var st = {
        hovered: false,
        inView: true,
        forceAwakeUntil: 0,
        scale: 1, vScale: 0,
        lift: 0, vLift: 0,
        framePos: (illusIdx * 7) % totalFrames,
        drawnIdx: -1,
        raf: 0,
        lastTs: 0
      };

      function drawSpriteFrame(idx) {
        if (!ctx || !sheetImg) return;
        var clamped = ((idx % totalFrames) + totalFrames) % totalFrames;
        if (st.drawnIdx === clamped) return;
        st.drawnIdx = clamped;
        var col = clamped % cols;
        var row = Math.floor(clamped / cols);
        ctx.clearRect(0, 0, cellW, cellH);
        ctx.drawImage(sheetImg, col * cellW, row * cellH, cellW, cellH, 0, 0, cellW, cellH);
      }

      function isBoxLayoutVisible() {
        return !!(box.offsetWidth || box.offsetHeight || box.getClientRects().length);
      }

      function step(dt) {
        var k = 250;
        var d = 22;
        // Clean straight-up Pop-Up ONLY on hover — zero tilt / zero rotation
        var tScale = st.hovered ? 1.055 : 1;
        var tLift = st.hovered ? -7 : 0;

        st.vScale += ((tScale - st.scale) * k - st.vScale * d) * dt;
        st.scale += st.vScale * dt;

        st.vLift += ((tLift - st.lift) * k - st.vLift * d) * dt;
        st.lift += st.vLift * dt;

        var springSettled =
          Math.abs(tScale - st.scale) < 0.0008 &&
          Math.abs(st.vScale) < 0.002 &&
          Math.abs(tLift - st.lift) < 0.04;

        if (!springSettled || st.hovered) {
          box.style.transform =
            'translate3d(0,' + st.lift.toFixed(2) + 'px,0) ' +
            'scale3d(' + st.scale.toFixed(4) + ',' + st.scale.toFixed(4) + ',1)';
        } else {
          box.style.transform = '';
        }

        // Always-moving continuous sprite loop whenever visible on screen
        var activeNow = (st.inView || performance.now() < st.forceAwakeUntil) && isBoxLayoutVisible() && !document.hidden;
        var spriteAnimating = false;
        if (sheetImg && !reducedMotion && activeNow) {
          var fps = st.hovered ? 20.0 : 16.0;
          st.framePos = (st.framePos + dt * fps) % totalFrames;
          drawSpriteFrame(Math.floor(st.framePos));
          box.classList.add('is-anim-live');
          spriteAnimating = true;
        }

        return springSettled && !st.hovered && !spriteAnimating;
      }

      function loop(ts) {
        if (document.hidden) {
          st.raf = 0;
          st.lastTs = 0;
          return;
        }
        if (!st.lastTs) st.lastTs = ts;
        var dt = Math.min(0.032, Math.max(0.004, (ts - st.lastTs) / 1000));
        st.lastTs = ts;
        if (step(dt)) {
          box.style.transform = '';
          st.raf = 0;
          st.lastTs = 0;
          return;
        }
        st.raf = requestAnimationFrame(loop);
      }

      function wake() {
        if (reducedMotion || document.hidden) return;
        if (!st.raf) {
          st.lastTs = 0;
          st.raf = requestAnimationFrame(loop);
        }
      }

      function preloadAndPlayNow() {
        st.forceAwakeUntil = performance.now() + 1800;
        if (sheetUrl && !sheetImg && !reducedMotion) {
          loadIllusSheet(sheetUrl, function (im) {
            sheetImg = im;
            drawSpriteFrame(Math.floor(st.framePos));
            box.classList.add('is-anim-live');
            wake();
          });
        } else if (sheetImg && !reducedMotion) {
          drawSpriteFrame(Math.floor(st.framePos));
          box.classList.add('is-anim-live');
          wake();
        }
      }
      box.__sxPreloadSheet = preloadAndPlayNow;
      __sxIllusWakeFns.push(preloadAndPlayNow);

      // Observe viewport visibility so every on-screen illustration animates automatically (even when x-show expands!)
      if (sheetUrl && !reducedMotion && 'IntersectionObserver' in window) {
        st.inView = false;
        var io = new IntersectionObserver(function (entries) {
          entries.forEach(function (ent) {
            st.inView = ent.isIntersecting;
            if (ent.isIntersecting) {
              preloadAndPlayNow();
            }
          });
        }, { rootMargin: '420px' });
        io.observe(box);
      } else if (sheetUrl && !reducedMotion) {
        preloadAndPlayNow();
      }

      // If already visible at boot time, start immediately
      if (isBoxLayoutVisible()) {
        preloadAndPlayNow();
      }

      function startPop() {
        st.hovered = true;
        box.classList.add('is-popping');
        preloadAndPlayNow();
      }

      function endPop() {
        st.hovered = false;
        box.classList.remove('is-popping');
        wake();
      }

      box.addEventListener('pointerenter', function (e) {
        if (e.pointerType === 'touch') return;
        startPop();
      });
      box.addEventListener('pointerleave', function (e) {
        if (e.pointerType === 'touch') return;
        endPop();
      });
      box.addEventListener('focus', startPop);
      box.addEventListener('blur', endPop);
    });
  }

  window.saxazWakeLivingIllustrations = function () {
    initSurfBadges();
    initLivingIllustrations();
    __sxBadgeWakeFns.forEach(function (fn) { try { fn(); } catch (e) {} });
    __sxIllusWakeFns.forEach(function (fn) { try { fn(); } catch (e) {} });
  };

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && window.saxazWakeLivingIllustrations) {
      window.saxazWakeLivingIllustrations();
    }
  });

  function bootSaxazInteractive() {
    initTooltips();
    initSurfBadges();
    initLivingIllustrations();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootSaxazInteractive);
  } else {
    bootSaxazInteractive();
  }
  document.addEventListener('htmx:afterSwap', function () {
    initSurfBadges();
    initLivingIllustrations();
  });
})();
