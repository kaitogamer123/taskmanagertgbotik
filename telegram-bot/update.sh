#!/usr/bin/env bash
# Обновление и перезапуск TaskMNGR на сервере.
#
# Работает в двух режимах:
#   * если папка — git-репозиторий: git pull/reset, затем перезапуск;
#   * если git нет (как на текущем сервере): просто ставит зависимости
#     и перезапускает бота. Код в этом случае заливается через TaskMNGR.bat.
set -euo pipefail

cd "$(dirname "$0")"

SCREEN_NAME="${SCREEN_NAME:-taskbot}"
if [ -x "venv/bin/python" ]; then
    PY="venv/bin/python"
else
    PY="python3"
fi
PIP="venv/bin/pip"

echo "=============================================="
echo "🚀 ОБНОВЛЕНИЕ TASKMNRG"
echo "=============================================="

# 1. Git — только если это действительно репозиторий
if [ -d ".git" ]; then
    echo "[1/3] Загрузка изменений с Git..."
    git config core.fileMode false 2>/dev/null || true
    git pull --ff-only || {
        echo "Локальные правки — синхронизирую с удалённой веткой..."
        git fetch origin
        UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo origin/main)"
        git reset --hard "$UPSTREAM"
    }
else
    echo "[1/3] Git-репозиторий не найден — пропускаю git pull."
    echo "      Код обновляется через TaskMNGR.bat с ПК."
fi

# 2. Зависимости
echo "[2/3] Проверка зависимостей..."
if [ -x "$PIP" ] && [ -f "requirements.txt" ]; then
    "$PIP" install -q --disable-pip-version-check -r requirements.txt
else
    echo "      venv/pip не найдены — пропускаю установку (использую $PY)."
fi

chmod 600 .env 2>/dev/null || true

# 3. Перезапуск
echo "[3/3] Перезапуск бота..."
if command -v screen >/dev/null 2>&1; then
    screen -S "$SCREEN_NAME" -X quit 2>/dev/null || true
    sleep 1

    # Аккуратно добиваем только ЭТОТ бот (cwd = текущая папка),
    # не трогая чужие bot.py на сервере.
    for pid in $(pgrep -f '^\./venv/bin/python bot\.py' 2>/dev/null || true); do
        if [ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)" = "$(pwd)" ]; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    sleep 1

    screen -dmS "$SCREEN_NAME" "$PY" bot.py
    sleep 3
    if ! screen -list | grep -q "$SCREEN_NAME"; then
        echo "❌ ОШИБКА: screen-сессия не запустилась."
        exit 1
    fi
    screen -ls || true
else
    # Резервный вариант без screen
    for pid in $(pgrep -f "$(pwd)/bot.py" 2>/dev/null || true); do
        kill "$pid" 2>/dev/null || true
    done
    nohup "$PY" bot.py >> bot.log 2>&1 &
    echo "✅ Бот запущен в фоне (PID: $!)."
fi

echo "=============================================="
echo "✅ Готово."
echo "=============================================="
