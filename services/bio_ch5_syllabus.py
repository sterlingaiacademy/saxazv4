"""
Strict verbatim Class 10 Biology — Chapter 5: Life Processes official client syllabus:
- Mock Test 1 (Total mark : 30, 15 Questions + Official Answers)
- Mock Test 2 (Total mark : 30, 13 Questions + Official Answers)
- Mock Test 3 (Total mark : 30, 16 Questions + Official Answers)
- Real Exam   (Time: 40 Mins, Max. Marks: 25, Sections A–D, 12 Questions + Official Answers & Diagram)
"""

import json

AR_DIRECTIONS_MOCK = (
    "For these questions two statements are given - one labelled as Assertion (A) and the other "
    "labelled as Reason (R). Select the correct answer to these questions from the codes (a), (b), (c) "
    "and (d) as given below."
)

AR_OPTIONS_MOCK = json.dumps([
    "(a) Both A and R are true and R is correct explanation of the assertion",
    "(b) Both A and R are true but R is not the correct explanation of the assertion.",
    "(c) A is true but R is false.",
    "(d) A is false but R is true.",
])

AR_DIRECTIONS_REAL = (
    "For these questions two statements are given - one labelled as Assertion (A) and the other "
    "labelled as Reason (R). Select the correct answer to these questions from the codes (a), (b), (c) "
    "and (d) as given below."
)

AR_OPTIONS_REAL = json.dumps([
    "a) Both A and R true, R is correct explanation of A.",
    "b) Both true, R is NOT correct explanation of A.",
    "c) A true, R false.",
    "d) A false, R true.",
])


# ==============================================================================
# 1. MOCK TEST 1 (exam_paper_id = 13, Total mark : 30)
#    Modules: 25 (1M), 26 (2M), 27 (3M), 28 (5M)
# ==============================================================================
MOCK_TEST_1_MODULES = [
    (25, 13, "1 Mark Questions", 1, 1, 60, "MCQ"),
    (26, 13, "2 Mark Questions", 2, 2, 90, "SHORT_ANSWER"),
    (27, 13, "3 Mark Questions", 3, 3, 150, "LONG_ANSWER"),
    (28, 13, "5 Mark Questions", 5, 4, 240, "LONG_ANSWER"),
]

