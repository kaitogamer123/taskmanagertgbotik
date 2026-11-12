#!/usr/bin/env bash
# Разворачивает бота на сервере: создаёт отдельную папку с виртуальным
# окружением и ставит туда все нужные библиотеки, не трогая системный Python.
#
# Использование:
#   chmod +x setup.sh
#   ./setup.sh
set -e

cd "$(dirname "$0")"

# Чтобы chmod +x не мешал последующему git pull на сервере
git config core.fileMode false 2>/dev/null || true

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
    else
        cat > .env << 'EOF'
BOT_TOKEN=PASTE_YOUR_BOT_TOKEN_HERE
TIMEZONE=Europe/Moscow
NOTIFIER_POLL_INTERVAL=60
AUTO_PULL_ENABLED=1
AUTO_PULL_INTERVAL=900
OWNER_IDS=7899153362
EOF
    fi
    echo "Создан файл .env — впиши туда свой BOT_TOKEN перед запуском!"
fi

echo "Создаю виртуальное окружение в ./venv ..."
if ! python3 -m venv venv 2>/dev/null; then
    echo "Пакет python3-venv не найден, пробую установить автоматически..."
    rm -rf venv
    if [ "$(id -u)" -eq 0 ] && command -v apt-get >/dev/null 2>&1; then
        apt-get update -y && apt-get install -y python3-venv
        python3 -m venv venv
    elif command -v sudo >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -y && sudo apt-get install -y python3-venv
        python3 -m venv venv
    fi
fi

if [ -x "./venv/bin/pip" ]; then
    echo "Устанавливаю зависимости в ./venv ..."
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install -r requirements.txt
    RUN_PY="./venv/bin/python"
else
    echo "Устанавливаю зависимости через системный pip ..."
    pip3 install --break-system-packages -r requirements.txt 2>/dev/null || pip3 install -r requirements.txt
    RUN_PY="python3"
fi

mkdir -p PlanesUser
chmod +x update.sh 2>/dev/null || true

echo ""
echo "Готово! Запустить бота можно командой:"
echo "  $RUN_PY bot.py"
echo "Или в фоне через screen с автопуллом из Git:"
echo "  ./update.sh"
