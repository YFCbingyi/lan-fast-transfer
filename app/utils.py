import socket
import os

def _lan_ip_priority(ip):
    """IP 优先级：192.168. > 10. > 172.16-31. > 其他"""
    if ip.startswith('192.168.'):
        return 0
    if ip.startswith('10.'):
        return 1
    parts = ip.split('.')
    if len(parts) == 4 and parts[0] == '172':
        try:
            second = int(parts[1])
            if 16 <= second <= 31:
                return 2
        except ValueError:
            pass
    return 3

def get_lan_ips():
    """获取所有候选局域网 IP，按优先级排序。"""
    candidates = []
    try:
        _, _, ip_list = socket.gethostbyname_ex(socket.gethostname())
        candidates = [ip for ip in ip_list if not ip.startswith('127.')]
    except Exception:
        pass

    if candidates:
        candidates.sort(key=_lan_ip_priority)
        return candidates

    # 兜底
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return [ip]
    except:
        return ["127.0.0.1"]

def get_lan_ip():
    """获取最优的局域网 IP（兼容旧接口）。"""
    return get_lan_ips()[0]

def format_size(bytes_size):
    if bytes_size == 0:
        return "0 B"
    k = 1024
    sizes = ['B', 'KB', 'MB', 'GB']
    i = int((len(str(bytes_size)) - 1) // 3)
    i = min(i, len(sizes) - 1)
    return f"{bytes_size / (k ** i):.2f} {sizes[i]}"