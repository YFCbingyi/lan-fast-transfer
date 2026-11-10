import os
import time
import uuid
import atexit
import shutil
import hashlib
import ipaddress
from urllib.parse import quote

import gevent
from flask import Flask, request, send_from_directory, render_template_string, Response
from flask_socketio import SocketIO
import engineio.async_drivers.gevent

from app.config import load_config, DEFAULT_DOWNLOAD_FOLDER
from app.signal import signal_emitter
from app.ui.theme import apply_phone_tokens

config = load_config()

UPLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "LanChatUploads")
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

DOWNLOAD_FOLDER = config.get('download_path', DEFAULT_DOWNLOAD_FOLDER)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

app = Flask(__name__, static_folder=None)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = os.urandom(24).hex()
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 4MB 分片 + multipart 开销，防止无限写盘

# 放宽心跳参数：手机浏览器切后台时页面被冻结无法及时回应 ping，
# ping_timeout=60 可大幅减少"切后台即断开"的误判
socketio = SocketIO(app, async_mode='gevent',
                    ping_interval=25, ping_timeout=60)

temp_downloads = {}
phone_uploads = {}
phone_sids = set()                 # 当前在线手机 sid
phone_device_ids = {}             # sid -> 稳定设备 ID（浏览器 localStorage）
device_id_sids = {}               # 稳定设备 ID -> 当前 sid
pc_sids = {}                      # sid -> {'name', 'ip'}
client_ips = {}                   # sid -> 握手来源 IP
_temp_zip_files = set()

RUNTIME_PORT = 5000               # 实际监听端口（被占用时自动顺延）
SESSION_TTL = 30 * 60             # 未完成上传会话的空闲保留时长
GRACE_SECONDS = 90                # 手机断线宽限期，需覆盖 ping_timeout 与重连耗时


@app.before_request
def _lan_only():
    """只接受局域网来源，不做任何需要用户操作的鉴权。"""
    addr = request.remote_addr or ''
    try:
        ip = ipaddress.ip_address(addr)
        if not (ip.is_private or ip.is_loopback or ip.is_link_local):
            return '仅允许局域网访问', 403
    except ValueError:
        return '无法识别的来源地址', 403

