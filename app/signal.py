from PyQt5.QtCore import pyqtSignal, QObject


class SignalEmitter(QObject):
    received_text = pyqtSignal(str, str)
    received_file = pyqtSignal(str, str, str)
    phone_connected = pyqtSignal(bool)
    phone_sid_updated = pyqtSignal(str)
    device_connected = pyqtSignal(str, str, str, str, str)  # (设备 key, 类型, 显示名, 当前 sid, 来源 IP)
    device_disconnected = pyqtSignal(str)              # 设备 key
    device_list_updated = pyqtSignal(object)
    phone_text_key = pyqtSignal(str)                   # 手机消息来源设备 key

    server_status = pyqtSignal(bool, int, str)         # (是否运行, 端口, 说明)
    system_message = pyqtSignal(str)                   # 跨线程安全写入聊天区
    send_progress = pyqtSignal(str, int, int)          # (描述, 已完成字节, 总字节)；空描述表示结束
    pc_message = pyqtSignal(str, str)                  # (内容, 来源 PC 的 IP)
    transfer_finished = pyqtSignal()                   # 一次后台传输结束（成功/失败/取消均触发）


signal_emitter = SignalEmitter()
