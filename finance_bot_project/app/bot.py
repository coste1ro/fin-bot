from __future__ import annotations

import logging
import os
from textwrap import dedent

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .storage import Storage
from .utils import (
    build_categories_report,
    build_period_summary,
    filter_current_month,
    filter_today,
    format_entry,
    parse_entry_text,
    sum_amount,
)

logging.basicConfig(
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv('TG_BOT_API_KEY')
storage = Storage()

START_TEXT = dedent(
    """
    *Финансовый бот запущен*

    Пиши операции прямо в чат:
    `-350 кофе`
    `+50000 зарплата`
    `-1290 продукты - пятёрочка`

    Логика простая, как человеческая любовь к подпискам:
    • `-` это расход
    • `+` это доход
    • после суммы можно указать категорию
    • после разделителя `-`, `—`, `|` или `/` можно добавить заметку

    Команды:
    /today - сводка за сегодня
    /month - сводка за месяц
    /balance - общий баланс
    /categories - расходы по категориям за месяц
    /last - последние 10 операций
    /undo - удалить последнюю операцию
    /help - помощь
    """
).strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT, parse_mode=ParseMode.MARKDOWN)


async def add_entry_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.message.text:
        return

    parsed = parse_entry_text(update.message.text)
    if not parsed:
        await update.message.reply_text(
            'Не понял запись. Пример: `-350 кофе` или `+120000 зарплата`',
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    amount, category, note = parsed
    entry = storage.add_entry(update.effective_user.id, amount, category, note)
    action = 'доход' if amount > 0 else 'расход'
    sign = '+' if amount > 0 else ''
    await update.message.reply_text(
        f'Сохранил {action}: {sign}{amount:.2f} ₽\nКатегория: {entry.category}\n'
        f'{f"Заметка: {entry.note}\n" if entry.note else ""}ID: {entry.id}'
    )


async def today_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    entries = filter_today(storage.list_entries(user_id))
    await update.message.reply_text(build_period_summary(entries, 'Сводка за сегодня'))


async def month_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    entries = filter_current_month(storage.list_entries(user_id))
    await update.message.reply_text(build_period_summary(entries, 'Сводка за текущий месяц'))


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    total = sum_amount(storage.list_entries(user_id))
    await update.message.reply_text(f'Текущий баланс: {total:.2f} ₽')


async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    entries = filter_current_month(storage.list_entries(user_id))
    await update.message.reply_text(build_categories_report(entries))


async def last_entries(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    entries = storage.list_entries(user_id)[-10:]
    if not entries:
        await update.message.reply_text('Операций пока нет.')
        return
    text = 'Последние 10 операций:\n' + '\n'.join(f'• {format_entry(item)}' for item in entries)
    await update.message.reply_text(text)


async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    entries = storage.list_entries(user_id)
    if not entries:
        await update.message.reply_text('Удалять пока нечего.')
        return
    last = entries[-1]
    removed = storage.delete_entry(last.id, user_id)
    if removed:
        await update.message.reply_text(f'Удалил последнюю операцию:\n{format_entry(removed)}')
    else:
        await update.message.reply_text('Не удалось удалить последнюю операцию.')


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception('Ошибка при обработке апдейта', exc_info=context.error)


def validate_env() -> None:
    if not BOT_TOKEN:
        raise RuntimeError('Не найден TG_BOT_API_KEY в .env файле')


def main() -> None:
    validate_env()
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('today', today_summary))
    application.add_handler(CommandHandler('month', month_summary))
    application.add_handler(CommandHandler('balance', balance))
    application.add_handler(CommandHandler('categories', categories))
    application.add_handler(CommandHandler('last', last_entries))
    application.add_handler(CommandHandler('undo', undo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_entry_from_text))
    application.add_error_handler(error_handler)

    logger.info('Бот запущен')
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
