import os
import uuid
import atexit
import shutil
import hashlib
import zipfile
import tempfile
from datetime import datetime
from urllib.parse import quote

import gevent
from flask import Flask, request, send_from_directory, render_template_string, Response
from flask_socketio import SocketIO, emit
import engineio.async_drivers.gevent

from app.config import load_config, DEFAULT_DOWNLOAD_FOLDER
from app.signal import signal_emitter
from app.utils import get_lan_ip

config = load_config()

UPLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "LanChatUploads")
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

DOWNLOAD_FOLDER = config.get('download_path', DEFAULT_DOWNLOAD_FOLDER)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

app = Flask(__name__, static_folder=None)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = 'secret!'
# 放宽心跳参数：手机浏览器切后台时页面被冻结无法及时回应 ping，
# ping_timeout=60 可大幅减少"切后台即断开"的误判
socketio = SocketIO(app, async_mode='gevent',
                    ping_interval=25, ping_timeout=60)

temp_downloads = {}
phone_uploads = {}
phone_sids = set()
pc_sids = {}  # sid -> device_name（PC 客户端）
grace_sids = set()  # 断线宽限期内的手机 sid（切后台回前台可无感恢复）
_temp_zip_files = set()

PHONE_PAGE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>局域网文件/消息传输</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
               height: 100vh; display: flex; justify-content: center; align-items: center; }
        .container { width: 90%; max-width: 400px; background: white; border-radius: 20px;
                     box-shadow: 0 10px 40px rgba(0,0,0,0.3); overflow: hidden;
                     display: flex; flex-direction: column; height: 80vh; }
        .header { background: #6c5ce7; color: white; padding: 15px; text-align: center;
                  font-size: 18px; font-weight: bold; letter-spacing: 1px; display: flex; align-items: center; justify-content: space-between; }
        .messages { flex: 1; padding: 15px; overflow-y: auto; background: #f8f9fa;
                    display: flex; flex-direction: column; }
        .msg { margin-bottom: 10px; max-width: 80%; word-wrap: break-word; }
        .msg.local { align-self: flex-end; background: #6c5ce7; color: white;
                     border-radius: 15px 15px 0 15px; padding: 10px; }
        .msg.remote { align-self: flex-start; background: white; border: 1px solid #ddd;
                      border-radius: 15px 15px 15px 0; padding: 10px; }
        .file-link { color: #6c5ce7; text-decoration: underline; cursor: pointer; }
        .input-area { display: flex; padding: 10px; background: white; border-top: 1px solid #ddd; }
        #textInput { flex: 1; border: none; outline: none; font-size: 16px; padding: 8px;
                     border-radius: 20px; background: #f1f3f5; }
        button { background: #6c5ce7; color: white; border: none; border-radius: 20px;
                 padding: 8px 15px; margin-left: 5px; font-size: 14px; cursor: pointer; }
        button:active { opacity: 0.8; }
        #fileInput { display: none; }
        .status { text-align: center; color: #777; font-size: 12px; padding: 5px; }
        .progress-container { width: 100%; background-color: #e0e0e0; border-radius: 5px; height: 8px; margin-top: 5px; }
        .progress-bar { height: 100%; background-color: #00b894; border-radius: 5px; transition: width 0.3s ease; }
        .upload-status { font-size: 12px; color: #666; }
        .about-modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; justify-content: center; align-items: center; }
        .about-content { background: white; width: 90%; max-width: 350px; border-radius: 15px; padding: 20px; max-height: 85vh; overflow-y: auto; -webkit-overflow-scrolling: touch; }
        .about-title { font-size: 18px; font-weight: bold; text-align: center; color: #2d3436; margin-bottom: 5px; position: sticky; top: 0; background: white; padding-bottom: 10px; }
        .about-version { font-size: 12px; color: #636e72; text-align: center; margin-bottom: 15px; }
        .about-section { margin: 15px 0; }
        .about-section-title { font-size: 14px; font-weight: bold; color: #2d3436; margin-bottom: 8px; }
        .about-text { font-size: 12px; color: #636e72; line-height: 1.6; }
        .privacy-box { background: #f8f9fa; padding: 10px; border-radius: 8px; border-left: 3px solid #00b894; }
        .disclaimer-box { background: #fff8e6; padding: 10px; border-radius: 8px; border-left: 3px solid #ffc107; }
        .about-close { width: 100%; padding: 12px; background: #6c5ce7; color: white; border: none; border-radius: 8px; font-size: 14px; cursor: pointer; margin-top: 15px; position: sticky; bottom: 0; }
        .about-close:active { background: #5a4bd1; }
        .input-area { position: relative; }
        .popup-menu { display: none; position: absolute; bottom: 60px; right: 10px; background: white; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); overflow: hidden; z-index: 10; }
        .popup-menu.show { display: block; }
        .popup-item { padding: 12px 20px; font-size: 15px; cursor: pointer; white-space: nowrap; border: none; background: none; width: 100%; text-align: left; color: #2d3436; }
        .popup-item:hover { background: #f5f5f5; }
        .popup-item:first-child { border-bottom: 1px solid #eee; }
        .popup-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 9; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <span style="flex: 1; text-align: center;">📡 局域网传输</span>
            <span style="font-size: 14px; color: white; cursor: pointer; padding: 0 10px;" onclick="showAbout()">ℹ️ 关于</span>
        </div>
        <div class="messages" id="messages">
            <div class="status">等待连接...</div>
        </div>
        <div class="input-area">
            <input type="text" id="textInput" placeholder="输入文字..." autocomplete="off">
            <button id="sendBtn" onclick="sendText()" style="display:none">发送</button>
            <button id="plusBtn" onclick="togglePopup()">+</button>
            <div class="popup-overlay" id="popupOverlay" onclick="hidePopup()"></div>
            <div class="popup-menu" id="popupMenu">
                <button class="popup-item" onclick="document.getElementById('fileInput').click();hidePopup()">📎 发送文件</button>
                <button class="popup-item" onclick="document.getElementById('dirInput').click();hidePopup()">📁 发送文件夹</button>
            </div>
            <input type="file" id="dirInput" webkitdirectory style="display:none" onchange="sendDirectory(this.files)">
            <input type="file" id="fileInput" onchange="sendFiles(this.files)" multiple>
        </div>
    </div>
    
    <div class="about-modal" id="aboutModal">
        <div class="about-content">
            <div class="about-title">📡 局域网双向传输</div>
            <div class="about-version">版本 v2.0</div>
            
            <div class="about-section">
                <div class="about-section-title">🔧 简介</div>
                <div class="about-text">
                    一款简洁高效的局域网文件传输工具，支持电脑与手机之间的实时消息和文件互传。
                </div>
            </div>
            
            <div class="about-section">
                <div class="about-section-title">✨ 特性</div>
                <div class="about-text">
                    • 本地局域网传输，无需互联网<br>
                    • 支持大文件高速传输<br>
                    • 实时消息和文件互传
                </div>
            </div>
            
            <div class="about-section">
                <div class="about-section-title">🔒 隐私与安全</div>
                <div class="about-text privacy-box">
                    ✓ 仅在本地局域网内传输数据<br>
                    ✓ 不上传数据到远程服务器<br>
                    ✓ 不收集用户隐私信息<br>
                    ✓ 不监控剪贴板内容
                </div>
            </div>
            
            <div class="about-section">
                <div class="about-section-title">⚠️ 免责声明</div>
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

        socket.on('connect', () => {
            socket.emit('identify', {type: 'phone'});
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
            addStatus('连接断开');
        });

        socket.on('text_message', (data) => {
            addMessage(data.message, 'remote');
        });

        socket.on('file_download', (data) => {
            const link = `<a class="file-link" href="${data.url}" download>📁 ${data.filename}</a>`;
            addMessage(link, 'remote');
        });

        socket.on('upload_status', (data) => {
            addStatus(data.msg);
        });

        function addMessage(content, type) {
            const div = document.createElement('div');
            div.className = `msg ${type}`;
            div.innerHTML = content;
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

        function sendFiles(files) {
            if (!files || files.length === 0) return;
            
            const fileCount = files.length;
            addStatus(`📤 准备上传 ${fileCount} 个文件...`);
            
            let successCount = 0;
            let processedCount = 0;
            
            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                sendSingleFile(file, file.name, fileCount, function(success) {
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
                sendSingleFile(file, displayName, fileCount, function(success) {
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

        function sendSingleFile(file, displayName, totalCount, callback) {
            const sizeId = `upload-size-${displayName.replace(/[^a-zA-Z0-9]/g, '_')}`;

            const statusDiv = document.createElement('div');
            statusDiv.className = 'status';
            statusDiv.innerHTML = `📤 正在上传: ${displayName} (<span id="${sizeId}">0</span>/${formatSize(file.size)})`;
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
                statusDiv.innerHTML = `❌ 上传失败: ${displayName} (${msg})`;
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
                        up.statusDiv.innerHTML = `✅ 上传成功: ${up.displayName}`;
                        delete activeUploads[uploadId];
                        if (up.callback) up.callback(true);
                    } else {
                        up.statusDiv.innerHTML = `❌ 上传失败: ${d.msg || '合并失败'}`;
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
            const i = Math.floor(Math.log(bytes) / Math.log(k));
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
            document.getElementById('aboutModal').style.display = 'flex';
        }
        
        function hideAbout() {
            document.getElementById('aboutModal').style.display = 'none';
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
    data = request.get_json(silent=True) or request.form or {}
    upload_id = data.get('upload_id', '')
    session = upload_sessions.pop(upload_id, None)
    if not session:
        return {'status': 'error', 'msg': '上传会话不存在'}, 404
    if len(session['received']) < session['total']:
        return {'status': 'error', 'msg': f"分片不完整 ({len(session['received'])}/{session['total']})"}, 400

    file_id = uuid.uuid4().hex[:8]
    save_path = os.path.join(UPLOAD_FOLDER, f"{file_id}_{session['safe_filename']}")

    # 顺序合并分片（1MB 写盘缓冲），可选 MD5 校验
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
        if md5 is not None and md5.hexdigest() != session['md5']:
            os.remove(save_path)
            return {'status': 'error', 'msg': 'MD5 校验失败，请重传'}, 400
    finally:
        shutil.rmtree(session['dir'], ignore_errors=True)

    phone_uploads[file_id] = save_path
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

@socketio.on('connect')
def handle_connect():
    from flask import request
    sid = request.sid
    phone_sids.add(sid)
    print('新连接, sid:', sid)

@socketio.on('disconnect')
def handle_disconnect():
    from flask import request
    sid = request.sid

    # 从 pc_sids 移除
    pc_name = pc_sids.pop(sid, None)
    if pc_name:
        print(f'PC 断开连接: {pc_name} (sid: {sid[:4]})')
        signal_emitter.device_disconnected.emit(sid)
        return

    # 手机断开：进入 5 秒宽限期，不立即通知 UI
    # （手机切后台时浏览器冻结页面、心跳停发是常态，回前台后 socket.io 会自动重连并重新 identify）
    was_phone = sid in phone_sids
    phone_sids.discard(sid)

    if was_phone:
        grace_sids.add(sid)
        print(f'手机连接中断, sid: {sid[:4]} (进入 5 秒宽限期)')

        def _grace_check():
            gevent.sleep(5)
            grace_sids.discard(sid)
            if phone_sids:
                # 宽限期内已有其他手机连接（或本机重连拿到新 sid），无需处理
                signal_emitter.device_disconnected.emit(sid)
                return
            print(f'手机确认离线 (宽限期内未恢复), sid: {sid[:4]}')
            signal_emitter.phone_connected.emit(False)
            signal_emitter.phone_sid_updated.emit(None)
            signal_emitter.device_disconnected.emit(sid)

        gevent.spawn(_grace_check)

@socketio.on('identify')
def handle_identify(data):
    """客户端身份识别：区分手机 / PC 客户端"""
    from flask import request
    sid = request.sid
    client_type = data.get('type', '')
    client_name = data.get('name', 'Unknown')

    if client_type == 'pc':
        # 从 phone_sids 移入 pc_sids
        phone_sids.discard(sid)
        pc_sids[sid] = client_name
        display_name = f"🖥️ {client_name}"
        print(f'PC 客户端已识别: {client_name} (sid: {sid[:4]})')
        signal_emitter.device_connected.emit(sid, 'pc', display_name)
    else:
        # 手机客户端（默认已加入 phone_sids）
        print(f'手机客户端已识别: {sid[:4]}')
        signal_emitter.phone_connected.emit(True)
        signal_emitter.phone_sid_updated.emit(sid)
        signal_emitter.device_connected.emit(sid, 'phone', f'手机-{sid[:4]}')

@socketio.on('text_message')
def handle_text_message(data):
    from flask import request
    msg = data.get('message', '')
    sid = request.sid

    if sid in pc_sids:
        # 来自 PC 客户端
        pc_name = pc_sids[sid]
        source_msg = f"[{pc_name}] {msg}"
        print(f"收到 PC 文本: {source_msg}")
        signal_emitter.received_text.emit(source_msg, 'remote_pc')
    else:
        # 来自手机
        source_msg = f"[{sid[:4]}] {msg}"
        print(f"收到手机文本: {source_msg}")
        signal_emitter.phone_text_sid.emit(sid)
        signal_emitter.received_text.emit(source_msg, 'phone')

@socketio.on('upload_complete')
def handle_upload_complete(data):
    msg = f"📤 手机上传了文件: {data.get('filename')} ({data.get('size')} 字节)"
    signal_emitter.received_text.emit(msg, 'system')

@socketio.on('file_uploaded')
def handle_file_uploaded(data):
    from flask import request
    file_id = data.get('file_id')
    filename = data.get('filename')
    source_sid = request.sid

    if source_sid in pc_sids:
        # 来自 PC 客户端
        pc_name = pc_sids[source_sid]
        print(f"PC 发送文件完成: {filename} (来自: {pc_name})")
        signal_emitter.received_file.emit(file_id, filename, 'pc')
    else:
        # 来自手机
        print(f"手机上传文件完成: {filename} (来源: {source_sid[:4]})")
        signal_emitter.received_file.emit(file_id, filename, source_sid)

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

def start_flask(host='0.0.0.0', port=5000):
    """启动传输服务。

    与 flask_socketio.run 的 gevent 分支等价：装了 gevent-websocket 就用它的
    WebSocketHandler，否则由 engineio/simple-websocket 在应用层完成握手；
    并对每个接入连接调大 socket 缓冲区、禁用 Nagle，以跑满局域网带宽。
    """
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

    cleanup_chunk_folder()
    server = TunedWSGIServer((host, port), app, **server_kwargs)
    print(f'传输服务已启动: http://{host}:{port}')
    try:
        server.serve_forever()
    except Exception as e:
        print(f'传输服务异常退出: {e}')