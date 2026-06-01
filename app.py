import os
import json
import shutil
import subprocess
import uuid
import json
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
import eventlet
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading

from bootstrap import InstanceBootstrapper

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
socketio = SocketIO(app, cors_allowed_origins="*")

# Global state
terminal_processes = {}  # sid -> ptyprocess.PtyProcess
terminal_read_threads = {}  # sid -> threading.Thread
instances_registry = {}  # instance_id -> metadata
current_instance_id = None
bootstrapper = InstanceBootstrapper()

# ==================== Instance Discovery & Repair ====================

def refresh_instances_registry():
    """Re-scan instances directory and update registry."""
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
                        # Ensure instance_id is present
                        if 'instance_id' not in metadata:
                            metadata['instance_id'] = str(uuid.uuid4())
                        # Re-detect runtime
                        metadata['detected_runtime'] = bootstrapper._detect_runtime(item)
                        # Update file count
                        files_dir = item / "files"
                        metadata['total_files'] = sum(1 for _ in files_dir.iterdir() if _.is_file()) if files_dir.exists() else 0
                        new_registry[metadata['instance_id']] = metadata
                except Exception as e:
                    print(f"Error loading metadata for {item.name}: {e}")
    instances_registry = new_registry
    socketio.emit('instances_changed', {'instances': list(instances_registry.values())})

class InstancesDirHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        # Debounce: wait a bit then refresh
        eventlet.spawn_after(0.5, refresh_instances_registry)

def start_watchdog():
    observer = Observer()
    observer.schedule(InstancesDirHandler(), path="instances", recursive=True)
    observer.start()

# ==================== Helper Functions ====================

def get_instance_path(instance_id: str) -> Path:
    """Get filesystem path for an instance."""
    metadata = instances_registry.get(instance_id)
    if not metadata:
        raise ValueError("Instance not found")
    return Path("instances") / metadata['name']

def update_instance_metadata(instance_id: str, updates: dict):
    """Update metadata.json and registry."""
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

