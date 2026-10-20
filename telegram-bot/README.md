# Telegram-бот «Планы» (aiogram 3)

Чистый Telegram-бот на Python + aiogram 3. Никакого веб-интерфейса —
только бот, который хранит планы пользователей в персональных SQLite
базах данных.

## Возможности

- `/start` — приветствие и список команд.
- `/MyPlans` — показывает планы на ближайшие 7 дней (кнопками, начиная с
  сегодняшнего дня). Можно просто написать дату («19.10», «в четверг»,
  «на следующей неделе в четверг», «через 3 дня» и т.д.) — бот откроет
  планы на этот день.
- Нажатие на конкретный план показывает подробное описание
  (или «Описание отсутствует»), а также напоминание
  `Успей закончить "<предыдущая задача>"!!`, если перед ней в этот день
  есть другая задача. Кнопка «Назад» возвращает к списку дня.
- `/NewPlan` — добавление разовой задачи: бот спрашивает дату, время
  начала (можно пропустить), время окончания (можно пропустить),
  название и (опционально) описание.
- `/everyN` — добавление повторяющейся задачи. Поддерживаются как кнопки,
  так и обычные текстовые фразы-триггеры:
  - «каждый день» / «ежедневно»
  - «каждые 3 дня»
  - «каждый понедельник» / «по понедельникам и средам»
  - «каждый месяц 15 числа» / «каждое 1 число»
  - «каждый год 1 января» / «каждый год 01.01»
- `/database` — присылает файл своей базы данных (.db), который можно
  открыть любой программой для просмотра SQLite (например, DB Browser
  for SQLite).

## Хранение данных

У каждого пользователя — своя SQLite база в папке `PlanesUser/`:

```
PlanesUser/
  ka1d3en.db       # если есть username
  123456789.db     # если username нет — используется telegram id
  _index.json      # служебный файл: соответствие telegram_id -> файл базы
```

Первая запись в базе (таблица `user_meta`) — это telegram id владельца.
При каждом обращении к боту (но не чаще раза в 5 минут) проверяется,
не изменился ли username пользователя. Если изменился — файл базы
автоматически переименовывается.

При первом обращении в базу пользователя также добавляется тестовое
демо-расписание (среда–воскресенье), чтобы сразу было что посмотреть
в `/MyPlans`.

### Структура таблиц

- `user_meta(telegram_id, username, first_name, created_at, last_checked)`
- `plans(id, plan_date, time_start, time_end, title, description)`
- `recurring_rules(id, title, description, time_start, time_end, start_date, rule_type, rule_value, created_at)`
  - `rule_type`: `interval` (каждые N дней), `weekday` (список дней недели
    через запятую, 0=понедельник), `monthly` (число месяца),
    `yearly` (значение вида `DD-MM`).

## Установка и запуск на сервере

Бот разворачивается в отдельной папке и ставит все библиотеки в своё
собственное виртуальное окружение — никак не затрагивая системный Python.

```bash
# 1. Скопируй папку telegram-bot на сервер и зайди в неё
cd telegram-bot

# 2. Запусти установку (создаст venv/ и PlanesUser/, поставит зависимости)
chmod +x setup.sh
./setup.sh

# 3. Впиши токен бота в файл .env (BOT_TOKEN=...)
nano .env

# 4. Запусти бота
./venv/bin/python bot.py
```

### Запуск как systemd-сервис (опционально)

Создай файл `/etc/systemd/system/plans-bot.service`:

```ini
[Unit]
Description=Telegram Plans Bot
After=network.target

[Service]
WorkingDirectory=/путь/до/telegram-bot
ExecStart=/путь/до/telegram-bot/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Затем:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now plans-bot
```

## Структура проекта

```
telegram-bot/
├── bot.py                  # точка входа
├── config.py                # загрузка токена и путей из .env
├── states.py                 # состояния FSM (/NewPlan, /everyN)
├── requirements.txt
├── setup.sh                  # создаёт venv и ставит зависимости
├── .env.example
├── database/
│   ├── db_manager.py         # создание/поиск/переименование баз пользователей
│   ├── plans_repo.py         # CRUD по планам и повторяющимся задачам
│   └── seed.py                # тестовое демо-расписание
├── handlers/
│   ├── start.py               # /start
│   ├── database_cmd.py        # /database
│   ├── myplans.py             # /MyPlans + просмотр дней/задач + разбор дат из текста
│   ├── newplan.py             # /NewPlan (FSM)
│   └── everyn.py               # /everyN (FSM)
├── keyboards/
│   └── inline.py               # инлайн-клавиатуры
├── middlewares/
│   └── db_middleware.py        # открытие БД пользователя + проверка username
├── utils/
│   ├── date_utils.py            # разбор дат/времени на русском
│   └── repeat_parser.py         # разбор текстовых триггеров повторения
└── PlanesUser/                   # сюда складываются базы данных пользователей
```