PHONE_PAGE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>局域网文件/消息传输</title>
    <style>/*__PHONE_CSS__*/</style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="brand">
                <span class="brand-mark">__ICON_LOGO__</span>
                <div>
                    <div class="brand-name">局域网传输</div>
                    <div class="brand-sub">本地网络 · 无需互联网</div>
                </div>
            </div>
            <button class="icon-btn icon-about" onclick="showAbout()" aria-label="关于">__ICON_INFO__关于</button>
        </div>
        <div class="messages" id="messages">
            <div class="status">等待连接...</div>
        </div>
        <div class="input-area">
            <input type="text" id="textInput" placeholder="输入文字..." autocomplete="off">
            <button id="sendBtn" onclick="sendText()" style="display:none">发送</button>
            <button id="plusBtn" onclick="togglePopup()" aria-label="添加">__ICON_PLUS__</button>
            <div class="popup-overlay" id="popupOverlay" onclick="hidePopup()"></div>
            <div class="popup-menu" id="popupMenu">
                <button class="popup-item" onclick="document.getElementById('fileInput').click();hidePopup()">__ICON_FILE__发送文件</button>
                <button class="popup-item" onclick="document.getElementById('dirInput').click();hidePopup()">__ICON_FOLDER__发送文件夹</button>
            </div>
            <input type="file" id="dirInput" webkitdirectory style="display:none" onchange="sendDirectory(this.files)">
            <input type="file" id="fileInput" onchange="sendFiles(this.files)" multiple>
        </div>
    </div>

    <div class="about-modal" id="aboutModal">
        <div class="about-content">
            <div class="about-title">__ICON_LOGO_LIGHT__局域网双向传输</div>
            <div class="about-version">版本 v2.0</div>

            <div class="about-section">
                <div class="about-section-title">__ICON_INFO_SECTION__简介</div>
                <div class="about-text">
                    一款简洁高效的局域网文件传输工具，支持电脑与移动设备之间的实时消息和文件互传。
                </div>
            </div>

            <div class="about-section">
                <div class="about-section-title">__ICON_SPARKLE_SECTION__特性</div>
                <div class="about-text">
                    • 本地局域网传输，无需互联网<br>
                    • 支持大文件高速传输<br>
                    • 实时消息和文件互传
                </div>
            </div>

            <div class="about-section">
                <div class="about-section-title">__ICON_SHIELD_SECTION__隐私与安全</div>
                <div class="about-text privacy-box">
                    ✓ 仅在本地局域网内传输数据<br>
                    ✓ 不上传数据到远程服务器<br>
                    ✓ 不收集用户隐私信息<br>
                    ✓ 不监控剪贴板内容
                </div>
            </div>

            <div class="about-section">
                <div class="about-section-title">__ICON_ALERT_SECTION__免责声明</div>
                <div class="about-text disclaimer-box">
                    本软件为个人免费工具，仅供个人非商业用途使用。作者不对使用本软件造成的任何直接或间接损失负责。
                </div>
            </div>

            <button class="about-close" onclick="hideAbout()">关闭</button>
        </div>
    </div>
    <script src="/static/socket.io.min.js"></script>
    <script>
        // 强制 websocket：局域网直连无代理劫持，跳过 polling 握手，延迟更低、重连更快
        const socket = io({ transports: ['websocket'], reconnection: true });
        const messagesDiv = document.getElementById('messages');
        const activeUploads = {}; // upload_id -> 上传会话（断点续传用）
        const CHUNK_SIZE = 4 * 1024 * 1024; // 4MB 分片
        const UPLOAD_PARALLEL = 2;          // 每个文件并行分片数
        const MAX_FILE_PARALLEL = 3;        // 同时上传的文件数上限，避免目录上传压垮服务端

        // 稳定设备 ID：锁屏/切后台/换网络重连后仍是同一台设备，聊天记录不会丢。
        // 隐私模式或 WebView 禁用 localStorage 时退化为会话内 ID，保证页面功能仍可用。
        let deviceId = null;
        try {
            deviceId = localStorage.getItem('lft_device_id');
            if (!deviceId) {
                deviceId = 'p-' + Math.random().toString(36).slice(2) + '-' + Date.now().toString(36);
                localStorage.setItem('lft_device_id', deviceId);
            }
        } catch (e) {
            deviceId = 'p-' + Math.random().toString(36).slice(2) + '-' + Date.now().toString(36);
        }

        socket.on('connect', () => {
            socket.emit('identify', {type: 'phone', device_id: deviceId});
            addStatus('已连接到电脑');
            // 断线重连后，自动恢复所有未完成的上传（断点续传）
            for (const uploadId of Object.keys(activeUploads)) {
                const up = activeUploads[uploadId];
                if (up && up.paused) {
                    addStatus(`🔗 连接恢复，继续上传: ${up.displayName}`);
                    up.paused = false;
                    resumeUpload(uploadId);
                }
            }
        });

        socket.on('disconnect', () => {
            addStatus('连接中断，正在自动重连…');
        });

        socket.on('text_message', (data) => {
            addMessage(data.message, 'remote');
        });

        socket.on('file_download', (data) => {
            let url;
            try {
                url = new URL(data.url || '', location.href);
            } catch (e) {
                return;
            }
            if (url.origin !== location.origin) return;   // 只接受同源下载链接
            const link = document.createElement('a');
            link.className = 'file-link';
            link.href = url.href;
            link.innerHTML = '__ICON_FILE_16__';
            const label = document.createElement('span');
            label.textContent = data.filename || '文件';
            link.appendChild(label);
            link.setAttribute('download', data.filename || '');
            addMessage(link, 'remote');
        });

        socket.on('upload_status', (data) => {
            addStatus(data.msg);
        });

        function addMessage(content, type) {
            const div = document.createElement('div');
            div.className = `msg ${type}`;
            if (content instanceof Node) div.appendChild(content);
            else div.textContent = content == null ? '' : String(content);
            messagesDiv.appendChild(div);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }

        function addStatus(text) {
            const div = document.createElement('div');
            div.className = 'status';
            div.textContent = text;
            messagesDiv.appendChild(div);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }

        function sendText() {
            const input = document.getElementById('textInput');
            const text = input.value.trim();
            if (!text) return;
            socket.emit('text_message', { message: text });
            addMessage(text, 'local');
            input.value = '';
            input.dispatchEvent(new Event('input'));
        }

        // 全局队列：一次最多 3 个文件同时上传，选整个目录也不会瞬间打出上千请求
        const fileQueue = [];
        let activeFiles = 0;

        function enqueueFile(file, displayName, totalCount, callback) {
            fileQueue.push({file, displayName, totalCount, callback});
            pumpQueue();
        }

        function pumpQueue() {
            while (activeFiles < MAX_FILE_PARALLEL && fileQueue.length > 0) {
                const item = fileQueue.shift();
                activeFiles++;
                sendSingleFile(item.file, item.displayName, item.totalCount, (ok) => {
                    activeFiles--;
                    item.callback(ok);
                    pumpQueue();
                });
            }
        }

        function sendFiles(files) {
            if (!files || files.length === 0) return;

            const fileCount = files.length;
            addStatus(`📤 准备上传 ${fileCount} 个文件...`);

            let successCount = 0;
            let processedCount = 0;

            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                enqueueFile(file, file.name, fileCount, function(success) {
                    processedCount++;
                    if (success) successCount++;
                    if (processedCount === fileCount) {
                        addStatus(`✅ 上传完成: ${successCount}/${fileCount} 个文件`);
                    }
                });
            }

            document.getElementById('fileInput').value = '';
        }

        function sendDirectory(files) {
            if (!files || files.length === 0) return;

            const fileCount = files.length;
            addStatus(`📁 准备发送目录，共 ${fileCount} 个文件...`);

            let successCount = 0;
            let processedCount = 0;

            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                const displayName = file.webkitRelativePath || file.name;
                enqueueFile(file, displayName, fileCount, function(success) {
                    processedCount++;
                    if (success) successCount++;
                    if (processedCount === fileCount) {
                        addStatus(`✅ 目录发送完成: ${successCount}/${fileCount} 个文件`);
                    }
                });
            }

            document.getElementById('dirInput').value = '';
        }
        
        function chunkLen(up, index) {
            const start = index * CHUNK_SIZE;
            return Math.min(CHUNK_SIZE, up.file.size - start);
        }

        function updateProgress(up) {
            let bytes = 0;
            up.received.forEach(i => { bytes += chunkLen(up, i); });
            const percent = up.file.size > 0 ? Math.round((bytes / up.file.size) * 100) : 100;
            up.progressBar.style.width = percent + '%';
            const sizeEl = document.getElementById(up.sizeId);
            if (sizeEl) sizeEl.textContent = formatSize(bytes);
        }

        let uploadSeq = 0;
        function sendSingleFile(file, displayName, totalCount, callback) {
            const sizeId = `upload-size-${++uploadSeq}`;

            const statusDiv = document.createElement('div');
            statusDiv.className = 'status';
            statusDiv.appendChild(document.createTextNode(`📤 正在上传: ${displayName} (`));
            const sizeSpan = document.createElement('span');
            sizeSpan.id = sizeId;
            sizeSpan.textContent = '0';
            statusDiv.appendChild(sizeSpan);
            statusDiv.appendChild(document.createTextNode(`/${formatSize(file.size)}`));
            messagesDiv.appendChild(statusDiv);

            const progressContainer = document.createElement('div');
            progressContainer.className = 'progress-container';
            const progressBar = document.createElement('div');
            progressBar.className = 'progress-bar';
            progressBar.style.width = '0%';
            progressContainer.appendChild(progressBar);
            messagesDiv.appendChild(progressContainer);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;

            const totalChunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE));

            // 1. 初始化上传会话
            const fd = new FormData();
            fd.append('filename', displayName);
            fd.append('size', file.size);
            fd.append('total', totalChunks);
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/upload/init', true);
            xhr.timeout = 30000;
            xhr.onload = function() {
                if (xhr.status !== 200) { fail('HTTP ' + xhr.status); return; }
                let data;
                try { data = JSON.parse(xhr.responseText); } catch (err) { fail('响应解析失败'); return; }
                if (data.status !== 'ok') { fail(data.msg || '初始化失败'); return; }
                activeUploads[data.upload_id] = {
                    file, displayName, sizeId, statusDiv, progressBar, callback,
                    totalChunks, received: new Set(), paused: false, running: false
                };
                // 2. 查询已收分片并启动并行上传
                resumeUpload(data.upload_id);
            };
            xhr.onerror = () => fail('网络错误');
            xhr.ontimeout = () => fail('超时');
            xhr.send(fd);

            function fail(msg) {
                statusDiv.textContent = `❌ 上传失败: ${displayName} (${msg})`;
                progressBar.style.backgroundColor = '#e74c3c';
                if (callback) callback(false);
            }
        }

        function resumeUpload(uploadId) {
            const up = activeUploads[uploadId];
            if (!up || up.running) return;
            up.running = true;
            fetch(`/upload/status?upload_id=${uploadId}`)
                .then(r => r.json())
                .then(d => {
                    if (d.status !== 'ok') {
                        // 会话已失效（如服务重启）：明确失败，不再对着失效 id 无限重传
                        up.running = false;
                        up.statusDiv.textContent = `❌ 上传失败: ${up.displayName} (会话已失效，请重发)`;
                        up.progressBar.style.backgroundColor = '#e74c3c';
                        delete activeUploads[uploadId];
                        if (up.callback) up.callback(false);
                        return;
                    }
                    (d.received || []).forEach(i => { if (!up.received.has(i)) up.received.add(i); });
                    updateProgress(up);
                    runWorkers(uploadId);
                })
                .catch(() => {
                    // 网络不可用：挂起，等待重连后由 connect 事件恢复
                    up.running = false;
                    up.paused = true;
                });
        }

        function runWorkers(uploadId) {
            const up = activeUploads[uploadId];
            if (!up) return;
            const pending = [];
            for (let i = 0; i < up.totalChunks; i++) {
                if (!up.received.has(i)) pending.push(i);
            }
            let cursor = 0;
            const worker = async () => {
                while (!up.paused) {
                    const idx = cursor++;
                    if (idx >= pending.length) return;
                    const ok = await uploadChunk(uploadId, pending[idx]);
                    if (!ok) return; // 失败：暂停，等待重连后 resumeUpload 恢复
                    up.received.add(pending[idx]);
                    updateProgress(up);
                }
            };
            const all = [];
            for (let w = 0; w < UPLOAD_PARALLEL; w++) all.push(worker());
            Promise.all(all).then(() => {
                up.running = false;
                if (!up.paused && up.received.size >= up.totalChunks) {
                    finishUpload(uploadId);
                }
            });
        }

        function uploadChunk(uploadId, index, attempt) {
            attempt = attempt || 0;
            return new Promise(resolve => {
                const up = activeUploads[uploadId];
                if (!up || up.paused) { resolve(false); return; }
                const start = index * CHUNK_SIZE;
                const fd = new FormData();
                fd.append('upload_id', uploadId);
                fd.append('index', index);
                fd.append('chunk', up.file.slice(start, Math.min(start + CHUNK_SIZE, up.file.size)));
                const xhr = new XMLHttpRequest();
                xhr.open('POST', '/upload/chunk', true);
                xhr.timeout = 120000;
                xhr.onload = () => resolve(xhr.status === 200);
                xhr.onerror = () => resolve(false);
                xhr.ontimeout = () => resolve(false);
                xhr.send(fd);
            }).then(ok => {
                if (ok || attempt >= 3) {
                    if (!ok) {
                        const up = activeUploads[uploadId];
                        if (up) {
                            up.paused = true;
                            addStatus(`⏳ ${up.displayName} 网络中断，重连后自动续传...`);
                        }
                    }
                    return ok;
                }
                // 失败自动重试（最多 3 次，间隔递增）
                return new Promise(resolve => setTimeout(() => resolve(uploadChunk(uploadId, index, attempt + 1)), 500 * (attempt + 1)));
            });
        }

        function finishUpload(uploadId) {
            const up = activeUploads[uploadId];
            const fd = new FormData();
            fd.append('upload_id', uploadId);
            fetch('/upload/finish', { method: 'POST', body: fd })
                .then(r => r.json())
                .then(d => {
                    if (d.status === 'ok') {
                        socket.emit('file_uploaded', { file_id: d.file_id, filename: up.displayName });
                        up.progressBar.style.width = '100%';
                        up.progressBar.style.backgroundColor = '#00b894';
                        up.statusDiv.textContent = `✅ 上传成功: ${up.displayName}`;
                        delete activeUploads[uploadId];
                        if (up.callback) up.callback(true);
                    } else {
                        up.statusDiv.textContent = `❌ 上传失败: ${d.msg || '合并失败'}`;
                        up.progressBar.style.backgroundColor = '#e74c3c';
                        delete activeUploads[uploadId];
                        if (up.callback) up.callback(false);
                    }
                })
                .catch(() => {
                    // 网络中断：挂起，等待重连后重新 finish
                    up.paused = true;
                    up.running = false;
                    addStatus(`⏳ ${up.displayName} 网络中断，重连后自动续传...`);
                });
        }
        
        function formatSize(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }

        document.getElementById('textInput').addEventListener('input', function() {
            const sendBtn = document.getElementById('sendBtn');
            const plusBtn = document.getElementById('plusBtn');
            if (this.value.trim()) {
                sendBtn.style.display = '';
                plusBtn.style.display = 'none';
            } else {
                sendBtn.style.display = 'none';
                plusBtn.style.display = '';
            }
        });
        
        document.getElementById('textInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendText();
        });
        
        function togglePopup() {
            const menu = document.getElementById('popupMenu');
            const overlay = document.getElementById('popupOverlay');
            const isShow = menu.classList.contains('show');
            menu.classList.toggle('show');
            overlay.style.display = isShow ? 'none' : 'block';
        }
        
        function hidePopup() {
            document.getElementById('popupMenu').classList.remove('show');
            document.getElementById('popupOverlay').style.display = 'none';
        }
        
        function showAbout() {
            document.getElementById('aboutModal').classList.add('is-open');
        }

        function hideAbout() {
            document.getElementById('aboutModal').classList.remove('is-open');
        }

        document.getElementById('aboutModal').addEventListener('click', (e) => {
            if (e.target === document.getElementById('aboutModal')) {
                hideAbout();
            }
        });
    </script>
