#!/usr/bin/env python3
from flask import Flask, request, send_file, redirect, url_for
from werkzeug.utils import secure_filename
import subprocess, os, threading, uuid, cv2, numpy as np, time
from concurrent.futures import ThreadPoolExecutor
from glob import glob

app = Flask(__name__)
app.secret_key = '123'
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'output'
TEMP = 'temp'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(TEMP, exist_ok=True)
jobs = {}

def process_frame(frame_path):
    img = cv2.imread(frame_path)
    h, w = img.shape[:2]
    
    # Máscara en negro
    mask = np.zeros((h, w), dtype=np.uint8)
    
    # Watermark izquierdo - ALTURA REDUCIDA A LA MITAD
    mask[530:620, 10:440] = 255
    
    # Watermark derecho - ALTURA REDUCIDA A LA MITAD
    mask[140:190, 910:1280] = 255
    
    # Inpaint
    result = cv2.inpaint(img, mask, 5, cv2.INPAINT_TELEA)
    cv2.imwrite(frame_path, result)

def remove_watermark(inp, out):
    subprocess.run(['ffmpeg', '-y', '-i', inp, f'{TEMP}/%06d.png'], check=True)
    
    frames = sorted(glob(f'{TEMP}/*.png'))
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        executor.map(process_frame, frames)
    
    subprocess.run([
        'ffmpeg', '-y', '-r', '24', '-i', f'{TEMP}/%06d.png',
        '-i', inp, '-map', '0:v', '-map', '1:a?', 
        '-c:v', 'libx264', '-crf', '18', '-preset', 'fast', out
    ], check=True)
    
    # Limpia frames temp
    for f in frames:
        os.remove(f)

def cleanup_old_files():
    """Limpia archivos temporales cada 2 horas"""
    while True:
        time.sleep(7200)  # 2 horas
        try:
            # Limpia temp
            for f in glob(f'{TEMP}/*'):
                if os.path.exists(f):
                    os.remove(f)
            # Limpia outputs viejos (más de 3 horas)
            now = time.time()
            for f in glob(f'{OUTPUT_FOLDER}/*'):
                if os.path.exists(f) and now - os.path.getmtime(f) > 10800:
                    os.remove(f)
            # Limpia uploads viejos (más de 3 horas)
            for f in glob(f'{UPLOAD_FOLDER}/*'):
                if os.path.exists(f) and now - os.path.getmtime(f) > 10800:
                    os.remove(f)
        except:
            pass

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        file = request.files['file']
        if not file or not file.filename: return "Error", 400
        name = secure_filename(file.filename)
        inp = os.path.join(UPLOAD_FOLDER, name)
        out = os.path.join(OUTPUT_FOLDER, 'limpio_' + name)
        file.save(inp)
        jid = str(uuid.uuid4())
        jobs[jid] = {"status": "processing", "out": out}
        
        def run():
            try:
                remove_watermark(inp, out)
                jobs[jid]['status'] = 'done'
            except Exception as e:
                jobs[jid]['status'] = 'error'
                jobs[jid]['error'] = str(e)
            finally:
                if os.path.exists(inp): os.remove(inp)
        
        threading.Thread(target=run, daemon=True).start()
        return redirect(url_for("status", job_id=jid))
    
    return '<h1>Quitar MovieFlow</h1><form method="post" enctype="multipart/form-data"><input type="file" name="file" accept="video/*"><button>Subir</button></form>'

@app.route("/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id)
    if not job: return "404", 404
    if job['status'] == 'processing':
        return '<meta http-equiv="refresh" content="5"><h2>Procesando...</h2>'
    if job['status'] == 'done':
        return f'<h2>✅ LISTO</h2><a href="/get/{job_id}" style="font-size:24px;color:green;">DESCARGAR</a>'
    return f'<h2>Error</h2>{job.get("error", "")}'

@app.route("/get/<job_id>")
def get(job_id):
    job = jobs.get(job_id)
    if not job or job['status'] != 'done': return "404", 404
    path = job['out']
    if not os.path.exists(path): return "404", 404
    threading.Thread(target=lambda: [time.sleep(10800), os.remove(path) if os.path.exists(path) else None], daemon=True).start()
    return send_file(path, as_attachment=True)

if __name__ == "__main__":
    # Inicia limpieza automática en background
    threading.Thread(target=cleanup_old_files, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
