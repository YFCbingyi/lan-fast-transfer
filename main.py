import os
import sys
import threading
import argparse

from app.config import load_config, save_config, DEFAULT_DOWNLOAD_FOLDER
from app.server import start_flask
from app.ui.main_window import LanChatWindow

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='局域网双向传输工具')
    parser.add_argument('--download-path', type=str, help='设置文件下载保存路径')
    args = parser.parse_args()

    config = load_config()

    if args.download_path:
        config['download_path'] = args.download_path
        save_config(config)

    DOWNLOAD_FOLDER = config.get('download_path', DEFAULT_DOWNLOAD_FOLDER)
    try:
        os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    except OSError as e:
        DOWNLOAD_FOLDER = DEFAULT_DOWNLOAD_FOLDER
        os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
        print(f"下载目录不可用，已回退到默认目录: {e}")

    flask_thread = threading.Thread(target=start_flask, daemon=True, name='TransferServer')
    flask_thread.start()

    from PyQt5.QtWidgets import QApplication

    qt_app = QApplication(sys.argv)
    window = LanChatWindow(DOWNLOAD_FOLDER)
    window.show()
    sys.exit(qt_app.exec_())
