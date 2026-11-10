"""桌面端图标与轻量过渡动效工具（基于 app/ui/theme.py 的统一令牌）。"""

from PyQt5.QtCore import Qt, QByteArray, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt5.QtWidgets import (
    QWidget, QPushButton, QGraphicsColorizeEffect, QGraphicsOpacityEffect
)

try:
    from PyQt5.QtSvg import QSvgRenderer
except ImportError:                      # 极简环境缺 QtSvg 时降级为无图标，不影响功能
    QSvgRenderer = None

from app.ui.theme import (
    svg, COLORS, ANIM_FAST_MS, ANIM_BASE_MS,
    reduced_motion, normalize_style_sheet,
)


def svg_pixmap(name, size=18, color=None):
    """把统一令牌里的 SVG 路径渲染成 QPixmap。"""
    if QSvgRenderer is None:
        return QPixmap()
    renderer = QSvgRenderer(QByteArray(svg(name, size, color or COLORS['primary']).encode('utf-8')))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def svg_icon(name, size=18, color=None):
    return QIcon(svg_pixmap(name, size, color))


class GlowButton(QPushButton):
    """hover / 按下时 150ms 平滑提亮，不覆盖全局 QSS 的其他属性。

    系统开启「减少动效」时退化为 QSS 自带的瞬时状态切换。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._glow = None
        self._anim = None
        if reduced_motion():
            return
        effect = QGraphicsColorizeEffect(self)
        effect.setColor(QColor('#FFFFFF'))
        effect.setStrength(0.0)
        self.setGraphicsEffect(effect)
        self._glow = effect
        self._anim = QPropertyAnimation(effect, b'strength', self)
        self._anim.setDuration(ANIM_FAST_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def _to(self, value):
        if self._glow is None:
            return
        self._anim.stop()
        self._anim.setStartValue(self._glow.strength())
        self._anim.setEndValue(value)
        self._anim.start()

    def enterEvent(self, event):
        self._to(0.22)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._to(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._to(0.06)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._to(0.22 if self.underMouse() else 0.0)
        super().mouseReleaseEvent(event)


def fade_widget(widget, duration=ANIM_BASE_MS):
    """控件内容淡入（聊天视图切换、对话框出现）。"""
    if reduced_motion() or widget is None:
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.55)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b'opacity', widget)
    anim.setDuration(duration)
    anim.setStartValue(0.55)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    widget._lft_fade = (effect, anim)        # 保活，避免动画被 GC 提前终止
    anim.start()


def height_animation(widget, start, end, duration=ANIM_BASE_MS):
    """折叠面板高度动画，调用方负责在 finished 时恢复 maximumHeight / 可见性。"""
    anim = QPropertyAnimation(widget, b'maximumHeight', widget)
    anim.setDuration(0 if reduced_motion() else duration)
    anim.setStartValue(int(start))
    anim.setEndValue(int(end))
    anim.setEasingCurve(QEasingCurve.OutCubic)
    return anim


def apply_theme(root):
    """把一棵控件树上的历史内联 QSS 归一化到当前视觉令牌。"""
    if root is None:
        return
    for widget in root.findChildren(QWidget):
        sheet = widget.styleSheet()
        if not sheet:
            continue
        normalized = normalize_style_sheet(sheet)
        if normalized != sheet:
            widget.setStyleSheet(normalized)
