#!/usr/bin/env bash
# Разворачивает бота на сервере: создаёт отдельную папку с виртуальным
# окружением и ставит туда все нужные библиотеки, не трогая системный Python.
#
# Использование:
#   chmod +x setup.sh
#   ./setup.sh
set -e

cd "$(dirname "$0")"

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Создан файл .env — впиши туда свой BOT_TOKEN перед запуском!"
fi

echo "Создаю виртуальное окружение в ./venv ..."
python3 -m venv venv

echo "Устанавливаю зависимости из requirements.txt ..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

mkdir -p PlanesUser

echo ""
echo "Готово! Запустить бота можно командой:"
echo "  ./venv/bin/python bot.py"
