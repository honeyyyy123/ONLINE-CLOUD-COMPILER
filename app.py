import os
import subprocess
import time
import threading
import queue
import webbrowser
from flask import Flask, request, jsonify, render_template_string

# --- CONFIGURATION ---
PORT = 8080
app = Flask(__name__)

# Global process storage
active_process = None
process_queue = queue.Queue()

# --- FRONTEND (HTML/CSS/JS) ---
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>VS Code Interactive</title>
    <style>
        :root { --bg: #1e1e1e; --side: #252526; --text: #d4d4d4; --accent: #007acc; --border: #3e3e42; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Segoe UI', monospace; background: var(--bg); color: var(--text); height: 100vh; display: flex; overflow: hidden; }
        
        /* Sidebar */
        .sidebar { width: 200px; background: var(--side); border-right: 1px solid var(--border); display: flex; flex-direction: column; }
        .header { padding: 10px; font-size: 11px; font-weight: bold; color: #888; display: flex; justify-content: space-between; }
        .add-btn { cursor: pointer; color: white; } .add-btn:hover { color: var(--accent); }
        .file-list { list-style: none; margin-top: 5px; overflow-y: auto; flex: 1; }
        .file-item { padding: 5px 15px; cursor: pointer; font-size: 13px; border-left: 2px solid transparent; display: flex; justify-content: space-between; }
        .file-item:hover { background: #2a2d2e; }
        .file-item.active { background: #37373d; color: white; border-left: 2px solid var(--accent); }
        .del { color: #ff5f56; display: none; font-weight: bold; } .file-item:hover .del { display: block; }

        /* Main Editor */
        .main { flex: 1; display: flex; flex-direction: column; }
        .editor-area { flex: 1; position: relative; display: flex; }
        textarea#code { width: 100%; height: 100%; background: var(--bg); color: #d4d4d4; border: none; padding: 15px; font-family: 'Consolas', monospace; font-size: 15px; resize: none; outline: none; line-height: 1.5; }
        
        .run-btn { position: absolute; top: 10px; right: 20px; background: #2da042; color: white; border: none; padding: 6px 15px; border-radius: 3px; cursor: pointer; font-size: 12px; font-weight: 600; z-index: 10; display: flex; align-items: center; gap: 5px; }
        .run-btn:hover { background: #217a32; }
        .stop-btn { background: #be1100; } .stop-btn:hover { background: #a00e00; }

        /* Terminal */
        .terminal { height: 35%; background: var(--bg); border-top: 1px solid var(--border); display: flex; flex-direction: column; }
        .term-head { padding: 5px 15px; font-size: 11px; font-weight: bold; color: #888; border-bottom: 1px solid var(--border); background: #252526; display: flex; justify-content: space-between; }
        .term-body { flex: 1; padding: 10px; font-family: 'Consolas', monospace; font-size: 14px; overflow-y: auto; white-space: pre-wrap; cursor: text; }
        
        /* Interactive Input */
        .input-line { display: flex; align-items: center; }
        .prompt { color: #007acc; margin-right: 5px; font-weight: bold; }
        #term-input { background: transparent; border: none; color: white; font-family: inherit; font-size: inherit; outline: none; flex: 1; }
    </style>
</head>
<body>

<div class="sidebar">
    <div class="header">EXPLORER <span class="add-btn" onclick="addFile()">+</span></div>
    <ul class="file-list" id="files"></ul>
</div>

<div class="main">
    <div class="editor-area">
        <button class="run-btn" id="btn-run" onclick="runCode()">▶ Run</button>
        <textarea id="code" oninput="saveCode()" spellcheck="false"></textarea>
    </div>

    <div class="terminal" onclick="focusInput()">
        <div class="term-head">
            <span>TERMINAL</span>
            <span style="cursor: pointer" onclick="clearTerm()">✕ Clear</span>
        </div>
        <div class="term-body" id="term-body">
            <div id="output-content">Welcome. Click Run to start.<br></div>
            <div class="input-line" id="input-wrapper" style="display:none;">
                <span class="prompt">Input ></span>
                <input type="text" id="term-input" autocomplete="off">
            </div>
        </div>
    </div>
</div>

<script>
    // --- FILE DATA ---
    let files = {
        "main.py": { lang: "python", code: "print('Hello Python')\\n" },
        "code.c": { lang: "c", code: "#include <stdio.h>\\nint main() {\\n  printf(\\"Hello C World\\");\\n  return 0;\\n}" }
    };
    let curFile = "main.py";
    let isRunning = false;
    let pollInterval = null;

    // --- UI FUNCTIONS ---
    function render() {
        const ul = document.getElementById('files'); ul.innerHTML = "";
        Object.keys(files).forEach(name => {
            let li = document.createElement('li');
            li.className = `file-item ${name === curFile ? 'active' : ''}`;
            li.onclick = () => switchFile(name);
            li.innerHTML = `📄 ${name} <span class="del" onclick="delFile(event, '${name}')">✕</span>`;
            ul.appendChild(li);
        });
        document.getElementById('code').value = files[curFile].code;
    }

    function switchFile(name) { files[curFile].code = document.getElementById('code').value; curFile = name; render(); }
    function saveCode() { files[curFile].code = document.getElementById('code').value; }
    function addFile() {
        let name = prompt("File Name (e.g. test.py):");
        if(name && !files[name]) {
            let lang = name.endsWith(".py") ? "python" : (name.endsWith(".c") ? "c" : "cpp");
            files[name] = { lang: lang, code: "" };
            switchFile(name);
        }
    }
    function delFile(e, name) { e.stopPropagation(); if(Object.keys(files).length > 1) { delete files[name]; switchFile(Object.keys(files)[0]); } }
    function clearTerm() { document.getElementById('output-content').innerHTML = ""; }
    function focusInput() { if(isRunning) document.getElementById('term-input').focus(); }

    // --- RUNTIME FUNCTIONS ---
    async function runCode() {
        if (isRunning) return stopCode();

        // UI Setup
        isRunning = true;
        document.getElementById('btn-run').innerHTML = "⏹ Stop";
        document.getElementById('btn-run').className = "run-btn stop-btn";
        document.getElementById('output-content').innerHTML += "<span style='color:yellow'>Running...</span><br>";
        document.getElementById('term-input').value = "";

        try {
            const response = await fetch("/start", {
                method: "POST",
                body: JSON.stringify({ lang: files[curFile].lang, code: document.getElementById('code').value })
            });
            const data = await response.json();

            // ERROR HANDLING: If compilation failed
            if (data.status === "error") {
                document.getElementById('output-content').innerHTML += `<span style='color:#ff5f56'>${data.message.replace(/\\n/g, "<br>")}</span><br>`;
                stopCode();
                return;
            }

            // Success: Start Input UI and Polling
            document.getElementById('input-wrapper').style.display = 'flex';
            document.getElementById('term-input').focus();
            pollInterval = setInterval(fetchOutput, 300);

        } catch(e) {
            stopCode();
            document.getElementById('output-content').innerHTML += "<span style='color:red'>System Error.</span><br>";
        }
    }

    async function stopCode() {
        isRunning = false;
        clearInterval(pollInterval);
        await fetch("/stop");
        
        document.getElementById('btn-run').innerHTML = "▶ Run";
        document.getElementById('btn-run').className = "run-btn";
        document.getElementById('input-wrapper').style.display = 'none';
        document.getElementById('output-content').innerHTML += "<span style='color:#007acc'>[Process Ended]</span><br>";
    }

    async function fetchOutput() {
        if(!isRunning) return;
        try {
            const res = await fetch("/stream");
            const data = await res.json();
            
            if (data.output) {
                let fmt = data.output.replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\\n/g, "<br>");
                document.getElementById('output-content').innerHTML += fmt;
                document.querySelector('.term-body').scrollTop = document.querySelector('.term-body').scrollHeight;
            }
            
            if (!data.active) stopCode(); // Stop if process ended
        } catch(e) { console.log("Poll error", e); }
    }

    document.getElementById('term-input').addEventListener("keypress", async function(event) {
        if (event.key === "Enter") {
            event.preventDefault();
            const val = this.value;
            document.getElementById('output-content').innerHTML += `<span style='color:white'>${val}</span><br>`;
            this.value = "";
            await fetch("/input", { method: "POST", body: JSON.stringify({ data: val }) });
        }
    });

    render();
</script>
</body>
</html>
"""

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
def home(): return render_template_string(HTML_CONTENT)

@app.route("/start", methods=["POST"])
def start_process():
    global active_process
    
    if active_process and active_process.poll() is None:
        active_process.kill()
    
    with process_queue.mutex: process_queue.queue.clear()

    data = request.get_json(force=True)
    lang, code = data.get("lang"), data.get("code")

    # File Setup
    fname = "main.py" if lang == "python" else "main.c"
    with open(fname, "w", encoding="utf-8") as f: f.write(code)

    cmd = []
    
    # --- PYTHON ---
    if lang == "python":
        cmd = ["python", "-u", fname] # -u for unbuffered output
    
    # --- C LANGUAGE (Needs GCC) ---
    elif lang == "c":
        exe = "app.exe" if os.name=='nt' else "./app.out"
        try:
            # 1. Compile Step
            comp = subprocess.run(["gcc", fname, "-o", exe], capture_output=True, text=True)
            
            # 2. Check for Compilation Errors
            if comp.returncode != 0:
                return jsonify({
                    "status": "error", 
                    "message": f"Compilation Failed:\n{comp.stderr}\n(Make sure MinGW/GCC is installed)"
                })
            
            # 3. Run Step (If compile success)
            cmd = [exe]

        except FileNotFoundError:
            return jsonify({
                "status": "error", 
                "message": "Error: 'gcc' not found.\n\nYou need to install MinGW (GCC compiler) to run C code.\nOr use Python instead."
            })
    
    # Start Process
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
    print(f"Server running at http://127.0.0.1:{PORT}/")
    threading.Thread(target=lambda: (time.sleep(1), webbrowser.open(f"http://127.0.0.1:{PORT}/"))).start()
    app.run(port=PORT, debug=False, threaded=True)