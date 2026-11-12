#!/usr/bin/env bash
set -e

# Переходим в папку, где лежит сам скрипт (telegram-bot/)
cd "$(dirname "$0")"

SCREEN_NAME="plans_bot"

echo "=============================================="
echo "🚀 ОБНОВЛЕНИЕ БОТА TASK MANAGER"
echo "=============================================="

# Игнорируем смену прав (chmod +x), чтобы git pull никогда не конфликтовал
git config core.fileMode false 2>/dev/null || true

# 1. Скачиваем свежий код с GitHub (БД в PlanesUser/ и .env защищены .gitignore)
echo "[1/3] Загрузка изменений с Git..."
git pull --ff-only || {
    echo "Обнаружены локальные правки в отслеживаемых файлах — синхронизирую с веткой GitHub..."
    git fetch origin
    UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo "origin/main")
    git reset --hard "$UPSTREAM"
}

# Подбираем интерпретатор Python (venv или системный)
if [ -x "venv/bin/python" ]; then
    PY="venv/bin/python"
    PIP="venv/bin/pip"
elif python3 -m venv venv 2>/dev/null; then
    PY="venv/bin/python"
    PIP="venv/bin/pip"
else
    rm -rf venv
    PY="python3"
    PIP="pip3"
fi

# 2. Проверяем и обновляем библиотеки (если добавлял новые)
if [ -f "requirements.txt" ]; then
    echo "[2/3] Проверка и установка зависимостей..."
    $PIP install -q -r requirements.txt 2>/dev/null || $PIP install -q --break-system-packages -r requirements.txt
fi

mkdir -p PlanesUser

# 3. Перезапускаем бота в фоновом режиме (screen)
echo "[3/3] Перезапуск процесса бота..."

if command -v screen >/dev/null 2>&1; then
    # Завершаем старую сессию бота, если она запущена
    screen -S "$SCREEN_NAME" -X quit 2>/dev/null || true
    sleep 1

    # Запускаем бота в новой изолированной фоновой сессии screen
    screen -dmS "$SCREEN_NAME" "$PY" bot.py

    echo "=============================================="
    echo "✅ Бот успешно обновлен и перезапущен!"
    echo "Текущие фоновые процессы:"
    screen -ls || true
    echo "=============================================="
else
    pkill -f "bot.py" 2>/dev/null || true
    sleep 1
    nohup "$PY" bot.py >> bot.log 2>&1 &
    echo "=============================================="
    echo "✅ Бот успешно обновлен и запущен в фоне (PID: $!)!"
    echo "=============================================="
fi
