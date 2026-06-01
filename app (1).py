import os
import json
import shutil
import subprocess
import uuid
import threading
import select
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from bootstrap import InstanceBootstrapper

try:
    import ptyprocess
    PTY_AVAILABLE = True
except ImportError:
    PTY_AVAILABLE = False

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Global state
instances_registry = {}
current_instance_id = None
bootstrapper = InstanceBootstrapper()

# Terminal sessions
terminal_processes = {}
terminal_read_threads = {}

# ── Python binary resolution (ARM Linux may only have python3) ────────────────
def _find_python() -> str:
    for candidate in ("python3", "python"):
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0:
                return candidate
        except FileNotFoundError:
            continue
    return "python3"  # last resort — will fail with a clear error message

PYTHON_BIN = _find_python()


# ==================== Instance Discovery & Repair ====================

def refresh_instances_registry():
    global instances_registry
    instances_dir = Path("instances")
    if not instances_dir.exists():
        return

    new_registry = {}
    for item in instances_dir.iterdir():
        if item.is_dir():
            metadata_path = item / "metadata.json"
            if metadata_path.exists():
                try:
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)
                    if 'instance_id' not in metadata:
                        metadata['instance_id'] = str(uuid.uuid4())
                    metadata['detected_runtime'] = bootstrapper._detect_runtime(item)
                    files_dir = item / "files"
                    metadata['total_files'] = sum(
                        1 for _ in files_dir.iterdir() if _.is_file()
                    ) if files_dir.exists() else 0
                    new_registry[metadata['instance_id']] = metadata
                except Exception as e:
                    print(f"Error loading metadata for {item.name}: {e}")

    instances_registry = new_registry
    # emit safely from any thread
    socketio.emit('instances_changed', {'instances': list(instances_registry.values())})


class InstancesDirHandler(FileSystemEventHandler):
    _timer = None

    def on_any_event(self, event):
        # Debounce: only refresh 0.5 s after the last filesystem event
        if self._timer:
            self._timer.cancel()
        self.__class__._timer = threading.Timer(0.5, refresh_instances_registry)
        self.__class__._timer.start()


def start_watchdog():
    observer = Observer()
    observer.schedule(InstancesDirHandler(), path="instances", recursive=True)
    observer.daemon = True
    observer.start()


# ==================== Helper Functions ====================

def get_instance_path(instance_id: str) -> Path:
    metadata = instances_registry.get(instance_id)
    if not metadata:
        raise ValueError("Instance not found")
    return Path("instances") / metadata['name']


def update_instance_metadata(instance_id: str, updates: dict):
    if instance_id not in instances_registry:
        return
    metadata = instances_registry[instance_id]
    metadata.update(updates)
    instance_path = get_instance_path(instance_id)
    metadata_path = instance_path / "metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    instances_registry[instance_id] = metadata
    socketio.emit('instances_changed', {'instances': list(instances_registry.values())})


def log_execution(instance_id: str, runtime: str, stdout: str, stderr: str,
                  exit_code: int, duration_ms: float):
    instance_path = get_instance_path(instance_id)
    timestamp = datetime.now()
    log_filename = f"execution_{timestamp.strftime('%Y%m%d_%H%M%S')}.log"
    log_path = instance_path / "logs" / log_filename

    log_content = (
        f"Timestamp: {timestamp.isoformat()}\n"
        f"Runtime: {runtime}\n"
        f"Duration: {duration_ms:.2f} ms\n"
        f"Exit Code: {exit_code}\n"
        f"\n=== STDOUT ===\n{stdout}\n"
        f"\n=== STDERR ===\n{stderr}\n"
    )
    log_path.write_text(log_content)

    history_path = instance_path / "history" / "history.json"
    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text())
        except Exception:
            pass

    history.append({
        "timestamp": timestamp.isoformat(),
        "runtime": runtime,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "log_file": log_filename,
    })
    if len(history) > 100:
        history = history[-100:]
    history_path.write_text(json.dumps(history, indent=2))

    metadata = instances_registry[instance_id]
    update_instance_metadata(instance_id, {
        "last_used": timestamp.isoformat(),
        "total_executions": metadata.get("total_executions", 0) + 1,
    })


