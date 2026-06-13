import os
import uuid
import atexit
import zipfile
import tempfile
from datetime import datetime

from flask import Flask, request, send_from_directory, render_template_string
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

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='gevent')

temp_downloads = {}
phone_uploads = {}
phone_sids = set()
pc_sids = {}  # sid -> device_name（PC 客户端）
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
    <script src="https://cdn.socket.io/4.7.4/socket.io.min.js"></script>
    <script>
        const socket = io();
        const messagesDiv = document.getElementById('messages');

        socket.on('connect', () => {
            socket.emit('identify', {type: 'phone'});
            addStatus('已连接到电脑');
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
        
        function sendSingleFile(file, displayName, totalCount, callback) {
            const fileSize = file.size;
            const fileName = file.name;
            
            const statusDiv = document.createElement('div');
            statusDiv.className = 'status';
            statusDiv.innerHTML = `📤 正在上传: ${fileName} (<span id="upload-size-${fileName.replace(/[^a-zA-Z0-9]/g, '_')}">0</span>/${formatSize(fileSize)})`;
            messagesDiv.appendChild(statusDiv);
            
            const progressContainer = document.createElement('div');
            progressContainer.className = 'progress-container';
            const progressBar = document.createElement('div');
            progressBar.className = 'progress-bar';
            progressBar.style.width = '0%';
            progressContainer.appendChild(progressBar);
            messagesDiv.appendChild(progressContainer);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
            
            const formData = new FormData();
            formData.append('file', file);
            
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/upload', true);
            
            const sizeId = `upload-size-${fileName.replace(/[^a-zA-Z0-9]/g, '_')}`;
            
            xhr.upload.addEventListener('progress', function(e) {
                if (e.lengthComputable) {
                    const percent = Math.round((e.loaded / e.total) * 100);
                    progressBar.style.width = percent + '%';
                    const sizeEl = document.getElementById(sizeId);
                    if (sizeEl) sizeEl.textContent = formatSize(e.loaded);
                }
            });
            
            xhr.addEventListener('load', function() {
                if (xhr.status === 200) {
                    try {
                        const data = JSON.parse(xhr.responseText);
                        if (data.status === 'ok') {
                            socket.emit('file_uploaded', { file_id: data.file_id, filename: data.filename });
                            progressBar.style.backgroundColor = '#00b894';
                            statusDiv.innerHTML = `✅ 上传成功: ${fileName}`;
                            if (callback) callback(true);
                        } else {
                            statusDiv.innerHTML = `❌ 上传失败: ${data.msg || '未知错误'}`;
                            progressBar.style.backgroundColor = '#e74c3c';
                            if (callback) callback(false);
                        }
                    } catch (err) {
                        statusDiv.innerHTML = '❌ 上传失败: 解析响应失败';
                        progressBar.style.backgroundColor = '#e74c3c';
                        if (callback) callback(false);
                    }
                } else {
                    statusDiv.innerHTML = `❌ 上传失败: HTTP ${xhr.status}`;
                    progressBar.style.backgroundColor = '#e74c3c';
                    if (callback) callback(false);
                }
            });
            
            xhr.addEventListener('error', function() {
                statusDiv.innerHTML = '❌ 上传失败: 网络错误';
                progressBar.style.backgroundColor = '#e74c3c';
                if (callback) callback(false);
            });
            
            xhr.addEventListener('abort', function() {
                statusDiv.innerHTML = '⏹️ 上传已取消';
                if (callback) callback(false);
            });
            
            xhr.send(formData);
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

@app.route('/download/<file_id>')
def download_file(file_id):
    if file_id in temp_downloads:
        filename, filepath = temp_downloads[file_id]
        return send_from_directory(os.path.dirname(filepath), filename, as_attachment=True)
    return "文件不存在", 404

@app.route('/get_file/<file_id>')
def get_file(file_id):
    if file_id in phone_uploads:
        filepath = phone_uploads[file_id]
        return send_from_directory(os.path.dirname(filepath), os.path.basename(filepath), as_attachment=True)
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

    # 从 phone_sids 移除
    phone_sids.discard(sid)
    # 从 pc_sids 移除
    pc_name = pc_sids.pop(sid, None)

    if pc_name:
        print(f'PC 断开连接: {pc_name} (sid: {sid[:4]})')
        signal_emitter.device_disconnected.emit(sid)
    else:
        print(f'手机断开连接, sid: {sid[:4]}')
        if not phone_sids:
            signal_emitter.phone_connected.emit(False)
            signal_emitter.phone_sid_updated.emit(None)
        signal_emitter.device_disconnected.emit(sid)

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

def start_flask():
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)