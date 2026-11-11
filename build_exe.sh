#!/usr/bin/env bash
# 构建 LanFastTransfer.exe（PyInstaller 单文件打包，使用 icon/icon.ico）
# 用法: ./build_exe.sh
set -euo pipefail

# 始终以脚本所在目录为根，保证相对路径（spec/icon/app/static）正确
cd "$(dirname "$0")"

# 优先使用项目虚拟环境中的 Python
if [ -f "venv/Scripts/python.exe" ]; then
    PY="venv/Scripts/python.exe"
elif [ -f "venv/bin/python" ]; then
    PY="venv/bin/python"
else
    PY="python"
fi

echo "==> 使用 Python: $("$PY" -c 'import sys; print(sys.executable)')"

# 校验 PyInstaller 可用
if ! "$PY" -m PyInstaller --version >/dev/null 2>&1; then
    echo "错误: 未找到 PyInstaller，请先安装: $PY -m pip install pyinstaller" >&2
    exit 1
fi
echo "==> PyInstaller 版本: $("$PY" -m PyInstaller --version)"

# 校验图标文件存在
ICON="icon/icon.ico"
if [ ! -f "$ICON" ]; then
    echo "错误: 未找到图标文件 $ICON" >&2
    exit 1
fi
echo "==> 使用图标: $ICON"

# 清理旧的构建缓存与产物，按 spec 重新打包
echo "==> 开始构建（可能需要几分钟）..."
"$PY" -m PyInstaller LanFastTransfer.spec --noconfirm --clean

EXE="dist/LanFastTransfer.exe"
if [ -f "$EXE" ]; then
    SIZE=$(du -h "$EXE" | cut -f1)
    echo "==> 构建成功: $EXE ($SIZE)"
else
    echo "错误: 构建完成但未找到 $EXE" >&2
    exit 1
fi