# ==================== Routes ====================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/instances', methods=['GET'])
def get_instances():
    return jsonify(list(instances_registry.values()))


@app.route('/api/instances/create', methods=['POST'])
def create_instance():
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Instance name required'}), 400

    safe_name = "".join(c for c in name if c.isalnum() or c in ' ._-')
    if not safe_name:
        safe_name = "Instance"

    instances_dir = Path("instances")
    instance_path = instances_dir / safe_name
    counter = 1
    while instance_path.exists():
        instance_path = instances_dir / f"{safe_name}_{counter}"
        counter += 1

    instance_path.mkdir()
    instance_id = str(uuid.uuid4())
    metadata = {
        "instance_id": instance_id,
        "name": instance_path.name,
        "creation_date": datetime.now().isoformat(),
        "last_used": None,
        "description": data.get('description', ''),
        "tags": data.get('tags', []),
        "detected_runtime": "none",
        "total_files": 0,
        "total_executions": 0,
    }
    bootstrapper._repair_instance(instance_path, metadata)
    refresh_instances_registry()
    return jsonify({'instance_id': instance_id, 'name': instance_path.name}), 201


@app.route('/api/instances/<instance_id>/rename', methods=['PUT'])
def rename_instance(instance_id):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404

    data = request.json
    new_name = data.get('name', '').strip()
    if not new_name:
        return jsonify({'error': 'New name required'}), 400

    safe_name = "".join(c for c in new_name if c.isalnum() or c in ' ._-')
    if not safe_name:
        safe_name = "RenamedInstance"

    old_path = get_instance_path(instance_id)
    new_path = old_path.parent / safe_name
    if new_path.exists():
        return jsonify({'error': 'Name already exists'}), 409

    old_path.rename(new_path)
    update_instance_metadata(instance_id, {'name': safe_name})
    refresh_instances_registry()
    return jsonify({'success': True, 'new_name': safe_name})


@app.route('/api/instances/<instance_id>', methods=['DELETE'])
def delete_instance(instance_id):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404

    instance_path = get_instance_path(instance_id)
    shutil.rmtree(instance_path)
    refresh_instances_registry()

    global current_instance_id
    if current_instance_id == instance_id:
        current_instance_id = next(iter(instances_registry.keys()), None)
        if current_instance_id:
            bootstrapper.save_last_active(current_instance_id)

    return jsonify({'success': True})


@app.route('/api/instances/<instance_id>/duplicate', methods=['POST'])
def duplicate_instance(instance_id):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404

    src_path = get_instance_path(instance_id)
    new_name = f"{src_path.name}_copy"
    dest_path = src_path.parent / new_name
    counter = 1
    while dest_path.exists():
        dest_path = src_path.parent / f"{new_name}_{counter}"
        counter += 1

    shutil.copytree(src_path, dest_path)

    new_instance_id = str(uuid.uuid4())
    metadata_path = dest_path / "metadata.json"
    if metadata_path.exists():
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
        metadata['instance_id'] = new_instance_id
        metadata['name'] = dest_path.name
        metadata['creation_date'] = datetime.now().isoformat()
        metadata['total_executions'] = 0
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

    refresh_instances_registry()
    return jsonify({'success': True, 'instance_id': new_instance_id})


@app.route('/api/instances/switch/<instance_id>', methods=['POST'])
def switch_instance(instance_id):
    global current_instance_id
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404

    current_instance_id = instance_id
    bootstrapper.save_last_active(instance_id)
    update_instance_metadata(instance_id, {'last_used': datetime.now().isoformat()})
    return jsonify({'success': True, 'instance': instances_registry[instance_id]})


