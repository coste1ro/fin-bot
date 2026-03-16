# Finance Telegram Bot

Минимальный Telegram-бот для учета личных финансов.

## Локальный запуск

1. Скопируй `.env.example` в `.env`
2. Вставь токен бота в `TG_BOT_API_KEY`
3. Установи зависимости:
   `pip install -r requirements.txt`
4. Запусти:
   `python main.py`

## Деплой

Для Railway/подобных платформ загружай **содержимое архива сразу в корень проекта**, не папку внутри папки.

Файл `Procfile` уже добавлен:
`worker: python main.py`
