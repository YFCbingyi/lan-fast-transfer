import os
import socket
import time
import uuid

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
                 on_connected=None, on_disconnected=None):
        super().__init__()
        self.target_ip = target_ip
        self.target_port = target_port

        # 回调函数（非 Qt 环境使用）
        self.on_message = on_message
        self.on_file = on_file
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected

        self.sio = None
        self._connected = False
        self.own_name = os.environ.get('COMPUTERNAME') or socket.gethostname()

    @property
    def base_url(self):
        return f"http://{self.target_ip}:{self.target_port}"

    def connect(self):
        """建立连接

        流程：
          1. HTTP GET 根路径验证目标 PC 可达
          2. 创建 SocketIO 客户端并建立 WebSocket 连接
          3. 连接成功后发送 identify 事件注册为 pc_client
        """
        if self._connected:
            self.disconnect()

        # Step 1: HTTP 可达性验证
        try:
            resp = requests.get(self.base_url, timeout=5)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ConnectionError(f"目标 PC 不可达: {e}")

        # Step 2: SocketIO 客户端
        self.sio = socketio.Client()

        @self.sio.on('connect')
        def on_connect():
            # Step 3: 发送识别事件
            self.sio.emit('identify', {'type': 'pc', 'name': self.own_name})
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

        self.sio.connect(self.base_url)

    def send_text(self, text):
        """发送文字消息"""
        if not self._connected or not self.sio:
            raise ConnectionError("未连接到目标 PC")
        self.sio.emit('text_message', {'message': text})

    def send_file(self, file_path, progress_cb=None):
        """发送文件（分片上传协议，支持大文件与失败重试）

        流程：
          1. POST /upload/init 创建上传会话，得到 upload_id
          2. 逐片 POST /upload/chunk（单片失败重试 3 次）
          3. POST /upload/finish 合并分片，得到 file_id
          4. 通过 SocketIO 发送 file_uploaded 事件通知
        """
        if not self._connected or not self.sio:
            raise ConnectionError("未连接到目标 PC")

        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        total_chunks = max(1, (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE)

        # Step 1: 初始化上传会话
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

        # Step 2: 逐片上传
        with open(file_path, 'rb') as f:
            for index in range(total_chunks):
                data = f.read(CHUNK_SIZE)
                if not data:
                    break
                self._post_chunk(upload_id, index, data)
                if progress_cb:
                    progress_cb(min(file_size, (index + 1) * CHUNK_SIZE), file_size)

        # Step 3: 合并分片
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

        # Step 4: SocketIO 通知
        self.sio.emit('file_uploaded', {
            'file_id': file_id,
            'filename': filename
        })

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
        """断开连接"""
        if self.sio and self._connected:
            self.sio.disconnect()
        self._connected = False
        self.sio = None
