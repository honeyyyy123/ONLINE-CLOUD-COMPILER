import os
import subprocess
import time
import threading
import queue
import webbrowser
from flask import Flask, request, jsonify, render_template

# --- CONFIGURATION ---
PORT = 8080
app = Flask(__name__)

# Global process storage
active_process = None
process_queue = queue.Queue()

# --- BACKEND LOGIC ---

def read_output(process):
    while True:
        try:
            output = process.stdout.read(1) 
            if output == '' and process.poll() is not None:
                break
            if output:
                process_queue.put(output)
        except:
            break

@app.route("/")
def home():
    # Ab yeh templates/index.html file ko load karega
    return render_template("index.html")

@app.route("/start", methods=["POST"])
def start_process():
    global active_process
    
    if active_process and active_process.poll() is None:
        active_process.kill()
    
    with process_queue.mutex: process_queue.queue.clear()

    data = request.get_json(force=True)
    lang, code = data.get("lang"), data.get("code")

    fname = "main.py" if lang == "python" else "main.c"
    with open(fname, "w", encoding="utf-8") as f: f.write(code)

    cmd = []
    
    # --- PYTHON ---
    if lang == "python":
        cmd = ["python", "-u", fname]
    
    # --- C LANGUAGE ---
    elif lang == "c":
        exe = "app.exe" if os.name=='nt' else "./app.out"
        try:
            comp = subprocess.run(["gcc", fname, "-o", exe], capture_output=True, text=True)
            if comp.returncode != 0:
                return jsonify({"status": "error", "message": f"Compilation Failed:\n{comp.stderr}"})
            cmd = [exe]
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "Error: 'gcc' not found. Install MinGW for C support."})
    
    try:
        active_process = subprocess.Popen(
            cmd, 
            stdin=subprocess.PIPE, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0
        )
        
        t = threading.Thread(target=read_output, args=(active_process,))
        t.daemon = True
        t.start()

        return jsonify({"status": "started"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/stream")
def stream_output():
    output_buffer = ""
    try:
        while not process_queue.empty():
            output_buffer += process_queue.get_nowait()
    except: pass
    is_active = active_process is not None and active_process.poll() is None
    return jsonify({"output": output_buffer, "active": is_active})

@app.route("/input", methods=["POST"])
def send_input():
    if active_process and active_process.poll() is None:
        data = request.get_json(force=True).get("data", "")
        try:
            active_process.stdin.write(data + "\n")
            active_process.stdin.flush()
        except: pass
        return jsonify({"status": "sent"})
    return jsonify({"status": "no_process"})

@app.route("/stop")
def stop_process():
    global active_process
    if active_process:
        active_process.kill()
        active_process = None
    return jsonify({"status": "stopped"})

if __name__ == "__main__":
    # Cloud servers ke liye host 0.0.0.0 hona chahiye
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))