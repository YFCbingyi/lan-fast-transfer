from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QCheckBox, QScrollArea, QWidget
)
from PyQt5.QtCore import Qt, QTimer

from app.ui.theme import COLORS
from app.ui.icons import (
    GlowButton, svg_pixmap, apply_theme, fade_widget,
)


class DeviceSelector(QDialog):
    """设备选择对话框，支持多选设备后发送文件/文件夹"""

    def __init__(self, devices, parent=None, default_keys=None):
        """
        :param devices: dict, 格式同 self.devices = {key: {'type': str, 'display_name': str, ...}}
        :param default_keys: 默认勾选的设备 key（通常是当前聊天对象）
        """
        super().__init__(parent)
        self.setWindowTitle("选择目标设备")
        self.setFixedSize(380, 420)

        self._checkboxes = {}       # key -> QCheckBox
        self._all_selected = False   # 是否点过"全选"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = QLabel("选择要发送到的设备")
        title.setStyleSheet(f"color: {COLORS['text']}; font-size: 15px; font-weight: 600;")
        layout.addWidget(title)

        hint = QLabel("可多选，文件将同时发送到勾选的设备")
        hint.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        layout.addWidget(hint)

        # 滚动区域 —— 设备列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: 1px solid {COLORS['border']}; "
            f"border-radius: 8px; background-color: {COLORS['surface']}; }}"
        )

        scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(scroll_content)
        self._scroll_layout.setContentsMargins(12, 10, 12, 10)
        self._scroll_layout.setSpacing(6)
        self._scroll_layout.addStretch()

        # 按类型分组添加设备
        phone_items = [(k, v) for k, v in devices.items() if v['type'] == 'phone']
        pc_items = [(k, v) for k, v in devices.items() if v['type'] == 'pc']

        if not phone_items and not pc_items:
            no_dev = QLabel("暂无已连接的设备")
            no_dev.setStyleSheet(f"color: {COLORS['subtle']}; font-size: 13px;")
            no_dev.setAlignment(Qt.AlignCenter)
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, no_dev)
        else:
            if phone_items:
                self._add_section_header("移动设备", 'phone')
                for key, info in phone_items:
                    self._add_device_checkbox(key, info, default_keys)

            if pc_items:
                self._add_section_header("PC 设备", 'monitor')
                for key, info in pc_items:
                    self._add_device_checkbox(key, info, default_keys)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.select_all_btn = GlowButton("全选")
        self.select_all_btn.setObjectName("secondary")
        self.select_all_btn.clicked.connect(self._on_select_all)

        self.send_btn = GlowButton("发送到所选设备")
        self.send_btn.clicked.connect(self.accept)

        self.cancel_btn = GlowButton("取消")
        self.cancel_btn.setObjectName("ghost")
        self.cancel_btn.clicked.connect(self.reject)

        for btn in (self.select_all_btn, self.send_btn, self.cancel_btn):
            btn.setFixedHeight(36)

        btn_layout.addWidget(self.select_all_btn)
        btn_layout.addWidget(self.send_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        if self._checkboxes and all(cb.isChecked() for cb in self._checkboxes.values()):
            self._all_selected = True
            self.select_all_btn.setText("取消全选")

        apply_theme(self)
        QTimer.singleShot(0, lambda: fade_widget(scroll_content))

    def _add_device_checkbox(self, key, info, default_keys):
        cb = QCheckBox(info['display_name'])
        cb.setChecked(key in (default_keys or []))
        cb.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px;")
        if info.get('ip'):
            cb.setToolTip(f"来源 IP: {info['ip']}")
        self._checkboxes[key] = cb
        self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, cb)

    def _add_section_header(self, text, icon):
        """添加分组标题（线性图标 + 文本，不用 emoji 作结构图标）"""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 6, 0, 2)
        row_layout.setSpacing(6)

        icon_label = QLabel()
        icon_label.setPixmap(svg_pixmap(icon, 14, COLORS['muted']))
        icon_label.setFixedSize(14, 14)

        text_label = QLabel(text)
        text_label.setObjectName("sectionTitle")

        row_layout.addWidget(icon_label)
        row_layout.addWidget(text_label)
        row_layout.addStretch()
        self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, row)

    def _on_select_all(self):
        """全选 / 取消全选切换"""
        all_checked = all(cb.isChecked() for cb in self._checkboxes.values())
        for cb in self._checkboxes.values():
            cb.setChecked(not all_checked)
        self._all_selected = not all_checked
        self.select_all_btn.setText("取消全选" if self._all_selected else "全选")

    def get_selected_devices(self):
        """返回选中的设备 ID 列表"""
        return [key for key, cb in self._checkboxes.items() if cb.isChecked()]

    def is_send_all(self):
        """返回当前是否选中了全部设备"""
        if not self._checkboxes:
            return False
        return all(cb.isChecked() for cb in self._checkboxes.values())
