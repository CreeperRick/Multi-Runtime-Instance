// Global state
let instances = [];
let currentInstance = null;
let socket = io();

// DOM elements
const instanceListEl = document.getElementById('instanceList');
const searchInput = document document.getElementById('searchInstances');
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

let modalAction = null; // 'create' or 'rename'
let renameInstanceId = null;

// Helper: Fetch instances from API
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

    // Attach click handlers
    document.querySelectorAll('.instance-card').forEach(card => {
        card.addEventListener('click', (e) => {
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
            renderInstanceList(); // refresh active highlight
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
    
    // Load files
    await loadFiles();
    // Load logs
    await loadLogs();
    // Load history
    await loadHistory();
    // Load settings
    await loadSettings();
    
    // Setup runtime selector based on detected runtime
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
    // Attach delete handlers
    document.querySelectorAll('.delete-file').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const filename = btn.dataset.filename;
            if (confirm(`Delete ${filename}?`)) {
                await fetch(`/api/instances/${currentInstance.instance_id}/files/${filename}`, { method: 'DELETE' });
                loadFiles();
                fetchInstances(); // refresh counts
            }
        });
    });
    // Attach view handlers
    document.querySelectorAll('.file-name').forEach(span => {
        span.addEventListener('click', () => {
            alert('File content preview not implemented. Download via /api/instances/.../files/...');
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

// Save settings
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
    // Update current instance metadata
    currentInstance.description = payload.description;
    currentInstance.tags = payload.tags;
    fetchInstances();
    alert('Settings saved');
});

// Run code
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

// ==================== FILE UPLOAD HANDLER ====================
if (uploadBtn && fileUpload) {
    uploadBtn.addEventListener('click', () => {
        fileUpload.click();
    });

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

// ==================== INSTANCE CRUD MODALS ====================
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
            body: 'application/json' },
            body: JSON.stringify({ name, description, tags JSON.stringify({ name, description, tags })
        });
        await fetchInstances })
        });
       ();
    } else await fetchInstances();
    } else if (modalAction if (modalAction === 'rename' === 'rename' && && renameInstanceId renameInstanceId) {
        await) {
        await fetch(`/api fetch(`/api/instances/${/instances/${renameInstanceId}/rename`, {
           renameInstanceId}/ method: 'PUTrename`, {
           ',
            headers: method: 'PUT',
            headers: { 'Content-Type { 'Content-Type': 'application': 'application/json/json' },
            body' },
            body:: JSON.stringify({ JSON.stringify({ name })
        });
        await fetchInst name })
        });
        await fetchInstances();
        ifances();
        if (currentInstance && (currentInstance && currentInstance.instance_id currentInstance.instance_id === renameInstanceId === renameInstanceId) {
            await) {
            await loadInstance( loadInstance(renameInstanceId);
        }
renameInstanceId);
        }
       }
    modal }
   .style.display = 'none';
    modalDescription.style.display modal.style.display = 'none';
    modalDescription.style = 'block';
   .display = 'block';
    modalTags.style.display modalTags.style.display = 'block = 'block';
});

document.getElementById('renameInstance';
});

document.getElementById('renameInstanceBtn').Btn').addEventListener('clickaddEventListener('click', () =>', () => {
    if (!currentInstance) return {
    if (!currentInstance) return;
    modalTitle.textContent = 'R;
    modalTitle.textContent = 'Rename Instance';
   ename Instance';
    modalInput.value = modalInput.value = currentInstance.name currentInstance.name;
    modalDescription.style.display = 'none;
    modalDescription.style.display = 'none';
    modalTags';
    modalTags.style.display = '.style.display = 'none';
none';
    modalAction = 'rename    modalAction = 'rename';
    renameInstance';
    renameInstanceId = currentInstance.instance_id;
    modal.style.displayId = currentInstance =.instance_id;
    modal.style.display = 'block';
 'block';
});

