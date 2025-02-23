from flask import Flask, request, jsonify, send_from_directory, render_template
import urllib.parse
import requests
import os
import re
import sqlite3
import tempfile  # Untuk menyimpan file di sistem read-only
from docx import Document
from datetime import datetime

app = Flask(__name__, template_folder='template')

# Folder penyimpanan sementara di Vercel
TEMP_DIR = tempfile.gettempdir()

# Batas maksimum panjang prompt (dalam karakter)
MAX_PROMPT_LENGTH = 1500
DATABASE = os.path.join(TEMP_DIR, 'novels.db')  # Simpan SQLite di /tmp/

# Inisialisasi database
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

# Hapus data lebih dari 7 hari
def delete_old_chapters():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, doc_filepath FROM chapters WHERE created_at < datetime('now', '-7 days')")
    rows = c.fetchall()
    for row in rows:
        _, doc_filepath = row
        if doc_filepath and os.path.exists(doc_filepath):
            try:
                os.remove(doc_filepath)
            except Exception as e:
                print("Gagal menghapus file:", doc_filepath, e)
    c.execute("DELETE FROM chapters WHERE created_at < datetime('now', '-7 days')")
    conn.commit()
    conn.close()

def sanitize_title(title):
    return re.sub(r'\W+', '', title.replace(" ", "_"))

def get_chapter_order(chapter_input):
    chapter_lower = chapter_input.lower().strip()
    if chapter_lower == "prolog":
        return 0
    else:
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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate_novel', methods=['POST'])
def generate_novel_endpoint():
    try:
        delete_old_chapters()

        data = request.json
        chapter_input   = data.get("chapter", "Prolog")
        character_name  = data.get("character_name", "Alex")
        genre           = data.get("genre", "Fantasy")
        world_setting   = data.get("world_setting", "Dunia paralel penuh keajaiban")
        conflict        = data.get("conflict", "Menyelamatkan dunia dari ancaman gelap")
        special_power   = data.get("special_power", "Mengendalikan elemen")
        plot_twist      = data.get("plot_twist", "Musuh utama ternyata saudara kembarnya")
        writing_style   = data.get("writing_style", "Misterius dan dramatis")
        narrative_type  = data.get("narrative_type", "linear")
        novel_title     = data.get("novel_title", "Novel Tanpa Judul")
        chapter_title   = data.get("chapter_title", "")

        new_order = get_chapter_order(chapter_input)
        if new_order is None:
            return jsonify({"status": "error", "message": "Format chapter tidak valid. Gunakan 'Prolog' atau 'Bab <nomor>'."}), 400

        context_prompt = get_context_from_db(novel_title, new_order) if narrative_type.lower() == "linear" else ""

        chapter_prompt = f"""
        === {chapter_input.upper()} ===
        Genre: {genre}
        Dunia: {world_setting}
        Tokoh Utama: {character_name} dengan kekuatan {special_power}
        Konflik: {conflict}
        Plot Twist: {plot_twist}
        Gaya: {writing_style}
        """

        full_prompt = chapter_prompt + "\n" + context_prompt
        if len(full_prompt) > MAX_PROMPT_LENGTH:
            full_prompt = full_prompt[:MAX_PROMPT_LENGTH]

        encoded_prompt = urllib.parse.quote(full_prompt)
        response = requests.get(f"https://text.pollinations.ai/openai/{encoded_prompt}")
        
        if response.status_code == 200:
            generated_story = response.text

            # Simpan file ke /tmp/
            doc = Document()
            doc.add_heading(chapter_title if chapter_title else chapter_input, level=1)
            doc.add_paragraph(generated_story)

            doc_filename = f"bab{new_order}.doc" if new_order else "prolog.doc"
            doc_filepath = os.path.join(TEMP_DIR, doc_filename)
            doc.save(doc_filepath)

            # Simpan ke database
            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            c.execute("""
                INSERT INTO chapters (novel_title, chapter, chapter_title, chapter_order, narrative_type, content, doc_filepath)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (novel_title, chapter_input, chapter_title, new_order, narrative_type, generated_story, doc_filepath))
            conn.commit()
            conn.close()

            return jsonify({
                "status": "success",
                "novel_title": novel_title,
                "chapter": chapter_input,
                "order": new_order,
                "doc_filepath": doc_filepath,
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
