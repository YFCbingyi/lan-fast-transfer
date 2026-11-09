import json
import socket
import time
import threading
import ipaddress

from PyQt5.QtCore import pyqtSignal, QObject


class DeviceDiscovery(QObject):
    device_found = pyqtSignal(dict)
    device_lost = pyqtSignal(dict)

    BROADCAST_PORT = 51234
    BROADCAST_INTERVAL = 3
    TIMEOUT_THRESHOLD = 15  # 5 次广播未收到才判离线，避免列表闪烁

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

    @staticmethod
    def _valid_ip(ip):
        try:
            addr = ipaddress.ip_address(str(ip))
            return addr.version == 4 and not addr.is_loopback and not addr.is_multicast
        except ValueError:
            return False

    def _get_broadcast_data(self):
        return {
            'device_name': self._own_name,
            'ip': self._own_ip,
            'port': self._own_port,
            'timestamp': time.time()
        }

    def set_endpoint(self, ip, port=None):
        """网络切换 / 服务换端口时更新广播内容（不重建对象）。"""
        new_port = port or self._own_port
        if ip == self._own_ip and new_port == self._own_port:
            return
        was_running = self._running
        if was_running:
            self.stop()
        self._own_ip = ip
        self._own_port = new_port
        if was_running:
            self.start()

    def _broadcast_loop(self):
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

        # 全局广播 + /24 定向广播：多网卡 / 路由器对 255.255.255.255 转发不一致时仍能发现
        targets = ['255.255.255.255']
        parts = self._own_ip.split('.')
        if len(parts) == 4:
            directed = f'{parts[0]}.{parts[1]}.{parts[2]}.255'
            if directed not in targets:
                targets.append(directed)

        while not self._stop_event.is_set():
            try:
                message = json.dumps(self._get_broadcast_data()).encode('utf-8')
                for target in targets:
                    try:
                        send_sock.sendto(message, (target, self.BROADCAST_PORT))
                    except Exception as e:
                        print(f"广播发送失败({target}): {e}")
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
            recv_sock.close()
            return

        while not self._stop_event.is_set():
            try:
                data, addr = recv_sock.recvfrom(4096)
                message = json.loads(data.decode('utf-8'))

                device_ip = message.get('ip', addr[0])
                if not self._valid_ip(device_ip):
                    device_ip = addr[0]
                if device_ip == self._own_ip:
                    continue

                try:
                    port = int(message.get('port', 5000))
                    if not 1 <= port <= 65535:
                        port = 5000
                except (TypeError, ValueError):
                    port = 5000

                device_info = {
                    'device_name': str(message.get('device_name', 'Unknown'))[:64],
                    'ip': device_ip,
                    'port': port,
                    'timestamp': message.get('timestamp', time.time())
                }

                is_new = device_ip not in self._devices
                self._devices[device_ip] = {**device_info, 'last_seen': time.time()}

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
            for ip, info in list(self._devices.items()):
                if current_time - info['last_seen'] > self.TIMEOUT_THRESHOLD:
                    lost = self._devices.pop(ip, None)
                    if lost:
                        emit_info = {k: v for k, v in lost.items() if k != 'last_seen'}
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
            target=self._broadcast_loop, daemon=True, name='DiscoveryBroadcast')
        self._listen_thread = threading.Thread(
            target=self._listen_loop, daemon=True, name='DiscoveryListen')
        self._timeout_thread = threading.Thread(
            target=self._timeout_check_loop, daemon=True, name='DiscoveryTimeout')
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
