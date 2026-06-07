from PyQt5.QtCore import pyqtSignal, QObject

class SignalEmitter(QObject):
    received_text = pyqtSignal(str, str)
    received_file = pyqtSignal(str, str)
    phone_connected = pyqtSignal(bool)
    phone_sid_updated = pyqtSignal(str)

signal_emitter = SignalEmitter()