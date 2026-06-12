import json
import socket
import time
import threading

from PyQt5.QtCore import pyqtSignal, QObject


class DeviceDiscovery(QObject):
    device_found = pyqtSignal(dict)
    device_lost = pyqtSignal(dict)

    BROADCAST_PORT = 51234
    BROADCAST_INTERVAL = 3
    TIMEOUT_THRESHOLD = 10

    def __init__(self, own_name, own_ip, own_port=5000):
        super().__init__()
        self._own_name = own_name
        self._own_ip = own_ip
        self._own_port = own_port

        self._devices = {}
        self._running = False
        self._broadcast_thread = None
        self._listen_thread = None
        self._timeout_thread = None
        self._stop_event = threading.Event()

        self.on_device_found = None
        self.on_device_lost = None

    def _get_broadcast_data(self):
        return {
            'device_name': self._own_name,
            'ip': self._own_ip,
            'port': self._own_port,
            'timestamp': time.time()
        }

    def _broadcast_loop(self):
        # 发送套接字：绑定到具体 IP，确保广播从该 IP 对应的物理网卡发出
        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            send_sock.bind((self._own_ip, 0))
        except Exception as e:
            print(f"绑定发送套接字失败: {e}")
            send_sock.close()
            return
        send_sock.settimeout(1)

        while not self._stop_event.is_set():
            try:
                data = self._get_broadcast_data()
                message = json.dumps(data).encode('utf-8')
                send_sock.sendto(message, ('255.255.255.255', self.BROADCAST_PORT))
            except Exception as e:
                print(f"广播发送失败: {e}")

            for _ in range(self.BROADCAST_INTERVAL):
                if self._stop_event.wait(1):
                    break

        send_sock.close()

    def _listen_loop(self):
        recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        recv_sock.settimeout(1)

        try:
            recv_sock.bind(('0.0.0.0', self.BROADCAST_PORT))
        except Exception as e:
            print(f"绑定监听端口失败: {e}")
            return

        while not self._stop_event.is_set():
            try:
                data, addr = recv_sock.recvfrom(4096)
                message = json.loads(data.decode('utf-8'))

                device_ip = message.get('ip', addr[0])

                if device_ip == self._own_ip:
                    continue

                device_info = {
                    'device_name': message.get('device_name', 'Unknown'),
                    'ip': device_ip,
                    'port': message.get('port', 5000),
                    'timestamp': message.get('timestamp', time.time())
                }

                is_new = device_ip not in self._devices

                self._devices[device_ip] = {
                    **device_info,
                    'last_seen': time.time()
                }

                if is_new:
                    print(f"发现新设备: {device_info['device_name']} ({device_ip})")
                    self.device_found.emit(device_info)
                    if self.on_device_found:
                        self.on_device_found(device_info)

            except json.JSONDecodeError:
                pass
            except socket.timeout:
                pass
            except Exception as e:
                print(f"监听接收失败: {e}")

        recv_sock.close()

    def _timeout_check_loop(self):
        while not self._stop_event.is_set():
            current_time = time.time()
            lost_devices = []

            for ip, info in list(self._devices.items()):
                if current_time - info['last_seen'] > self.TIMEOUT_THRESHOLD:
                    lost_devices.append(ip)

            for ip in lost_devices:
                device_info = self._devices.pop(ip, None)
                if device_info:
                    emit_info = {k: v for k, v in device_info.items() if k != 'last_seen'}
                    print(f"设备离线: {emit_info['device_name']} ({ip})")
                    self.device_lost.emit(emit_info)
                    if self.on_device_lost:
                        self.on_device_lost(emit_info)

            self._stop_event.wait(1)

    def start(self):
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        self._broadcast_thread = threading.Thread(
            target=self._broadcast_loop, daemon=True, name='DiscoveryBroadcast'
        )
        self._listen_thread = threading.Thread(
            target=self._listen_loop, daemon=True, name='DiscoveryListen'
        )
        self._timeout_thread = threading.Thread(
            target=self._timeout_check_loop, daemon=True, name='DiscoveryTimeout'
        )

        self._broadcast_thread.start()
        self._listen_thread.start()
        self._timeout_thread.start()

        print(f"设备发现已启动 (设备名: {self._own_name}, IP: {self._own_ip}, 端口: {self._own_port})")

    def stop(self):
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        for thread in [self._broadcast_thread, self._listen_thread, self._timeout_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=2)

        self._broadcast_thread = None
        self._listen_thread = None
        self._timeout_thread = None
        self._devices.clear()

        print("设备发现已停止")

    @property
    def devices(self):
        return list(self._devices.values())
