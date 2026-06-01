// Global state
let instances = [];
let currentInstance = null;
let socket = io();

// DOM elements
const instanceListEl = document.getElementById('instanceList');
const searchInput = document.getElementById('searchInstances');
const sortSelect = document.getElementById('sortInstances');
const noInstanceDiv = document.getElementById('noInstanceSelected');
const workspaceDiv = document.getElementById('instanceWorkspace');
const instanceNameH1 = document.getElementById('instanceName');
const runtimeBadge = document.getElementById('runtimeBadge');
const fileCountSpan = document.getElementById('fileCount');
const execCountSpan = document.getElementById('execCount');
const fileListDiv = document.getElementById('fileList');
const runBtn = document.getElementById('runBtn');
const runtimeSelect = document.getElementById('runtimeSelect');
const outputPre = document.getElementById('outputContent');
const logListDiv = document.getElementById('logList');
const historyListDiv = document.getElementById('historyList');
const instanceDescription = document.getElementById('instanceDescription');
const instanceTags = document.getElementById('instanceTags');
const runtimeOverride = document.getElementById('runtimeOverride');
const executionTimeout = document.getElementById('executionTimeout');
const saveSettingsBtn = document.getElementById('saveSettingsBtn');

// File upload elements
const uploadBtn = document.getElementById('uploadBtn');
const fileUpload = document.getElementById('fileUpload');

// Modal elements
const modal = document.getElementById('modal');
const modalTitle = document.getElementById('modalTitle');
const modalInput = document.getElementById('modalInput');
const modalDescription = document.getElementById('modalDescription');
const modalTags = document.getElementById('modalTags');
const modalConfirm = document.getElementById('modalConfirm');
const closeModal = document.querySelector('.close');

let modalAction = null;
let renameInstanceId = null;

// Fetch instances
async function fetchInstances() {
    try {
        const res = await fetch('/api/instances');
        instances = await res.json();
        renderInstanceList();
        if (currentInstance) {
            const stillExists = instances.find(i => i.instance_id === currentInstance.instance_id);
            if (!stillExists) {
                currentInstance = null;
                showNoInstance();
            } else {
                await loadInstance(currentInstance.instance_id);
            }
        }
    } catch (err) {
        console.error('Failed to fetch instances:', err);
    }
}

// Render sidebar
function renderInstanceList() {
    let filtered = [...instances];
    const query = searchInput.value.toLowerCase();
    if (query) {
        filtered = filtered.filter(inst => 
            inst.name.toLowerCase().includes(query) ||
            (inst.description && inst.description.toLowerCase().includes(query)) ||
            (inst.tags && inst.tags.some(tag => tag.toLowerCase().includes(query)))
        );
    }
    const sortBy = sortSelect.value;
    if (sortBy === 'name') filtered.sort((a,b) => a.name.localeCompare(b.name));
    else if (sortBy === 'creation_date') filtered.sort((a,b) => (b.creation_date || '').localeCompare(a.creation_date || ''));
    else if (sortBy === 'last_used') filtered.sort((a,b) => (b.last_used || '').localeCompare(a.last_used || ''));

    instanceListEl.innerHTML = filtered.map(inst => `
        <div class="instance-card ${currentInstance && currentInstance.instance_id === inst.instance_id ? 'active' : ''}" data-id="${inst.instance_id}">
            <div class="instance-name">
                <span>${escapeHtml(inst.name)}</span>
                <span class="instance-runtime">${inst.detected_runtime || 'none'}</span>
            </div>
            <div class="instance-stats">
                Files: ${inst.total_files || 0} | Execs: ${inst.total_executions || 0}
            </div>
            <div class="instance-stats">
                Last used: ${inst.last_used ? new Date(inst.last_used).toLocaleString() : 'never'}
            </div>
        </div>
    `).join('');

    document.querySelectorAll('.instance-card').forEach(card => {
        card.addEventListener('click', () => {
            const id = card.dataset.id;
            const inst = instances.find(i => i.instance_id === id);
            if (inst) switchInstance(inst);
        });
    });
}

