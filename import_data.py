import sqlite3
import json
import re
import glob

def parse_txt(filename):
    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()
    
    pattern = re.compile(r'(?:^|\n)\s*(\d+\.\d+)\.?\s*(.*?)(?=\n\s*\d+\.\d+\.?\s*|\Z)', re.DOTALL)
    matches = pattern.findall(text)
    
    questions = []
    for m in matches:
        q_num_str = m[0]
        content = m[1].strip()
        
        parts = q_num_str.split('.')
        mark_val = int(parts[0])
        q_idx = int(parts[1])
        
        ans_match = re.search(r'\n(Ans:|Answer\s*:)\s*(.*)', content, re.DOTALL | re.IGNORECASE)
        if ans_match:
            q_text = content[:ans_match.start()].strip()
            a_text = ans_match.group(2).strip()
        else:
            q_text = content
            a_text = ""
            
        questions.append({
            'mark': mark_val,
            'idx': q_idx,
            'question': q_text,
            'answer': a_text
        })
    return questions

def run():
    # 1. Parse Questions
    chap5_qs = []
    for f in glob.glob('*_mark.txt'):
        chap5_qs.extend(parse_txt(f))
        
    chap6_qs = parse_txt('c6_full.txt')
    
    # 2. Parse YouTube Links
    yt_map = {}
    with open('playlist.json', 'r', encoding='utf-16') as f:
        data = json.load(f)
        for entry in data.get('entries', []):
            title = entry.get('title', '')
            url = entry.get('url', '')
            # Extract Chapter, Mark, Idx
            # "Biology Chapter 5.1.1"
            m = re.search(r'Chapter\s*(\d+)\.(\d+)\.(\d+)', title, re.IGNORECASE)
            if m:
                c, mk, idx = map(int, m.groups())
                yt_map[(c, mk, idx)] = url
                
    # 3. Database Insertion
    conn = sqlite3.connect('edusafari.db')
    cursor = conn.cursor()
    
    subject_id = 5 # Biology
    
    for chap_num, chap_name, qs in [(5, "Chapter 5: Life Processes", chap5_qs), (6, "Chapter 6: Control and Coordination", chap6_qs)]:
        # Create Chapter
        cursor.execute("INSERT INTO chapters (subject_id, name) VALUES (?, ?)", (subject_id, chap_name))
        chap_id = cursor.lastrowid
        
        # Create Exam Paper
        cursor.execute("INSERT INTO exam_papers (chapter_id, type, title, status) VALUES (?, 'mock', ?, 'published')", (chap_id, f"{chap_name} Question Bank"))
        exam_id = cursor.lastrowid
        
        # Group questions by mark
        by_mark = {}
        for q in qs:
            by_mark.setdefault(q['mark'], []).append(q)
            
        for mark_val in sorted(by_mark.keys()):
            # Create Module
            cursor.execute("INSERT INTO modules (exam_paper_id, name, mark_value) VALUES (?, ?, ?)", (exam_id, f"{mark_val} Mark Questions", mark_val))
            mod_id = cursor.lastrowid
            
            for i, q in enumerate(by_mark[mark_val]):
                yt_url = yt_map.get((chap_num, mark_val, q['idx']), None)
                media_type = 'video' if yt_url else None
                media_url = yt_url if yt_url else None
                
                cursor.execute("""
                    INSERT INTO questions (module_id, question_text, model_answer, max_marks, media_url, order_index)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (mod_id, q['question'], q['answer'], mark_val, media_url, i+1))
                
    conn.commit()
    conn.close()
    print("Database updated successfully!")

if __name__ == '__main__':
    run()