@app.route('/api/instances/<instance_id>/files', methods=['GET'])
def list_files(instance_id):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404

    instance_path = get_instance_path(instance_id)
    files_dir = instance_path / "files"
    files = []
    if files_dir.exists():
        for file_path in files_dir.iterdir():
            if file_path.is_file():
                files.append({
                    'name': file_path.name,
                    'size': file_path.stat().st_size,
                    'modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                })
    return jsonify(files)


@app.route('/api/instances/<instance_id>/upload', methods=['POST'])
def upload_file(instance_id):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400

    filename = secure_filename(file.filename)
    instance_path = get_instance_path(instance_id)
    files_dir = instance_path / "files"
    files_dir.mkdir(exist_ok=True)
    file.save(files_dir / filename)

    total_files = sum(1 for _ in files_dir.iterdir() if _.is_file())
    update_instance_metadata(instance_id, {'total_files': total_files})
    return jsonify({'success': True, 'filename': filename})


@app.route('/api/instances/<instance_id>/files/<filename>', methods=['DELETE'])
def delete_file(instance_id, filename):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404

    instance_path = get_instance_path(instance_id)
    file_path = instance_path / "files" / secure_filename(filename)
    if file_path.exists():
        file_path.unlink()
        total_files = sum(1 for _ in (instance_path / "files").iterdir() if _.is_file())
        update_instance_metadata(instance_id, {'total_files': total_files})
        return jsonify({'success': True})
    return jsonify({'error': 'File not found'}), 404


# ── Background process registry (for long-running instances like bots) ────────
# instance_id -> { 'proc': Popen, 'runtime': str, 'started_at': str, 'log_path': str }
running_processes = {}


def _build_command_and_entry(runtime: str, instance_path: Path):
    if runtime == 'python':
        return [PYTHON_BIN, "main.py"], instance_path / "main.py"
    else:
        return ["node", "main.js"], instance_path / "main.js"


def _stream_process_output(instance_id: str, proc, log_path: Path):
    """Read stdout+stderr from a background process and append to its log file."""
    try:
        with open(log_path, 'a') as lf:
            for line in proc.stdout:
                lf.write(line)
                lf.flush()
                socketio.emit('instance_output', {
                    'instance_id': instance_id,
                    'line': line,
                })
    except Exception as e:
        print(f"[stream] {instance_id}: {e}")
    finally:
        exit_code = proc.wait()
        running_processes.pop(instance_id, None)
        socketio.emit('instance_stopped', {
            'instance_id': instance_id,
            'exit_code': exit_code,
        })


@app.route('/api/instances/<instance_id>/run', methods=['POST'])
def run_code(instance_id):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404

    # If already running, return its status instead of launching again
    if instance_id in running_processes:
        info = running_processes[instance_id]
        return jsonify({
            'status': 'already_running',
            'runtime_used': info['runtime'],
            'started_at': info['started_at'],
        }), 200

    data = request.json or {}
    override_runtime = data.get('runtime')

    instance_path = get_instance_path(instance_id)
    metadata = instances_registry[instance_id]

    settings_path = instance_path / "settings.json"
    settings = {}
    if settings_path.exists():
        with open(settings_path, 'r') as f:
            settings = json.load(f)

    runtime_override = settings.get('runtime_override')
    if override_runtime:
        runtime = override_runtime
    elif runtime_override:
        runtime = runtime_override
    else:
        runtime = metadata.get('detected_runtime', 'none')

    if runtime == 'hybrid':
        runtime = 'python'

    if runtime not in ('python', 'javascript'):
        return jsonify({'error': f'No executable entry file for runtime: {runtime}'}), 400

    command, entry_file = _build_command_and_entry(runtime, instance_path)

    if not entry_file.exists():
        return jsonify({'error': f'{entry_file.name} not found in instance'}), 400

    # Log file for this run
    timestamp = datetime.now()
    log_filename = f"execution_{timestamp.strftime('%Y%m%d_%H%M%S')}.log"
    log_path = instance_path / "logs" / log_filename
    log_path.parent.mkdir(exist_ok=True)

    with open(log_path, 'w') as lf:
        lf.write(f"Started: {timestamp.isoformat()}\nRuntime: {runtime}\n\n")

    try:
        proc = subprocess.Popen(
            command,
            cwd=str(instance_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # merge stderr into stdout
            text=True,
            bufsize=1,                  # line-buffered
        )
    except FileNotFoundError as e:
        return jsonify({'error': f'Runtime not found: {e}. Is {command[0]} installed?'}), 500

    running_processes[instance_id] = {
        'proc': proc,
        'runtime': runtime,
        'started_at': timestamp.isoformat(),
        'log_path': str(log_path),
    }

    # Stream output in background thread — never blocks the web server
    t = threading.Thread(
        target=_stream_process_output,
        args=(instance_id, proc, log_path),
        daemon=True,
    )
    t.start()

    update_instance_metadata(instance_id, {
        'last_used': timestamp.isoformat(),
        'total_executions': metadata.get('total_executions', 0) + 1,
    })

    return jsonify({
        'status': 'started',
        'runtime_used': runtime,
        'started_at': timestamp.isoformat(),
        'log_file': log_filename,
    }), 200


@app.route('/api/instances/<instance_id>/stop', methods=['POST'])
def stop_instance(instance_id):
    """Stop a running background instance."""
    info = running_processes.pop(instance_id, None)
    if not info:
        return jsonify({'error': 'Instance is not running'}), 400

    proc = info['proc']
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'success': True, 'message': f'Instance {instance_id} stopped.'})


@app.route('/api/instances/<instance_id>/status', methods=['GET'])
def instance_status(instance_id):
    """Check whether a background instance is currently running."""
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404

    info = running_processes.get(instance_id)
    if info:
        proc = info['proc']
        alive = proc.poll() is None
        if not alive:
            running_processes.pop(instance_id, None)
        return jsonify({
            'running': alive,
            'runtime': info['runtime'],
            'started_at': info['started_at'],
            'log_path': info['log_path'],
        })
    return jsonify({'running': False})


@app.route('/api/instances/<instance_id>/logs', methods=['GET'])
def get_logs(instance_id):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404

    instance_path = get_instance_path(instance_id)
    logs_dir = instance_path / "logs"
    logs = []
    if logs_dir.exists():
        for log_file in sorted(logs_dir.glob("*.log"), reverse=True):
            logs.append({
                'name': log_file.name,
                'size': log_file.stat().st_size,
                'modified': datetime.fromtimestamp(log_file.stat().st_mtime).isoformat(),
            })
    return jsonify(logs)


@app.route('/api/instances/<instance_id>/logs/<logfile>', methods=['GET'])
def get_log_content(instance_id, logfile):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404
    if '..' in logfile:
        return jsonify({'error': 'Invalid log path'}), 400

    instance_path = get_instance_path(instance_id)
    log_path = instance_path / "logs" / logfile
    if not log_path.exists():
        return jsonify({'error': 'Log not found'}), 404
    return send_from_directory(str(instance_path / "logs"), logfile)


@app.route('/api/instances/<instance_id>/history', methods=['GET'])
def get_history(instance_id):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404

    instance_path = get_instance_path(instance_id)
    history_path = instance_path / "history" / "history.json"
    if history_path.exists():
        try:
            return jsonify(json.loads(history_path.read_text()))
        except Exception:
            pass
    return jsonify([])


@app.route('/api/instances/<instance_id>/settings', methods=['GET'])
def get_instance_settings(instance_id):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404

    instance_path = get_instance_path(instance_id)
    settings_path = instance_path / "settings.json"
    if settings_path.exists():
        with open(settings_path, 'r') as f:
            return jsonify(json.load(f))
    return jsonify({"runtime_override": None, "execution_timeout": 30, "auto_save_logs": True})


@app.route('/api/instances/<instance_id>/settings', methods=['PUT'])
def update_instance_settings(instance_id):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404

    data = request.json
    instance_path = get_instance_path(instance_id)
    settings_path = instance_path / "settings.json"
    settings = {}
    if settings_path.exists():
        with open(settings_path, 'r') as f:
            settings = json.load(f)

    settings.update({
        'runtime_override': data.get('runtime_override'),
        'execution_timeout': data.get('execution_timeout', 30),
        'auto_save_logs': data.get('auto_save_logs', True),
    })
    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)

    update_instance_metadata(instance_id, {
        'description': data.get('description', ''),
        'tags': data.get('tags', []),
    })
    return jsonify({'success': True})


