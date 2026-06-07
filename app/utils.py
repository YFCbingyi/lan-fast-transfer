import socket
import os

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def format_size(bytes_size):
    if bytes_size == 0:
        return "0 B"
    k = 1024
    sizes = ['B', 'KB', 'MB', 'GB']
    i = int((len(str(bytes_size)) - 1) // 3)
    i = min(i, len(sizes) - 1)
    return f"{bytes_size / (k ** i):.2f} {sizes[i]}"