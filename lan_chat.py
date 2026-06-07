import sys
import os

def resource_path(relative_path):
    """获取资源的绝对路径，兼容开发环境和 PyInstaller 打包后的环境"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


import os
import sys
import uuid
import socket
import threading
import queue
import json
import argparse
import requests
import zipfile
import tempfile
import shutil
import atexit
from datetime import datetime
from flask import Flask, request, send_from_directory, render_template_string
from flask_socketio import SocketIO, emit
import engineio.async_drivers.gevent
import qrcode
from PIL import Image
from io import BytesIO

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QScrollArea, QDialog
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread, QTimer, QUrl
from PyQt5.QtGui import QPixmap, QFont, QDesktopServices
# ------------------- 配置文件管理 -------------------
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
DEFAULT_DOWNLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "LanChatDownloads")

def load_config():
    """加载配置文件"""
    config = {
        'download_path': DEFAULT_DOWNLOAD_FOLDER
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
                config.update(loaded_config)
        except Exception as e:
            print(f"加载配置文件失败: {e}")
    return config

def save_config(config):
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"保存配置文件失败: {e}")
        return False

# 加载配置
config = load_config()

# ------------------- Flask 应用 & SocketIO -------------------
UPLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "LanChatUploads")
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# 下载路径从配置或命令行参数获取（将在 main 中更新）
DOWNLOAD_FOLDER = config.get('download_path', DEFAULT_DOWNLOAD_FOLDER)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='gevent')

# 存储待下载文件的临时映射 {random_id: (filename, filepath)}
temp_downloads = {}
# 存储手机上传文件的映射 {file_id: filepath}
phone_uploads = {}
# 手机客户端的连接 ID（一对一通信）
phone_sid = None
# 记录已创建的临时压缩包，用于退出时清理
_temp_zip_files = set()

# ------------------- 手机端网页（内联 CSS 美化） -------------------
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
        .file-btn { background: #00b894; }
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
            <button onclick="sendText()">发送</button>
            <button class="file-btn" onclick="document.getElementById('fileInput').click()">+</button>
            <input type="file" id="fileInput" onchange="sendFiles(this.files)" multiple>
        </div>
    </div>
    
    <!-- 关于弹窗 -->
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
            addStatus('已连接到电脑');
        });

        socket.on('disconnect', () => {
            addStatus('连接断开');
        });

        // 接收文本消息
        socket.on('text_message', (data) => {
            addMessage(data.message, 'remote');
        });

        // 接收文件下载链接
        socket.on('file_download', (data) => {
            const link = `<a class="file-link" href="${data.url}" download>📁 ${data.filename}</a>`;
            addMessage(link, 'remote');
        });

        // 文件上传状态通知
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

        // 回车发送
        document.getElementById('textInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendText();
        });
        
        // 显示关于弹窗
        function showAbout() {
            document.getElementById('aboutModal').style.display = 'flex';
        }
        
        // 隐藏关于弹窗
        function hideAbout() {
            document.getElementById('aboutModal').style.display = 'none';
        }
        
        // 点击弹窗背景关闭
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
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_{filename}")
    file.save(save_path)
    
    # 存储 file_id 到 filepath 的映射
    phone_uploads[file_id] = save_path
    
    return {'status': 'ok', 'filename': filename, 'file_id': file_id}

# 临时下载链接
@app.route('/download/<file_id>')
def download_file(file_id):
    if file_id in temp_downloads:
        filename, filepath = temp_downloads[file_id]
        return send_from_directory(os.path.dirname(filepath), filename, as_attachment=True)
    return "文件不存在", 404

# 桌面端获取手机发送的文件
@app.route('/get_file/<file_id>')
def get_file(file_id):
    if file_id in phone_uploads:
        filepath = phone_uploads[file_id]
        return send_from_directory(os.path.dirname(filepath), os.path.basename(filepath), as_attachment=True)
    return "文件不存在", 404

# ------------------- SocketIO 事件处理 -------------------
@socketio.on('connect')
def handle_connect():
    global phone_sid
    from flask import request
    phone_sid = request.sid
    print('手机已连接, sid:', phone_sid)
    signal_emitter.phone_connected.emit(True)

@socketio.on('disconnect')
def handle_disconnect():
    global phone_sid
    print('手机断开连接, sid:', phone_sid)
    phone_sid = None
    signal_emitter.phone_connected.emit(False)

@socketio.on('text_message')
def handle_text_message(data):
    msg = data.get('message', '')
    print(f"收到手机文本: {msg}")
    # 转发给所有其他客户端（包括桌面端我们自己）
    # 但桌面端通过信号更新，所以这里直接让桌面端接收
    signal_emitter.received_text.emit(msg, 'phone')
    # 同时也可以广播给其他手机（如果有多个），这里只做双向，不广播
    # 如果希望手机自己也能看到自己发的，已经在手机端本地添加，所以这里不再回传

@socketio.on('upload_complete')
def handle_upload_complete(data):
    msg = f"📤 手机上传了文件: {data.get('filename')} ({data.get('size')} 字节)"
    signal_emitter.received_text.emit(msg, 'system')

@socketio.on('file_uploaded')
def handle_file_uploaded(data):
    """手机上传文件完成，通知桌面端"""
    file_id = data.get('file_id')
    filename = data.get('filename')
    print(f"手机上传文件完成: {filename}")
    signal_emitter.received_file.emit(file_id, filename)

# ------------------- 线程间通信辅助对象 -------------------
class SignalEmitter(QObject):
    # 信号：文本接收（内容，来源 'phone'/'system'）
    received_text = pyqtSignal(str, str)
    # 信号：文件接收（file_id, filename）
    received_file = pyqtSignal(str, str)
    # 手机连接状态
    phone_connected = pyqtSignal(bool)

signal_emitter = SignalEmitter()

# ------------------- PyQt5 桌面端窗口 -------------------
class LanChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("局域网双向传输 v2.0")
        self.setGeometry(100, 100, 550, 700)
        self.setMinimumSize(500, 600)

        # 样式表 - 现代扁平风格
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f6fa;
            }
            QLabel#title {
                font-size: 20px;
                font-weight: bold;
                color: #2d3436;
                padding: 8px;
            }
            QLabel#ipLabel {
                font-size: 12px;
                color: #636e72;
            }
            QPushButton {
                background-color: #6c5ce7;
                color: white;
                border: none;
                border-radius: 20px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a4bd1;
            }
            QPushButton:pressed {
                background-color: #4a3db5;
            }
            QPushButton#sendFileBtn {
                background-color: #00b894;
            }
            QPushButton#sendFileBtn:hover {
                background-color: #00a381;
            }
            QListWidget {
                border: 1px solid #dfe6e9;
                border-radius: 15px;
                padding: 8px;
                background-color: white;
                font-size: 13px;
            }
            QTextEdit {
                border: 1px solid #dfe6e9;
                border-radius: 15px;
                padding: 8px;
                background-color: white;
                font-size: 14px;
            }
            QScrollBar:vertical {
                border: none;
                background: #dfe6e9;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #b2bec3;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)

        # 标题行 - 包含标题和关于按钮
        title_layout = QHBoxLayout()
        title_layout.addStretch()
        
        self.title_label = QLabel("📡 局域网双向传输")
        self.title_label.setObjectName("title")
        self.title_label.setAlignment(Qt.AlignCenter)
        
        # 关于按钮
        self.about_btn = QPushButton("ℹ️ 关于")
        self.about_btn.setFixedSize(80, 35)
        self.about_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #6c5ce7;
                border: none;
                border-radius: 8px;
                padding: 5px 12px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f0f0ff;
            }
            QPushButton:pressed {
                background-color: #e0e0ff;
            }
        """)
        self.about_btn.clicked.connect(self.show_about_dialog)
        
        title_layout.addWidget(self.title_label)
        title_layout.addWidget(self.about_btn)
        title_layout.addStretch()

        # 二维码展示
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setFixedHeight(200)

        # IP 地址显示
        self.ip_label = QLabel()
        self.ip_label.setObjectName("ipLabel")
        self.ip_label.setAlignment(Qt.AlignCenter)

        # 连接状态
        self.status_label = QLabel("手机未连接")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #d63031; font-weight: bold;")

        # 下载路径显示和设置
        path_container = QWidget()
        path_container.setStyleSheet("""
            QWidget {
                background-color: white;
                border: 1px solid #dfe6e9;
                border-radius: 12px;
                padding: 10px;
            }
        """)
        path_container_layout = QVBoxLayout(path_container)
        path_container_layout.setContentsMargins(10, 10, 10, 10)
        path_container_layout.setSpacing(8)
        
        path_title = QLabel("📁 下载路径")
        path_title.setStyleSheet("color: #2d3436; font-weight: bold; font-size: 13px;")
        
        self.download_path_label = QLabel(DOWNLOAD_FOLDER)
        self.download_path_label.setStyleSheet("color: #636e72; font-size: 12px;")
        self.download_path_label.setWordWrap(True)
        self.download_path_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        self.change_path_btn = QPushButton("更改下载路径")
        self.change_path_btn.setFixedHeight(35)
        self.change_path_btn.setStyleSheet("""
            QPushButton {
                background-color: #00b894;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00a381;
            }
            QPushButton:pressed {
                background-color: #008f71;
            }
        """)
        self.change_path_btn.clicked.connect(self.change_download_path)
        
        path_container_layout.addWidget(path_title)
        path_container_layout.addWidget(self.download_path_label)
        path_container_layout.addWidget(self.change_path_btn)

        # 消息列表 - 使用只读文本框，支持复制
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chat_display.setStyleSheet("""
            QTextEdit {
                border: 1px solid #dfe6e9;
                border-radius: 15px;
                padding: 10px;
                background-color: white;
                font-size: 13px;
            }
            QScrollBar:vertical {
                border: none;
                background: #dfe6e9;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #b2bec3;
                border-radius: 4px;
            }
        """)

        # 输入区域
        self.input_layout = QHBoxLayout()
        self.text_input = QTextEdit()
        self.text_input.setMaximumHeight(60)
        self.text_input.setPlaceholderText("输入要发送的文字...")
        self.send_text_btn = QPushButton("发送")
        self.send_file_btn = QPushButton("📎 文件")
        self.send_file_btn.setObjectName("sendFileBtn")
        self.send_folder_btn = QPushButton("📁 文件夹")
        self.send_folder_btn.setObjectName("sendFolderBtn")
        self.send_folder_btn.setStyleSheet("""
            QPushButton#sendFolderBtn {
                background-color: #fdcb6e;
                color: #2d3436;
            }
            QPushButton#sendFolderBtn:hover {
                background-color: #f9ca24;
            }
            QPushButton#sendFolderBtn:pressed {
                background-color: #e1b621;
            }
        """)
        self.input_layout.addWidget(self.text_input)
        self.input_layout.addWidget(self.send_text_btn)
        self.input_layout.addWidget(self.send_file_btn)
        self.input_layout.addWidget(self.send_folder_btn)

        # 添加到主布局
        self.main_layout.addLayout(title_layout)
        self.main_layout.addWidget(self.qr_label)
        self.main_layout.addWidget(self.ip_label)
        self.main_layout.addWidget(self.status_label)
        self.main_layout.addWidget(path_container)
        self.main_layout.addWidget(self.chat_display)
        self.main_layout.addLayout(self.input_layout)

        # 连接信号
        self.send_text_btn.clicked.connect(self.send_text)
        self.send_file_btn.clicked.connect(self.send_file)
        self.send_folder_btn.clicked.connect(self.send_folder)
        self.text_input.installEventFilter(self)  # 处理回车发送

        # 连接信号发射器
        signal_emitter.received_text.connect(self.add_message)
        signal_emitter.phone_connected.connect(self.update_connection_status)
        signal_emitter.received_file.connect(self.handle_received_file)

        # 启动后更新二维码
        self.update_qr_and_ip()

        # 设置焦点
        self.text_input.setFocus()

    def eventFilter(self, obj, event):
        """实现回车发送（Ctrl+Enter 换行）"""
        from PyQt5.QtCore import QEvent
        if obj is self.text_input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Return and not (event.modifiers() & Qt.ControlModifier):
                self.send_text()
                return True
        return super().eventFilter(obj, event)

    def update_qr_and_ip(self):
        lan_ip = get_lan_ip()
        port = 5000
        server_url = f"http://{lan_ip}:{port}"
        self.ip_label.setText(f"服务器地址: {server_url}   (手机需连接同一 Wi-Fi)")

        # 生成二维码
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(server_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#2d3436", back_color="white")
        # 转换为 QPixmap 并缩放
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue())
        self.qr_label.setPixmap(pixmap.scaledToHeight(190, Qt.SmoothTransformation))

    def add_message(self, content, source):
        """在聊天文本框中添加一条消息"""
        if source == 'phone':
            prefix = "📱 手机: "
            color = "#0984e3"
        elif source == 'pc':
            prefix = "💻 本机: "
            color = "#6c5ce7"
        else:
            prefix = ""
            color = "#636e72"

        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        
        # 设置消息颜色
        format = cursor.charFormat()
        format.setFontPointSize(13)
        cursor.setCharFormat(format)
        
        # 添加消息文本
        self.chat_display.append(f'<span style="color: {color};">{prefix}{content}</span>')
        self.chat_display.verticalScrollBar().setValue(
            self.chat_display.verticalScrollBar().maximum()
        )

    def update_connection_status(self, connected):
        if connected:
            self.status_label.setText("📱 手机已连接")
            self.status_label.setStyleSheet("color: #00b894; font-weight: bold;")
        else:
            self.status_label.setText("手机未连接")
            self.status_label.setStyleSheet("color: #d63031; font-weight: bold;")

    def show_about_dialog(self):
        """显示关于对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("关于 局域网双向传输")
        dialog.setFixedSize(450, 700)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #f5f6fa;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        
        # 标题
        title_label = QLabel("📡 局域网双向传输")
        title_label.setStyleSheet("""
            color: #2d3436;
            font-size: 22px;
            font-weight: bold;
            padding: 10px;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 版本号
        version_label = QLabel("版本 v2.0")
        version_label.setStyleSheet("""
            color: #636e72;
            font-size: 14px;
            padding: 5px;
        """)
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: #dfe6e9;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #b2bec3;
                border-radius: 4px;
            }
        """)
        
        # 滚动内容容器
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 10, 5, 10)
        scroll_layout.setSpacing(12)
        
        # 分隔线
        line = QLabel()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #dfe6e9; margin: 5px 0;")
        scroll_layout.addWidget(line)
        
        # 简介
        intro_label = QLabel("🔧 简介")
        intro_label.setStyleSheet("color: #2d3436; font-size: 15px; font-weight: bold;")
        scroll_layout.addWidget(intro_label)
        
        intro_text = QLabel(
            "一款简洁高效的局域网文件传输工具，"
            "支持电脑与手机之间的实时消息和文件互传。\n"
            "专为同一网络环境下的快速文件共享而设计。"
        )
        intro_text.setWordWrap(True)
        intro_text.setStyleSheet("color: #636e72; font-size: 13px; line-height: 1.6;")
        scroll_layout.addWidget(intro_text)
        
        # 特性
        features_label = QLabel("✨ 特性")
        features_label.setStyleSheet("color: #2d3436; font-size: 15px; font-weight: bold;")
        scroll_layout.addWidget(features_label)
        
        features_text = QLabel(
            "• 本地局域网传输，无需互联网\n"
            "• 支持大文件高速传输\n"
            "• 实时消息和文件互传\n"
            "• 扫码即可连接"
        )
        features_text.setWordWrap(True)
        features_text.setStyleSheet("color: #636e72; font-size: 13px; line-height: 1.8;")
        scroll_layout.addWidget(features_text)
        
        # 隐私声明标题
        privacy_label = QLabel("🔒 隐私与安全")
        privacy_label.setStyleSheet("color: #2d3436; font-size: 15px; font-weight: bold;")
        scroll_layout.addWidget(privacy_label)
        
        # 隐私声明内容
        privacy_text = QLabel(
            "【重要声明】\n\n"
            "✓ 本软件仅在本地局域网内传输数据\n"
            "✓ 不上传任何数据到远程服务器\n"
            "✓ 不收集、不窃取用户隐私信息\n"
            "✓ 不监控、不记录用户剪贴板内容\n"
            "✓ 无后台运行、无隐蔽数据传输"
        )
        privacy_text.setWordWrap(True)
        privacy_text.setStyleSheet("""
            color: #636e72;
            font-size: 12px;
            line-height: 1.6;
            background-color: white;
            border: 1px solid #dfe6e9;
            border-radius: 8px;
            padding: 12px;
        """)
        scroll_layout.addWidget(privacy_text)
        
        # 免责声明标题
        disclaimer_label = QLabel("⚠️ 免责声明")
        disclaimer_label.setStyleSheet("color: #2d3436; font-size: 15px; font-weight: bold;")
        scroll_layout.addWidget(disclaimer_label)
        
        # 免责声明内容
        disclaimer_text = QLabel(
            "本软件为个人免费工具，仅供个人非商业用途使用。"
            "作者不对使用本软件造成的任何直接或间接损失负责。"
            "使用本软件即表示您同意上述条款。"
        )
        disclaimer_text.setWordWrap(True)
        disclaimer_text.setStyleSheet("""
            color: #636e72;
            font-size: 12px;
            line-height: 1.6;
            background-color: #fff8e6;
            border: 1px solid #ffc107;
            border-radius: 8px;
            padding: 12px;
        """)
        scroll_layout.addWidget(disclaimer_text)
        
        # 联系与反馈
        contact_label = QLabel("📧 联系与反馈")
        contact_label.setStyleSheet("color: #2d3436; font-size: 15px; font-weight: bold;")
        scroll_layout.addWidget(contact_label)
        
        contact_text = QLabel(
            "如有问题或建议，欢迎反馈！\n"
            "您的反馈是我们改进的动力。"
        )
        contact_text.setWordWrap(True)
        contact_text.setStyleSheet("color: #636e72; font-size: 12px; line-height: 1.6;")
        scroll_layout.addWidget(contact_text)
        
        # 将滚动内容添加到滚动区域
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)
        
        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.setFixedHeight(40)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c5ce7;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a4bd1;
            }
        """)
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        
        dialog.exec_()

    def change_download_path(self):
        """更改下载路径"""
        global DOWNLOAD_FOLDER
        new_path = QFileDialog.getExistingDirectory(
            self, "选择下载文件夹", DOWNLOAD_FOLDER
        )
        if new_path and new_path != DOWNLOAD_FOLDER:
            DOWNLOAD_FOLDER = new_path
            self.download_path_label.setText(DOWNLOAD_FOLDER)
            config['download_path'] = DOWNLOAD_FOLDER
            if save_config(config):
                self.add_message(f"下载路径已更改: {DOWNLOAD_FOLDER}", 'system')
            if not os.path.exists(DOWNLOAD_FOLDER):
                os.makedirs(DOWNLOAD_FOLDER)

    def handle_received_file(self, file_id, filename):
        """处理收到的文件"""
        self.add_message(f"收到文件: {filename}", 'system')
        threading.Thread(target=self.download_and_open_file, args=(file_id, filename), daemon=True).start()

    def download_and_open_file(self, file_id, filename):
        """下载并打开文件"""
        try:
            import requests
            lan_ip = get_lan_ip()
            download_url = f"http://{lan_ip}:5000/get_file/{file_id}"
            save_path = os.path.join(DOWNLOAD_FOLDER, filename)
            
            # 如果文件已存在，直接打开
            if os.path.exists(save_path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(save_path))
                self.add_message(f"已打开: {filename}", 'system')
                return
            
            # 下载文件
            response = requests.get(download_url, timeout=30)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                QDesktopServices.openUrl(QUrl.fromLocalFile(save_path))
                self.add_message(f"已下载并打开: {filename}", 'system')
            else:
                self.add_message(f"下载失败: {filename}", 'system')
        except Exception as e:
            self.add_message(f"打开文件出错: {str(e)}", 'system')

    def send_text(self):
        text = self.text_input.toPlainText().strip()
        print(f"\n=== send_text 方法调用 ===")
        print(f"输入文本: {text}")
        
        if not text:
            print("✗ 文本为空，不发送")
            return
        
        # 检查手机是否连接
        print(f"phone_sid = {phone_sid}")
        if not phone_sid:
            self.add_message("手机未连接，无法发送", 'system')
            print("✗ 手机未连接")
            return
        
        # 同时显示在本机界面
        self.add_message(text, 'pc')
        self.text_input.clear()
        
        # 使用 server.emit 直接发送（绕过请求上下文检查）
        try:
            print("尝试使用 server.emit 发送消息...")
            socketio.server.emit('text_message', {'message': text}, room=phone_sid)
            print(f"✓ 消息发送成功到 room: {phone_sid}")
        except Exception as e:
            self.add_message(f"发送失败: {e}", 'system')
            print(f"✗ server.emit 发送失败: {e}")
            import traceback
            traceback.print_exc()

    def send_file(self):
        """选择多个文件并生成下载链接推送给手机"""
        print(f"\n=== send_file 方法调用 ===")
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择要发送的文件（可多选）")
        
        if not file_paths:
            print("✗ 未选择文件")
            return
        
        # 检查手机是否连接
        print(f"phone_sid = {phone_sid}")
        if not phone_sid:
            self.add_message("手机未连接，无法发送文件", 'system')
            print("✗ 手机未连接")
            return
        
        file_count = len(file_paths)
        self.add_message(f"📎 正在发送 {file_count} 个文件...", 'pc')
        
        success_count = 0
        for file_path in file_paths:
            filename = os.path.basename(file_path)
            print(f"选择的文件: {filename}")
            
            file_id = str(uuid.uuid4())[:8]
            temp_downloads[file_id] = (filename, file_path)
            download_url = f"http://{get_lan_ip()}:5000/download/{file_id}"
            
            try:
                print("尝试使用 server.emit 发送文件链接...")
                socketio.server.emit('file_download', {'url': download_url, 'filename': filename}, room=phone_sid)
                print(f"✓ 文件链接发送成功到 room: {phone_sid}")
                success_count += 1
            except Exception as e:
                self.add_message(f"发送文件失败 {filename}: {e}", 'system')
                print(f"✗ server.emit 发送失败: {e}")
                import traceback
                traceback.print_exc()
        
        self.add_message(f"✅ 已发送 {success_count}/{file_count} 个文件", 'pc')

    def send_folder(self):
        """选择文件夹并压缩后发送给手机"""
        print(f"\n=== send_folder 方法调用 ===")
        folder_path = QFileDialog.getExistingDirectory(self, "选择要发送的文件夹")
        
        if not folder_path:
            print("✗ 未选择文件夹")
            return
        
        # 检查手机是否连接
        print(f"phone_sid = {phone_sid}")
        if not phone_sid:
            self.add_message("手机未连接，无法发送文件夹", 'system')
            print("✗ 手机未连接")
            return
        
        folder_name = os.path.basename(folder_path)
        print(f"选择的文件夹: {folder_name}")
        
        self.add_message(f"📁 正在压缩文件夹: {folder_name}...", 'pc')
        
        try:
            temp_dir = tempfile.gettempdir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"{folder_name}_{timestamp}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)
            
            file_count = 0
            total_size = 0
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, folder_path)
                        zipf.write(file_path, arcname)
                        file_count += 1
                        total_size += os.path.getsize(file_path)
            
            _temp_zip_files.add(zip_path)
            
            zip_size = os.path.getsize(zip_path)
            size_str = self.format_size(zip_size)
            
            self.add_message(f"📦 压缩完成: {file_count} 个文件, 大小: {size_str}", 'pc')
            
            file_id = str(uuid.uuid4())[:8]
            temp_downloads[file_id] = (zip_filename, zip_path)
            download_url = f"http://{get_lan_ip()}:5000/download/{file_id}"
            
            socketio.server.emit('file_download', {'url': download_url, 'filename': zip_filename}, room=phone_sid)
            self.add_message(f"📎 已发送文件夹: {folder_name}.zip ({size_str})", 'pc')
            print(f"✓ 文件夹压缩包发送成功")
            
        except Exception as e:
            self.add_message(f"发送文件夹失败: {e}", 'system')
            print(f"✗ 发送文件夹失败: {e}")
            import traceback
            traceback.print_exc()

    def format_size(self, bytes_size):
        """格式化文件大小"""
        if bytes_size == 0:
            return "0 B"
        k = 1024
        sizes = ['B', 'KB', 'MB', 'GB']
        i = int((len(str(bytes_size)) - 1) // 3)
        i = min(i, len(sizes) - 1)
        return f"{bytes_size / (k ** i):.2f} {sizes[i]}"

    def closeEvent(self, event):
        """窗口关闭时停止 Flask 服务并清理临时文件"""
        cleanup_temp_files()
        os._exit(0)  # 简易退出，实际项目中可以优雅关闭

# ------------------- 工具函数 -------------------
def send_text_to_clients(text):
    """在后台任务中发送文本消息（一对一）"""
    print(f"=== 发送文本消息 ===")
    print(f"当前线程: {threading.current_thread().name}")
    global phone_sid
    print(f"phone_sid = {phone_sid}")
    
    if phone_sid:
        try:
            # 直接使用 socketio 发送（在后台任务中不需要额外的 app_context）
            print(f"准备发送消息: {text}")
            socketio.emit('text_message', {'message': text}, to=phone_sid)
            print(f"✓ 消息发送成功到 sid: {phone_sid}")
        except Exception as e:
            print(f"✗ 发送失败: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("✗ 没有连接的手机客户端")

def send_file_to_clients(download_url, filename):
    """在后台任务中发送文件下载链接（一对一）"""
    print(f"=== 发送文件链接 ===")
    print(f"当前线程: {threading.current_thread().name}")
    global phone_sid
    print(f"phone_sid = {phone_sid}")
    
    if phone_sid:
        try:
            print(f"准备发送文件: {filename}, URL: {download_url}")
            socketio.emit('file_download', {'url': download_url, 'filename': filename}, to=phone_sid)
            print(f"✓ 文件链接发送成功到 sid: {phone_sid}")
        except Exception as e:
            print(f"✗ 发送失败: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("✗ 没有连接的手机客户端")

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

# ------------------- 启动服务 -------------------
def start_flask():
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ------------------- 临时文件清理 -------------------
def cleanup_temp_files():
    """清理所有临时压缩包文件"""
    global _temp_zip_files
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

if __name__ == '__main__':
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='局域网双向传输工具')
    parser.add_argument('--download-path', type=str, help='设置文件下载保存路径')
    args = parser.parse_args()

    # 应用命令行参数（优先级最高）
    if args.download_path:
        DOWNLOAD_FOLDER = args.download_path
        config['download_path'] = DOWNLOAD_FOLDER
        save_config(config)

    # 确保下载目录存在
    if not os.path.exists(DOWNLOAD_FOLDER):
        os.makedirs(DOWNLOAD_FOLDER)

    # 启动 Flask-SocketIO 在守护线程
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # 启动 PyQt5 应用
    qt_app = QApplication(sys.argv)
    window = LanChatWindow()
    window.show()
    sys.exit(qt_app.exec_())