@app.route('/api/instances/search', methods=['GET'])
def search_instances():
    query = request.args.get('q', '').lower()
    results = [
        inst for inst in instances_registry.values()
        if (query in inst['name'].lower()
            or query in inst.get('description', '').lower()
            or any(query in tag.lower() for tag in inst.get('tags', [])))
    ]
    return jsonify(results)


@app.route('/api/instances/sort', methods=['GET'])
def sort_instances():
    sort_by = request.args.get('by', 'name')
    reverse = request.args.get('reverse', 'false').lower() == 'true'
    instances_list = list(instances_registry.values())

    key_map = {
        'name':          lambda x: x['name'].lower(),
        'creation_date': lambda x: x.get('creation_date', ''),
        'last_used':     lambda x: x.get('last_used') or '',
    }
    instances_list.sort(key=key_map.get(sort_by, key_map['name']), reverse=reverse)
    return jsonify(instances_list)


# ==================== Terminal ====================

@socketio.on('terminal_start')
def handle_terminal_start():
    if not PTY_AVAILABLE:
        emit('terminal_error', {'message': 'ptyprocess not installed'})
        return

    sid = request.sid
    if sid in terminal_processes:
        return

    try:
        env = os.environ.copy()
        env['TERM'] = 'xterm-256color'
        proc = ptyprocess.PtyProcess.spawn(['/bin/bash', '-i'], env=env, echo=False)
        proc.setwinsize(24, 80)
        terminal_processes[sid] = proc

        def read_output():
            while sid in terminal_processes and proc.isalive():
                try:
                    r, _, _ = select.select([proc.fd], [], [], 0.1)
                    if r:
                        data_bytes = proc.read(4096)
                        if data_bytes:
                            socketio.emit(
                                'terminal_output',
                                {'data': data_bytes.decode('utf-8', errors='replace')},
                                room=sid,
                            )
                except Exception as e:
                    print(f"Terminal read error: {e}")
                    break
            _cleanup_terminal(sid)

        t = threading.Thread(target=read_output, daemon=True)
        t.start()
        terminal_read_threads[sid] = t
        emit('terminal_ready')

    except Exception as e:
        print(f"Terminal start error: {e}")
        emit('terminal_error', {'message': str(e)})


