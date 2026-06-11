import os
import socket
import uuid

import requests
import socketio
from PyQt5.QtCore import pyqtSignal, QObject


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

    def send_file(self, file_path):
        """发送文件

        流程：
          1. HTTP POST /upload 上传文件到目标服务器
          2. 通过 SocketIO 发送 file_uploaded 事件通知
        """
        if not self._connected or not self.sio:
            raise ConnectionError("未连接到目标 PC")

        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        filename = os.path.basename(file_path)

        # Step 1: HTTP 上传文件
        with open(file_path, 'rb') as f:
            resp = requests.post(
                f"{self.base_url}/upload",
                files={'file': (filename, f)},
                timeout=60
            )

        if resp.status_code != 200:
            raise RuntimeError(f"文件上传失败: HTTP {resp.status_code}")

        result = resp.json()
        if result.get('status') != 'ok':
            raise RuntimeError(f"文件上传失败: {result.get('msg', '未知错误')}")

        file_id = result['file_id']

        # Step 2: SocketIO 通知
        self.sio.emit('file_uploaded', {
            'file_id': file_id,
            'filename': filename
        })

        return file_id

    def disconnect(self):
        """断开连接"""
        if self.sio and self._connected:
            self.sio.disconnect()
        self._connected = False
        self.sio = None