document.getElementById('du});

document.getElementById('duplicateInstanceBtn').addplicateInstanceBtn').addEventListener('click', async () =>EventListener('click', async () => {
    if (!currentInstance) return {
    if (!currentInstance) return;
    if (confirm(`;
    if (confirm(`Duplicate "${Duplicate "${currentInstance.name}"?`))currentInstance.name}" {
        await fetch(`/?`)) {
        await fetch(`/api/api/instances/${currentInstanceinstances/${currentInstance.instance_id}/du.instance_id}/duplicate`, { methodplicate`, { method: 'POST': 'POST' });
        await });
        await fetchInstances();
    fetchInstances();
    }
});

document.getElementById }
});

document.getElementById('deleteInstanceBtn').add('deleteInstanceBtnEventListener('click', async').addEventListener(' ()click', async () => {
    if => {
    if (!currentInstance) return;
 (!currentInstance) return;
    if (confirm(`Delete instance "${currentInstance.name}"? This    if (confirm(`Delete instance "${currentInstance.name}"? This cannot be undone. cannot be undone.`)) {
`)) {
        await fetch(`/api/instances        await fetch(`//${currentInstance.instanceapi/instances/${currentInstance.instance_id}`, {_id}`, { method: 'DELETE' });
        current method: 'DELETE' });
        currentInstance = nullInstance = null;
        await fetchInst;
        await fetchInstancesances();
        show();
        showNoInstance();
    }
});

function showNoInstance();
    }
});

function showNoInstance()NoInstance() {
    noInstanceDiv {
    noInstanceDiv.style.display = '.style.display = 'block';
block';
    workspace    workspaceDiv.style.display =Div.style.display = 'none';
    'none';
    currentInstance = null;
}

// Search currentInstance = null;
}

// Search and sort and sort
searchInput.addEventListener('input',
searchInput.addEventListener('input', () => () => renderInstanceList renderInstanceList());
sortSelect.addEventListener('());
sortSelect.addEventListener('change', () =>change', () => renderInstanceList());

// renderInstanceList());

// Tab Tab switching switching
document.querySelectorAll('.tab-btn').forEach
document.querySelectorAll('.tab-btn').forEach(btn =>(btn => {
    btn.addEventListener('click', () => {
    btn.addEventListener('click', () => {
        const tab {
        const tabId = btn.datId = btn.dataset.tabaset.tab;
       ;
        document.querySelectorAll('.tab-btn'). document.querySelectorAll('.tab-btn').forEach(b => bforEach(b => b.classList.remove('active.classList.remove('active'));
        btn.classList.add('active'));
        btn.classList.add');
('active');
        document.querySelectorAll('.tab-content').        document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('forEach(tc =>active'));
        document tc.classList.remove('active'));
        document.getElementById(`${tabId.getElementById(`${tabId}Tab`).}Tab`).classList.addclassList.add('('active');
        
       active');
        
        // If terminal // If terminal tab is opened tab is opened and and terminal terminal not initialized, init not initialized, init it
        if it
        if (tabId === (tabId === 'terminal' && 'terminal' && !terminalInitialized) {
            !terminalInitialized setTimeout(initTerminal, 100) {
            setTimeout(initTerm);
        }inal, 100);
        else if (tab } else if (tabId === 'terminalId === 'terminal' && term &&' && term && fitAddon) fitAddon) {
            {
            setTimeout(() setTimeout(() => {
                fit => {
                fitAddon.fitAddon.fit();
                socket.emit('terminal_resize', { rows:();
                socket.emit('terminal_resize', { rows: term.rows, term.rows, cols: term.col cols: term.cols });
            },s });
            }, 100);
        100);
        }
    });
 }
    });
});

// Socket events
});

// Socket events
socket.on('instsocket.on('instances_changed',ances_changed', (data) (data) => => {
    fetchInst {
    fetchInstances();
});

socketances();
});

socket.on('active_instance.on('active_instance_changed', (data) =>_changed', (data) => {
    if (data {
    if (data.instance.instance_id && (!_idcurrentInstance || currentInstance && (!currentInstance || currentInstance.instance_id !==.instance_id !== data.instance_id)) data.instance_id)) {
        const inst {
        const inst = instances.find(i => i.instance_id = instances.find(i => i.instance_id === data === data.instance_id);
       .instance_id);
        if ( if (inst) switchInstanceinst) switchInstance(inst);
   (inst);
    }
});

// Helper }
});

// Helper: escape HTML: escape HTML
function escapeHtml(str) {
    if
function escapeHtml(str) {
    if (!str (!str) return '';
    return str.replace(/[) return '';
    return str.replace(/[&<>]/g,&<>]/g, function(m) function(m) {
        if (m === '&') {
        if (m === '&') return '&amp return '&amp;';
        if;';
        if (m === '< (m === '<') return '&') return '&lt;';
       lt;';
        if (m === if (m === '>') return '>') return '&gt;';
        return m '&gt;';
        return m;
    });
;
    });
}

// ====================}

// ==================== TERMINAL TERMINAL ( (ROOT) =ROOT) ====================
let===================
let term = null term = null;
let fitAddon;
let fitAddon = null;
let = null;
let terminalInitialized = false;

function init terminalInitialized = false;

function initTerminal()Terminal() {
    if (terminal {
    if (terminalInitialized) returnInitialized) return;
    if (typeof Terminal === 'undefined') {
;
    if (typeof Terminal === 'undefined') {
               console.warn(' console.warn('xterm.js notxterm.js not loaded yet, retrying...');
        setTimeout(initTerm loaded yet, retrying...');
        setTimeout(initTerminalinal, 200);
        return;
    }
    const container = document.getElementById, 200);
        return;
    }
    const container = document.getElementById('terminal-container('terminal-container');
    if (!container');
    if (!container) return;
    
    term) return;
    
    term = new Terminal({
        cursor = new Terminal({
        cursorBlink: trueBlink: true,
        theme: {
            background:,
        theme: {
            background: '#000000 '#000000',
            foreground:',
            foreground: '# '#00ff00'
00ff00'
        }
    });
    fitAddon        }
    });
    fitAddon = new FitAdd = new FitAddon.FitAddon.FitAddon();
    termon();
    term.loadAddon(f.loadAddon(fitAddon);
    termitAddon);
    term.open(.open(container);
    fitcontainer);
    fitAddon.fitAddon.fit();
    
    term.on();
    
    term.onData((data)Data((data) => {
        socket => {
        socket.emit('.emit('terminal_input', { dataterminal_input', { data: data });
    });
: data });
    });
    
    socket    
    socket.on('terminal_output.on('terminal_output', (msg) => {
        if', (msg) => {
        if (term) term (term) term.write(msg.write(msg.data.data);
    });
    
    socket.on('terminal_ready', ());
    });
    
    socket.on('terminal => {
        term_ready', () => {
        term.write('\r\n.write('\r\n\x1b[32m*** Root\x1b[ terminal ready ***32m*** Root terminal ready ***\x1b\x1b[0m\r\n');
        term.write('\x1[0m\r\n');
        term.write('\x1b[1;b[1;32m$ \32m$ \x1b[x1b[0m0m');
    });
    
    socket.on('terminal_error');
    });
    
    socket.on('terminal_error', (msg', (msg) => {
        term) => {
        term.write(`\r.write(`\r\n\x1b\n\x1b[31mError: ${[31mError: ${msg.message}\x1bmsg.message}\x1b[0m\r\n`);
    });
    
    socket.emit('[0m\r\n`);
    });
    
    socket.emit('terminal_start');
    
    windowterminal_start.addEventListener('resize');
    
    window.addEventListener('resize', () =>', () => {
        if (fitAddon && {
        if (fitAddon && term term && document.getElementById(' && document.getElementById('terminalTab').classterminalTab').classList.contains('activeList.contains('active')) {
')) {
            fit            fitAddon.fitAddon.fit();
            socket.emit('terminal_resize();
            socket.emit('terminal_resize', {', { rows rows: term.rows: term.rows, cols: term.cols });
       , cols: term.cols });
 }
    });
        }
    });
    
    terminalInitialized    
    terminalInitialized = true;
 = true;
}

// Start}

// Start
fetchInstances
fetchInstances();