@socketio.on('terminal_input')
def handle_terminal_input(data):
    sid = request.sid
    proc = terminal_processes.get(sid)
    if proc and proc.isalive():
        try:
            proc.write(data.get('data', '').encode())
        except Exception as e:
            print(f"Terminal write error: {e}")


@socketio.on('terminal_resize')
def handle_terminal_resize(data):
    sid = request.sid
    proc = terminal_processes.get(sid)
    if proc and proc.isalive():
        try:
            proc.setwinsize(rows=data.get('rows', 24), cols=data.get('cols', 80))
        except Exception as e:
            print(f"Terminal resize error: {e}")


# ── FIX: clean up terminal process when client disconnects ───────────────────
@socketio.on('disconnect')
def handle_disconnect():
    _cleanup_terminal(request.sid)


def _cleanup_terminal(sid):
    proc = terminal_processes.pop(sid, None)
    if proc and proc.isalive():
        proc.terminate(force=True)
    terminal_read_threads.pop(sid, None)


# ==================== SocketIO Events ====================

@socketio.on('connect')
def handle_connect():
    emit('instances_changed', {'instances': list(instances_registry.values())})
    if current_instance_id:
        emit('active_instance_changed', {'instance_id': current_instance_id})


# ==================== Main ====================

if __name__ == '__main__':
    bootstrap_result = bootstrapper.bootstrap()
    instances_registry.update(bootstrap_result['instances'])
    current_instance_id = bootstrap_result['last_active']

    watchdog_thread = threading.Thread(target=start_watchdog, daemon=True)
    watchdog_thread.start()

    print(f"Using Python binary: {PYTHON_BIN}")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
