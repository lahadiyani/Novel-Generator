from flask import Flask, request, jsonify, send_from_directory, render_template
import urllib.parse
import requests
import os
import re
import sqlite3
import tempfile
from docx import Document
from datetime import datetime

app = Flask(__name__, template_folder='template')

# Gunakan direktori sementara untuk penyimpanan
TEMP_DIR = tempfile.gettempdir()
MAX_PROMPT_LENGTH = 1500
DATABASE = os.path.join(TEMP_DIR, 'novels.db')

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            novel_title TEXT,
            chapter TEXT,
            chapter_title TEXT,
            chapter_order INTEGER,
            narrative_type TEXT,
            content TEXT,
            doc_filepath TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

db_initialized = False
@app.before_request
def initialize_db_once():
    global db_initialized
    if not db_initialized:
        init_db()
        db_initialized = True

def sanitize_title(title):
    return re.sub(r'\W+', '', title.replace(" ", "_"))

def get_chapter_order(chapter_input):
    chapter_lower = chapter_input.lower().strip()
    if chapter_lower == "prolog":
        return 0
    match = re.search(r'bab\s*(\d+)', chapter_lower)
    return int(match.group(1)) if match else None

def get_context_from_db(novel_title, new_order):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("""
        SELECT chapter, content FROM chapters 
        WHERE novel_title = ? AND chapter_order < ? 
        ORDER BY chapter_order ASC
    """, (novel_title, new_order))
    rows = c.fetchall()
    conn.close()
    return "\n".join(f"{chapter}: {content}" for chapter, content in rows)

def add_markdown_to_doc(doc, markdown_text):
    for line in markdown_text.splitlines():
        if not line.strip():
            continue
        p = doc.add_paragraph()
        p.add_run(line)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate_novel', methods=['POST'])
def generate_novel_endpoint():
    try:
        data = request.json

        chapter_input = data.get("chapter", "Prolog")
        novel_title = data.get("novel_title", "Novel Tanpa Judul")
        genre = data.get("genre", "Fantasy")
        world_setting = data.get("world_setting", "Dunia paralel penuh keajaiban")
        conflict = data.get("conflict", "Menyelamatkan dunia dari ancaman gelap")
        special_power = data.get("special_power", "Mengendalikan elemen")
        plot_twist = data.get("plot_twist", "Musuh utama ternyata saudara kembarnya")
        writing_style = data.get("writing_style", "Misterius dan dramatis")
        narrative_type = data.get("narrative_type", "linear")
        chapter_title = data.get("chapter_title", "")
        chapter_instructions = data.get("chapter_instructions", "Ceritakan bab ini dengan detail.")

        new_order = get_chapter_order(chapter_input)
        if new_order is None:
            return jsonify({"status": "error", "message": "Format chapter tidak valid."}), 400

        context_prompt = get_context_from_db(novel_title, new_order) if narrative_type.lower() == "linear" else ""

        chapter_prompt = f"""
        === {chapter_input.upper()} ===
        Tuliskan bab ini sebagai kelanjutan cerita yang naratif.
        Gunakan informasi berikut:
        Genre: {genre}
        Dunia: {world_setting}
        Tokoh Utama: memiliki kekuatan {special_power}
        Konflik: {conflict}
        Plot Twist: {plot_twist}
        Gaya: {writing_style}
        
        {chapter_instructions}
        """
        
        # Hapus template_info dari prompt
        full_prompt = chapter_prompt + "\n" + context_prompt

        if len(full_prompt) > MAX_PROMPT_LENGTH:
            required_prompt = chapter_prompt + "\n"
            allowed_context_length = MAX_PROMPT_LENGTH - len(required_prompt)
            trimmed_context = context_prompt[-allowed_context_length:] if allowed_context_length > 0 else ""
            full_prompt = required_prompt + trimmed_context

        encoded_prompt = urllib.parse.quote(full_prompt)
        pollinations_url = f"https://text.pollinations.ai/openai/{encoded_prompt}"
        response = requests.get(pollinations_url)
        
        if response.status_code == 200:
            generated_story = response.text

            doc = Document()
            doc.add_heading(chapter_title if chapter_title else chapter_input, level=1)
            add_markdown_to_doc(doc, generated_story)
            
            relative_folder = f"novel_{sanitize_title(novel_title)}"
            folder_name = os.path.join(TEMP_DIR, relative_folder)
            os.makedirs(folder_name, exist_ok=True)

            doc_filename = "prolog.doc" if chapter_input.lower() == "prolog" else f"bab{new_order}.doc"
            doc_filepath = os.path.join(folder_name, doc_filename)
            doc.save(doc_filepath)
            
            relative_doc_path = os.path.join(relative_folder, doc_filename)

            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            c.execute("""
                INSERT INTO chapters (novel_title, chapter, chapter_title, chapter_order, narrative_type, content, doc_filepath)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (novel_title, chapter_input, chapter_title, new_order, narrative_type, generated_story, relative_doc_path))
            conn.commit()
            conn.close()

            return jsonify({
                "status": "success",
                "novel_title": novel_title,
                "chapter": chapter_input,
                "order": new_order,
                "doc_filepath": relative_doc_path,
                "novel": generated_story
            })
        else:
            return jsonify({"status": "error", "message": "Gagal mengambil cerita dari AI"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/download/<path:filename>', methods=['GET'])
def download_file(filename):
    try:
        return send_from_directory(TEMP_DIR, filename, as_attachment=True)
    except Exception as e:
        return str(e), 404

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
