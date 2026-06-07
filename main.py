import os
import sys
import threading
import argparse

from app.config import load_config, save_config, DEFAULT_DOWNLOAD_FOLDER
from app.server import start_flask
from app.ui.main_window import LanChatWindow

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='局域网双向传输工具')
    parser.add_argument('--download-path', type=str, help='设置文件下载保存路径')
    args = parser.parse_args()

    config = load_config()
    
    if args.download_path:
        DOWNLOAD_FOLDER = args.download_path
        config['download_path'] = DOWNLOAD_FOLDER
        save_config(config)
    else:
        DOWNLOAD_FOLDER = config.get('download_path', DEFAULT_DOWNLOAD_FOLDER)

    if not os.path.exists(DOWNLOAD_FOLDER):
        os.makedirs(DOWNLOAD_FOLDER)

    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    from PyQt5.QtWidgets import QApplication
    
    qt_app = QApplication(sys.argv)
    window = LanChatWindow(DOWNLOAD_FOLDER)
    window.show()
    sys.exit(qt_app.exec_())