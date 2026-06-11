from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QCheckBox, QPushButton, QScrollArea, QWidget
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor


class DeviceSelector(QDialog):
    """设备选择对话框，支持多选设备后发送文件/文件夹"""

    def __init__(self, devices, parent=None):
        """
        :param devices: dict, 格式同 self.devices = {key: {'type': str, 'display_name': str, ...}}
        """
        super().__init__(parent)
        self.setWindowTitle("选择目标设备")
        self.setFixedSize(360, 400)
        self.setStyleSheet("""
            QDialog {
                background-color: #f5f6fa;
            }
        """)

        self._checkboxes = {}       # key -> QCheckBox
        self._all_selected = False   # 是否点过"全选"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # 标题
        title = QLabel("请选择要发送到的设备：")
        title.setStyleSheet("color: #2d3436; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        # 滚动区域 —— 设备列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #dfe6e9;
                border-radius: 8px;
                background-color: white;
            }
            QScrollBar:vertical {
                border: none;
                background: #dfe6e9;
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #b2bec3;
                border-radius: 3px;
            }
        """)

        scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(scroll_content)
        self._scroll_layout.setContentsMargins(10, 10, 10, 10)
        self._scroll_layout.setSpacing(8)
        self._scroll_layout.addStretch()

        # 按类型分组添加设备
        phone_items = [(k, v) for k, v in devices.items() if v['type'] == 'phone']
        pc_items = [(k, v) for k, v in devices.items() if v['type'] == 'pc']

        if not phone_items and not pc_items:
            no_dev = QLabel("暂无已连接的设备")
            no_dev.setStyleSheet("color: #b2bec3; font-size: 13px;")
            no_dev.setAlignment(Qt.AlignCenter)
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, no_dev)
        else:
            if phone_items:
                self._add_section_header("📱 手机设备")
                for key, info in phone_items:
                    cb = QCheckBox(info['display_name'])
                    cb.setStyleSheet(f"color: #0984e3; font-size: 13px;")
                    self._checkboxes[key] = cb
                    self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, cb)

            if pc_items:
                self._add_section_header("🖥️ PC 设备")
                for key, info in pc_items:
                    cb = QCheckBox(info['display_name'])
                    cb.setStyleSheet(f"color: #6c5ce7; font-size: 13px;")
                    self._checkboxes[key] = cb
                    self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, cb)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #dfe6e9;
                color: #2d3436;
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #b2bec3;
            }
        """)
        self.select_all_btn.clicked.connect(self._on_select_all)

        self.send_btn = QPushButton("发送到所选设备")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c5ce7;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a4bd1;
            }
        """)
        self.send_btn.clicked.connect(self.accept)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #636e72;
                border: 1px solid #dfe6e9;
                border-radius: 8px;
                padding: 10px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
            }
        """)
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(self.select_all_btn)
        btn_layout.addWidget(self.send_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def _add_section_header(self, text):
        """添加分组标题"""
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #636e72; font-size: 11px; font-weight: bold;")
        self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, lbl)

    def _on_select_all(self):
        """全选/取消全选切换"""
        all_checked = all(cb.isChecked() for cb in self._checkboxes.values())
        for cb in self._checkboxes.values():
            cb.setChecked(not all_checked)
        self._all_selected = True

    def get_selected_devices(self):
        """返回选中的设备 ID 列表"""
        return [key for key, cb in self._checkboxes.items() if cb.isChecked()]

    def is_send_all(self):
        """返回当前是否选中了全部设备"""
        if not self._checkboxes:
            return False
        return all(cb.isChecked() for cb in self._checkboxes.values())
