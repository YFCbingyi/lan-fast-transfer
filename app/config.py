import os
import sys
import json


def _config_dir():
    # 打包后配置写在 exe 同目录；源码运行时写在项目根目录。
    # 避免 onefile 模式下写进 _MEIPASS 临时目录，退出即丢失。
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


CONFIG_FILE = os.path.join(_config_dir(), 'config.json')
DEFAULT_DOWNLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "LanChatDownloads")


def load_config():
    config = {
        'download_path': DEFAULT_DOWNLOAD_FOLDER
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
                config.update(loaded_config)
        except Exception as e:
            print(f"加载配置文件失败: {e}")
    return config


def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"保存配置文件失败: {e}")
        return False