# Tuple: (id, module_id, order_index, textbook_order, max_marks, q_type, question_text, options_json, model_answer, answer_media_url)
MOCK_TEST_1_QUESTIONS = [
    (
        1101, 25, 1, 1, 1, "MCQ",
        "Which of the following is the immediate product of photosynthesis?",
        json.dumps(["(a) Starch", "(b) Sucrose", "(c) Fructose", "(d) Glucose"]),
        "(d) Glucose\nLater glucose is converted into starch for storage.",
        "",
    ),
    (
        1102, 25, 2, 2, 1, "MCQ",
        "The muscle which regulates the exit of food from the stomach into the small intestine is called:",
        json.dumps(["(a) Cardiac muscle", "(b) Biceps muscle", "(c) Sphincter muscle", "(d) Triceps muscle"]),
        "(c) Sphincter muscle\nThis muscle found at the end of stomach.",
        "",
    ),
    (
        1103, 25, 3, 3, 1, "MCQ",
        "The process in which transport of soluble products of photosynthesis takes place in plants is known as:",
        json.dumps(["(a) Transpiration", "(b) Evaporation", "(c) Conduction", "(d) Translocation"]),
        "(d) Translocation\nThis is the process of transportation of food and others through phloem to all parts of the plant.",
        "",
    ),
    (
        1104, 25, 4, 4, 1, "MCQ",
        "Which among the following is the name of the procedure used in the working of artificial kidney?",
        json.dumps(["(a) Radiation", "(b) Dialysis", "(c) Physiotherapy", "(d) Laparoscopy"]),
        "(b) Dialysis\nWhen kidneys fail blood is purified using a machine.",
        "",
    ),
    (
        1105, 25, 5, 5, 1, "MCQ",
        "The bundle of capillaries present in the Bowman’s capsule is called:",
        json.dumps(["(a) Bronchioles", "(b) Villus", "(c) Bundle of His", "(d) Glomerulus"]),
        "(d) Glomerulus\nThe filtration of blood is starts here.",
        "",
    ),
    (
        1106, 25, 6, 6, 1, "ASSERTION_REASON",
        f"{AR_DIRECTIONS_MOCK}\n\n"
        "Assertion (A) : The inner lining of the small intestine has numerous finger-like projections called villi.\n"
        "Reason (R) : Villi increase the surface area for the efficient absorption of digested food.",
        AR_OPTIONS_MOCK,
        "(a) Both A and R are true, and R is the correct explanation of A.",
        "",
    ),
    (
        1107, 25, 7, 7, 1, "ASSERTION_REASON",
        f"{AR_DIRECTIONS_MOCK}\n\n"
        "Assertion (A) : Human heart has four chambers: two atria and two ventricles.\n"
        "Reason (R) : Four-chambered hearts prevent the mixing of oxygenated and deoxygenated blood, ensuring an efficient supply of oxygen.",
        AR_OPTIONS_MOCK,
        "(a) Both A and R are true, and R is the correct explanation of A.",
        "",
    ),
    (
        1108, 26, 8, 8, 2, "SHORT_ANSWER",
        "What is the reason for the accumulation of lactic acid in our muscles?",
        None,
        "When there is lack of oxygen in the muscle cells, the pyruvate is converted into lactic acid. The build up of lactic acid in the muscles during sudden activity causes cramps.",
        "",
    ),
    (
        1109, 26, 9, 9, 2, "SHORT_ANSWER",
        "The left side of the heart is completely separated from the right side by a partition called septum. Why?",
        None,
        "The separation of the left and right sides of the heart is necessary to prevent the mixing of the oxygenated blood in the left ventricle with the deoxygenated blood in the right ventricle. Such a mixing will lower the O2 concentration in blood.",
        "",
    ),
    (
        1110, 26, 10, 10, 2, "SHORT_ANSWER",
        "All veins carry deoxygenated blood. Do you agree? Why?",
        None,
        "All the veins do not carry deoxygenated blood. The pulmonary veins carry oxygenated blood from the lungs to the heart. All the other veins carry deoxygenated blood.",
        "",
    ),
    (
        1111, 27, 11, 11, 3, "LONG_ANSWER",
        "A man eats food standing upside down. Still the food goes up and reaches his stomach. What is the reason?",
        None,
        "Food moves as a result of the contraction of the involuntary muscles in the oesophagus. This wave-like movement is called peristalsis.\n"
        "As this movement takes place throughout the alimentary canal in only one direction, the food goes up into the stomach.",
        "",
    ),
    (
        1112, 27, 12, 12, 3, "LONG_ANSWER",
        "Describe the role of bile in digestion.",
        None,
        "(i) The acidic food coming from stomach is made alkaline for pancreatic enzymes to act.\n"
        "(ii) The fats present in the intestine in the form of large globules are broken down into smaller globules to increase the efficiency of enzymes action.",
        "",
    ),
    (
        1113, 27, 13, 13, 3, "LONG_ANSWER",
        "What is transpiration? State two functions of it. Can you find an analogous system in humans?",
        None,
        "The loss of water in the form of water vapour from the aerial parts of the plant is known as transpiration.\n"
        "Functions: It helps in the absorption and upward movement of water and minerals dissolved in it from roots to the leaves. It also helps in temperature regulation.\n"
        "Human beings consume water. It helps in mediating many physiological activities in the body. Human beings perspire (sweat) during hard work. The water that is drunk by human beings helps in the intake of salts and minerals necessary for the body.",
        "",
    ),
    (
        1114, 27, 14, 14, 3, "LONG_ANSWER",
        "Explain the process of breakdown of glucose by various pathways.",
        None,
        "Cytoplasm: Glucose (6-carbon) is broken into Pyruvate (3-carbon).\n"
        "In Mitochondria (Aerobic): Pyruvate breaks into H2O, and a large amount of Energy (ATP).\n"
        "In Muscle Cells (Anaerobic): During heavy exercise, Pyruvate converts to Lactic Acid + Energy (causing cramps).\n"
        "In Yeast (Fermentation): Pyruvate converts to Ethanol + CO2 + Energy.",
        "",
    ),
    (
        1115, 28, 15, 15, 5, "LONG_ANSWER",
        "While presenting a seminar paper Raju stated that plants and animals exhibit 2 processes that support life on earth, though their body structure and organisation are different. So we must protect them and conserve them in order to sustain life on earth.\n"
        "(a) Do you agree with this statement?\n"
        "(b) Can you guess which are the 2 important processes that Raju mentioned?\n"
        "(c) What is the ultimate source of energy for all organisms?\n"
        "(d) How does energy flow between living organisms?\n"
        "(e) How is CO2 and oxygen ratio of atmosphere maintained?",
        None,
        "(a) Yes. I do agree with this statement.\n"
        "(b) Photosynthesis and respiration are the two processes that Raju mentioned.\n"
        "(c) Sun is the ultimate source of energy for all organisms.\n"
        "(d) Solar energy is trapped by green plants during photosynthesis. The food thus synthesised is used by plants and animals as energy source. Food on oxidation releases energy which is stored in ATP molecules to meet the energy demand of all cells. The flow of energy occurs between living organisms by eating and subsequent oxidation of food by heterotrophs through the process of respiration.\n"
        "Equation for respiration:\n"
        "C2H12O6 + 6O2 + 6CO2 + 6H2O + 673 Kcal.\n"
        "(e) During respiration of animals and plants CO2 is released into the atmosphere. Burning of fuels and other materials also release CO2 in the atmosphere. But the percentage of atmospheric CO2 remains constant because plants take up CO2 during photosynthesis and release O2. This keeps the CO2/O2 ratio of atmosphere constant.",
        "",
    ),
]


