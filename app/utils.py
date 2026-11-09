import socket

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


def _default_route_ip():
    """取默认路由出口 IP（UDP connect 不实际发包，无需联网）。

    它最可能就是手机可访问的地址，优先于 gethostbyname_ex 返回的虚拟网卡 IP。
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def get_lan_ips():
    """获取候选局域网 IP：默认路由出口优先，其余按私网优先级排序。"""
    candidates = []
    try:
        _, _, ip_list = socket.gethostbyname_ex(socket.gethostname())
        candidates = [ip for ip in ip_list if not ip.startswith('127.')]
    except Exception:
        pass

    route_ip = _default_route_ip()
    if route_ip and not route_ip.startswith('127.'):
        candidates.append(route_ip)

    candidates = list(dict.fromkeys(candidates))
    rest = [ip for ip in candidates if ip != route_ip]
    rest.sort(key=_lan_ip_priority)
    result = ([route_ip] if route_ip and not route_ip.startswith('127.') else []) + rest
    return result or ["127.0.0.1"]


def get_lan_ip():
    """获取最优的局域网 IP（兼容旧接口）。"""
    return get_lan_ips()[0]


def format_size(bytes_size):
    if bytes_size == 0:
        return "0 B"
    k = 1024
    sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    value = float(bytes_size)
    while value >= k and i < len(sizes) - 1:
        value /= k
        i += 1
    return f"{value:.2f} {sizes[i]}"
