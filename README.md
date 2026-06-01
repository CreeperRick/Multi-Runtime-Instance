# Multi-Instance Code Runner

A web-based execution environment that supports multiple isolated Python and JavaScript (Node.js) workspaces, with automatic runtime detection, real-time UI updates, and full instance lifecycle management.

---

## Table of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Running the Application](#running-the-application)
- [How It Works](#how-it-works)
- [Instance Management](#instance-management)
- [Runtime Detection](#runtime-detection)
- [Execution](#execution)
- [API Reference](#api-reference)
- [WebSocket Events](#websocket-events)
- [Instance File Structure](#instance-file-structure)
- [Security & Isolation](#security--isolation)
- [Configuration](#configuration)
- [Extending the Application](#extending-the-application)

---

## Features

- **Multiple isolated instances** — each instance is a fully independent workspace
- **Auto-discovery** — any folder in `/instances` with a `settings.json` or `metadata.json` is detected automatically
- **Dual-language support** — run Python (`main.py`) and JavaScript (`main.js`) side by side
- **Hybrid instances** — if both entry files exist, choose the runtime per execution
- **Real-time UI** — file system watcher pushes changes to all connected clients via WebSocket
- **Auto-repair** — missing subfolders and config files are regenerated on startup
- **Execution history** — every run is logged with stdout, stderr, exit code, and duration
- **File management** — upload, list, and delete files scoped to each instance
- **Search & sort** — filter instances by name, description, or tags; sort by name, creation date, or last used
- **Persistent state** — the last active instance is remembered across restarts

---

## Project Structure

```
project/
├── app.py                  # Flask application — routes, SocketIO, execution logic
├── bootstrap.py            # Instance discovery, validation, repair, and initialization
├── requirements.txt        # Python dependencies
├── last_instance.txt       # Persists the last active instance ID (auto-generated)
├── templates/
│   └── index.html          # Single-page WebUI
├── static/
│   ├── css/
│   │   └── style.css       # UI styles
│   └── js/
│       └── app.js          # Client-side logic, API calls, real-time updates
├── instances/              # Auto-created on first run
│   ├── Default/            # Default instance (created automatically)
│   │   ├── main.py         # Sample Python entry point
│   │   ├── main.js         # Sample JavaScript entry point
│   │   ├── files/          # Uploaded files
│   │   ├── logs/           # Per-execution log files
│   │   ├── history/        # Execution history (JSON)
│   │   ├── settings.json   # Instance settings
│   │   └── metadata.json   # Instance metadata
│   └── ...                 # Additional instances
├── uploads/                # Global temporary upload staging
├── logs/                   # Global application logs
├── history/                # Global history staging
└── temp/                   # Temporary files
```

---

## Requirements

- Python 3.8+
- Node.js (for JavaScript execution)
- pip

---

## Installation

```bash
# Clone or download the project
git clone https://github.com/CreeperRick/Multi-Runtime-Instance
cd Multi-Runtime-Instance

# Install Python dependencies
pip install setuptools --upgrade --break-system-packages
pip install gevent gevent-websocket --break-system-packages
pip install -r requirements.txt
```

**`requirements.txt`**

```
Flask==2.3.3
flask-socketio==5.3.4
python-socketio==5.9.0
gevent==23.9.1
gevent-websocket==0.10.1
watchdog==3.0.0
ptyprocess==0.7.0
```

---

## Running the Application

```bash
python app.py
```

Then open your browser to:

```
http://localhost:5000
```

On first launch, the application will automatically:

1. Create all required global directories
2. Scan the `/instances` folder
3. Repair any incomplete instances
4. Create a `Default` instance with sample `main.py` and `main.js` files
5. Load the last active instance (if any)

---

## How It Works

### Bootstrap Process

`bootstrap.py` runs at startup and handles everything before the server accepts requests:

1. Create global directories (`instances/`, `uploads/`, `logs/`, `history/`, `temp/`)
2. Scan `/instances` for valid instance folders
3. Validate and repair each instance (create missing subfolders, regenerate `metadata.json` / `settings.json`)
4. Create the `Default` instance if no instances exist
5. Return the full instance registry and last active instance ID to `app.py`

### Real-Time Directory Monitoring

The application uses **Watchdog** to monitor the `/instances` directory. Any external change — creating a folder, deleting an instance, adding files — triggers a registry refresh and broadcasts an `instances_changed` event to all connected WebUI clients.

---

## Instance Management

### Creating an Instance

Click **+ New** in the sidebar, enter a name, optional description, and tags. The server creates the folder, generates `metadata.json` and `settings.json`, and broadcasts the update.

### Auto-Discovery

Any folder placed manually inside `/instances` that contains either `settings.json` or `metadata.json` is automatically discovered on the next scan — no configuration required.

### Duplicate, Rename, Delete

Available from the instance workspace header. Deleting an instance removes all its files, logs, and history permanently. If the active instance is deleted, the UI switches to the next available instance.

### Persistent Selection

The active instance ID is written to `last_instance.txt`. On restart, the application restores this selection automatically.

---

## Runtime Detection

On instance load, the application scans the instance folder for entry files:

| Files present         | Detected runtime |
|-----------------------|------------------|
| `main.py` only        | `python`         |
| `main.js` only        | `javascript`     |
| Both `main.py` + `main.js` | `hybrid`    |
| Neither               | `none`           |

The detected runtime is stored in `metadata.json` and displayed as a badge in the UI. For hybrid instances, the user can select the runtime per execution. If no selection is made, Python is used by default.

A runtime override can also be set permanently in the **Settings** tab, which takes precedence over auto-detection.

---

## Execution

Click **▶ Run** in the Run tab. The server:

1. Resolves the runtime (request override → settings override → auto-detected)
2. Checks that the entry file (`main.py` or `main.js`) exists
3. Runs the process in the instance directory with a configurable timeout
4. Captures stdout, stderr, exit code, and duration
5. Writes a timestamped log file to `instance/logs/`
6. Appends an entry to `instance/history/history.json` (capped at 100 entries)
7. Updates `last_used` and `total_executions` in `metadata.json`
8. Returns the result to the UI

**Python execution:**
```bash
python main.py
```

**JavaScript execution:**
```bash
node main.js
```

Both commands run with the instance folder as the working directory.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/instances` | List all instances |
| `POST` | `/api/instances/create` | Create a new instance |
| `DELETE` | `/api/instances/<id>` | Delete an instance |
| `PUT` | `/api/instances/<id>/rename` | Rename an instance |
| `POST` | `/api/instances/<id>/duplicate` | Duplicate an instance |
| `POST` | `/api/instances/switch/<id>` | Set the active instance |
| `GET` | `/api/instances/<id>/files` | List files in an instance |
| `POST` | `/api/instances/<id>/upload` | Upload a file to an instance |
| `DELETE` | `/api/instances/<id>/files/<filename>` | Delete a file |
| `POST` | `/api/instances/<id>/run` | Execute `main.py` or `main.js` |
| `GET` | `/api/instances/<id>/logs` | List execution log files |
| `GET` | `/api/instances/<id>/logs/<logfile>` | Get log file content |
| `GET` | `/api/instances/<id>/history` | Get execution history |
| `GET` | `/api/instances/<id>/settings` | Get instance settings |
| `PUT` | `/api/instances/<id>/settings` | Update instance settings |
| `GET` | `/api/instances/search?q=<query>` | Search instances |
| `GET` | `/api/instances/sort?by=<field>` | Sort instances |

### Run Request Body

```json
{
  "runtime": "python"
}
```

`runtime` is optional. Omit it for auto-detection.

### Settings Body (PUT)

```json
{
  "description": "My project description",
  "tags": ["web", "demo"],
  "runtime_override": "python",
  "execution_timeout": 30,
  "auto_save_logs": true
}
```

---

## WebSocket Events

The server uses **Socket.IO** to push updates to connected clients.

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `instances_changed` | Server → Client | `{ instances: [...] }` | Instance list has changed |
| `active_instance_changed` | Server → Client | `{ instance_id: "..." }` | Active instance switched |

---

## Instance File Structure

```
instances/
└── MyInstance/
    ├── main.py             # Python entry point (optional)
    ├── main.js             # JavaScript entry point (optional)
    ├── files/              # User-uploaded files
    ├── logs/
    │   └── execution_20250101_120000.log
    ├── history/
    │   └── history.json
    ├── settings.json
    └── metadata.json
```

### `metadata.json`

```json
{
  "instance_id": "uuid-v4",
  "name": "MyInstance",
  "creation_date": "2025-01-01T12:00:00",
  "last_used": "2025-01-02T15:30:00",
  "description": "Optional description",
  "tags": ["python", "demo"],
  "detected_runtime": "python",
  "total_files": 3,
  "total_executions": 12
}
```

### `settings.json`

```json
{
  "runtime_override": null,
  "execution_timeout": 30,
  "auto_save_logs": true
}
```

---

## Security & Isolation

- **Path sanitization** — all file operations validate paths stay within the instance directory
- **No cross-instance access** — files, logs, and history are scoped strictly per instance
- **No shell injection** — `subprocess.run` is called with a list of arguments, never `shell=True`
- **Filename sanitization** — uploaded filenames are cleaned with `werkzeug.utils.secure_filename`
- **Log path traversal prevention** — log file routes check for `..` before serving content

---

## Configuration

All per-instance configuration lives in `settings.json` inside the instance folder.

| Setting | Default | Description |
|---------|---------|-------------|
| `runtime_override` | `null` | Force a specific runtime (`"python"` or `"javascript"`). `null` = auto-detect. |
| `execution_timeout` | `30` | Maximum execution time in seconds before the process is killed. |
| `auto_save_logs` | `true` | Whether to write a log file after each execution. |

Global application settings (port, secret key, max upload size) are configured directly in `app.py`.

---

## Extending the Application

**Add authentication**
Wrap routes with a Flask login decorator (e.g. Flask-Login) and add a user session layer.

**Add more runtimes**
Extend `_detect_runtime()` in `bootstrap.py` to check for additional entry files (e.g. `main.go`, `main.rb`) and add the corresponding command in the `/run` route.

**Long-running scripts**
Replace the synchronous `subprocess.run` call with a Celery task queue backed by Redis, and stream output back over WebSocket.

**Docker isolation**
Run each execution inside a Docker container rather than directly on the host for stronger sandboxing.

**Per-user instances**
Add a user ID prefix to the instances directory path and `last_instance.txt` to support multi-user deployments.

---

## License

MIT