def log_execution(instance_id: str, runtime: str, stdout: str, stderr: str, exit_code: int, duration_ms: float):
    """Save execution log and update history."""
    instance_path = get_instance_path(instance_id)
    timestamp = datetime.now()
    
    # Save log file
    log_filename = f"execution_{timestamp.strftime('%Y%m%d_%H%M%S')}.log"
    log_path = instance_path / "logs" / log_filename
    log_content = f"""Timestamp: {timestamp.isoformat()}
Runtime: {runtime}
Duration: {duration_ms:.2f} ms
Exit Code: {exit_code}

=== STDOUT ===
{stdout}

=== STDERR ===
{stderr}
"""
    log_path.write_text(log_content)
    
    # Update history.json
    history_path = instance_path / "history" / "history.json"
    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text())
        except:
            pass
    
    history_entry = {
        "timestamp": timestamp.isoformat(),
        "runtime": runtime,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "log_file": log_filename
    }
    history.append(history_entry)
    # Keep last 100 entries
    if len(history) > 100:
        history = history[-100:]
    history_path.write_text(json.dumps(history, indent=2))
    
    # Update metadata totals
    metadata = instances_registry[instance_id]
    update_instance_metadata(instance_id, {
        "last_used": timestamp.isoformat(),
        "total_executions": metadata.get("total_executions", 0) + 1
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
    
    # Sanitize name for filesystem
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
        "total_executions": 0
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
    
    # If current instance was deleted, switch to first available
    global current_instance_id
    if current_instance_id == instance_id:
        current_instance_id = next(iter(instances_registry.keys())) if instances_registry else None
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
    # Generate new instance ID
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
                    'modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
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
    
    # Update file count
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
        # Update file count
        total_files = sum(1 for _ in (instance_path / "files").iterdir() if _.is_file())
        update_instance_metadata(instance_id, {'total_files': total_files})
        return jsonify({'success': True})
    return jsonify({'error': 'File not found'}), 404

@app.route('/api/instances/<instance_id>/run', methods=['POST'])
def run_code(instance_id):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404
    
    data = request.json or {}
    override_runtime = data.get('runtime')  # 'python', 'javascript', or None for auto
    
    instance_path = get_instance_path(instance_id)
    metadata = instances_registry[instance_id]
    settings_path = instance_path / "settings.json"
    settings = {}
    if settings_path.exists():
        with open(settings_path, 'r') as f:
            settings = json.load(f)
    
    runtime_override = settings.get('runtime_override')
    # Priority: request override > instance settings > auto-detect
    if override_runtime:
        runtime = override_runtime
    elif runtime_override:
        runtime = runtime_override
    else:
        runtime = metadata.get('detected_runtime', 'none')
        if runtime == 'hybrid':
            runtime = 'python'  # default for hybrid
    
    if runtime not in ['python', 'javascript']:
        return jsonify({'error': f'No executable entry file for runtime: {runtime}'}), 400
    
    # Check entry file exists
    if runtime == 'python':
        entry_file = instance_path / "main.py"
        command = ['python', str(entry_file)]
    else:
        entry_file = instance_path / "main.js"
        command = ['node', str(entry_file)]
    
    if not entry_file.exists():
        return jsonify({'error': f'Entry file {entry_file.name} not found in instance'}), 400
    
    timeout = settings.get('execution_timeout', 30)
    start_time = datetime.now()
    try:
        result = subprocess.run(
            command,
            cwd=str(instance_path),
            capture_output=True,
            text=True,
            timeout=timeout
        )
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        log_execution(instance_id, runtime, result.stdout, result.stderr, result.returncode, duration_ms)
        return jsonify({
            'stdout': result.stdout,
            'stderr': result.stderr,
            'exit_code': result.returncode,
            'duration_ms': duration_ms,
            'runtime_used': runtime
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': f'Execution timed out after {timeout} seconds'}), 408
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
                'modified': datetime.fromtimestamp(log_file.stat().st_mtime).isoformat()
            })
    return jsonify(logs)

@app.route('/api/instances/<instance_id>/logs/<logfile>', methods=['GET'])
def get_log_content(instance_id, logfile):
    if instance_id not in instances_registry:
        return jsonify({'error': 'Instance not found'}), 404
    instance_path = get_instance_path(instance_id)
    log_path = instance_path / "logs" / logfile
    if not log_path.exists() or '..' in logfile:
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
            history = json.loads(history_path.read_text())
            return jsonify(history)
        except:
            pass
    return jsonify([])

@app.route('/api/instances/search', methods=['GET'])
def search_instances():
    query = request.args.get('q', '').lower()
    results = []
    for inst in instances_registry.values():
        if (query in inst['name'].lower() or 
            query in inst.get('description', '').lower() or
            any(query in tag.lower() for tag in inst.get('tags', []))):
            results.append(inst)
    return jsonify(results)

@app.route('/api/instances/sort', methods=['GET'])
def sort_instances():
    sort_by = request.args.get('by', 'name')
    reverse = request.args.get('reverse', 'false').lower() == 'true'
    instances_list = list(instances_registry.values())
    if sort_by == 'name':
        instances_list.sort(key=lambda x: x['name'].lower(), reverse=reverse)
    elif sort_by == 'creation_date':
        instances_list.sort(key=lambda x: x.get('creation_date', ''), reverse=reverse)
    elif sort_by == 'last_used':
        instances_list.sort(key=lambda x: x.get('last_used') or '', reverse=reverse)
    return jsonify(instances_list)

# ==================== SocketIO Events ====================

@socketio.on('connect')
def handle_connect():
    emit('instances_changed', {'instances': list(instances_registry.values())})
    if current_instance_id:
        emit('active_instance_changed', {'instance_id': current_instance_id})
        
@socketio.on('terminal_start')
def handle_terminal_start():
    """Spawn a root shell for the client."""
    sid = request.sid
    if sid in terminal_processes:
        # already running
        return
    
    try:
        # Spawn bash with sudo to become root (requires NOPASSWD in sudoers)
        # Alternatively use ['/bin/bash'] if app is already root.
        proc = ptyprocess.PtyProcess.spawn(['sudo', '-i'], echo=False)
        terminal_processes[sid] = proc
        
        # Start reading thread
        def read_output():
            while sid in terminal_processes and proc.isalive():
                try:
                    # Use select to avoid blocking forever
                    r, _, _ = select.select([proc.fd], [], [], 0.1)
                    if r:
                        data = proc.read(4096)
                        if data:
                            socketio.emit('terminal_output', {'data': data}, room=sid)
                    else:
                        # Check if process died
                        if not proc.isalive():
                            break
                except Exception as e:
                    print(f"Terminal read error: {e}")
                    break
            # Cleanup on exit
            cleanup_terminal(sid)
        
        thread = threading.Thread(target=read_output, daemon=True)
        thread.start()
        terminal_read_threads[sid] = thread
        socketio.emit('terminal_ready', room=sid)
    except Exception as e:
        socketio.emit('terminal_error', {'message': str(e)}, room=sid)

@socketio.on('terminal_input')
def handle_terminal_input(data):
    sid = request.sid
    proc = terminal_processes.get(sid)
    if proc and proc.isalive():
        try:
            proc.write(data.get('data', ''))
        except Exception as e:
            print(f"Write error: {e}")

@socketio.on('terminal_resize')
def handle_terminal_resize(data):
    sid = request.sid
    proc = terminal_processes.get(sid)
    if proc and proc.isalive():
        try:
            proc.setwinsize(rows=data.get('rows', 24), cols=data.get('cols', 80))
        except Exception as e:
            print(f"Resize error: {e}")

def cleanup_terminal(sid):
    """Kill process and remove references."""
    proc = terminal_processes.pop(sid, None)
    if proc and proc.isalive():
        proc.terminate(force=True)
    terminal_read_threads.pop(sid, None)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    cleanup_terminal(sid)

# ==================== Main ====================

if __name__ == '__main__':
    # Bootstrap
    bootstrap_result = bootstrapper.bootstrap()
    instances_registry.update(bootstrap_result['instances'])
    current_instance_id = bootstrap_result['last_active']
    
    # Start watchdog for real-time instance detection
    watchdog_thread = threading.Thread(target=start_watchdog, daemon=True)
    watchdog_thread.start()
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
