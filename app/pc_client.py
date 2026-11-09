import os
import socket
import time
import uuid
import threading

import requests
import socketio
from PyQt5.QtCore import pyqtSignal, QObject

CHUNK_SIZE = 4 * 1024 * 1024  # 4MB 分片，与服务端一致


class PCClient(QObject):
    """PC 客户端连接模块，用于主动连接其他 PC 的服务器。"""

    connected = pyqtSignal()
    disconnected = pyqtSignal()
    text_received = pyqtSignal(str, str)  # (消息内容, 发送者标识)
    file_received = pyqtSignal(str, str)  # (file_id, filename)

    def __init__(self, target_ip, target_port=5000,
                 on_message=None, on_file=None,
                 on_connected=None, on_disconnected=None, own_ip=''):
        super().__init__()
        self.target_ip = target_ip
        self.target_port = target_port
        self.own_ip = own_ip

        self.on_message = on_message
        self.on_file = on_file
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected

        self.sio = None
        self._connected = False
        self._manual_close = False
        self._reconnect_thread = None
        self.own_name = socket.gethostname()

    @property
    def base_url(self):
        return f"http://{self.target_ip}:{self.target_port}"

    def connect(self, reopen=False):
        """建立连接；reopen=True 用于断线后的自动重连。"""
        if not reopen:
            self._manual_close = False
        self._connected = False
        if self.sio is not None:
            try:
                self.sio.disconnect()
            except Exception:
                pass
            self.sio = None

        # Step 1: HTTP 可达性验证
        try:
            resp = requests.get(self.base_url, timeout=3)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ConnectionError(f"目标 PC 不可达: {e}")

        # Step 2: SocketIO 客户端（重连由本模块的退避循环负责）
        self.sio = socketio.Client(reconnection=False)

        @self.sio.on('connect')
        def on_connect():
            self.sio.emit('identify', {
                'type': 'pc', 'name': self.own_name, 'ip': self.own_ip
            })
            self._connected = True
            self.connected.emit()
            if self.on_connected:
                self.on_connected()

        @self.sio.on('disconnect')
        def on_disconnect():
            self._connected = False
            self.disconnected.emit()
            if self.on_disconnected:
                self.on_disconnected()
            if not self._manual_close:
                self._schedule_reconnect()

        @self.sio.on('text_message')
        def on_text_message(data):
            msg = data.get('message', '')
            sender = data.get('sender', 'pc')
            self.text_received.emit(msg, sender)
            if self.on_message:
                self.on_message(msg, sender)

        @self.sio.on('file_uploaded')
        def on_file_uploaded(data):
            file_id = data.get('file_id', '')
            filename = data.get('filename', '')
            self.file_received.emit(file_id, filename)
            if self.on_file:
                self.on_file(file_id, filename)

        # Step 3: 优先直连 WebSocket（跳过 polling 握手，建连更快、断开更利落），
        # 服务端不支持时自动回退 polling
        self.sio.connect(self.base_url, transports=['websocket', 'polling'],
                         wait_timeout=3)

    def _schedule_reconnect(self):
        if self._manual_close:
            return
        t = self._reconnect_thread
        if t and t.is_alive():
            return
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop, daemon=True, name='PCReconnect')
        self._reconnect_thread.start()

    def _reconnect_loop(self):
        """意外断开后指数退避自动重连，让 PC 之间"随时能连上"。"""
        delay = 2
        while not self._manual_close and not self._connected:
            time.sleep(delay)
            if self._manual_close or self._connected:
                return
            try:
                self.connect(reopen=True)
                print(f"PC 已自动重连: {self.target_ip}")
                return
            except Exception:
                delay = min(delay * 2, 30)

    def send_text(self, text):
        if not self._connected or not self.sio:
            raise ConnectionError("未连接到目标 PC")
        self.sio.emit('text_message', {'message': text})

    def send_file(self, file_path, progress_cb=None, cancel_event=None):
        """发送文件（分片上传协议），支持进度回调与取消。"""
        if not self._connected or not self.sio:
            raise ConnectionError("未连接到目标 PC")
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        total_chunks = max(1, (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE)

        resp = requests.post(
            f"{self.base_url}/upload/init",
            json={'filename': filename, 'size': file_size, 'total': total_chunks},
            timeout=15
        )
        if resp.status_code != 200:
            raise RuntimeError(f"初始化上传失败: HTTP {resp.status_code}")
        result = resp.json()
        if result.get('status') != 'ok':
            raise RuntimeError(f"初始化上传失败: {result.get('msg', '未知错误')}")
        upload_id = result['upload_id']

        with open(file_path, 'rb') as f:
            for index in range(total_chunks):
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("传输已取消")
                data = f.read(CHUNK_SIZE)
                if not data:
                    break
                self._post_chunk(upload_id, index, data)
                if progress_cb:
                    progress_cb(min(file_size, (index + 1) * CHUNK_SIZE), file_size)

        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("传输已取消")

        resp = requests.post(
            f"{self.base_url}/upload/finish",
            data={'upload_id': upload_id},
            timeout=600
        )
        if resp.status_code != 200:
            raise RuntimeError(f"合并文件失败: HTTP {resp.status_code}")
        result = resp.json()
        if result.get('status') != 'ok':
            raise RuntimeError(f"合并文件失败: {result.get('msg', '未知错误')}")

        file_id = result['file_id']
        self.sio.emit('file_uploaded', {'file_id': file_id, 'filename': filename})
        return file_id

    def _post_chunk(self, upload_id, index, data):
        """上传单个分片，失败自动重试 3 次"""
        last_error = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{self.base_url}/upload/chunk",
                    data={'upload_id': upload_id, 'index': index},
                    files={'chunk': (str(index), data)},
                    timeout=120
                )
                if resp.status_code == 200 and resp.json().get('status') == 'ok':
                    return
                last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:100]}")
            except requests.RequestException as e:
                last_error = e
            time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"分片 {index} 上传失败（已重试 3 次）: {last_error}")

    def disconnect(self):
        """主动断开（不触发自动重连），不阻塞调用方（通常是 Qt 主线程）。"""
        self._manual_close = True
        self._connected = False
        sio, self.sio = self.sio, None
        if sio is None:
            return

        def _close():
            try:
                sio.disconnect()
            except Exception:
                pass

        # polling 模式下 disconnect 要等一次网络往返，可能拖上数秒；
        # 放到后台线程，避免切换设备 / 关闭窗口时界面卡住
        threading.Thread(target=_close, daemon=True, name='PCDisconnect').start()
