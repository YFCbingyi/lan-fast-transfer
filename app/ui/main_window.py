import os
import sys
import uuid
import zipfile
import tempfile
from datetime import datetime

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QFileDialog, QDialog, QScrollArea
)
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QPixmap
import qrcode
from PIL import Image
from io import BytesIO

from app.signal import signal_emitter
from app.config import save_config, DEFAULT_DOWNLOAD_FOLDER
from app.utils import get_lan_ip, format_size
from app.server import temp_downloads, _temp_zip_files, socketio

class LanChatWindow(QMainWindow):
    def __init__(self, download_folder):
        super().__init__()
        self.DOWNLOAD_FOLDER = download_folder
        self.phone_sid = None
        self.setWindowTitle("局域网双向传输 v2.0")
        self.setGeometry(100, 100, 550, 700)
        self.setMinimumSize(500, 600)

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
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)

        title_layout = QHBoxLayout()
        title_layout.addStretch()
        
        self.title_label = QLabel("📡 局域网双向传输")
        self.title_label.setObjectName("title")
        self.title_label.setAlignment(Qt.AlignCenter)
        
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
        """)
        self.about_btn.clicked.connect(self.show_about_dialog)
        
        title_layout.addWidget(self.title_label)
        title_layout.addWidget(self.about_btn)
        title_layout.addStretch()

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setFixedHeight(200)

        self.ip_label = QLabel()
        self.ip_label.setObjectName("ipLabel")
        self.ip_label.setAlignment(Qt.AlignCenter)

        self.status_label = QLabel("手机未连接")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #d63031; font-weight: bold;")

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
        
        self.download_path_label = QLabel(self.DOWNLOAD_FOLDER)
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
        """)
        self.change_path_btn.clicked.connect(self.change_download_path)
        
        path_container_layout.addWidget(path_title)
        path_container_layout.addWidget(self.download_path_label)
        path_container_layout.addWidget(self.change_path_btn)

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.input_layout = QHBoxLayout()
        self.text_input = QTextEdit()
        self.text_input.setMaximumHeight(60)
        self.text_input.setPlaceholderText("输入要发送的文字...")
        self.send_text_btn = QPushButton("发送")
        self.send_file_btn = QPushButton("📎 文件")
        self.send_file_btn.setObjectName("sendFileBtn")
        self.send_folder_btn = QPushButton("📁 文件夹")
        self.send_folder_btn.setObjectName("sendFolderBtn")
        self.input_layout.addWidget(self.text_input)
        self.input_layout.addWidget(self.send_text_btn)
        self.input_layout.addWidget(self.send_file_btn)
        self.input_layout.addWidget(self.send_folder_btn)

        self.main_layout.addLayout(title_layout)
        self.main_layout.addWidget(self.qr_label)
        self.main_layout.addWidget(self.ip_label)
        self.main_layout.addWidget(self.status_label)
        self.main_layout.addWidget(path_container)
        self.main_layout.addWidget(self.chat_display)
        self.main_layout.addLayout(self.input_layout)

        self.send_text_btn.clicked.connect(self.send_text)
        self.send_file_btn.clicked.connect(self.send_file)
        self.send_folder_btn.clicked.connect(self.send_folder)
        self.text_input.installEventFilter(self)

        signal_emitter.received_text.connect(self.add_message)
        signal_emitter.phone_connected.connect(self.update_connection_status)
        signal_emitter.received_file.connect(self.handle_received_file)
        signal_emitter.phone_sid_updated.connect(self.update_phone_sid)

        self.update_qr_and_ip()
        self.text_input.setFocus()

    def eventFilter(self, obj, event):
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

        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(server_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#2d3436", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue())
        self.qr_label.setPixmap(pixmap.scaledToHeight(190, Qt.SmoothTransformation))

    def add_message(self, content, source):
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
        
        format = cursor.charFormat()
        format.setFontPointSize(13)
        cursor.setCharFormat(format)
        
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

    def update_phone_sid(self, sid):
        self.phone_sid = sid

    def show_about_dialog(self):
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
        
        title_label = QLabel("📡 局域网双向传输")
        title_label.setStyleSheet("""
            color: #2d3436;
            font-size: 22px;
            font-weight: bold;
            padding: 10px;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        version_label = QLabel("版本 v2.0")
        version_label.setStyleSheet("""
            color: #636e72;
            font-size: 14px;
            padding: 5px;
        """)
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)
        
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
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 10, 5, 10)
        scroll_layout.setSpacing(12)
        
        line = QLabel()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #dfe6e9; margin: 5px 0;")
        scroll_layout.addWidget(line)
        
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
        
        features_label = QLabel("✨ 特性")
        features_label.setStyleSheet("color: #2d3436; font-size: 15px; font-weight: bold;")
        scroll_layout.addWidget(features_label)
        
        features_text = QLabel(
            "• 本地局域网传输，无需互联网\n"
            "• 支持大文件高速传输\n"
            "• 实时消息和文件互传\n"
            "• 支持多文件和文件夹传输\n"
            "• 扫码即可连接"
        )
        features_text.setWordWrap(True)
        features_text.setStyleSheet("color: #636e72; font-size: 13px; line-height: 1.8;")
        scroll_layout.addWidget(features_text)
        
        privacy_label = QLabel("🔒 隐私与安全")
        privacy_label.setStyleSheet("color: #2d3436; font-size: 15px; font-weight: bold;")
        scroll_layout.addWidget(privacy_label)
        
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
        
        disclaimer_label = QLabel("⚠️ 免责声明")
        disclaimer_label.setStyleSheet("color: #2d3436; font-size: 15px; font-weight: bold;")
        scroll_layout.addWidget(disclaimer_label)
        
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
        
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)
        
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
        new_path = QFileDialog.getExistingDirectory(
            self, "选择下载文件夹", self.DOWNLOAD_FOLDER
        )
        if new_path and new_path != self.DOWNLOAD_FOLDER:
            self.DOWNLOAD_FOLDER = new_path
            self.download_path_label.setText(self.DOWNLOAD_FOLDER)
            config = {'download_path': self.DOWNLOAD_FOLDER}
            if save_config(config):
                self.add_message(f"下载路径已更改: {self.DOWNLOAD_FOLDER}", 'system')
            if not os.path.exists(self.DOWNLOAD_FOLDER):
                os.makedirs(self.DOWNLOAD_FOLDER)

    def handle_received_file(self, file_id, filename):
        self.add_message(f"收到文件: {filename}", 'system')
        import threading
        threading.Thread(target=self.download_and_open_file, args=(file_id, filename), daemon=True).start()

    def download_and_open_file(self, file_id, filename):
        try:
            import requests
            download_url = f"http://127.0.0.1:5000/get_file/{file_id}"
            save_path = os.path.join(self.DOWNLOAD_FOLDER, filename)
            
            if os.path.exists(save_path):
                signal_emitter.received_text.emit(f"文件已存在: {filename}", 'system')
                return
            
            response = requests.get(download_url, timeout=30)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                signal_emitter.received_text.emit(f"已下载: {filename}", 'system')
            else:
                signal_emitter.received_text.emit(
                    f"下载失败: {filename} (HTTP {response.status_code})", 'system')
        except Exception as e:
            signal_emitter.received_text.emit(f"下载文件出错: {str(e)}", 'system')

    def send_text(self):
        text = self.text_input.toPlainText().strip()
        
        if not text:
            return
        
        if not self.phone_sid:
            self.add_message("手机未连接，无法发送", 'system')
            return
        
        self.add_message(text, 'pc')
        self.text_input.clear()
        
        try:
            socketio.server.emit('text_message', {'message': text}, room=self.phone_sid)
        except Exception as e:
            self.add_message(f"发送失败: {e}", 'system')

    def send_file(self):
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择要发送的文件（可多选）")
        
        if not file_paths:
            return
        
        if not self.phone_sid:
            self.add_message("手机未连接，无法发送文件", 'system')
            return
        
        file_count = len(file_paths)
        self.add_message(f"📎 正在发送 {file_count} 个文件...", 'pc')
        
        success_count = 0
        for file_path in file_paths:
            filename = os.path.basename(file_path)
            
            file_id = str(uuid.uuid4())[:8]
            temp_downloads[file_id] = (filename, file_path)
            download_url = f"http://{get_lan_ip()}:5000/download/{file_id}"
            
            try:
                socketio.server.emit('file_download', {'url': download_url, 'filename': filename}, room=self.phone_sid)
                success_count += 1
            except Exception as e:
                self.add_message(f"发送文件失败 {filename}: {e}", 'system')
        
        self.add_message(f"✅ 已发送 {success_count}/{file_count} 个文件", 'pc')

    def send_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择要发送的文件夹")
        
        if not folder_path:
            return
        
        if not self.phone_sid:
            self.add_message("手机未连接，无法发送文件夹", 'system')
            return
        
        folder_name = os.path.basename(folder_path)
        self.add_message(f"📁 正在压缩文件夹: {folder_name}...", 'pc')
        
        try:
            temp_dir = tempfile.gettempdir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"{folder_name}_{timestamp}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)
            
            file_count = 0
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, folder_path)
                        zipf.write(file_path, arcname)
                        file_count += 1
            
            _temp_zip_files.add(zip_path)
            
            zip_size = os.path.getsize(zip_path)
            size_str = format_size(zip_size)
            
            self.add_message(f"📦 压缩完成: {file_count} 个文件, 大小: {size_str}", 'pc')
            
            file_id = str(uuid.uuid4())[:8]
            temp_downloads[file_id] = (zip_filename, zip_path)
            download_url = f"http://{get_lan_ip()}:5000/download/{file_id}"
            
            socketio.server.emit('file_download', {'url': download_url, 'filename': zip_filename}, room=self.phone_sid)
            self.add_message(f"📎 已发送文件夹: {folder_name}.zip ({size_str})", 'pc')
            
        except Exception as e:
            self.add_message(f"发送文件夹失败: {e}", 'system')

    def closeEvent(self, event):
        from app.server import cleanup_temp_files
        cleanup_temp_files()
        os._exit(0)