# ==============================================================================
# 2. MOCK TEST 2 (exam_paper_id = 45, Total mark : 30)
#    Modules: 91 (1M), 92 (2M), 93 (3M), 94 (5M)
# ==============================================================================
MOCK_TEST_2_MODULES = [
    (91, 45, "1 Mark Questions", 1, 1, 60, "MCQ"),
    (92, 45, "2 Mark Questions", 2, 2, 90, "SHORT_ANSWER"),
    (93, 45, "3 Mark Questions", 3, 3, 150, "LONG_ANSWER"),
    (94, 45, "5 Mark Questions", 5, 4, 240, "LONG_ANSWER"),
]

MOCK_TEST_2_QUESTIONS = [
    (
        1201, 91, 1, 1, 1, "MCQ",
        "Name the physiological processes in which stomata play a vital role in plant.",
        json.dumps(["(a) Transpiration and Photosynthesis", "(b) Guttation", "(c) Photosynthesis only", "(d) None of these"]),
        "(a) Transpiration and Photosynthesis\nBoth of them are the vital roles of stomata",
        "",
    ),
    (
        1202, 91, 2, 2, 1, "MCQ",
        "Which vessels carry blood away from the heart to the various organs of the body?",
        json.dumps(["(a) Veins", "(b) Arteries", "(c) Both arteries and veins", "(d) Capillaries"]),
        "(b) Arteries\nArteries carry oxygenated blood only",
        "",
    ),
    (
        1203, 91, 3, 3, 1, "ASSERTION_REASON",
        f"{AR_DIRECTIONS_MOCK}\n\n"
        "Assertion (A) : Pyruvate is a six-carbon molecule.\n"
        "Reason (R) : It is prepared in the cytoplasm as the first step of cellular respiration.",
        AR_OPTIONS_MOCK,
        "(d) A is false but R is true.\nGlucose is a 6-carbon molecule; Pyruvate is a 3-carbon molecule.",
        "",
    ),
    (
        1204, 91, 4, 4, 1, "ASSERTION_REASON",
        f"{AR_DIRECTIONS_MOCK}\n\n"
        "Assertion (A) : The rate of breathing in aquatic organisms is much faster than in terrestrial organisms.\n"
        "Reason (R) : The amount of dissolved oxygen in water is fairly low compared to the amount of oxygen in the air.",
        AR_OPTIONS_MOCK,
        "(a) Both A and R are true and R is correct explanation of the assertion.\nLow oxygen concentration in water forces aquatic animals to breathe faster to meet metabolic needs.",
        "",
    ),
    (
        1205, 92, 5, 5, 2, "SHORT_ANSWER",
        "What is respiration at molecular level in an organism?",
        None,
        "First in the cytoplasm, and then in the mitochondria of the cell, the glucose molecule is completely broken down into carbon dioxide and water, using oxygen to liberate energy.",
        "",
    ),
    (
        1206, 92, 6, 6, 2, "SHORT_ANSWER",
        "Name any four organs that can be donated only after the death of the donor or the person is declared brain dead.",
        None,
        "Heart, Cornea, Pancreas, liver.",
        "",
    ),
    (
        1207, 92, 7, 7, 2, "SHORT_ANSWER",
        "What is artificial kidney?",
        None,
        "Artificial kidney is a device used to remove the nitrogenous waste products like urea and uric acid from the blood of a patient whose kidneys are not working. This process is called dialysis.",
        "",
    ),
    (
        1208, 92, 8, 8, 2, "SHORT_ANSWER",
        "State the reason why plants have low energy needs compared to animals.",
        None,
        "Plants do not move and plant bodies have large proportion of dead cells in many tissues.",
        "",
    ),
    (
        1209, 93, 9, 9, 3, "LONG_ANSWER",
        "What is meant by dental caries? How are they caused? What harm can they do?",
        None,
        "- The formation of small cavities (holes) in the teeth due to the action of acid-forming bacteria and improper dental care is called dental caries.\n"
        "This happens as follows:\n"
        "- The bacteria present in our mouth act on the sugars in the food which we eat to produce acids.\n"
        "- These acids first dissolve calcium salts from the tooth enamel and then from dentine forming small cavities or holes in the tooth over a period of time.\n"
        "- If the cavities caused by dental decay are not cleaned and filled by a dentist, the bacteria will reach the pulp cavity of the tooth causing inflammation and infection leading to severe pain.",
        "",
    ),
    (
        1210, 93, 10, 10, 3, "LONG_ANSWER",
        "During a group discussion in our class my friend Lakshmi said that her neighbour carries a kind of tape recorder on his shoulder. He says he is making a Holter tape. But Lakshmi had a doubt “Is this a form of stress ECG?” It was our teacher who gave her answer. What may be the answer?",
        None,
        "A Holter monitor is a lightweight portable piece of ECG equipment which can be carried by means of a shoulder strap, while going about with the normal day’s activities. The usual electrodes are pasted to the body, and the ECG is recorded on magnetic tape by a device similar to a tape recorder. The test usually lasts 24 hours and the tape is then analysed by a technician and a doctor to assess rhythm disturbances and to correlate them with any symptoms reported by the patient.",
        "",
    ),
    (
        1211, 93, 11, 11, 3, "LONG_ANSWER",
        "Describe the need for the development of the circulatory system and its components in animals.",
        None,
        "All cells in an animal are not in contact with outer environment for exchange of materials like that is unicellular organism. Hence a transport system has evolved, carrying nutrients to each cell and remaining waste from it. Blood is the medium of transport of materials in animal body. There is the need of a pumping organ (heart) to push blood around the body. There is the need of a network of tubes to reach blood to all tissues (arteries, veins and capillary) and a system is place to ensure that this network can be repaired if damaged.",
        "",
    ),
    (
        1212, 93, 12, 12, 3, "LONG_ANSWER",
        "Explain the working of artificial kidney (dialysing unit).",
        None,
        "Artificial kidney contain a number of tubes with a semi-permeable lining, suspended in a tank filled with dialysing fluid. This fluid has the same osmotic pressure as blood. The patient’s blood is passed through these tubes. During this passage, the waste products from the blood passes into dialysing fluid by diffusion. The purified blood is pumped back into the patient. This is similar to the functioning of the kidney.",
        "",
    ),
    (
        1213, 94, 13, 13, 5, "LONG_ANSWER",
        "(a) Enumerate the events that actually happen during the process of photosynthesis.\n"
        "(b) Name any two parasitic plants and two parasitic animals.",
        None,
        "(a) The following events occur during this process:\n"
        "(i) Absorption of light energy by chlorophyll.\n"
        "(ii) Conversion of light energy to chemical energy and splitting of water molecules into hydrogen and oxygen.\n"
        "(iii) Reduction of carbon dioxide to carbohydrates.\n"
        "(b) Parasitic plants: Cuscuta and orchids.\n"
        "Parasitic animals: Ticks, lice, leeches and tapeworms.",
        "",
    ),
]