async function switchInstance(instance) {
    try {
        const res = await fetch(`/api/instances/switch/${instance.instance_id}`, { method: 'POST' });
        if (res.ok) {
            await loadInstance(instance.instance_id);
            renderInstanceList();
        } else {
            alert('Failed to switch instance');
        }
    } catch (err) {
        console.error(err);
    }
}

async function loadInstance(instanceId) {
    const inst = instances.find(i => i.instance_id === instanceId);
    if (!inst) return;
    currentInstance = inst;
    noInstanceDiv.style.display = 'none';
    workspaceDiv.style.display = 'block';
    
    instanceNameH1.textContent = inst.name;
    runtimeBadge.textContent = inst.detected_runtime || 'none';
    runtimeBadge.className = `badge ${inst.detected_runtime || 'none'}`;
    fileCountSpan.textContent = inst.total_files || 0;
    execCountSpan.textContent = inst.total_executions || 0;
    
    await loadFiles();
    await loadLogs();
    await loadHistory();
    await loadSettings();
    
    if (inst.detected_runtime === 'hybrid') {
        runtimeSelect.disabled = false;
        runtimeSelect.value = 'auto';
    } else if (inst.detected_runtime === 'python') {
        runtimeSelect.disabled = false;
        runtimeSelect.value = 'python';
    } else if (inst.detected_runtime === 'javascript') {
        runtimeSelect.disabled = false;
        runtimeSelect.value = 'javascript';
    } else {
        runtimeSelect.disabled = true;
        runtimeSelect.value = 'auto';
    }
}

async function loadFiles() {
    if (!currentInstance) return;
    const res = await fetch(`/api/instances/${currentInstance.instance_id}/files`);
    const files = await res.json();
    fileListDiv.innerHTML = files.map(file => `
        <div class="file-item">
            <span class="file-name" data-filename="${file.name}">📄 ${file.name}</span>
            <span>${(file.size / 1024).toFixed(2)} KB</span>
            <button class="delete-file" data-filename="${file.name}">Delete</button>
        </div>
    `).join('');
    document.querySelectorAll('.delete-file').forEach(btn => {
        btn.addEventListener('click', async () => {
            const filename = btn.dataset.filename;
            if (confirm(`Delete ${filename}?`)) {
                await fetch(`/api/instances/${currentInstance.instance_id}/files/${filename}`, { method: 'DELETE' });
                loadFiles();
                fetchInstances();
            }
        });
    });
}

async function loadLogs() {
    if (!currentInstance) return;
    const res = await fetch(`/api/instances/${currentInstance.instance_id}/logs`);
    const logs = await res.json();
    logListDiv.innerHTML = logs.map(log => `
        <div class="log-item">
            <span class="log-name" data-log="${log.name}">📋 ${log.name}</span>
            <span>${new Date(log.modified).toLocaleString()}</span>
            <span>${(log.size / 1024).toFixed(2)} KB</span>
        </div>
    `).join('');
    document.querySelectorAll('.log-name').forEach(span => {
        span.addEventListener('click', async () => {
            const logfile = span.dataset.log;
            const res = await fetch(`/api/instances/${currentInstance.instance_id}/logs/${logfile}`);
            const content = await res.text();
            document.getElementById('logContent').textContent = content;
            document.getElementById('logViewer').style.display = 'block';
        });
    });
}

async function loadHistory() {
    if (!currentInstance) return;
    const res = await fetch(`/api/instances/${currentInstance.instance_id}/history`);
    const history = await res.json();
    historyListDiv.innerHTML = history.map(entry => `
        <div class="history-item">
            <div><strong>${new Date(entry.timestamp).toLocaleString()}</strong> - ${entry.runtime} - Exit: ${entry.exit_code}</div>
            <div>Duration: ${entry.duration_ms.toFixed(2)} ms</div>
            <details><summary>Output</summary><pre>${escapeHtml(entry.stdout || '')}</pre></details>
        </div>
    `).join('');
}

