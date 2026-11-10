"""
LanFastTransfer 统一视觉令牌（桌面 QSS + 手机 CSS）。

设计基线：Flat Design / 极简 2D / 无重阴影 / 主色 #2563EB / 强调色 #D97706 /
150-200ms 微动效（motion 3/10）。两端共用同一份颜色、圆角、时长与线性图标，
字体全部使用系统字体栈——软件运行在离线局域网，不引用任何外部字体或 CDN。

本模块只依赖标准库，服务端 app/server.py 可以安全导入。
"""

import os
from string import Template

# --------------------------------------------------------------------------
# 颜色 / 排版 / 动效令牌
# --------------------------------------------------------------------------

COLORS = {
    'bg': '#F8FAFC',
    'surface': '#FFFFFF',
    'surface_alt': '#F1F5F9',
    'primary_soft': '#EFF6FF',
    'accent_soft': '#FFFBEB',
    'success_soft': '#ECFDF5',
    'border': '#E2E8F0',
    'border_strong': '#CBD5E1',
    'text': '#0F172A',
    'muted': '#64748B',
    'subtle': '#94A3B8',
    'primary': '#2563EB',
    'primary_hover': '#1D4ED8',
    'primary_press': '#1E40AF',
    'primary_ring': 'rgba(37, 99, 235, 0.14)',
    'accent': '#D97706',
    'success': '#059669',
    'danger': '#DC2626',
    'warning': '#F59E0B',
    'on_primary': '#FFFFFF',
}

MOTION = {
    'fast': '150ms',
    'base': '200ms',
    'ease': 'cubic-bezier(0.22, 1, 0.36, 1)',
}
ANIM_FAST_MS = 150
ANIM_BASE_MS = 180

FONT_STACK = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', "
              "'Microsoft YaHei', Roboto, sans-serif")
DESKTOP_FONT = "'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif"


