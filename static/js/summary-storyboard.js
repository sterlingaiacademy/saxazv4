/* SAXAZ Smart Sentence-Synced Storyboard, Looping 3D Sprite Renderer & Key-Term Engine */
(function () {
  'use strict';

  var V = '?v=541';
  var SP = '/static/images/saxaz_web/summary_sprites/';
  var SY = '/static/images/saxaz_web/syllabus/';

  // Key biology & board-exam terms highlighted in text and emphasized in Gemini 3.8 TTS voice
  var KEY_TERMS = [
    'Life Processes', 'Autotrophic Nutrition', 'Heterotrophic Nutrition',
    'Photosynthesis', 'Chlorophyll', 'Carbon dioxide', 'Glucose', 'Oxygen',
    'Nutrition', 'Digestion', 'Saliva', 'Starch', 'Stomach', 'Enzymes', 'Proteins',
    'Small intestine', 'Absorption', 'Large intestine', 'Mouth',
    'Anaerobic respiration', 'Lactic acid', 'Energy currency',
    'Respiration', 'Breathing', 'ATP', 'Trachea', 'Lungs',
    'Pons', 'Medulla', 'Brain',
    'Transportation', 'Right atrium', 'Right ventricle', 'Left atrium', 'Left ventricle',
    'Heart', 'Arteries', 'Veins', 'Capillaries',
    'RBC', 'WBC', 'Platelets', 'Plasma', 'Xylem', 'Phloem', 'Translocation',
    '250 crore', '30 feet',
    '1 million', 'Filters of the body',
    'Excretion', 'Kidneys', 'Kidney', 'Nephrons', 'Urea', 'Urine',
    'Ureter', 'Urinary bladder', 'Urethra', 'Sweat', 'Liver',
    'Transpiration', 'Stomata', 'Resins', 'Gums'
  ];

  var KEY_SINGLE_WORDS = new Set([
    'life', 'processes', 'nutrition', 'autotrophic', 'heterotrophic', 'photosynthesis',
    'chlorophyll', 'glucose', 'oxygen', 'carbon', 'dioxide', 'sunlight',
    'digestion', 'mouth', 'saliva', 'starch', 'stomach', 'acid', 'enzymes', 'proteins',
    'intestine', 'absorption', 'respiration', 'breathing', 'atp', 'currency',
    'trachea', 'lungs', 'anaerobic', 'lactic', 'pons', 'medulla', 'brain',
    'transportation', 'heart', 'chambers', 'atrium', 'ventricle', 'arteries', 'veins', 'capillaries',
    'rbc', 'wbc', 'platelets', 'plasma', 'xylem', 'phloem', 'translocation',
    '250', 'crore', '30', 'feet', 'excretion', 'urea', 'kidneys', 'kidney', 'nephrons', 'million',
    'urine', 'ureter', 'bladder', 'urethra', 'sweat', 'liver', 'transpiration', 'stomata', 'resins', 'gums'
  ]);

  window.saxazIsKeyScienceWord = function (visWord) {
    var clean = String(visWord || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    return clean.length >= 2 && KEY_SINGLE_WORDS.has(clean);
  };

  window.saxazExtractBeatKeywords = function (beatText) {
    var low = String(beatText || '').toLowerCase();
    var out = [];
    for (var i = 0; i < KEY_TERMS.length; i++) {
      var t = KEY_TERMS[i];
      var tl = t.toLowerCase();
      if (low.indexOf(tl) !== -1 && out.indexOf(t) === -1) {
        out.push(t);
        if (out.length >= 5) break;
      }
    }
    return out;
  };

  window.saxazCountSyllables = function (rawWord) {
    var w = String(rawWord || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    if (!w) return 0.5;
    if (w === 'atp' || w === 'rbc' || w === 'wbc' || w === 'co2') return 3.0;
    if (w === 'o2') return 2.0;
    if (w === 'h2o') return 3.0;
    if (/^\d+$/.test(w)) return Math.min(4.0, Math.max(1.2, w.length * 1.1));
    if (w.length <= 3) return 1.0;
    var cleaned = w.replace(/(?:[^laeiouy]es|ed|[^laeiouy]e)$/, '').replace(/^y/, '');
    var matches = cleaned.match(/[aeiouy]{1,2}/g);
    return Math.max(1.0, matches ? matches.length : 1.0);
  };

  // Full 12-part Chapter 5 Smart Popup Storyboard (every sentence covered with looping 36-frame 3D sprites!)
  window.SAXAZ_SUMMARY_CUES = {
    0: [
      {
        id: 'body_alive',
        label: '4 Jobs Alive',
        idle: SP + 'anim_body_alive.webp' + V,
        sheet: SP + 'anim_body_alive_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['hey', 'alive', 'four', 'sleeping', 'sitting', 'playing'],
        tutorPose: 'amazed',
        tutorCallout: '4 organs work 24/7!',
        tapLabel: 'Tap to Check Vitals',
        tapFacts: [
          'Heart, Lungs, Stomach & Kidneys never sleep!',
          'All 4 Life Processes run even while you dream!'
        ]
      },
      {
        id: 'team_intro',
        label: 'Life Processes Team',
        idle: SY + 'nutshell_p1_img1.webp' + V,
        sheet: SY + 'nutshell_p1_img1_sheet.webp' + V,
        w: 408, h: 272, cols: 6, frames: 36,
        triggers: ['life processes', 'survive', 'detail'],
        tutorPose: 'cheer',
        tutorCallout: 'Meet the 4 Life Processes!',
        tapLabel: 'Tap to Meet All 4 Heroes',
        tapFacts: [
          'Nutrition + Respiration + Transport + Excretion!',
          'If even 1 stops, the body cannot survive!'
        ]
      }
    ],
    1: [
      {
        id: 'nutrition_fuel',
        label: 'Food = Fuel',
        idle: SP + 'anim_nutrition_fuel.webp' + V,
        sheet: SP + 'anim_nutrition_fuel_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['nutrition', 'energy', 'growth', 'repair', 'two types'],
        tutorPose: 'pointing',
        tutorCallout: 'Food powers growth & repair!',
        tapLabel: 'Tap to Boost Vitality',
        tapFacts: [
          'Nutrition = Food for Energy, Growth & Repair!',
          'Two types: Autotrophic (Plants) & Heterotrophic (Animals)!'
        ]
      },
      {
        id: 'photosynthesis',
        label: 'Photosynthesis',
        idle: SP + 'anim_photosynthesis_plant.webp' + V,
        sheet: SP + 'anim_photosynthesis_plant_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['autotrophic', 'photosynthesis', 'sunlight', 'roots', 'chlorophyll', 'glucose', 'oxygen', 'equation', '6co2'],
        tutorPose: 'amazed',
        tutorCallout: 'Leaves make Glucose + O2!',
        tapLabel: 'Tap to Shine Sunlight',
        tapFacts: [
          'Sunlight + Water + CO2 -> Glucose + Oxygen!',
          'Chlorophyll inside leaves traps golden sunlight!',
          'Equation: 6CO2 + 12H2O -> C6H12O6 + 6O2 + 6H2O'
        ]
      }
    ],
    2: [
      {
        id: 'mouth_chew',
        label: '1. Mouth & Saliva',
        idle: SY + 'nutshell_p1_img0.webp' + V,
        sheet: SY + 'nutshell_p1_img0_sheet.webp' + V,
        w: 360, h: 240, cols: 6, frames: 36,
        triggers: ['heterotrophic', 'depend', 'mouth', 'teeth', 'saliva', 'starch'],
        tutorPose: 'pointing',
        tutorCallout: 'Digestion starts in the Mouth!',
        tapLabel: 'Tap to Mix Saliva',
        tapFacts: [
          'Teeth chew food & Saliva breaks down starch!',
          'Exam Tip: Mouth is the 1st major digestive organ!'
        ]
      },
      {
        id: 'stomach_acid',
        label: '2. Stomach Acid',
        idle: SP + 'anim_stomach_acid.webp' + V,
        sheet: SP + 'anim_stomach_acid_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['stomach', 'acid', 'enzymes', 'proteins'],
        tutorPose: 'amazed',
        tutorCallout: 'Acid + Enzymes break Proteins!',
        tapLabel: 'Tap to Churn Stomach',
        tapFacts: [
          'Stomach acid & enzymes break down proteins!',
          'Acid softens food and protects against germs!'
        ]
      },
      {
        id: 'intestine_absorb',
        label: '3. Small Intestine',
        idle: SP + 'anim_intestine_absorb.webp' + V,
        sheet: SP + 'anim_intestine_absorb_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['small intestine', 'absorption', 'blood', 'large intestine', 'removed', 'fuel'],
        tutorPose: 'cheer',
        tutorCallout: 'Nutrients absorbed into Blood!',
        tapLabel: 'Tap to Absorb Nutrients',
        tapFacts: [
          'Most digestion & absorption happens in Small Intestine!',
          'Digested food enters blood; waste leaves via Large Intestine!'
        ]
      }
    ],
    3: [
      {
        id: 'lungs_breathe',
        label: '1. Breathing Lungs',
        idle: SP + 'anim_lungs_breathe.webp' + V,
        sheet: SP + 'anim_lungs_breathe_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['respiration', 'breathing', 'taking in', 'giving out'],
        tutorPose: 'pointing',
        tutorCallout: 'O2 in, CO2 out!',
        tapLabel: 'Tap to Take a Deep Breath',
        tapFacts: [
          'Breathing = taking in Oxygen & giving out CO2!',
          'Real respiration happens deep inside EVERY cell!'
        ]
      },
      {
        id: 'cell_atp',
        label: '2. Cell ATP Power',
        idle: SP + 'anim_cell_atp.webp' + V,
        sheet: SP + 'anim_cell_atp_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['inside every cell', 'glucose', 'release energy', 'atp', 'currency', 'equation'],
        tutorPose: 'amazed',
        tutorCallout: 'ATP = Cell Energy Currency!',
        tapLabel: 'Tap to Charge ATP Energy',
        tapFacts: [
          'ATP is called the Energy Currency of the Cell!',
          'Glucose + Oxygen -> CO2 + Water + ATP Energy!'
        ]
      }
    ],
    4: [
      {
        id: 'airway_path',
        label: '1. Airway to Blood',
        idle: SP + 'anim_lungs_breathe.webp' + V,
        sheet: SP + 'anim_lungs_breathe_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['nose', 'trachea', 'lungs', 'carries oxygen'],
        tutorPose: 'pointing',
        tutorCallout: 'Nose -> Trachea -> Lungs!',
        tapLabel: 'Tap to Trace Oxygen Path',
        tapFacts: [
          'Air path: Nose -> Trachea -> Lungs -> Blood -> Cells!',
          'Blood picks up O2 and drops off CO2 at the lungs!'
        ]
      },
      {
        id: 'muscle_sprint',
        label: '2. Muscles & Lactic Acid',
        idle: SP + 'anim_muscle_sprint.webp' + V,
        sheet: SP + 'anim_muscle_sprint_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['heavy exercise', 'less oxygen', 'anaerobic', 'muscles', 'lactic acid', 'muscle pain', 'without respiration'],
        tutorPose: 'amazed',
        tutorCallout: 'Low O2 makes Lactic Acid!',
        tapLabel: 'Tap to Sprint & Feel Energy',
        tapFacts: [
          'Heavy sprint + low O2 = Anaerobic Respiration!',
          'Lactic Acid buildup causes muscle cramps & pain!'
        ]
      }
    ],
    5: [
      {
        id: 'brain_control',
        label: '1. Brain Auto-Pilot',
        idle: SY + 'nutshell_p2_img1.webp' + V,
        sheet: SY + 'nutshell_p2_img1_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['how is breathing', 'controlled', 'brain'],
        tutorPose: 'thinking',
        tutorCallout: 'Who controls breathing?',
        tapLabel: 'Tap to Check Auto-Pilot',
        tapFacts: [
          'Your brain paces every breath automatically!',
          'Special centres inside the brainstem run the show!'
        ]
      },
      {
        id: 'pons_medulla',
        label: '2. Pons & Medulla',
        idle: SP + 'anim_pons_medulla.webp' + V,
        sheet: SP + 'anim_pons_medulla_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['special centres', 'pons', 'medulla'],
        tutorPose: 'amazed',
        tutorCallout: '2 in Pons + 2 in Medulla!',
        tapLabel: 'Tap to Pulse Brain Stem',
        tapFacts: [
          'Exam Key: 2 centres in Pons + 2 centres in Medulla!',
          'Golden Pons + Cyan Medulla send rhythmic signals!'
        ]
      }
    ],
    6: [
      {
        id: 'heart_chambers',
        label: '1. 4-Chamber Heart',
        idle: SY + 'nutshell_p2_img2.webp' + V,
        sheet: SY + 'nutshell_p2_img2_sheet.webp' + V,
        w: 262, h: 360, cols: 6, frames: 36,
        triggers: ['transportation', 'heart', 'pump', '4 chambers', 'atrium', 'ventricle'],
        tutorPose: 'pointing',
        tutorCallout: '4 Chambers keep blood pure!',
        tapLabel: 'Tap to Pump Lub-Dub',
        tapFacts: [
          '4 Chambers: Right & Left Atrium + Right & Left Ventricle!',
          'Heart pumps blood non-stop to every single cell!'
        ]
      },
      {
        id: 'blood_vessels',
        label: '2. Arteries, Veins & Capillaries',
        idle: SP + 'anim_blood_vessels.webp' + V,
        sheet: SP + 'anim_blood_vessels_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['blood vessels', 'arteries', 'veins', 'capillaries', 'exchange'],
        tutorPose: 'amazed',
        tutorCallout: '3 Blood Vessel Highways!',
        tapLabel: 'Tap to Inspect All 3 Vessels',
        tapFacts: [
          'Arteries: O2-rich blood FROM Heart TO Body!',
          'Veins: CO2-rich blood FROM Body TO Heart!',
          'Capillaries: Ultra-thin exchange web at cells!'
        ]
      }
    ],
    7: [
      {
        id: 'blood_crew',
        label: '1. Blood Crew',
        idle: SP + 'anim_blood_crew.webp' + V,
        sheet: SP + 'anim_blood_crew_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['blood', 'rbc', 'wbc', 'platelets', 'plasma'],
        tutorPose: 'pointing',
        tutorCallout: 'RBC, WBC, Platelets & Plasma!',
        tapLabel: 'Tap to Meet Blood Crew',
        tapFacts: [
          'RBC = Carries Oxygen | WBC = Fights Disease!',
          'Platelets = Blood Clotting | Plasma = Carries Food & Waste!'
        ]
      },
      {
        id: 'xylem_phloem',
        label: '2. Xylem & Phloem',
        idle: SP + 'anim_xylem_phloem.webp' + V,
        sheet: SP + 'anim_xylem_phloem_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['plants', 'two tissues', 'xylem', 'phloem', 'translocation', 'stay in one place'],
        tutorPose: 'amazed',
        tutorCallout: 'Xylem UP · Phloem Both Ways!',
        tapLabel: 'Tap to Run Plant Elevators',
        tapFacts: [
          'Xylem lifts Water & Minerals UP ONLY from roots!',
          'Phloem moves Food UP & DOWN — called Translocation!'
        ]
      }
    ],
    8: [
      {
        id: 'heart_30ft',
        label: '250 Crore Beats · 30 Feet!',
        idle: SY + 'nutshell_p3_img2.webp' + V,
        sheet: SY + 'nutshell_p3_img2_sheet.webp' + V,
        w: 360, h: 240, cols: 6, frames: 36,
        triggers: ['oh my heart', '250', 'crore', 'lifetime', 'pressure', '30', 'feet'],
        tutorPose: 'amazed',
        tutorCallout: 'Whoa! 30 feet high!',
        tapLabel: 'Tap to Super-Pump 30 Feet!',
        tapFacts: [
          '250 Crore beats in a lifetime — zero vacations!',
          'Heart pressure can shoot blood 30 FEET straight up!'
        ]
      }
    ],
    9: [
      {
        id: 'kidneys_main',
        label: '1. Two Kidneys',
        idle: SY + 'nutshell_p3_img0.webp' + V,
        sheet: SY + 'nutshell_p3_img0_sheet.webp' + V,
        w: 328, h: 360, cols: 6, frames: 36,
        triggers: ['excretion', 'harmful waste', 'urea', 'poison', 'kidneys', 'two kidneys'],
        tutorPose: 'pointing',
        tutorCallout: 'Kidneys clear harmful waste!',
        tapLabel: 'Tap to Scan Kidneys',
        tapFacts: [
          'Excretion clears toxic Urea, extra water & salts!',
          'Two bean-shaped Kidneys are our main cleaners!'
        ]
      },
      {
        id: 'nephron_filter',
        label: '2. 1 Million Nephrons',
        idle: SP + 'anim_nephron_filter.webp' + V,
        sheet: SP + 'anim_nephron_filter_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['nephrons', '1 million', 'million', 'filter', 'urine'],
        tutorPose: 'amazed',
        tutorCallout: '1 Million Nephrons each!',
        tapLabel: 'Tap to Run Nephron Filter',
        tapFacts: [
          'Each kidney has ~1 MILLION microscopic Nephrons!',
          'Nephrons filter blood & send urea + water out as urine!'
        ]
      }
    ],
    10: [
      {
        id: 'urine_path',
        label: '1. Urinary Path',
        idle: SY + 'nutshell_p3_img0.webp' + V,
        sheet: SY + 'nutshell_p3_img0_sheet.webp' + V,
        w: 328, h: 360, cols: 6, frames: 36,
        triggers: ['urine goes', 'ureter', 'urinary bladder', 'urethra'],
        tutorPose: 'pointing',
        tutorCallout: 'Kidney -> Ureter -> Bladder!',
        tapLabel: 'Tap to Trace Urine Path',
        tapFacts: [
          'Path: Kidney -> Ureter -> Urinary Bladder -> Urethra!'
        ]
      },
      {
        id: 'body_excretors',
        label: '2. Lungs, Skin & Liver',
        idle: SP + 'anim_body_excretors.webp' + V,
        sheet: SP + 'anim_body_excretors_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['other ways', 'lungs', 'skin', 'sweat', 'liver', 'bile'],
        tutorPose: 'amazed',
        tutorCallout: 'Lungs, Skin & Liver help too!',
        tapLabel: 'Tap to Trigger Clean-Up',
        tapFacts: [
          'Lungs clear CO2 | Skin clears Sweat | Liver clears Bile!'
        ]
      },
      {
        id: 'plant_excretion',
        label: '3. Plant Excretion',
        idle: SP + 'anim_plant_excretion.webp' + V,
        sheet: SP + 'anim_plant_excretion_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['in plants', 'transpiration', 'stomata', 'old leaves', 'resins', 'gums', 'bark'],
        tutorPose: 'pointing',
        tutorCallout: 'Stomata, Old Leaves & Resins!',
        tapLabel: 'Tap to Release Vapour & Leaf',
        tapFacts: [
          'Plants clear waste via Stomata Transpiration!',
          'Also stored in falling old leaves, plus bark resins & gums!'
        ]
      },
      {
        id: 'body_filters',
        label: '4. Filters of Body',
        idle: SY + 'nutshell_p3_img1.webp' + V,
        sheet: SY + 'nutshell_p3_img1_sheet.webp' + V,
        w: 360, h: 260, cols: 6, frames: 36,
        triggers: ['filters of the body', 'clean our blood', 'dirty things', 'useful things'],
        tutorPose: 'cheer',
        tutorCallout: 'Keep the good, toss the waste!',
        tapLabel: 'Tap to Filter Blood',
        tapFacts: [
          'Kidneys keep good nutrients and flush out dirty waste!'
        ]
      }
    ],
    11: [
      {
        id: 'recap_nutrition',
        label: 'Nutrition',
        idle: SP + 'anim_photosynthesis_plant.webp' + V,
        sheet: SP + 'anim_photosynthesis_plant_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['conclusion', 'nutrition gives'],
        tutorPose: 'pointing',
        tutorCallout: '1. Nutrition = Food!',
        tapLabel: 'Tap to Recap Nutrition',
        tapFacts: ['Nutrition gives our body food & fuel!']
      },
      {
        id: 'recap_respiration',
        label: 'Respiration',
        idle: SP + 'anim_cell_atp.webp' + V,
        sheet: SP + 'anim_cell_atp_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['respiration gives'],
        tutorPose: 'amazed',
        tutorCallout: '2. Respiration = ATP Energy!',
        tapLabel: 'Tap to Recap Respiration',
        tapFacts: ['Respiration unlocks ATP energy from food!']
      },
      {
        id: 'recap_transport',
        label: 'Transport',
        idle: SP + 'anim_blood_crew.webp' + V,
        sheet: SP + 'anim_blood_crew_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['transportation delivers'],
        tutorPose: 'pointing',
        tutorCallout: '3. Transport = Delivery!',
        tapLabel: 'Tap to Recap Transport',
        tapFacts: ['Transportation delivers food & O2 to every cell!']
      },
      {
        id: 'recap_excretion',
        label: 'Excretion',
        idle: SP + 'anim_nephron_filter.webp' + V,
        sheet: SP + 'anim_nephron_filter_sheet.webp' + V,
        w: 360, h: 270, cols: 6, frames: 36,
        triggers: ['excretion removes'],
        tutorPose: 'pointing',
        tutorCallout: '4. Excretion = Clean-up!',
        tapLabel: 'Tap to Recap Excretion',
        tapFacts: ['Excretion removes harmful waste to keep us clean!']
      },
      {
        id: 'recap_team',
        label: 'All 4 Team!',
        idle: SY + 'nutshell_p1_img1.webp' + V,
        sheet: SY + 'nutshell_p1_img1_sheet.webp' + V,
        w: 408, h: 272, cols: 6, frames: 36,
        triggers: ['all four', 'like a team', 'team member', 'life processes'],
        tutorPose: 'cheer',
        tutorCallout: 'All 4 work as 1 Team!',
        tapLabel: 'Tap to High-Five the Team!',
        tapFacts: [
          'All 4 Life Processes work as ONE unstoppable team!',
          'You mastered Chapter 5 — ready to crush the exam!'
        ]
      }
    ]
  };

  // Global cached 60fps looping Sprite Sheet Player for the Smart Popup Canvas
  var sheetCache = {};
  function getSheet(url, cb) {
    if (!url) return;
    var entry = sheetCache[url];
    if (!entry) {
      var img = new Image();
      img.decoding = 'async';
      entry = { img: img, ready: false, cbs: [] };
      sheetCache[url] = entry;
      img.onload = function () {
        entry.ready = true;
        var list = entry.cbs.slice();
        entry.cbs.length = 0;
        for (var i = 0; i < list.length; i++) list[i](img);
      };
      img.src = url;
    }
    if (entry.ready) cb(entry.img);
    else entry.cbs.push(cb);
  }

  window.saxazCreateSmartCanvasLoop = function () {
    var activeCanvas = null;
    var activeBtn = null;
    var activeCue = null;
    var activeImg = null;
    var rafId = 0;
    var framePos = 0;
    var lastTs = 0;
    var boostUntil = 0;

    function tick(ts) {
      if (!activeCanvas || !activeCue || !activeImg || document.hidden) {
        rafId = 0;
        lastTs = 0;
        return;
      }
      if (!lastTs) lastTs = ts;
      var dt = Math.min(0.04, Math.max(0.004, (ts - lastTs) / 1000));
      lastTs = ts;

      var fps = (ts < boostUntil) ? 26.0 : 16.5;
      var total = activeCue.frames || 36;
      var cols = activeCue.cols || 6;
      var cw = activeCue.w || 360;
      var ch = activeCue.h || 270;

      framePos = (framePos + dt * fps) % total;
      var fIdx = Math.floor(framePos);
      var col = fIdx % cols;
      var row = Math.floor(fIdx / cols);
      var ctx = activeCanvas.getContext('2d');
      if (ctx) {
        ctx.clearRect(0, 0, cw, ch);
        ctx.drawImage(activeImg, col * cw, row * ch, cw, ch, 0, 0, cw, ch);
      }
      rafId = requestAnimationFrame(tick);
    }

    function setCue(canvasEl, btnEl, cue) {
      if (!canvasEl || !cue) return;
      activeCanvas = canvasEl;
      activeBtn = btnEl;
      activeCue = cue;
      activeImg = null;
      framePos = 0;
      lastTs = 0;
      var cw = cue.w || 360;
      var ch = cue.h || 270;
      if (canvasEl.width !== cw) canvasEl.width = cw;
      if (canvasEl.height !== ch) canvasEl.height = ch;
      if (btnEl) btnEl.classList.remove('is-sheet-ready');

      getSheet(cue.sheet, function (img) {
        if (activeCue !== cue) return;
        activeImg = img;
        if (btnEl) btnEl.classList.add('is-sheet-ready');
        if (!rafId) rafId = requestAnimationFrame(tick);
      });
    }

    function preloadSlideCues(sIdx) {
      var list = window.SAXAZ_SUMMARY_CUES[sIdx] || [];
      for (var i = 0; i < list.length; i++) {
        if (list[i].sheet) getSheet(list[i].sheet, function () {});
      }
    }

    function boost() {
      boostUntil = performance.now() + 950;
      if (activeCanvas && activeCue && activeImg && !rafId) {
        rafId = requestAnimationFrame(tick);
      }
    }

    function stop() {
      if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
      lastTs = 0;
    }

    return { setCue: setCue, preloadSlideCues: preloadSlideCues, boost: boost, stop: stop };
  };
})();