async function loadSettings() {
    if (!currentInstance) return;
    const res = await fetch(`/api/instances/${currentInstance.instance_id}/settings`);
    if (res.ok) {
        const settings = await res.json();
        instanceDescription.value = currentInstance.description || '';
        instanceTags.value = (currentInstance.tags || []).join(', ');
        runtimeOverride.value = settings.runtime_override || '';
        executionTimeout.value = settings.execution_timeout || 30;
    }
}

saveSettingsBtn.addEventListener('click', async () => {
    if (!currentInstance) return;
    const payload = {
        description: instanceDescription.value,
        tags: instanceTags.value.split(',').map(t => t.trim()).filter(t => t),
        runtime_override: runtimeOverride.value || null,
        execution_timeout: parseInt(executionTimeout.value, 10)
    };
    await fetch(`/api/instances/${currentInstance.instance_id}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    currentInstance.description = payload.description;
    currentInstance.tags = payload.tags;
    fetchInstances();
    alert('Settings saved');
});

runBtn.addEventListener('click', async () => {
    if (!currentInstance) return;
    const runtime = runtimeSelect.value === 'auto' ? null : runtimeSelect.value;
    outputPre.textContent = 'Running...';
    try {
        const res = await fetch(`/api/instances/${currentInstance.instance_id}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ runtime })
        });
        const data = await res.json();
        if (res.ok) {
            outputPre.textContent = `[Exit code: ${data.exit_code}, Duration: ${data.duration_ms.toFixed(2)} ms]\n\nSTDOUT:\n${data.stdout}\n\nSTDERR:\n${data.stderr}`;
            loadHistory();
            loadLogs();
            fetchInstances();
        } else {
            outputPre.textContent = `Error: ${data.error}`;
        }
    } catch (err) {
        outputPre.textContent = `Exception: ${err.message}`;
    }
});

// File upload
if (uploadBtn && fileUpload) {
    uploadBtn.addEventListener('click', () => fileUpload.click());
    fileUpload.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file || !currentInstance) return;
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch(`/api/instances/${currentInstance.instance_id}/upload`, {
                method: 'POST',
                body: formData
            });
            if (res.ok) {
                await loadFiles();
                await fetchInstances();
            } else {
                alert('Upload failed');
            }
        } catch (err) {
            console.error(err);
            alert('Upload error');
        }
        fileUpload.value = '';
    });
}

// Create instance
document.getElementById('createInstanceBtn').addEventListener('click', () => {
    modalTitle.textContent = 'Create New Instance';
    modalInput.value = '';
    modalDescription.value = '';
    modalTags.value = '';
    modalAction = 'create';
    modal.style.display = 'block';
});

modalConfirm.addEventListener('click', async () => {
    const name = modalInput.value.trim();
    if (!name) return alert('Name required');
    const description = modalDescription.value;
    const tags = modalTags.value.split(',').map(t => t.trim()).filter(t => t);
    if (modalAction === 'create') {
        await fetch('/api/instances/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description, tags })
        });
        await fetchInstances();
    } else if (modalAction === 'rename' && renameInstanceId) {
        await fetch(`/api/instances/${renameInstanceId}/rename`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        await fetchInstances();
        if (currentInstance && currentInstance.instance_id === renameInstanceId) {
            await loadInstance(renameInstanceId);
        }
    }
    modal.style.display = 'none';
    modalDescription.style.display = 'block';
    modalTags.style.display = 'block';
});

document.getElementById('renameInstanceBtn').addEventListener('click', () => {
    if (!currentInstance) return;
    modalTitle.textContent = 'Rename Instance';
    modalInput.value = currentInstance.name;
    modalDescription.style.display = 'none';
    modalTags.style.display = 'none';
    modalAction = 'rename';
    renameInstanceId = currentInstance.instance_id;
    modal.style.display = 'block';
});