</body>
</html>
"""

# CSS / 线性图标 / 旧状态文案统一由视觉令牌注入，服务端只保留页面结构与协议逻辑
PHONE_PAGE = apply_phone_tokens(PHONE_PAGE)


@app.route('/')
def index():
    return render_template_string(PHONE_PAGE)

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return {'status': 'error', 'msg': '没有文件'}
    file = request.files['file']
    if file.filename == '':
        return {'status': 'error', 'msg': '空文件名'}
    
    file_id = str(uuid.uuid4())[:8]
    filename = file.filename
    safe_filename = os.path.basename(filename.replace('\\', '/'))
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_{safe_filename}")
    file.save(save_path)
    
    phone_uploads[file_id] = save_path

    return {'status': 'ok', 'filename': filename, 'file_id': file_id}

# ================================================================
# 分片上传协议（手机网页与 PC 客户端共用）
# init -> chunk* -> status(续传查询) -> finish(合并登记)
# ================================================================

CHUNK_SIZE_DEFAULT = 4 * 1024 * 1024
CHUNK_FOLDER = os.path.join(UPLOAD_FOLDER, 'chunks')
upload_sessions = {}  # upload_id -> 会话信息字典


def cleanup_chunk_folder():
    """清理分片临时目录（启动时清残留，退出时兜底）"""
    if os.path.isdir(CHUNK_FOLDER):
        shutil.rmtree(CHUNK_FOLDER, ignore_errors=True)
    os.makedirs(CHUNK_FOLDER, exist_ok=True)


def _safe_basename(name):
    return os.path.basename(str(name).replace('\\', '/')) or 'file'


@app.route('/upload/init', methods=['POST'])
def upload_init():
    data = request.get_json(silent=True) or request.form or {}
    filename = data.get('filename', 'file')
    try:
        size = int(data.get('size', 0))
        total = int(data.get('total', 0))
    except (TypeError, ValueError):
        return {'status': 'error', 'msg': 'size/total 无效'}, 400
    if total <= 0:
        return {'status': 'error', 'msg': '总分片数无效'}, 400

    upload_id = uuid.uuid4().hex[:12]
    session_dir = os.path.join(CHUNK_FOLDER, upload_id)
    os.makedirs(session_dir, exist_ok=True)
    upload_sessions[upload_id] = {
        'dir': session_dir,
        'filename': filename,
        'safe_filename': _safe_basename(filename),
        'size': size,
        'total': total,
        'chunk_size': CHUNK_SIZE_DEFAULT,
        'md5': data.get('md5') or None,
        'received': set(),
        'last_active': time.time(),
        'finished': False,
        'file_id': None,
    }
    return {'status': 'ok', 'upload_id': upload_id, 'chunk_size': CHUNK_SIZE_DEFAULT}


@app.route('/upload/chunk', methods=['POST'])
def upload_chunk():
    upload_id = request.form.get('upload_id', '')
    session = upload_sessions.get(upload_id)
    if not session:
        return {'status': 'error', 'msg': '上传会话不存在'}, 404
    try:
        index = int(request.form.get('index', -1))
    except (TypeError, ValueError):
        return {'status': 'error', 'msg': 'index 无效'}, 400
    if index < 0 or index >= session['total']:
        return {'status': 'error', 'msg': 'index 超出范围'}, 400

    blob = request.files.get('chunk')
    if blob is None:
        return {'status': 'error', 'msg': '缺少分片数据'}, 400

    # 先写 .tmp 再原子替换，避免并行上传同名分片时文件损坏
    final_path = os.path.join(session['dir'], f'{index}.part')
    tmp_path = final_path + '.tmp'
    blob.save(tmp_path)
    os.replace(tmp_path, final_path)
    session['received'].add(index)
    session['last_active'] = time.time()
    return {'status': 'ok'}


@app.route('/upload/status', methods=['GET'])
def upload_status():
    """断点续传查询：返回已成功接收的分片索引列表"""
    upload_id = request.args.get('upload_id', '')
    session = upload_sessions.get(upload_id)
    if not session:
        return {'status': 'error', 'msg': '上传会话不存在'}, 404
    return {
        'status': 'ok',
        'received': sorted(session['received']),
        'total': session['total'],
        'chunk_size': session['chunk_size'],
    }


@app.route('/upload/finish', methods=['POST'])
def upload_finish():
    """合并分片；幂等且不在失败时销毁会话，保证断点续传可用。"""
    data = request.get_json(silent=True) or request.form or {}
    upload_id = data.get('upload_id', '')
    session = upload_sessions.get(upload_id)
    if not session:
        return {'status': 'error', 'msg': '上传会话不存在'}, 404

    # 网络重试导致重复 finish：直接返回第一次的结果
    if session.get('finished'):
        return {'status': 'ok', 'file_id': session['file_id'],
                'filename': session['filename']}

    if len(session['received']) < session['total']:
        # 不删除会话，客户端可继续查询已收分片后续传
        session['last_active'] = time.time()
        return {'status': 'error',
                'msg': f"分片不完整 ({len(session['received'])}/{session['total']})"}, 400

    file_id = uuid.uuid4().hex[:8]
    save_path = os.path.join(UPLOAD_FOLDER, f"{file_id}_{session['safe_filename']}")
    md5 = hashlib.md5() if session.get('md5') else None
    try:
        with open(save_path, 'wb') as out:
            for i in range(session['total']):
                with open(os.path.join(session['dir'], f'{i}.part'), 'rb') as f:
                    while True:
                        block = f.read(1024 * 1024)
                        if not block:
                            break
                        out.write(block)
                        if md5 is not None:
                            md5.update(block)
                gevent.sleep(0)  # 让出 hub，避免大文件合并期间心跳与其它连接饿死
        if md5 is not None and md5.hexdigest() != session['md5']:
            raise ValueError('MD5 校验失败，请重传')
    except Exception as e:
        try:
            if os.path.exists(save_path):
                os.remove(save_path)
        except OSError:
            pass
        # 清空已收标记，让客户端重传全部分片
        session['received'].clear()
        session['last_active'] = time.time()
        return {'status': 'error', 'msg': f'合并失败，请重传: {e}'}, 400

    shutil.rmtree(session['dir'], ignore_errors=True)
    phone_uploads[file_id] = save_path
    session['finished'] = True
    session['file_id'] = file_id
    session['last_active'] = time.time()
    return {'status': 'ok', 'file_id': file_id, 'filename': session['filename']}

def stream_file_response(filepath, filename):
    """1MB 缓冲流式响应，恒定内存跑满局域网带宽（替代 send_from_directory）"""
    def generate(path, buffer_size=1024 * 1024):
        with open(path, 'rb') as f:
            while True:
                block = f.read(buffer_size)
                if not block:
                    break
                yield block

    resp = Response(generate(filepath), mimetype='application/octet-stream')
    try:
        filename.encode('ascii')
        ascii_name = filename
    except UnicodeEncodeError:
        ascii_name = 'download'
    ascii_name = ascii_name.replace('"', "'").replace('\r', '').replace('\n', '')
    resp.headers['Content-Disposition'] = (
        f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'
    )
    resp.headers['Content-Length'] = str(os.path.getsize(filepath))
    return resp


@app.route('/download/<file_id>')
def download_file(file_id):
    if file_id in temp_downloads:
        filename, filepath = temp_downloads[file_id]
        return stream_file_response(filepath, os.path.basename(filepath))
    return "文件不存在", 404

@app.route('/get_file/<file_id>')
def get_file(file_id):
    if file_id in phone_uploads:
        filepath = phone_uploads[file_id]
        return stream_file_response(filepath, os.path.basename(filepath))
    return "文件不存在", 404

def _client_ip(req):
    """从 Socket.IO 上下文取来源 IP（仅用于界面显示，不参与访问控制）。

    不同 engineio / WSGI 版本里，remote_addr 可能只存在于握手 environ 中。
    """
    try:
        ip = req.remote_addr or ''
    except Exception:
        ip = ''
    if not ip:
        try:
            ip = req.environ.get('REMOTE_ADDR', '') or ''
        except Exception:
            ip = ''
    return ip


@socketio.on('connect')
def handle_connect():
    from flask import request
    # 握手阶段记录来源 IP；事件上下文取不到时用它兜底
    client_ips[request.sid] = _client_ip(request)
    print('新连接, sid:', request.sid, '来源:', client_ips[request.sid])


@socketio.on('disconnect')
def handle_disconnect():
    from flask import request
    sid = request.sid
    client_ips.pop(sid, None)

    pc_info = pc_sids.pop(sid, None)
    if pc_info:
        print(f'PC 断开连接: {pc_info["name"]} (sid: {sid[:4]})')
        return  # PC 设备由 UDP 发现管理，不以 sid 作为设备 key

    if sid not in phone_sids:
        return

    phone_sids.discard(sid)
    device_id = phone_device_ids.pop(sid, None)
    key = device_id or sid
    print(f'移动设备连接中断: {key} (进入 {GRACE_SECONDS} 秒宽限期)')

    def _grace_check():
        gevent.sleep(GRACE_SECONDS)
        if device_id:
            current = device_id_sids.get(device_id)
            if current and current != sid:
                return  # 已用新 sid 回来（切后台/换网络），设备与聊天记录都保留
            device_id_sids.pop(device_id, None)
        if not phone_sids:
            signal_emitter.phone_connected.emit(False)
            signal_emitter.phone_sid_updated.emit('')
        signal_emitter.device_disconnected.emit(key)

    gevent.spawn(_grace_check)


@socketio.on('identify')
def handle_identify(data):
    """客户端身份识别：移动设备用稳定 device_id，PC 客户端带上来源 IP。"""
    from flask import request
    data = data or {}
    sid = request.sid
    client_name = str(data.get('name', 'Unknown'))[:64]

    if data.get('type') == 'pc':
        pc_sids[sid] = {'name': client_name, 'ip': data.get('ip', '')}
        print(f'PC 客户端已识别: {client_name} (sid: {sid[:4]})')
        return

    device_id = str(data.get('device_id') or sid)[:64]
    source_ip = _client_ip(request) or client_ips.get(sid, '')
    old_sid = device_id_sids.get(device_id)
    if old_sid and old_sid != sid:
        phone_sids.discard(old_sid)
        phone_device_ids.pop(old_sid, None)
    device_id_sids[device_id] = sid
    phone_device_ids[sid] = device_id
    phone_sids.add(sid)

    print(f'移动设备已识别: {device_id} (来源: {source_ip})')
    signal_emitter.phone_connected.emit(True)
    signal_emitter.phone_sid_updated.emit(sid)
    signal_emitter.device_connected.emit(device_id, 'phone', '移动设备', sid, source_ip)


@socketio.on('text_message')
def handle_text_message(data):
    from flask import request
    data = data or {}
    msg = data.get('message', '')
    sid = request.sid

    if sid in pc_sids:
        info = pc_sids[sid]
        source_msg = f"[{info['name']}] {msg}"
        print(f"收到 PC 文本: {source_msg}")
        signal_emitter.pc_message.emit(source_msg, info.get('ip', ''))
    else:
        key = phone_device_ids.get(sid, sid)
        source_msg = f"[{key[-4:]}] {msg}"
        print(f"收到移动设备文本: {source_msg}")
        signal_emitter.phone_text_key.emit(key)
        signal_emitter.received_text.emit(source_msg, 'phone')


@socketio.on('file_uploaded')
def handle_file_uploaded(data):
    from flask import request
    data = data or {}
    file_id = data.get('file_id')
    filename = data.get('filename')
    source_sid = request.sid

    if source_sid in pc_sids:
        print(f"PC 发送文件完成: {filename} (来自: {pc_sids[source_sid]['name']})")
        signal_emitter.received_file.emit(file_id, filename, 'pc')
    else:
        key = phone_device_ids.get(source_sid, source_sid)
        print(f"移动设备上传文件完成: {filename} (来源: {key})")
        signal_emitter.received_file.emit(file_id, filename, key)

def cleanup_expired_sessions():
    """清理长时间未完成 / 已完成的上传会话，避免内存与磁盘碎片无限增长。"""
    while True:
        gevent.sleep(60)
        now = time.time()
        for upload_id, session in list(upload_sessions.items()):
            ttl = 5 * 60 if session.get('finished') else SESSION_TTL
            if now - session.get('last_active', now) > ttl:
                upload_sessions.pop(upload_id, None)
                shutil.rmtree(session['dir'], ignore_errors=True)


def cleanup_temp_files():
    files_to_remove = list(_temp_zip_files)
    for path in files_to_remove:
        try:
            if os.path.exists(path):
                os.remove(path)
                print(f"已清理临时文件: {path}")
        except Exception as e:
            print(f"清理临时文件失败 {path}: {e}")
    _temp_zip_files.clear()

atexit.register(cleanup_temp_files)
atexit.register(cleanup_chunk_folder)


def _pick_port(host, port, tries=20):
    """找第一个可绑定端口；不设 SO_REUSEADDR，避免 Windows 上把占用端口误判为可用。"""
    import socket
    for candidate in range(port, port + tries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((host, candidate))
            return candidate
        except OSError:
            continue
        finally:
            s.close()
    return None


def start_flask(host='0.0.0.0', port=5000):
    """启动传输服务：端口自动顺延、状态实时通知 UI、异常后自动重启。"""
    global RUNTIME_PORT
    import socket
    from gevent import pywsgi

    class TunedWSGIServer(pywsgi.WSGIServer):
        def handle(self, sock, address):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception:
                pass
            return super().handle(sock, address)

    server_kwargs = {'log': None}
    try:
        from geventwebsocket.handler import WebSocketHandler
        server_kwargs['handler_class'] = WebSocketHandler
        print('WebSocket 传输: gevent-websocket')
    except ImportError:
        print('WebSocket 传输: simple-websocket(engineio 内置)')

    cleanup_chunk_folder()  # 仅进程首次启动时清残留；自动重启不清，避免打断续传
    gevent.spawn(cleanup_expired_sessions)

    first = True
    backoff = 1
    while True:
        # 重启时优先复用原端口，避免已发出的二维码/链接失效
        chosen = None if first else _pick_port(host, RUNTIME_PORT, tries=1)
        if chosen is None:
            chosen = _pick_port(host, port)
        if chosen is None:
            signal_emitter.server_status.emit(False, 0, '没有可用端口，5 秒后重试')
            gevent.sleep(5)
            continue

        RUNTIME_PORT = chosen
        server = TunedWSGIServer((host, chosen), app, **server_kwargs)
        signal_emitter.server_status.emit(True, chosen, f'服务已启动，端口 {chosen}')
        print(f'传输服务已启动: http://{host}:{chosen}')
        try:
            server.serve_forever()
            reason = '服务已停止，正在自动恢复'
        except Exception as e:
            reason = f'服务异常退出: {e}'
        try:
            server.stop()
        except Exception:
            pass
        signal_emitter.server_status.emit(False, chosen, reason)
        print(f'{reason}，{backoff} 秒后自动重启')
        gevent.sleep(backoff)
        backoff = min(backoff * 2, 10)
        first = False