# ==============================================================================
# 3. MOCK TEST 3 (exam_paper_id = 46, Total mark : 30)
#    Modules: 95 (1M), 96 (2M), 97 (3M), 98 (5M)
# ==============================================================================
MOCK_TEST_3_MODULES = [
    (95, 46, "1 Mark Questions", 1, 1, 60, "MCQ"),
    (96, 46, "2 Mark Questions", 2, 2, 90, "SHORT_ANSWER"),
    (97, 46, "3 Mark Questions", 3, 3, 150, "LONG_ANSWER"),
    (98, 46, "5 Mark Questions", 5, 4, 240, "LONG_ANSWER"),
]

MOCK_TEST_3_QUESTIONS = [
    (
        1301, 95, 1, 1, 1, "MCQ",
        "Identify the correct statements regarding nutrition in Amoeba:\n"
        "I. Amoeba takes in food using temporary finger-like extensions called pseudopodia.\n"
        "II. Digestion of food takes place inside the food vacuole.\n"
        "III. Undigested food is expelled through a specific fixed point on the body.",
        json.dumps(["(a) I and II", "(b) II and III", "(c) I and III", "(d) I, II, and III"]),
        "(a) I and II\nStatement III is false for Amoeba. It does not have a fixed point for excretion; the cell membrane simply ruptures to discard waste. (Paramecium has a fixed spot).",
        "",
    ),
    (
        1302, 95, 2, 2, 1, "MCQ",
        "Consider the following statements regarding the human respiratory system:\n"
        "1. The tracheal rings are made of hyaline cartilage to prevent collapse during low air pressure.\n"
        "2. The diffusion of gases at the alveolar surface is governed by a concentration gradient.\n"
        "3. Inhalation is a passive process, while exhalation is an active process involving ATP.\n"
        "4. Haemoglobin has a higher affinity for CO2 than for O2.\n"
        "Which of the above statements are INCORRECT?",
        json.dumps(["(a) 1 and 2", "(b) 3 and 4", "(c) 2 and 3", "(d) 1 and 4"]),
        "(b) 3 and 4\nBreathing is active; haemoglobin likes O2 more than CO2.",
        "",
    ),
    (
        1303, 95, 3, 3, 1, "MCQ",
        "If a plant is kept in a bell jar with a substance ‘X’ that absorbs CO2, what will be the observed result in a starch test after 24 hours of sunlight?",
        json.dumps([
            "(a) Leaf turns blue-black (Starch present)",
            "(b) Leaf remains colorless/brown",
            "(c) Only the edges turn blue-black",
            "(d) The leaf turns yellow due to excess oxygen",
        ]),
        "(b) Leaf remains colorless/brown\nColourless because absence of starch",
        "",
    ),
    (
        1304, 95, 4, 4, 1, "MCQ",
        "If the xylem of a plant is mechanically blocked, which of the following processes will be affected first?",
        json.dumps([
            "(a) Translocation of sucrose from leaves to roots.",
            "(b) Absorption of light energy by chlorophyll.",
            "(c) Photolysis of water in the light reaction.",
            "(d) Opening and closing of stomata.",
        ]),
        "(c) Photolysis of water in the light reaction.\nXylem carries water from roots to leaves.",
        "",
    ),
    (
        1305, 95, 5, 5, 1, "MCQ",
        "Which part of the nephron is responsible for the maximum reabsorption of water, glucose, and amino acids?",
        json.dumps([
            "(a) Bowman’s Capsule",
            "(b) Loop of Henle",
            "(c) Distal Convoluted Tubule (DCT)",
            "(d) Proximal Convoluted Tubule (PCT)",
        ]),
        "(d) Proximal Convoluted Tubule (PCT)\nPCT is the first tubule after Bowman’s capsule. Here reabsorption starts.",
        "",
    ),
    (
        1306, 95, 6, 6, 1, "ASSERTION_REASON",
        f"{AR_DIRECTIONS_MOCK}\n\n"
        "Assertion (A) : Bile juice contains no digestive enzymes yet it is important for digestion.\n"
        "Reason (R) : Bile juice emulsifies fats and provides an alkaline medium for pancreatic enzymes to act.",
        AR_OPTIONS_MOCK,
        "(a) Both A and R are true and R is correct explanation of the assertion\nBile breaks large fat globules into smaller ones (emulsification), aiding lipase activity.",
        "",
    ),
    (
        1307, 95, 7, 7, 1, "ASSERTION_REASON",
        f"{AR_DIRECTIONS_MOCK}\n\n"
        "Assertion (A) : Transpiration helps in the absorption and upward movement of water and minerals.\n"
        "Reason (R) : The evaporation of water molecules from the cells of a leaf creates a suction pull.",
        AR_OPTIONS_MOCK,
        "(a) Both A and R are true and R is correct explanation of the assertion\nThis is known as the “transpiration pull,” which is the primary force for water transport in tall trees.",
        "",
    ),
    (
        1308, 95, 8, 8, 1, "ASSERTION_REASON",
        f"{AR_DIRECTIONS_MOCK}\n\n"
        "Assertion (A) : The walls of the ventricles are thicker than those of the atria.\n"
        "Reason (R) : Ventricles have to pump blood into various organs with high pressure.",
        AR_OPTIONS_MOCK,
        "(a) Both Assertion (A) and Reason (R) are true, and Reason (R) is the correct explanation of Assertion (A).",
        "",
    ),
    (
        1309, 96, 9, 9, 2, "SHORT_ANSWER",
        "What is peristalsis?",
        None,
        "Rhythmic contraction along the wall of the alimentary canal brought about by the muscle on the alimentary canal that helps the food in one place to move forward is called peristalsis.",
        "",
    ),
    (
        1310, 96, 10, 10, 2, "SHORT_ANSWER",
        "Comment on the role of mucus produced in the alimentary canal.",
        None,
        "Protects the inner lining of the stomach from the action of the acid produced in the stomach.",
        "",
    ),
    (
        1311, 96, 11, 11, 2, "SHORT_ANSWER",
        "Why is urine yellow in colour?",
        None,
        "Urine is yellow in colour due to the presence of the pigment urochrome.",
        "",
    ),
    (
        1312, 96, 12, 12, 2, "SHORT_ANSWER",
        "The two openings of the pharynx, one leading to trachea and the other leading to oesophagus, lie very close to each other. Yet food we swallow normally does not enter into our trachea. Why?",
        None,
        "The food does not enter into trachea because during swallowing, the aperture leading to trachea (glottis) gets covered by a cartilaginous flap called epiglottis and the food has no other passage except going into the oesophagus.",
        "",
    ),
    (
        1313, 97, 13, 13, 3, "LONG_ANSWER",
        "Describe the role of bile in digestion.",
        None,
        "(i) The acidic food coming from stomach is made alkaline for pancreatic enzymes to act.\n"
        "(ii) The fats present in the intestine in the form of large globules are broken down into smaller globules to increase the efficiency of enzymes action.",
        "",
    ),
    (
        1314, 97, 14, 14, 3, "LONG_ANSWER",
        "State the number of chambers in the following group of animals.\nFish, Bird, Amphibians, Mammal, Reptile.",
        None,
        "Name — Chambers:\nFish: 2\nBird: 4\nAmphibian: 3\nMammal: 4\nReptile: 3",
        "",
    ),
    (
        1315, 97, 15, 15, 3, "LONG_ANSWER",
        "(a) Which of the four chambers of the human heart has the thickest muscular walls?\n"
        "(b) Veins and arteries carry blood.\n"
        "(i) Which of these carry blood away from the heart?\n"
        "(ii) Which carry blood back to the heart?",
        None,
        "(a) Left ventricle.\n"
        "(b) (i) Arteries carry blood away from the heart.\n"
        "(ii) Veins carry blood back to the heart.",
        "",
    ),
    (
        1316, 98, 16, 16, 5, "LONG_ANSWER",
        "(i) During vigorous exercise, the pH of the blood in the muscle capillaries decreases. This is primarily due to:\n"
        "(a) Increased concentration of bicarbonate ions.\n"
        "(b) Accumulation of Lactic acid and dissolved CO2.\n"
        "(c) Excessive intake of oxygen by the cells.\n"
        "(d) Rapid breakdown of ATP into ADP.\n\n"
        "(ii) Leaves of a healthy potted plant were coated with vaseline to block the stomata. Will this plant remain healthy for long? State three reasons for your answer.\n\n"
        "(iii) State any two differences between autotrophic nutrition and heterotrophic nutrition.",
        None,
        "(i) (b) Accumulation of Lactic acid and dissolved CO2.\n"
        "Explanation: Intense muscle activity leads to anaerobic respiration, producing lactic acid. Additionally, increased aerobic metabolism produces CO2, which reacts with water to form carbonic acid, thereby lowering the pH.\n"
        "(ii) Plant will not remain healthy for long because:\n"
        "1. No gaseous exchange.\n"
        "2. Transpiration will not take place.\n"
        "3. Photosynthesis will reduce or will not take place.\n"
        "(iii) Autotrophic nutrition:\n"
        "- In this nutrition, organisms manufacture their own food from inorganic materials i.e., by photosynthesis.\n"
        "- Autotrophs are either: (i) Photoautotrophic – e.g. Green plants (ii) Chemoautotrophic – e.g. Some bacteria\n"
        "Heterotrophic nutrition:\n"
        "- The organisms depend directly or indirectly on other organisms for food.\n"
        "- Heterotrophs are consumers. i.e., they depend on autotrophs for food. e.g. All animals, Fungi etc.",
        "",
    ),
]