document.getElementById('duplicateInstanceBtn').addEventListener('click', async () => {
    if (!currentInstance) return;
    if (confirm(`Duplicate "${currentInstance.name}"?`)) {
        await fetch(`/api/instances/${currentInstance.instance_id}/duplicate`, { method: 'POST' });
        await fetchInstances();
    }
});

document.getElementById('deleteInstanceBtn').addEventListener('click', async () => {
    if (!currentInstance) return;
    if (confirm(`Delete instance "${currentInstance.name}"? This cannot be undone.`)) {
        await fetch(`/api/instances/${currentInstance.instance_id}`, { method: 'DELETE' });
        currentInstance = null;
        await fetchInstances();
        showNoInstance();
    }
});

function showNoInstance() {
    noInstanceDiv.style.display = 'block';
    workspaceDiv.style.display = 'none';
    currentInstance = null;
}

searchInput.addEventListener('input', () => renderInstanceList());
sortSelect.addEventListener('change', () => renderInstanceList());

// Tab switching
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const tabId = btn.dataset.tab;
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
        document.getElementById(`${tabId}Tab`).classList.add('active');
        if (tabId === 'terminal' && !terminalInitialized) {
            setTimeout(initTerminal, 100);
        } else if (tabId === 'terminal' && term && fitAddon) {
            setTimeout(() => {
                fitAddon.fit();
                socket.emit('terminal_resize', { rows: term.rows, cols: term.cols });
                term.focus();
            }, 100);
        }
    });
});

socket.on('instances_changed', () => fetchInstances());
socket.on('active_instance_changed', (data) => {
    if (data.instance_id && (!currentInstance || currentInstance.instance_id !== data.instance_id)) {
        const inst = instances.find(i => i.instance_id === data.instance_id);
        if (inst) switchInstance(inst);
    }
});

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>]/g, (m) => {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        return m;
    });
}

// ==================== TERMINAL (ROOT) ====================
let term = null;
let fitAddon = null;
let terminalInitialized = false;

function initTerminal() {
    if (terminalInitialized) {
        console.log("Terminal already initialized");
        return;
    }
    if (typeof Terminal === 'undefined') {
        console.warn('xterm.js not loaded – retrying in 500ms');
        setTimeout(initTerminal, 500);
        return;
    }
    const container = document.getElementById('terminal-container');
    if (!container) {
        console.error("Terminal container not found!");
        return;
    }
    console.log("Creating xterm.js terminal...");
    term = new Terminal({
        cursorBlink: true,
        theme: { background: '#000000', foreground: '#00ff00' },
        fontSize: 14,
        convertEol: true
    });
    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(container);
    fitAddon.fit();
    
    // Write a test line to confirm terminal works
    term.write("Initializing terminal...\r\n");
    
    term.onData((data) => {
        console.log("Sending input:", JSON.stringify(data));
        socket.emit('terminal_input', { data: data });
    });
    
    socket.on('terminal_output', (msg) => {
        console.log("Received output, length:", msg.data.length);
        if (term) {
            term.write(msg.data);
        }
    });
    
    socket.on('terminal_ready', () => {
        console.log("Terminal ready event received");
        term.write('\r\n\x1b[32m*** Root terminal ready ***\x1b[0m\r\n');
        term.write('\x1b[1;32m# \x1b[0m');  // root prompt
        setTimeout(() => {
            term.focus();
            console.log("Terminal focused");
        }, 200);
    });
    
    socket.on('terminal_error', (msg) => {
        console.error("Terminal error:", msg);
        term.write(`\r\n\x1b[31mError: ${msg.message}\x1b[0m\r\n`);
    });
    
    socket.emit('terminal_start');
    
    window.addEventListener('resize', () => {
        if (fitAddon && term && document.getElementById('terminalTab').classList.contains('active')) {
            fitAddon.fit();
            socket.emit('terminal_resize', { rows: term.rows, cols: term.cols });
        }
    });
    
    terminalInitialized = true;
}

fetchInstances();
