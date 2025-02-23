from flask import Flask, request, jsonify, send_from_directory, render_template
import urllib.parse
import requests
import os
import json
import re
from docx import Document

app = Flask(__name__, template_folder='template')

# Batas maksimum panjang prompt (dalam karakter)
MAX_PROMPT_LENGTH = 1500

def sanitize_title(title):
    return re.sub(r'\W+', '', title.replace(" ", "_"))

def get_chapter_order(chapter_input):
    chapter_lower = chapter_input.lower().strip()
    if chapter_lower == "prolog":
        return 0
    else:
        match = re.search(r'bab\s*(\d+)', chapter_lower)
        if match:
            return int(match.group(1))
        else:
            return None

def get_context(folder, new_order):
    context = ""
    files = [f for f in os.listdir(folder) if f.endswith(".json")]
    chapters = []
    for f in files:
        if f.lower() == "prolog.json":
            order = 0
        else:
            match = re.search(r'bab(\d+)\.json', f.lower())
            order = int(match.group(1)) if match else None
        if order is not None and order < new_order:
            filepath = os.path.join(folder, f)
            with open(filepath, 'r', encoding='utf-8') as infile:
                data = json.load(infile)
                chapters.append((order, f"{data.get('chapter', '')}: {data.get('content', '')}"))
    chapters = sorted(chapters, key=lambda x: x[0])
    for order, text in chapters:
        context += f"Bab {order} content: {text}\n"
    return context

# Fungsi helper untuk menambahkan teks ke paragraf dengan mendeteksi format bold (teks antara **)
def add_markdown_line_to_paragraph(paragraph, text):
    parts = re.split(r'(\*\*.*?\*\*)', text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        else:
            paragraph.add_run(part)

def add_markdown_to_doc(doc, markdown_text):
    lines = markdown_text.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            text = line.lstrip("#").strip()
            level = level if level <= 4 else 4
            p = doc.add_heading("", level=level)
            add_markdown_line_to_paragraph(p, text)
        elif line.startswith("- "):
            p = doc.add_paragraph(style='List Bullet')
            add_markdown_line_to_paragraph(p, line[2:])
        else:
            p = doc.add_paragraph()
            add_markdown_line_to_paragraph(p, line)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate_novel', methods=['POST'])
def generate_novel():
    try:
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
        chapter_instructions = data.get("chapter_instructions", 
            "Ceritakan bab ini dengan detail, sertakan dialog antar karakter dan narasi yang hidup.")

        new_order = get_chapter_order(chapter_input)
        if new_order is None:
            return jsonify({"status": "error", "message": "Format chapter tidak valid. Gunakan 'Prolog' atau 'Bab <nomor>'."}), 400

        folder_name = f"novel_{sanitize_title(novel_title)}"
        if not os.path.exists(folder_name):
            os.makedirs(folder_name)

        context_prompt = ""
        if narrative_type.lower() == "linear":
            context_prompt = get_context(folder_name, new_order)

        # Jika chapter adalah "Prolog", gunakan template prolog; jika bukan, gunakan template naratif
        if chapter_input.lower() == "prolog":
            chapter_prompt = f"""
            === {chapter_input.upper()} ===
            Tuliskan prolog dengan pengenalan dunia dan karakter secara mendalam.
            Gunakan deskripsi, dialog, dan narasi untuk memperkenalkan latar cerita.
            Informasi tambahan:
            - Genre: {genre}
            - Dunia: {world_setting}
            - Tokoh Utama: {character_name} dengan kekuatan {special_power}
            - Konflik: {conflict}
            - Plot Twist: {plot_twist}
            - Gaya: {writing_style}
            
            {chapter_instructions}
            """
        else:
            # Untuk bab selanjutnya, instruksikan agar cerita bersifat naratif penuh, dialog, dan alur cerita yang utuh.
            chapter_prompt = f"""
            === {chapter_input.upper()} ===
            Tuliskan bab ini sebagai kelanjutan cerita yang naratif, dengan dialog antar karakter, deskripsi mendalam, dan alur cerita yang koheren.
            Jangan hanya menampilkan template, tetapi kembangkan cerita menjadi narasi yang hidup.
            Gunakan informasi berikut sebagai dasar:
            Genre: {genre}
            Dunia: {world_setting}
            Tokoh Utama: {character_name} dengan kekuatan {special_power}
            Konflik: {conflict}
            Plot Twist: {plot_twist}
            Gaya: {writing_style}
            
            {chapter_instructions}
            """
        # Template utama tetap digunakan untuk referensi, tapi tidak terlalu dominan
        template_info = f"""
        TEMPLATE UTAMA: WORLD-BUILDING & KARAKTERISASI
        Genre: {genre}
        Dunia: {world_setting}
        Tokoh Utama: {character_name}
        Konflik: {conflict}
        Plot Twist: {plot_twist}
        Gaya: {writing_style}
        """
        full_prompt = template_info + "\n" + chapter_prompt + "\n" + context_prompt

        if len(full_prompt) > MAX_PROMPT_LENGTH:
            required_prompt = template_info + "\n" + chapter_prompt + "\n"
            allowed_context_length = MAX_PROMPT_LENGTH - len(required_prompt)
            allowed_context_length = allowed_context_length if allowed_context_length > 0 else 0
            trimmed_context = context_prompt[-allowed_context_length:] if allowed_context_length > 0 else ""
            full_prompt = required_prompt + trimmed_context

        encoded_prompt = urllib.parse.quote(full_prompt)
        pollinations_url = f"https://text.pollinations.ai/openai/{encoded_prompt}"

        response = requests.get(pollinations_url)
        if response.status_code == 200:
            generated_story = response.text

            filename = "prolog.json" if chapter_input.lower() == "prolog" else f"bab{new_order}.json"
            filepath = os.path.join(folder_name, filename)
            chapter_data = {
                "novel_title": novel_title,
                "chapter": chapter_input,
                "chapter_title": chapter_title,
                "order": new_order,
                "narrative_type": narrative_type,
                "content": generated_story
            }
            with open(filepath, 'w', encoding='utf-8') as outfile:
                json.dump(chapter_data, outfile, ensure_ascii=False, indent=4)

            doc = Document()
            doc.add_heading(chapter_title if chapter_title else chapter_input, level=1)
            add_markdown_to_doc(doc, generated_story)
            doc_filename = "prolog.doc" if chapter_input.lower() == "prolog" else f"bab{new_order}.doc"
            doc_filepath = os.path.join(folder_name, doc_filename)
            doc.save(doc_filepath)

            return jsonify({
                "status": "success",
                "novel_title": novel_title,
                "chapter": chapter_input,
                "order": new_order,
                "json_filepath": filepath,
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
        return send_from_directory(directory=os.getcwd(), path=filename, as_attachment=True)
    except Exception as e:
        return str(e), 404

if __name__ == '__main__':
    app.run(debug=True)