# ==============================================================================
# 4. REAL EXAM (exam_paper_id = 14, Time: 40 Mins, Max. Marks: 25)
#    Modules: 101 (Section A, 1M), 102 (Section B, 2M), 103 (Section C, 3M), 104 (Section D, 5M)
# ==============================================================================
REAL_EXAM_MODULES = [
    (101, 14, "SECTION A (1 × 6 = 6)", 1, 1, 60, "MCQ"),
    (102, 14, "SECTION B (2 × 3 = 6)", 2, 2, 120, "SHORT_ANSWER"),
    (103, 14, "SECTION C (3 × 1 = 3)", 3, 3, 240, "LONG_ANSWER"),
    (104, 14, "SECTION D (5 × 2 = 10)", 5, 4, 360, "LONG_ANSWER"),
]

REAL_EXAM_QUESTIONS = [
    (
        1401, 101, 1, 1, 1, "MCQ",
        "The main function of Xylem is:",
        json.dumps([
            "a) Transport of food",
            "b) Transport of water and minerals",
            "c) Transport of blood",
            "d) Transport of oxygen",
        ]),
        "b) Transport of water and minerals",
        "",
    ),
    (
        1402, 101, 2, 2, 1, "MCQ",
        "The structural and functional unit of kidney is:",
        json.dumps([
            "a) Neuron",
            "b) Nephron",
            "c) Alveoli",
            "d) Glomerulus only",
        ]),
        "b) Nephron",
        "",
    ),
    (
        1403, 101, 3, 3, 1, "MCQ",
        "The reason for presence of valves in it is:",
        json.dumps([
            "a) High pressure",
            "b) To prevent backflow of blood",
            "c) To carry oxygenated blood",
            "d) To make blood clot",
        ]),
        "b) To prevent backflow of blood",
        "",
    ),
    (
        1404, 101, 4, 4, 1, "MCQ",
        "Which of the following is correct for Translocation?",
        json.dumps([
            "a) It occurs in Xylem",
            "b) It requires ATP",
            "c) It is only upward movement",
            "d) It occurs in dead cells",
        ]),
        "b) It requires ATP",
        "",
    ),
    (
        1405, 101, 5, 5, 1, "ASSERTION_REASON",
        f"{AR_DIRECTIONS_REAL}\n\n"
        "Assertion (A): Arteries have thick and elastic walls.\n"
        "Reason (R): Arteries carry blood away from heart under high pressure.",
        AR_OPTIONS_REAL,
        "a) Both A and R are true, R is the correct explanation of A.\n"
        "Explanation: Arteries have thick walls because they carry blood from the heart under high pressure.",
        "",
    ),
    (
        1406, 101, 6, 6, 1, "ASSERTION_REASON",
        f"{AR_DIRECTIONS_REAL}\n\n"
        "Assertion (A): Plants do not have kidneys.\n"
        "Reason (R): Plants store waste in leaves and remove it when leaves fall.",
        AR_OPTIONS_REAL,
        "a) Both A and R are true, R is the correct explanation of A.\n"
        "Explanation: Plants store waste in leaves and remove it when the leaves fall. Therefore, they do not need kidneys.",
        "",
    ),
    (
        1407, 102, 7, 7, 2, "SHORT_ANSWER",
        "Define:\n(a) Transpiration\n(b) Translocation",
        None,
        "a) Transpiration: Loss of water as water vapour from leaves through stomata.\n"
        "b) Translocation: Transport of food through phloem from leaves to other parts of the plant.",
        "",
    ),
    (
        1408, 102, 8, 8, 2, "SHORT_ANSWER",
        "Why is the wall of capillary only one-cell thick? Give two reasons.",
        None,
        "1. To make the exchange of oxygen, food, carbon dioxide and waste easy.\n"
        "2. To allow faster diffusion of substances.",
        "",
    ),
    (
        1409, 102, 9, 9, 2, "SHORT_ANSWER",
        "What is Dialysis? Name the condition when it is needed.",
        None,
        "Dialysis: Cleaning blood using a machine when the kidneys fail.\n"
        "Needed when: Kidney failure or when kidneys are not working properly.",
        "",
    ),
    (
        1410, 103, 10, 10, 3, "LONG_ANSWER",
        "Draw a neat labelled diagram of Human Excretory System and label Kidney, Ureter, Urinary Bladder.",
        None,
        "Neat labelled diagram of Human Excretory System showing Kidney, Ureter, Urinary Bladder (and Urethra).",
        "/static/images/saxaz_web/syllabus/real_exam_q10_ans_0.webp",
    ),
    (
        1411, 104, 11, 11, 5, "LONG_ANSWER",
        "Read the case and answer:\n"
        "Rahul got injured while playing football. Blood started flowing from his wound. After some time, bleeding stopped automatically. Doctor said Platelets helped him. Later, doctor checked his urine report and said his kidneys filter 180 L blood daily but only 1-1.5 L urine is formed.\n"
        "a. What is the role of Platelets in Rahul’s case?\n"
        "b. Why does bleeding stop after some time?\n"
        "c. What are the three steps in Nephron that lead to urine formation?\n"
        "d. Why is only 1-1.5 L urine formed from 180 L filtrate?\n"
        "OR\n"
        "e. Name the part in Nephron where filtration takes place?",
        None,
        "a. Platelets help in blood clotting and stop blood loss from the wound.\n"
        "b. Platelets form a clot at the wound, which stops bleeding.\n"
        "c. 1. Filtration\n2. Reabsorption\n3. Urine Formation\n"
        "d. Glucose, amino acids, water and salts are reabsorbed back into the blood. Only the remaining waste forms urine.\n"
        "OR\n"
        "e. Glomerulus (inside Bowman's Capsule).",
        "",
    ),
    (
        1412, 104, 12, 12, 5, "LONG_ANSWER",
        "(A) How does Excretion happen in Plants? Write in 5 points how plants remove waste without kidney.\n"
        "OR\n"
        "(B) Write the 4 parts of Human Excretory System and their functions.",
        None,
        "(A) Excretion in Plants:\n"
        "1. Oxygen goes out through stomata.\n"
        "2. Carbon dioxide is reused.\n"
        "3. Water goes out through transpiration.\n"
        "4. Waste is stored in dead cells and leaves.\n"
        "5. Leaves fall off, removing the stored waste.\n"
        "OR\n"
        "(B). Human Excretory System:\n"
        "1. Kidney – Filters blood.\n"
        "2. Ureter – Carries urine from kidney to bladder.\n"
        "3. Bladder – Stores urine.\n"
        "4. Urethra – Removes urine from the body.",
        "",
    ),
]
