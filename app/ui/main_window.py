import os
import sys
import uuid
import zipfile
import tempfile
import socket
from datetime import datetime

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QFileDialog, QDialog, QScrollArea,
    QListWidget, QListWidgetItem, QSplitter, QFrame
)
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QPixmap, QColor, QFont
import qrcode
from PIL import Image
from io import BytesIO

from app.signal import signal_emitter
from app.config import save_config, DEFAULT_DOWNLOAD_FOLDER
from app.utils import get_lan_ips, format_size
from app.server import temp_downloads, _temp_zip_files, socketio, phone_sids
from app.discovery import DeviceDiscovery
from app.pc_client import PCClient
from app.ui.device_selector import DeviceSelector


class LanChatWindow(QMainWindow):
    def __init__(self, download_folder):
        super().__init__()
        self.DOWNLOAD_FOLDER = download_folder
        self.phone_sid = None
        self.pc_client = None
        self.setWindowTitle("局域网双向传输 v2.0")
        self.setGeometry(100, 100, 820, 650)
        self.setMinimumSize(680, 550)

        # ---- 数据 ----
        self.devices = {}                        # key -> device_info
        self.chat_history = {}                   # key -> list of dicts
        self.current_chat_key = None             # 当前选中的设备 key
        self._last_phone_sid = None              # 最近收到手机消息的 SID

        # ---- 全局样式 ----
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f6fa;
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

        # ============================================================
        # 主布局：QSplitter 左右分割
        # ============================================================
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(2)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #dfe6e9;
            }
        """)

        # ---- 左侧面板 ----
        self.left_panel = self._build_left_panel()
        self.splitter.addWidget(self.left_panel)

        # ---- 右侧面板 ----
        self.right_panel = self._build_right_panel()
        self.splitter.addWidget(self.right_panel)

        # 设置初始比例：左侧约 160px，其余给右侧
        self.splitter.setSizes([180, 640])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.splitter)

        # ============================================================
        # 信号连接
        # ============================================================
        self.send_text_btn.clicked.connect(self.send_text)
        self.send_file_btn.clicked.connect(self.send_file)
        self.send_folder_btn.clicked.connect(self.send_folder)
        self.text_input.installEventFilter(self)

        signal_emitter.received_text.connect(self.add_message)
        signal_emitter.phone_connected.connect(self._update_phone_status)
        signal_emitter.received_file.connect(self.handle_received_file)
        signal_emitter.phone_sid_updated.connect(self.update_phone_sid)
        signal_emitter.phone_text_sid.connect(self._on_phone_text_source)
        signal_emitter.device_connected.connect(self._on_device_connected)
        signal_emitter.device_disconnected.connect(self._on_device_disconnected)

        # 设备发现
        self.lan_ip = self._choose_lan_ip()
        hostname = socket.gethostname()
        self.discovery = DeviceDiscovery(hostname, self.lan_ip)
        self.discovery.device_found.connect(self._on_pc_device_found)
        self.discovery.device_lost.connect(self._on_pc_device_lost)
        self.discovery.start()

        self.update_qr_and_ip()
        self._show_placeholder()
        self.text_input.setFocus()

    def _choose_lan_ip(self):
        """弹出 IP 选择对话框，让用户选择使用的局域网 IP。"""
        ips = get_lan_ips()
        if len(ips) == 1:
            print(f"使用局域网 IP: {ips[0]}")
            return ips[0]

        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QRadioButton,
                                     QButtonGroup, QDialogButtonBox, QLabel)

        dialog = QDialog(self)
        dialog.setWindowTitle("选择局域网 IP")
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel("检测到多个局域网 IP，请选择要使用的地址："))

        group = QButtonGroup(dialog)
        for i, ip in enumerate(ips):
            btn = QRadioButton(f"  {ip}")
            if i == 0:
                btn.setChecked(True)
            group.addButton(btn, i)
            layout.addWidget(btn)

        layout.addSpacing(10)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() == QDialog.Accepted:
            selected = ips[group.checkedId()]
        else:
            selected = ips[0]  # 取消则用第一个

        print(f"用户选择 IP: {selected}")
        return selected

    # ================================================================
    # UI 构建
    # ================================================================

    def _build_left_panel(self) -> QWidget:
        """构建左侧面板（标题 + 折叠服务器信息 + 设备列表）"""
        panel = QWidget()
        panel.setObjectName("leftPanel")
        panel.setStyleSheet("""
            QWidget#leftPanel {
                background-color: #ffffff;
                border-right: 1px solid #dfe6e9;
            }
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(8)

        # ---- 顶部：标题 + 关于按钮 ----
        title_row = QHBoxLayout()
        title_label = QLabel("📡 局域网传输")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2d3436;")
        about_btn = QPushButton("ℹ️")
        about_btn.setFixedSize(30, 30)
        about_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #6c5ce7;
                border: none;
                border-radius: 15px;
                font-size: 16px;
                padding: 0;
            }
            QPushButton:hover {
                background-color: #f0f0ff;
            }
        """)
        about_btn.clicked.connect(self.show_about_dialog)
        title_row.addWidget(title_label)
        title_row.addStretch()
        title_row.addWidget(about_btn)
        layout.addLayout(title_row)

        # ---- 折叠服务器信息 ----
        self._server_info_visible = False
        self.server_info_toggle = QPushButton("📡 服务器信息 ▸")
        self.server_info_toggle.setObjectName("serverInfoToggle")
        self.server_info_toggle.setStyleSheet("""
            QPushButton#serverInfoToggle {
                background-color: #f0f0ff;
                color: #6c5ce7;
                border: 1px solid #dfe6e9;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
                text-align: left;
            }
            QPushButton#serverInfoToggle:hover {
                background-color: #e8e8ff;
            }
        """)
        self.server_info_toggle.clicked.connect(self._toggle_server_info)
        layout.addWidget(self.server_info_toggle)

        # 服务器信息内容（默认隐藏）
        self.server_info_content = QWidget()
        self.server_info_content.setVisible(False)
        info_layout = QVBoxLayout(self.server_info_content)
        info_layout.setContentsMargins(4, 4, 4, 4)
        info_layout.setSpacing(6)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setFixedHeight(100)
        info_layout.addWidget(self.qr_label)

        self.ip_label = QLabel()
        self.ip_label.setObjectName("ipLabel")
        self.ip_label.setAlignment(Qt.AlignCenter)
        self.ip_label.setStyleSheet("font-size: 11px; color: #636e72;")
        info_layout.addWidget(self.ip_label)

        self.status_label = QLabel("手机未连接")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #d63031; font-weight: bold; font-size: 11px;")
        info_layout.addWidget(self.status_label)

        # 下载路径
        path_box = QWidget()
        path_box.setStyleSheet("background-color: #f8f9fa; border-radius: 8px; padding: 6px;")
        path_box_layout = QVBoxLayout(path_box)
        path_box_layout.setContentsMargins(6, 6, 6, 6)
        path_box_layout.setSpacing(4)

        path_title = QLabel("📁 下载路径")
        path_title.setStyleSheet("color: #2d3436; font-weight: bold; font-size: 11px;")

        self.download_path_label = QLabel(self.DOWNLOAD_FOLDER)
        self.download_path_label.setStyleSheet("color: #636e72; font-size: 10px;")
        self.download_path_label.setWordWrap(True)

        self.change_path_btn = QPushButton("更改")
        self.change_path_btn.setFixedHeight(28)
        self.change_path_btn.setStyleSheet("""
            QPushButton {
                background-color: #00b894;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00a381;
            }
        """)
        self.change_path_btn.clicked.connect(self.change_download_path)

        path_box_layout.addWidget(path_title)
        path_box_layout.addWidget(self.download_path_label)
        path_box_layout.addWidget(self.change_path_btn)
        info_layout.addWidget(path_box)

        layout.addWidget(self.server_info_content)

        # ---- 设备列表 ----
        device_header = QLabel("📡 设备列表")
        device_header.setStyleSheet("color: #2d3436; font-weight: bold; font-size: 12px;")
        layout.addWidget(device_header)

        self.device_list = QListWidget()
        self.device_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #dfe6e9;
                border-radius: 8px;
                background-color: #f8f9fa;
                font-size: 12px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 6px 8px;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background-color: #e8e8ff;
            }
            QListWidget::item:selected {
                background-color: #6c5ce7;
                color: white;
            }
        """)
        self.device_list.itemClicked.connect(self._on_device_selected)
        self.device_list.itemDoubleClicked.connect(self._on_device_double_clicked)
        layout.addWidget(self.device_list, 1)  # stretch factor 1, fills remaining space

        return panel

    def _build_right_panel(self) -> QWidget:
        """构建右侧面板（聊天标题 + 消息区 + 输入区）"""
        panel = QWidget()
        panel.setObjectName("rightPanel")
        panel.setStyleSheet("QWidget#rightPanel { background-color: #ffffff; }")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # ---- 聊天标题 ----
        self.chat_header = QLabel("请选择一个设备开始聊天")
        self.chat_header.setObjectName("chatHeader")
        self.chat_header.setAlignment(Qt.AlignCenter)
        self.chat_header.setStyleSheet("""
            QLabel#chatHeader {
                font-size: 15px;
                font-weight: bold;
                color: #2d3436;
                padding: 8px;
                background-color: #f8f9fa;
                border: 1px solid #dfe6e9;
                border-radius: 10px;
            }
        """)
        layout.addWidget(self.chat_header)

        # ---- 聊天消息显示区 ----
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chat_display.setStyleSheet("""
            QTextEdit {
                border: 1px solid #dfe6e9;
                border-radius: 12px;
                padding: 12px;
                background-color: #fafafa;
                font-size: 13px;
            }
        """)
        layout.addWidget(self.chat_display, 1)

        # ---- 输入区域 ----
        input_container = QWidget()
        input_container.setStyleSheet("background-color: transparent;")
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)

        self.text_input = QTextEdit()
        self.text_input.setMaximumHeight(60)
        self.text_input.setPlaceholderText("输入要发送的文字...")
        self.text_input.setStyleSheet("""
            QTextEdit {
                border: 1px solid #dfe6e9;
                border-radius: 12px;
                padding: 8px 12px;
                background-color: white;
                font-size: 13px;
            }
        """)

        btn_style = """
            QPushButton {
                border-radius: 12px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
        """
        self.send_text_btn = QPushButton("发送")
        self.send_text_btn.setStyleSheet(btn_style)

        self.send_file_btn = QPushButton("📎 文件")
        self.send_file_btn.setObjectName("sendFileBtn")

        self.send_folder_btn = QPushButton("📁 文件夹")
        self.send_folder_btn.setObjectName("sendFolderBtn")

        # 按钮尺寸
        for btn in (self.send_text_btn, self.send_file_btn, self.send_folder_btn):
            btn.setFixedHeight(38)

        input_layout.addWidget(self.text_input, 1)
        input_layout.addWidget(self.send_text_btn)
        input_layout.addWidget(self.send_file_btn)
        input_layout.addWidget(self.send_folder_btn)

        layout.addWidget(input_container)

        return panel

    # ================================================================
    # 折叠服务器信息
    # ================================================================

    def _toggle_server_info(self):
        """切换服务器信息面板的展开/折叠"""
        self._server_info_visible = not self._server_info_visible
        self.server_info_content.setVisible(self._server_info_visible)
        arrow = "▾" if self._server_info_visible else "▸"
        self.server_info_toggle.setText(f"📡 服务器信息 {arrow}")

    # ================================================================
    # 设备列表管理
    # ================================================================

    def _add_device_to_list(self, key, device_type, display_name, **kwargs):
        if key not in self.devices:
            self.devices[key] = {'type': device_type, 'display_name': display_name, **kwargs}
        else:
            self.devices[key].update({'display_name': display_name, **kwargs})
        self._refresh_device_list()

    def _remove_device_from_list(self, key):
        if key in self.devices:
            # 如果移除的设备是当前聊天对象，清除选中状态
            if self.current_chat_key == key:
                self.current_chat_key = None
                self._show_placeholder()
            del self.devices[key]
            if key in self.chat_history:
                del self.chat_history[key]
            self._refresh_device_list()

    def _refresh_device_list(self):
        self.device_list.clear()

        phone_items = [(k, v) for k, v in self.devices.items() if v['type'] == 'phone']
        pc_items = [(k, v) for k, v in self.devices.items() if v['type'] == 'pc']

        def add_section(title):
            item = QListWidgetItem(title)
            item.setFlags(Qt.NoItemFlags)
            item.setForeground(QColor('#636e72'))
            font = QFont()
            font.setBold(True)
            font.setPointSize(9)
            item.setFont(font)
            self.device_list.addItem(item)

        if phone_items:
            add_section("📱 手机设备")
            for key, info in phone_items:
                item = QListWidgetItem(info['display_name'])
                item.setData(Qt.UserRole, key)
                item.setData(Qt.UserRole + 1, info['type'])
                item.setForeground(QColor('#0984e3'))
                self.device_list.addItem(item)

        if pc_items:
            add_section("🖥️ PC 设备")
            for key, info in pc_items:
                item = QListWidgetItem(info['display_name'])
                item.setData(Qt.UserRole, key)
                item.setData(Qt.UserRole + 1, info['type'])
                item.setForeground(QColor('#6c5ce7'))
                self.device_list.addItem(item)

    def _on_device_connected(self, sid, device_type, display_name):
        """手机设备连接"""
        if device_type == 'pc':
            return  # PC 设备由 UDP 发现管理，避免重复
        self._add_device_to_list(sid, device_type, display_name, sid=sid)
        self._update_phone_status()

    def _on_device_disconnected(self, sid):
        """手机设备断开"""
        self._remove_device_from_list(sid)
        self._update_phone_status()

    def _on_pc_device_found(self, device_info):
        """发现 PC 设备"""
        device_name = device_info.get('device_name', 'Unknown')
        ip = device_info.get('ip', '')
        display_name = f"🖥️ {device_name} ({ip})"
        self._add_device_to_list(ip, 'pc', display_name,
                                 device_name=device_name, ip=ip,
                                 port=device_info.get('port', 5000))

    def _on_pc_device_lost(self, device_info):
        """PC 设备离线"""
        ip = device_info.get('ip', '')
        if ip in self.devices and self.devices[ip]['type'] == 'pc':
            if self.pc_client and hasattr(self.pc_client, 'target_ip') and self.pc_client.target_ip == ip:
                self.pc_client.disconnect()
                self.pc_client = None
            self._remove_device_from_list(ip)

    # ================================================================
    # 设备选中 & 聊天切换
    # ================================================================

    def _on_device_selected(self, item):
        """单击设备列表项 —— 切换聊天视图"""
        key = item.data(Qt.UserRole)
        if key is None:
            return  # 点击的是分组标题
        self._switch_chat(key)

    def _on_device_double_clicked(self, item):
        """双击设备列表项 —— 如果是 PC 则发起连接"""
        device_type = item.data(Qt.UserRole + 1)
        key = item.data(Qt.UserRole)
        if key is None:
            return
        if device_type != 'pc':
            return

        device_info = self.devices.get(key)
        if not device_info:
            return

        target_ip = device_info['ip']
        target_port = device_info.get('port', 5000)

        if self.pc_client and self.pc_client._connected and self.pc_client.target_ip == target_ip:
            self.add_message(f"已连接到 {device_info['device_name']} ({target_ip})", 'system')
            return

        if self.pc_client:
            self.pc_client.disconnect()
            self.pc_client = None

        self.pc_client = PCClient(target_ip, target_port)
        self.pc_client.connected.connect(self._on_pc_connected)
        self.pc_client.disconnected.connect(self._on_pc_disconnected)
        self.pc_client.text_received.connect(self._on_pc_text_received)
        self.pc_client.file_received.connect(self._on_pc_file_received)

        self.add_message(f"正在连接到 PC {device_info['device_name']} ({target_ip})...", 'system')
        try:
            self.pc_client.connect()
        except Exception as e:
            self.add_message(f"连接 PC 失败: {e}", 'system')
            self.pc_client = None

    def _ensure_pc_connection(self, device_info):
        """确保已连接到指定 PC 设备，未连接则自动尝试连接。返回 True/False。"""
        target_ip = device_info['ip']
        target_port = device_info.get('port', 5000)

        if self.pc_client and self.pc_client._connected and self.pc_client.target_ip == target_ip:
            return True

        if self.pc_client:
            try:
                self.pc_client.disconnect()
            except Exception:
                pass
            self.pc_client = None

        # 建立新连接
        self.pc_client = PCClient(target_ip, target_port)
        self.pc_client.connected.connect(self._on_pc_connected)
        self.pc_client.disconnected.connect(self._on_pc_disconnected)
        self.pc_client.text_received.connect(self._on_pc_text_received)
        self.pc_client.file_received.connect(self._on_pc_file_received)

        try:
            self.pc_client.connect()
            return True
        except Exception as e:
            self.add_message(f"连接 PC {device_info.get('device_name', target_ip)} 失败: {e}", 'system')
            self.pc_client = None
            return False

    def _switch_chat(self, key):
        """切换到指定设备的聊天视图"""
        self.current_chat_key = key
        device_info = self.devices.get(key)
        if device_info:
            self.chat_header.setText(f"💬 与 {device_info['display_name']} 聊天")
        else:
            self.chat_header.setText("💬 聊天")
        self._render_chat_history()

    def _show_placeholder(self):
        """未选择设备时显示占位提示"""
        self.chat_header.setText("请选择一个设备开始聊天")
        self.chat_display.setHtml("""
            <div style="text-align: center; padding: 60px 20px;">
                <div style="font-size: 48px; margin-bottom: 16px;">💬</div>
                <div style="font-size: 16px; color: #b2bec3;">
                    请选择一个设备开始聊天
                </div>
                <div style="font-size: 13px; color: #dfe6e9; margin-top: 8px;">
                    点击左侧设备列表中的设备查看聊天
                </div>
            </div>
        """)

    def _render_chat_history(self):
        """根据 current_chat_key 渲染聊天历史"""
        if self.current_chat_key is None:
            self._show_placeholder()
            return

        history = self.chat_history.get(self.current_chat_key, [])
        html_parts = []
        for entry in history:
            html_parts.append(self._build_bubble_html(
                entry['content'], entry['source'],
                is_file=entry.get('is_file', False),
                timestamp=entry.get('timestamp', '')
            ))

        full_html = "<html><body style='margin: 0; padding: 0;'>" + "".join(html_parts) + "</body></html>"
        self.chat_display.setHtml(full_html)
        self.chat_display.verticalScrollBar().setValue(
            self.chat_display.verticalScrollBar().maximum()
        )

    # ================================================================
    # 消息气泡
    # ================================================================

    @staticmethod
    def _build_bubble_html(content, source, is_file=False, timestamp=""):
        """构造单条消息的 HTML 气泡"""
        ts_html = ""
        if timestamp:
            ts_html = f'<div style="font-size: 10px; color: #b2bec3; margin-top: 2px;">{timestamp}</div>'

        if source == 'system':
            return (
                f'<div style="text-align: center; margin: 6px 0;">'
                f'<span style="font-size: 11px; color: #b2bec3;">{content}</span>'
                f'{ts_html}'
                f'</div>'
            )

        if source == 'pc':
            # PC 消息 —— 右对齐，紫色
            text_color = "white"
            bg_color = "#6c5ce7"
            border_radius = "10px 10px 0 10px"
            align = "right"
            link_color = "white"
        elif source == 'remote_pc':
            # 远程 PC 消息 —— 左对齐，浅灰绿
            text_color = "#2d3436"
            bg_color = "#e8f5e9"
            border_radius = "10px 10px 10px 0"
            align = "left"
            link_color = "#0984e3"
        else:
            # 手机消息 —— 左对齐，浅灰
            text_color = "#2d3436"
            bg_color = "#f0f0f0"
            border_radius = "10px 10px 10px 0"
            align = "left"
            link_color = "#0984e3"

        if is_file:
            inner = f'📎 <a style="color: {link_color}; text-decoration: underline;" href="#">{content}</a>'
        else:
            inner = content.replace("\n", "<br>")

        return (
            f'<div style="text-align: {align}; margin: 5px 0;">'
            f'<span style="display: inline-block; background-color: {bg_color}; color: {text_color}; '
            f'padding: 8px 14px; border-radius: {border_radius}; max-width: 70%; '
            f'word-wrap: break-word; line-height: 1.4;">'
            f'{inner}'
            f'</span>'
            f'{ts_html}'
            f'</div>'
        )

    def _on_phone_text_source(self, sid):
        """记录最近收到手机消息的来源 SID"""
        self._last_phone_sid = sid

    def _find_pc_device_key(self, content):
        """从远程 PC 消息内容 [PC_Name] 中提取 PC 名，返回对应的设备 key（IP）"""
        import re
        m = re.match(r'^\[(.+?)\]\s', content)
        if not m:
            return None
        pc_name = m.group(1)
        for key, info in self.devices.items():
            if info['type'] == 'pc' and info.get('device_name') == pc_name:
                return key
        return None

    def add_message(self, content, source, is_file=False):
        """
        添加消息到聊天历史。

        扩展自原始签名 (self, content, source)，增加 is_file 参数。
        source 取值：'pc'（本机发送）、'remote_pc'（远程 PC 收到）、'phone'（手机收到）、'system'（系统消息）
        is_file=True 时以文件气泡样式渲染。
        """
        now_str = datetime.now().strftime("%H:%M")

        if source == 'pc':
            # 本机发送的消息 —— 存入当前聊天对象
            if self.current_chat_key:
                self._append_to_history(self.current_chat_key, content, source, is_file, now_str)
                self._render_chat_history()
            else:
                # 未选设备时仍记录但暂不显示
                if self.current_chat_key:
                    self._append_to_history(self.current_chat_key, content, source, is_file, now_str)

        elif source == 'remote_pc':
            # 远程 PC 发来的消息 —— 从内容中提取 PC 名，存入对应 PC 设备的历史
            target_key = self._find_pc_device_key(content)
            if target_key:
                self._append_to_history(target_key, content, source, is_file, now_str)
                if self.current_chat_key == target_key:
                    self._render_chat_history()
            else:
                # 找不到目标 PC 时回退到当前聊天对象
                if self.current_chat_key:
                    self._append_to_history(self.current_chat_key, content, source, is_file, now_str)
                    self._render_chat_history()

        elif source == 'phone':
            # 来自手机的消息 —— 只存入来源手机的历史
            source_sid = getattr(self, '_last_phone_sid', None)
            target_key = None
            if source_sid:
                for key, info in self.devices.items():
                    if info['type'] == 'phone' and info.get('sid') == source_sid:
                        target_key = key
                        break
            if target_key:
                self._append_to_history(target_key, content, source, is_file, now_str)
                if self.current_chat_key == target_key:
                    self._render_chat_history()
            else:
                # 找不到来源时回退：存入所有手机（兼容旧事件流）
                for key, info in self.devices.items():
                    if info['type'] == 'phone':
                        self._append_to_history(key, content, source, is_file, now_str)
                if self.current_chat_key and self.devices.get(self.current_chat_key, {}).get('type') == 'phone':
                    self._render_chat_history()

        elif source == 'system':
            # 系统消息 —— 存入当前聊天对象（如果有）；否则存入所有设备
            if self.current_chat_key:
                self._append_to_history(self.current_chat_key, content, source, is_file, now_str)
                self._render_chat_history()
            else:
                for key in self.devices:
                    self._append_to_history(key, content, source, is_file, now_str)

    def _append_to_history(self, key, content, source, is_file, timestamp):
        """向指定设备的聊天历史追加一条消息"""
        if key not in self.chat_history:
            self.chat_history[key] = []
        self.chat_history[key].append({
            'content': content,
            'source': source,
            'is_file': is_file,
            'timestamp': timestamp
        })

    # ================================================================
    # 连接状态
    # ================================================================

    def _update_phone_status(self):
        if self.pc_client and self.pc_client._connected:
            return
        count = len(phone_sids)
        if count > 0:
            self.status_label.setText(f"📱 {count} 台手机已连接")
            self.status_label.setStyleSheet("color: #00b894; font-weight: bold; font-size: 11px;")
        else:
            self.status_label.setText("手机未连接")
            self.status_label.setStyleSheet("color: #d63031; font-weight: bold; font-size: 11px;")

    def update_connection_status(self, connected):
        if connected:
            self.status_label.setText("📱 手机已连接")
            self.status_label.setStyleSheet("color: #00b894; font-weight: bold; font-size: 11px;")
        else:
            self.status_label.setText("手机未连接")
            self.status_label.setStyleSheet("color: #d63031; font-weight: bold; font-size: 11px;")

    def update_phone_sid(self, sid):
        self.phone_sid = sid

    def _on_pc_connected(self):
        if self.pc_client:
            self.status_label.setText(f"已连接到 {self.pc_client.target_ip}")
            self.status_label.setStyleSheet("color: #00b894; font-weight: bold; font-size: 11px;")

    def _on_pc_disconnected(self):
        self.pc_client = None
        self._update_phone_status()

    def _on_pc_text_received(self, msg, sender):
        self.add_message(msg, 'remote_pc')

    def _on_pc_file_received(self, file_id, filename):
        self.handle_received_file(file_id, filename, source_sid='pc')

    # ================================================================
    # 事件
    # ================================================================

    def eventFilter(self, obj, event):
        if obj is self.text_input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Return and not (event.modifiers() & Qt.ControlModifier):
                self.send_text()
                return True
        return super().eventFilter(obj, event)

    # ================================================================
    # QR / IP
    # ================================================================

    def update_qr_and_ip(self):
        lan_ip = self.lan_ip
        port = 5000
        server_url = f"http://{lan_ip}:{port}"
        self.ip_label.setText(f"服务器地址: {server_url}")

        qr = qrcode.QRCode(version=1, box_size=4, border=2)
        qr.add_data(server_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#2d3436", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue())
        self.qr_label.setPixmap(pixmap.scaledToHeight(90, Qt.SmoothTransformation))

    # ================================================================
    # 关于对话框
    # ================================================================

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

    # ================================================================
    # 下载路径
    # ================================================================

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

    # ================================================================
    # 文件接收
    # ================================================================

    def handle_received_file(self, file_id, filename, source_sid=None):
        print(f"收到文件通知: file_id={file_id}, filename={filename}")
        self.add_message(f"收到文件: {filename}", 'system')
        import threading
        threading.Thread(target=self.download_and_open_file, args=(file_id, filename), daemon=True).start()

    def download_and_open_file(self, file_id, filename):
        try:
            import requests
            download_url = f"http://127.0.0.1:5000/get_file/{file_id}"
            # 确保中间目录存在（文件名可能包含路径，如 "文件夹/文件.txt"）
            safe_filename = filename.replace('\\', '/')
            save_path = os.path.join(self.DOWNLOAD_FOLDER, safe_filename)
            save_dir = os.path.dirname(save_path)
            if save_dir and not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True)

            print(f"开始下载文件: {download_url} → {save_path}")

            if os.path.exists(save_path):
                print(f"文件已存在: {save_path}")
                signal_emitter.received_text.emit(f"文件已存在: {filename}", 'system')
                return

            response = requests.get(download_url, timeout=30)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                print(f"文件下载成功: {save_path} ({len(response.content)} 字节)")
                signal_emitter.received_text.emit(f"已下载: {filename}", 'system')
            else:
                print(f"下载失败: HTTP {response.status_code}")
                signal_emitter.received_text.emit(
                    f"下载失败: {filename} (HTTP {response.status_code})", 'system')
        except Exception as e:
            print(f"下载文件出错: {e}")
            signal_emitter.received_text.emit(f"下载文件出错: {str(e)}", 'system')

    # ================================================================
    # 发送文本
    # ================================================================

    def _get_target_keys(self):
        """
        获取发送目标设备列表。
        如果已在左侧设备列表中选中某设备，直接返回该设备 key；
        否则弹出设备选择对话框让用户选择。
        """
        if self.current_chat_key and self.current_chat_key in self.devices:
            return [self.current_chat_key]

        dialog = DeviceSelector(self.devices, self)
        if dialog.exec_() != QDialog.Accepted:
            return None

        keys = dialog.get_selected_devices()
        return keys if keys else None

    def send_text(self):
        text = self.text_input.toPlainText().strip()

        if not text:
            return

        if not self.devices:
            self.add_message("没有已连接的设备，无法发送", 'system')
            return

        target_keys = self._get_target_keys()
        if not target_keys:
            return

        self.add_message(text, 'pc')
        self.text_input.clear()

        # 发送到选中的目标设备
        for key in target_keys:
            device = self.devices.get(key)
            if not device:
                continue

            if device['type'] == 'phone':
                try:
                    socketio.server.emit('text_message', {'message': text}, room=key)
                except Exception as e:
                    self.add_message(f"发送到手机失败: {e}", 'system')

            elif device['type'] == 'pc':
                if not (self.pc_client and self.pc_client._connected
                        and self.pc_client.target_ip == device.get('ip', '')):
                    if not self._ensure_pc_connection(device):
                        continue
                try:
                    self.pc_client.send_text(text)
                except Exception as e:
                    self.add_message(f"发送到 PC 失败: {e}", 'system')

    # ================================================================
    # 发送文件 / 文件夹（带设备选择器）
    # ================================================================

    def send_file(self):
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择要发送的文件（可多选）")

        if not file_paths:
            return

        if not self.devices:
            self.add_message("没有已连接的设备，无法发送文件", 'system')
            return

        target_keys = self._get_target_keys()
        if not target_keys:
            return

        self._send_file_to_targets(file_paths, target_keys)

    def send_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择要发送的文件夹")

        if not folder_path:
            return

        if not self.devices:
            self.add_message("没有已连接的设备，无法发送文件夹", 'system')
            return

        target_keys = self._get_target_keys()
        if not target_keys:
            return

        self._send_folder_to_targets(folder_path, target_keys)

    # ================================================================
    # 实际发送逻辑
    # ================================================================

    def _send_file_to_targets(self, file_paths, target_keys):
        """
        将文件列表发送到指定设备列表。

        target_keys 中的 key 可能是手机 SID 或 PC 的 IP。
        手机通过 socketio 广播，PC 通过 pc_client 发送。
        """
        file_count = len(file_paths)
        self.add_message(f"📎 正在发送 {file_count} 个文件...", 'pc')

        success_count = 0
        for file_path in file_paths:
            filename = os.path.basename(file_path)
            file_id = str(uuid.uuid4())[:8]
            temp_downloads[file_id] = (filename, file_path)
            download_url = f"http://{self.lan_ip}:5000/download/{file_id}"

            sent_any = False

            for key in target_keys:
                device = self.devices.get(key)
                if not device:
                    continue

                if device['type'] == 'phone':
                    # 发送到手机（SocketIO）
                    try:
                        socketio.server.emit(
                            'file_download',
                            {'url': download_url, 'filename': filename},
                            room=key
                        )
                        sent_any = True
                    except Exception as e:
                        self.add_message(f"发送文件到手机失败 {filename}: {e}", 'system')

                elif device['type'] == 'pc':
                    # 发送到 PC（自动连接）
                    if not (self.pc_client and self.pc_client._connected
                            and self.pc_client.target_ip == device.get('ip', '')):
                        if not self._ensure_pc_connection(device):
                            continue
                    try:
                        self.pc_client.send_file(file_path)
                        sent_any = True
                    except Exception as e:
                        self.add_message(f"发送文件到 PC 失败 {filename}: {e}", 'system')

            if sent_any:
                success_count += 1
                self.add_message(f"📎 已发送: {filename}", 'pc', is_file=True)

        self.add_message(f"✅ 已发送 {success_count}/{file_count} 个文件", 'pc')

    def _send_folder_to_targets(self, folder_path, target_keys):
        """
        将文件夹压缩后发送到指定设备列表。
        """
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
            download_url = f"http://{self.lan_ip}:5000/download/{file_id}"

            sent_any = False

            for key in target_keys:
                device = self.devices.get(key)
                if not device:
                    continue

                if device['type'] == 'phone':
                    try:
                        socketio.server.emit(
                            'file_download',
                            {'url': download_url, 'filename': zip_filename},
                            room=key
                        )
                        sent_any = True
                    except Exception as e:
                        self.add_message(f"发送文件夹到手机失败: {e}", 'system')

                elif device['type'] == 'pc':
                    if not (self.pc_client and self.pc_client._connected
                            and self.pc_client.target_ip == device.get('ip', '')):
                        if not self._ensure_pc_connection(device):
                            continue
                    try:
                        self.pc_client.send_file(zip_path)
                        sent_any = True
                    except Exception as e:
                        self.add_message(f"发送文件夹到 PC 失败: {e}", 'system')

            if sent_any:
                self.add_message(f"📎 已发送文件夹: {folder_name}.zip ({size_str})", 'pc', is_file=True)
            else:
                self.add_message("❌ 文件夹发送失败", 'pc')
        except Exception as e:
            self.add_message(f"发送文件夹失败: {e}", 'system')

    # ================================================================
    # 关闭
    # ================================================================

    def closeEvent(self, event):
        if self.discovery:
            self.discovery.stop()
        if self.pc_client:
            self.pc_client.disconnect()
            self.pc_client = None
        from app.server import cleanup_temp_files
        cleanup_temp_files()
        os._exit(0)
