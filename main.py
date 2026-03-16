from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Optional
from uuid import uuid4

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv('TG_BOT_API_KEY')
DATA_DIR = Path('data')
DATA_FILE = DATA_DIR / 'finance_data.json'

START_TEXT = dedent(
    """
    *Финансовый бот запущен*

    Пиши операции прямо в чат:
    `-350 кофе`
    `+50000 зарплата`
    `-1290 продукты - пятёрочка`

    Что умеет:
    • `-` это расход
    • `+` это доход
    • после суммы можно указать категорию
    • после разделителя `-`, `—`, `|` или `/` можно добавить заметку

    Команды:
    /today - сводка за сегодня
    /month - сводка за текущий месяц
    /balance - общий баланс
    /categories - расходы по категориям за месяц
    /last - последние 10 операций
    /undo - удалить последнюю операцию
    /help - помощь
    """
).strip()


@dataclass
class Entry:
    id: str
    user_id: int
    amount: float
    category: str
    note: str
    created_at: str


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([])

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open('r', encoding='utf-8') as file:
            try:
                data = json.load(file)
            except json.JSONDecodeError:
                return []
        return data if isinstance(data, list) else []

    def _write(self, data: list[dict]) -> None:
        with self.path.open('w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    def add_entry(self, user_id: int, amount: float, category: str, note: str) -> Entry:
        entry = Entry(
            id=str(uuid4())[:8],
            user_id=user_id,
            amount=round(amount, 2),
            category=category,
            note=note,
            created_at=datetime.now().isoformat(timespec='seconds'),
        )
        data = self._read()
        data.append(asdict(entry))
        self._write(data)
        return entry

    def list_entries(self, user_id: int) -> list[Entry]:
        data = self._read()
        result: list[Entry] = []
        for item in data:
            if item.get('user_id') == user_id:
                result.append(Entry(**item))
        result.sort(key=lambda x: x.created_at)
        return result

    def delete_entry(self, entry_id: str, user_id: int) -> Optional[Entry]:
        data = self._read()
        kept: list[dict] = []
        removed: Optional[Entry] = None

        for item in data:
            if item.get('id') == entry_id and item.get('user_id') == user_id and removed is None:
                removed = Entry(**item)
                continue
            kept.append(item)

        self._write(kept)
        return removed


storage = Storage(DATA_FILE)
ENTRY_REGEX = re.compile(r'^\s*([+-])\s*(\d+(?:[.,]\d{1,2})?)\s*(.*)$')
NOTE_SEPARATORS = [' - ', ' — ', ' | ', ' / ']


def parse_entry_text(text: str) -> Optional[tuple[float, str, str]]:
    match = ENTRY_REGEX.match(text)
    if not match:
        return None

    sign, amount_raw, tail = match.groups()
    amount = float(amount_raw.replace(',', '.'))
    if sign == '-':
        amount = -amount

    category = 'прочее'
    note = ''
    tail = (tail or '').strip()

    if tail:
        category_part = tail
        for separator in NOTE_SEPARATORS:
            if separator in tail:
                category_part, note = tail.split(separator, 1)
                break
        category = category_part.strip().lower() or 'прочее'
        note = note.strip()

    return amount, category, note


def format_money(value: float) -> str:
    return f'{value:.2f} ₽'


def sum_amount(entries: list[Entry]) -> float:
    return round(sum(item.amount for item in entries), 2)


def filter_today(entries: list[Entry]) -> list[Entry]:
    today = datetime.now().date()
    return [item for item in entries if datetime.fromisoformat(item.created_at).date() == today]


def filter_current_month(entries: list[Entry]) -> list[Entry]:
    now = datetime.now()
    return [
        item for item in entries
        if (dt := datetime.fromisoformat(item.created_at)).year == now.year and dt.month == now.month
    ]


def build_period_summary(entries: list[Entry], title: str) -> str:
    if not entries:
        return f'{title}\n\nОпераций пока нет.'

    income = round(sum(item.amount for item in entries if item.amount > 0), 2)
    expense = round(sum(abs(item.amount) for item in entries if item.amount < 0), 2)
    total = round(income - expense, 2)

    return (
        f'{title}\n\n'
        f'Доходы: {format_money(income)}\n'
        f'Расходы: {format_money(expense)}\n'
        f'Баланс: {format_money(total)}\n'
        f'Операций: {len(entries)}'
    )


def build_categories_report(entries: list[Entry]) -> str:
    expenses = [item for item in entries if item.amount < 0]
    if not expenses:
        return 'В этом месяце расходов по категориям пока нет.'

    categories: dict[str, float] = {}
    for item in expenses:
        categories[item.category] = categories.get(item.category, 0) + abs(item.amount)

    lines = ['Расходы по категориям за текущий месяц:']
    for name, value in sorted(categories.items(), key=lambda pair: pair[1], reverse=True):
        lines.append(f'• {name}: {format_money(value)}')
    return '\n'.join(lines)


def format_entry(entry: Entry) -> str:
    created = datetime.fromisoformat(entry.created_at).strftime('%d.%m %H:%M')
    parts = [created, format_money(entry.amount), entry.category]
    if entry.note:
        parts.append(entry.note)
    return ' | '.join(parts)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(START_TEXT, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
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

    lines = [
        f'Сохранил {action}: {sign}{amount:.2f} ₽',
        f'Категория: {entry.category}',
    ]
    if entry.note:
        lines.append(f'Заметка: {entry.note}')
    lines.append(f'ID: {entry.id}')

    await update.message.reply_text('\n'.join(lines))


async def today_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    entries = filter_today(storage.list_entries(update.effective_user.id))
    await update.message.reply_text(build_period_summary(entries, 'Сводка за сегодня'))


async def month_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    entries = filter_current_month(storage.list_entries(update.effective_user.id))
    await update.message.reply_text(build_period_summary(entries, 'Сводка за текущий месяц'))


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    total = sum_amount(storage.list_entries(update.effective_user.id))
    await update.message.reply_text(f'Текущий баланс: {format_money(total)}')


async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    entries = filter_current_month(storage.list_entries(update.effective_user.id))
    await update.message.reply_text(build_categories_report(entries))


async def last_entries(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    entries = storage.list_entries(update.effective_user.id)[-10:]
    if not entries:
        await update.message.reply_text('Операций пока нет.')
        return
    text = 'Последние 10 операций:\n' + '\n'.join(f'• {format_entry(item)}' for item in entries)
    await update.message.reply_text(text)


async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    entries = storage.list_entries(update.effective_user.id)
    if not entries:
        await update.message.reply_text('Удалять пока нечего.')
        return
    last = entries[-1]
    removed = storage.delete_entry(last.id, update.effective_user.id)
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