def reduced_motion():
    """是否减少动效：环境变量 > Windows「动画效果」系统设置。

    LFT_MOTION=full 可强制开启动效（用于自动化验证），
    LFT_REDUCED_MOTION=1 可强制关闭。
    """
    if os.environ.get('LFT_MOTION', '').strip().lower() == 'full':
        return False
    if os.environ.get('LFT_REDUCED_MOTION', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        return True
    if os.name == 'nt':
        try:
            import ctypes
            enabled = ctypes.c_int(0)
            # SPI_GETCLIENTAREAANIMATION = 0x1042
            ok = ctypes.windll.user32.SystemParametersInfoW(
                0x1042, 0, ctypes.byref(enabled), 0)
            if ok and not enabled.value:
                return True
        except Exception:
            pass
    return False


# --------------------------------------------------------------------------
# 线性图标（单一来源，桌面 QIcon 与手机内联 SVG 共用）
# --------------------------------------------------------------------------

ICON_PATHS = {
    'broadcast': '<circle cx="12" cy="12" r="2"/><path d="M8 8a5.7 5.7 0 0 0 0 8M16 8a5.7 5.7 0 0 1 0 8M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14"/>',
    'info': '<circle cx="12" cy="12" r="9"/><path d="M12 11.5v5M12 8h.01"/>',
    'file': '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    'folder': '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    'chevron_right': '<path d="m9 6 6 6-6 6"/>',
    'chevron_down': '<path d="m6 9 6 6 6-6"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'chat': '<path d="M20 14a3 3 0 0 1-3 3H9l-5 3V6a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3z"/>',
    'phone': '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
    'monitor': '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    'download': '<path d="M12 3v12M7 11l5 5 5-5M4 20h16"/>',
    'close': '<path d="M6 6l12 12M18 6 6 18"/>',
    'check': '<path d="m5 12 4 4L19 6"/>',
    'shield': '<path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6z"/>',
    'sparkle': '<path d="M12 3v6M12 15v6M3 12h6M15 12h6"/>',
    'mail': '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    'alert': '<path d="M12 3 2 20h20z"/><path d="M12 9v5M12 17h.01"/>',
    'server': '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
}


def svg(name, size=18, color='currentColor', stroke_width=1.8):
    """生成内联 SVG 字符串；手机端直接嵌入，桌面端交给 QSvgRenderer 渲染。"""
    body = ICON_PATHS.get(name, '')
    return (
        '<svg width="%s" height="%s" viewBox="0 0 24 24" fill="none" '
        'stroke="%s" stroke-width="%s" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true" focusable="false">%s</svg>'
        % (size, size, color, stroke_width, body)
    )


# 手机页 HTML 里的图标占位符 -> 具体 SVG
PHONE_ICON_TOKENS = {
    'LOGO': svg('broadcast', 19, COLORS['primary']),
    'LOGO_LIGHT': svg('broadcast', 20, COLORS['primary']),
    'INFO': svg('info', 18, COLORS['muted']),
    'PLUS': svg('plus', 20, COLORS['on_primary']),
    'SEND': svg('plus', 18, COLORS['primary']),
    'FILE': svg('file', 18, COLORS['primary']),
    'FOLDER': svg('folder', 18, COLORS['primary']),
    'FILE_16': svg('file', 16, 'currentColor'),
    'INFO_SECTION': svg('info', 16, COLORS['primary']),
    'SPARKLE_SECTION': svg('sparkle', 16, COLORS['primary']),
    'SHIELD_SECTION': svg('shield', 16, COLORS['primary']),
    'ALERT_SECTION': svg('alert', 16, COLORS['accent']),
}


# --------------------------------------------------------------------------
# 桌面 QSS
# --------------------------------------------------------------------------

_QSS_VARS = dict(COLORS, **MOTION, font=DESKTOP_FONT)

DESKTOP_QSS = Template("""
/* LanFastTransfer · 统一桌面主题（Flat Design） */
QWidget {
    font-family: $font;
    font-size: 13px;
    color: $text;
}
QMainWindow, QDialog { background-color: $bg; }
QToolTip {
    background-color: $text;
    color: $surface;
    border: none;
    border-radius: 6px;
    padding: 5px 8px;
}
QStatusBar { background-color: $surface; border-top: 1px solid $border; color: $muted; }
QStatusBar::item { border: none; }

QPushButton {
    background-color: $primary;
    color: $on_primary;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover { background-color: $primary_hover; }
QPushButton:pressed { background-color: $primary_press; }
QPushButton:disabled { background-color: $border_strong; color: $subtle; }
QPushButton#secondary {
    background-color: $surface_alt;
    color: $text;
    border: 1px solid $border;
}
QPushButton#secondary:hover { background-color: $border; }
QPushButton#primarySoft {
    background-color: $primary_soft;
    color: $primary;
    border: 1px solid #BFDBFE;
}
QPushButton#primarySoft:hover { background-color: #DBEAFE; }
QPushButton#accent {
    background-color: $accent_soft;
    color: $accent;
    border: 1px solid #FDE68A;
}
QPushButton#accent:hover { background-color: #FEF3C7; }
QPushButton#ghost {
    background-color: transparent;
    color: $muted;
    border: 1px solid $border;
}
QPushButton#ghost:hover { background-color: $surface_alt; color: $primary; }
QPushButton#iconOnly {
    background-color: transparent;
    color: $muted;
    border: none;
    border-radius: 8px;
    padding: 0;
}
QPushButton#iconOnly:hover { background-color: $primary_soft; color: $primary; }

QLabel { color: $text; background: transparent; }
QLabel#muted { color: $muted; }
QLabel#sectionTitle { color: $muted; font-size: 11px; font-weight: 600; }
QLabel#chatHeader {
    color: $text;
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 10px;
    font-size: 14px;
    font-weight: 600;
}
QTextEdit, QLineEdit {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: $primary_soft;
    selection-color: $text;
}
QTextEdit:focus, QLineEdit:focus { border-color: $primary; }
QTextEdit#chatDisplay { background-color: $surface_alt; }
QListWidget {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 4px;
}
QListWidget::item { padding: 8px 10px; border-radius: 6px; margin: 1px 2px; }
QListWidget::item:hover { background-color: $primary_soft; color: $text; }
QListWidget::item:selected { background-color: $primary; color: $on_primary; }
QComboBox {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 5px 10px;
}
QComboBox:hover { border-color: $border_strong; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 6px;
    selection-background-color: $primary_soft;
    selection-color: $text;
}
QCheckBox { color: $text; spacing: 8px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; border: none; }
QScrollBar::handle:vertical { background: $border_strong; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: $subtle; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; border: none; }
QScrollBar::handle:horizontal { background: $border_strong; border-radius: 4px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QScrollArea { background: transparent; border: none; }
QSplitter::handle { background-color: $border; }
QFrame#sep { background-color: $border; max-height: 1px; border: none; }
QProgressBar {
    background-color: $surface_alt;
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk { background-color: $primary; border-radius: 4px; }
""").substitute(**_QSS_VARS).strip()


# --------------------------------------------------------------------------
# 手机 CSS
# --------------------------------------------------------------------------

_CSS_VARS = dict(COLORS, **MOTION, font=FONT_STACK)

PHONE_CSS = Template("""
:root {
  --lft-bg: $bg;
  --lft-surface: $surface;
  --lft-surface-alt: $surface_alt;
  --lft-primary-soft: $primary_soft;
  --lft-accent-soft: $accent_soft;
  --lft-success: $success;
  --lft-border: $border;
  --lft-border-strong: $border_strong;
  --lft-text: $text;
  --lft-muted: $muted;
  --lft-subtle: $subtle;
  --lft-primary: $primary;
  --lft-primary-hover: $primary_hover;
  --lft-accent: $accent;
  --lft-danger: $danger;
  --lft-warning: $warning;
  --lft-ring: $primary_ring;
  --lft-radius: 12px;
  --lft-fast: $fast;
  --lft-base: $base;
  --lft-ease: $ease;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; }
body {
  font-family: $font;
  background: var(--lft-bg);
  color: var(--lft-text);
  -webkit-font-smoothing: antialiased;
  display: flex; justify-content: center; align-items: center;
}
.container {
  width: 100%; max-width: 480px; height: 100dvh;
  background: var(--lft-surface);
  border-left: 1px solid var(--lft-border);
  border-right: 1px solid var(--lft-border);
  display: flex; flex-direction: column; overflow: hidden;
}
@media (min-width: 560px) {
  .container {
    height: 86dvh; max-height: 820px;
    border: 1px solid var(--lft-border);
    border-radius: 16px;
    box-shadow: 0 1px 3px rgba(15, 23, 42, .06);
  }
}

.header {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px;
  background: var(--lft-surface);
  border-bottom: 1px solid var(--lft-border);
}
.brand { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.brand-mark {
  width: 34px; height: 34px; flex: none;
  display: grid; place-items: center;
  border-radius: 10px;
  background: var(--lft-primary-soft);
}
.brand-name { font-size: 15px; font-weight: 650; letter-spacing: .2px; line-height: 1.2; }
.brand-sub { font-size: 11px; color: var(--lft-subtle); margin-top: 2px; }

button {
  font-family: inherit;
  background: var(--lft-primary); color: #fff;
  border: 1px solid transparent; border-radius: 10px;
  padding: 8px 14px; font-size: 14px; font-weight: 600;
  cursor: pointer;
  transition: background-color var(--lft-fast) var(--lft-ease),
              color var(--lft-fast) var(--lft-ease),
              border-color var(--lft-fast) var(--lft-ease),
              transform var(--lft-fast) var(--lft-ease),
              box-shadow var(--lft-fast) var(--lft-ease);
}
button:hover { background: var(--lft-primary-hover); }
button:active { transform: scale(.98); }
button:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--lft-ring); }
.icon-btn {
  width: 34px; height: 34px; padding: 0; flex: none;
  display: grid; place-items: center;
  background: var(--lft-surface); color: var(--lft-muted);
  border: 1px solid var(--lft-border);
}
.icon-btn:hover { background: var(--lft-primary-soft); color: var(--lft-primary); border-color: #BFDBFE; }
.icon-about { display: inline-flex; font-size: 12px; font-weight: 600; gap: 5px; width: auto; padding: 0 10px; }

.messages {
  flex: 1; overflow-y: auto; overscroll-behavior: contain;
  padding: 16px 14px;
  background: var(--lft-bg);
  display: flex; flex-direction: column; gap: 10px;
  -webkit-overflow-scrolling: touch;
}
.msg {
  max-width: 82%; padding: 10px 13px;
  font-size: 14px; line-height: 1.55; word-wrap: break-word;
  animation: msg-in var(--lft-base) var(--lft-ease) both;
}
.msg.local { align-self: flex-end; background: var(--lft-primary); color: #fff; border-radius: 12px 12px 4px 12px; }
.msg.remote { align-self: flex-start; background: var(--lft-surface); border: 1px solid var(--lft-border); border-radius: 12px 12px 12px 4px; }
.file-link { display: inline-flex; align-items: center; gap: 6px; color: var(--lft-primary); font-weight: 600; text-decoration: none; }
.file-link span { border-bottom: 1px solid #BFDBFE; }
.status {
  align-self: center; max-width: 92%; text-align: center;
  font-size: 11px; color: var(--lft-subtle); padding: 2px 8px;
  animation: msg-in var(--lft-base) var(--lft-ease) both;
}
.status::before { content: ''; display: inline-block; width: 4px; height: 4px; border-radius: 50%; background: var(--lft-border-strong); vertical-align: middle; margin-right: 6px; }

.input-area {
  position: relative; display: flex; align-items: center; gap: 8px;
  padding: 10px 12px;
  background: var(--lft-surface); border-top: 1px solid var(--lft-border);
}
#textInput {
  flex: 1; min-width: 0; height: 40px;
  border: 1px solid var(--lft-border); border-radius: 10px;
  background: var(--lft-surface-alt); color: var(--lft-text);
  padding: 0 12px; font-size: 16px; outline: none;
  transition: border-color var(--lft-fast) var(--lft-ease),
              box-shadow var(--lft-fast) var(--lft-ease),
              background-color var(--lft-fast) var(--lft-ease);
}
#textInput:focus { border-color: var(--lft-primary); background: var(--lft-surface); box-shadow: 0 0 0 3px var(--lft-ring); }
#textInput::placeholder { color: var(--lft-subtle); }
#plusBtn { width: 40px; height: 40px; padding: 0; display: grid; place-items: center; flex: none; }
#sendBtn { height: 40px; padding: 0 16px; flex: none; }
#fileInput, #dirInput { display: none; }

.progress-container { width: 100%; align-self: center; height: 6px; background: var(--lft-border); border-radius: 999px; overflow: hidden; }
.progress-bar { height: 100%; width: 0; background: var(--lft-primary); border-radius: 999px; transition: width var(--lft-base) var(--lft-ease), background-color var(--lft-base) var(--lft-ease); }
.upload-status { font-size: 12px; color: var(--lft-muted); }

.popup-menu {
  position: absolute; bottom: 62px; right: 12px; min-width: 176px;
  background: var(--lft-surface); border: 1px solid var(--lft-border);
  border-radius: var(--lft-radius); overflow: hidden; z-index: 10;
  box-shadow: 0 8px 24px rgba(15, 23, 42, .10);
  opacity: 0; visibility: hidden; pointer-events: none; transform: translateY(6px);
  transition: opacity var(--lft-fast) var(--lft-ease),
              transform var(--lft-base) var(--lft-ease),
              visibility 0s linear var(--lft-fast);
}
.popup-menu.show { opacity: 1; visibility: visible; pointer-events: auto; transform: none; transition-delay: 0s; }
.popup-item {
  display: flex; align-items: center; gap: 10px;
  width: 100%; padding: 11px 16px;
  background: var(--lft-surface); color: var(--lft-text);
  border: none; border-radius: 0; font-size: 14px; font-weight: 500;
  text-align: left; white-space: nowrap;
  transition: background-color var(--lft-fast) var(--lft-ease);
}
.popup-item:hover { background: var(--lft-primary-soft); }
.popup-item:active { transform: none; }
.popup-item + .popup-item { border-top: 1px solid var(--lft-border); }
.popup-item svg { color: var(--lft-primary); flex: none; }
.popup-overlay { display: none; position: fixed; inset: 0; z-index: 9; }

.about-modal {
  display: flex; justify-content: center; align-items: center;
  position: fixed; inset: 0; padding: 16px; z-index: 1000;
  background: rgba(15, 23, 42, .42);
  opacity: 0; visibility: hidden; pointer-events: none;
  transition: opacity var(--lft-base) var(--lft-ease), visibility 0s linear var(--lft-base);
}
.about-modal.is-open { opacity: 1; visibility: visible; pointer-events: auto; transition-delay: 0s; }
.about-content {
  background: var(--lft-surface); width: 100%; max-width: 360px;
  border: 1px solid var(--lft-border); border-radius: 16px;
  padding: 20px; max-height: 85dvh; overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  transform: translateY(10px) scale(.99);
  transition: transform var(--lft-base) var(--lft-ease);
}
.about-modal.is-open .about-content { transform: none; }
.about-title { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 650; color: var(--lft-text); margin-bottom: 4px; }
.about-version { font-size: 12px; color: var(--lft-subtle); text-align: center; margin-bottom: 12px; }
.about-section { margin: 16px 0; }
.about-section-title { display: flex; align-items: center; gap: 7px; font-size: 13px; font-weight: 650; color: var(--lft-text); margin-bottom: 8px; }
.about-text { font-size: 12px; color: var(--lft-muted); line-height: 1.7; }
.privacy-box, .disclaimer-box { padding: 10px 12px; border-radius: 8px; border-left: 3px solid var(--lft-success); background: #F0FDF4; }
.disclaimer-box { border-left-color: var(--lft-warning); background: var(--lft-accent-soft); }
.about-close { width: 100%; padding: 11px; margin-top: 8px; position: sticky; bottom: 0; }

@keyframes msg-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: none; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .01ms !important;
    scroll-behavior: auto !important;
  }
}
""").substitute(**_CSS_VARS).strip()


# --------------------------------------------------------------------------
# 兼容映射：把历史内联 QSS 的旧配色/圆角收敛到新令牌，避免散落修改
# --------------------------------------------------------------------------

LEGACY_STYLE_MAP = {
    '#6c5ce7': COLORS['primary'],
    '#5a4bd1': COLORS['primary_hover'],
    '#4a3db5': COLORS['primary_press'],
    '#f0f0ff': COLORS['primary_soft'],
    '#e8e8ff': COLORS['primary_soft'],
    '#0984e3': COLORS['primary'],
    '#0773c5': COLORS['primary_hover'],
    '#0662a8': COLORS['primary_press'],
    '#00b894': COLORS['success'],
    '#00a381': '#047857',
    '#fdcb6e': COLORS['accent'],
    '#f9ca24': '#B45309',
    '#e1b621': '#92400E',
    '#dfe6e9': COLORS['border'],
    '#b2bec3': COLORS['border_strong'],
    '#2d3436': COLORS['text'],
    '#636e72': COLORS['muted'],
    '#f5f6fa': COLORS['bg'],
    '#f8f9fa': COLORS['surface_alt'],
    '#d63031': COLORS['danger'],
    '#f0f1f3': COLORS['surface_alt'],
    '#fafafa': COLORS['bg'],
    '#888888': COLORS['subtle'],
    '#e8f5e9': COLORS['success_soft'],
    '#f0f0f0': COLORS['surface_alt'],
    '#fff8e6': COLORS['accent_soft'],
    '#ffc107': COLORS['warning'],
}

LEGACY_RADIUS_MAP = {
    'border-radius: 20px': 'border-radius: 8px',
    'border-radius: 15px': 'border-radius: 8px',
    'border-radius: 12px': 'border-radius: 8px',
    'border-radius: 10px': 'border-radius: 8px',
}


def normalize_style_sheet(sheet):
    """把一段历史内联 QSS 映射到当前视觉令牌。"""
    if not sheet:
        return sheet
    result = sheet
    for old, new in LEGACY_STYLE_MAP.items():
        result = result.replace(old, new)
    for old, new in LEGACY_RADIUS_MAP.items():
        result = result.replace(old, new)
    return result


# 旧版状态文案把 emoji 当图标、进度条颜色硬编码在 JS 里，统一收敛到新主题
LEGACY_PHONE_TEXT_MAP = {
    '📤 ': '', '✅ ': '', '❌ ': '', '⏳ ': '', '🔗 ': '', '📁 ': '',
    "'#e74c3c'": "'%s'" % COLORS['danger'],
    "'#00b894'": "'%s'" % COLORS['success'],
}


def apply_phone_tokens(html):
    """把手机页模板中的 CSS / 图标 / 旧状态文案替换为统一令牌产物。"""
    result = html.replace('/*__PHONE_CSS__*/', PHONE_CSS)
    for old, new in LEGACY_PHONE_TEXT_MAP.items():
        result = result.replace(old, new)
    for key, markup in PHONE_ICON_TOKENS.items():
        result = result.replace('__ICON_%s__' % key, markup)
    return result
