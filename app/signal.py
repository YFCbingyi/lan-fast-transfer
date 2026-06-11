from PyQt5.QtCore import pyqtSignal, QObject

class SignalEmitter(QObject):
    received_text = pyqtSignal(str, str)
    received_file = pyqtSignal(str, str, str)
    phone_connected = pyqtSignal(bool)
    phone_sid_updated = pyqtSignal(str)
    device_connected = pyqtSignal(str, str, str)
    device_disconnected = pyqtSignal(str)
    device_list_updated = pyqtSignal(object)
    phone_text_sid = pyqtSignal(str)  # 手机文本消息来源 SID

signal_emitter = SignalEmitter()
