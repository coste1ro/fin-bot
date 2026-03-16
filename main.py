import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("TG_BOT_API_KEY")
DATA_FILE = Path("data.json")

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


START_TEXT = """
*Финансовый бот*

Пиши операции прямо сообщением:

`-350 кофе`
`-1200 продукты`
`+50000 зарплата`
`-799 подписка яндекс`

Команды:
`/start` - запуск
`/help` - помощь
`/today` - сводка за сегодня
`/month` - сводка за текущий месяц
`/balance` - текущий баланс
`/categories` - расходы по категориям за месяц
`/last` - последние 10 операций
`/undo` - удалить последнюю операцию
"""

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        ["📅 Сегодня", "📆 Месяц"],
        ["💰 Баланс", "📊 Категории"],
        ["🕘 Последние", "↩️ Отменить"],
    ],
    resize_keyboard=True,
)


@dataclass
class Entry:
    id: str
    user_id: int
    amount: float
    description: str
    created_at: str


class Storage:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not self.file_path.exists():
            self.file_path.write_text("[]", encoding="utf-8")

    def _read(self) -> List[dict]:
        self._ensure_file()
        try:
            return json.loads(self.file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("data.json поврежден, создаю пустой список")
            self.file_path.write_text("[]", encoding="utf-8")
            return []

    def _write(self, data: List[dict]) -> None:
        self.file_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_entry(self, entry: Entry) -> None:
        data = self._read()
        data.append(asdict(entry))
        self._write(data)

    def list_entries(self, user_id: int) -> List[Entry]:
        data = self._read()
        entries = [
            Entry(**item)
            for item in data
            if int(item.get("user_id", 0)) == int(user_id)
        ]
        entries.sort(key=lambda x: x.created_at)
        return entries

    def delete_entry(self, entry_id: str, user_id: int) -> Optional[Entry]:
        data = self._read()
        removed_item = None
        new_data = []

        for item in data:
            if (
                item.get("id") == entry_id
                and int(item.get("user_id", 0)) == int(user_id)
                and removed_item is None
            ):
                removed_item = item
                continue
            new_data.append(item)

        self._write(new_data)
        return Entry(**removed_item) if removed_item else None


storage = Storage(DATA_FILE)


def parse_entry(text: str) -> Optional[tuple[float, str]]:
    """
    Парсит строки вида:
    -350 кофе
    +50000 зарплата
    -1200 продукты пятёрочка
    """
    cleaned = text.strip().replace(",", ".")
    pattern = r"^([+-]?\d+(?:\.\d{1,2})?)\s+(.+)$"
    match = re.match(pattern, cleaned)

    if not match:
        return None

    amount = float(match.group(1))
    description = match.group(2).strip()

    if not description:
        return None

    return amount, description


def format_money(amount: float) -> str:
    sign = "+" if amount > 0 else ""
    return f"{sign}{amount:.2f} ₽"


def format_entry(entry: Entry) -> str:
    dt = datetime.fromisoformat(entry.created_at)
    date_str = dt.strftime("%d.%m %H:%M")
    return f"{date_str} | {format_money(entry.amount)} | {entry.description}"


def sum_amount(entries: List[Entry]) -> float:
    return round(sum(entry.amount for entry in entries), 2)


def filter_today(entries: List[Entry]) -> List[Entry]:
    today = datetime.now().date()
    return [
        entry
        for entry in entries
        if datetime.fromisoformat(entry.created_at).date() == today
    ]


def filter_current_month(entries: List[Entry]) -> List[Entry]:
    now = datetime.now()
    return [
        entry
        for entry in entries
        if (
            datetime.fromisoformat(entry.created_at).year == now.year
            and datetime.fromisoformat(entry.created_at).month == now.month
        )
    ]


def build_period_summary(entries: List[Entry], title: str) -> str:
    if not entries:
        return f"{title}\n\nОпераций пока нет."

    income = round(sum(entry.amount for entry in entries if entry.amount > 0), 2)
    expense = round(sum(entry.amount for entry in entries if entry.amount < 0), 2)
    balance = round(income + expense, 2)

    lines = [
        title,
        "",
        f"Доходы: {format_money(income)}",
        f"Расходы: {format_money(expense)}",
        f"Баланс: {format_money(balance)}",
        "",
        "Последние операции:",
    ]

    for entry in entries[-5:]:
        lines.append(f"• {format_entry(entry)}")

    return "\n".join(lines)


def detect_category(description: str) -> str:
    text = description.lower()

    category_map = {
        "Еда": [
            "кофе", "еда", "продукты", "ресторан", "кафе", "пятерочка", "магнит",
            "вкусвилл", "доставка", "самокат", "перекресток", "обед", "ужин",
        ],
        "Транспорт": [
            "такси", "метро", "автобус", "транспорт", "бензин", "заправка",
            "каршеринг", "парковка",
        ],
        "Подписки": [
            "подписка", "spotify", "youtube", "yandex", "яндекс", "chatgpt",
            "netflix", "apple", "icloud",
        ],
        "Дом": [
            "аренда", "квартира", "жкх", "коммуналка", "интернет", "свет",
            "вода", "газ",
        ],
        "Здоровье": [
            "аптека", "лекарства", "врач", "больница", "анализы", "стоматолог",
        ],
        "Развлечения": [
            "кино", "игры", "steam", "ps", "playstation", "бар", "алкоголь",
            "развлечения",
        ],
        "Одежда": [
            "одежда", "кроссовки", "футболка", "джинсы", "куртка", "обувь",
        ],
        "Доход": [
            "зарплата", "аванс", "кэшбек", "кешбек", "премия", "фриланс", "доход",
        ],
    }

    for category, keywords in category_map.items():
        if any(keyword in text for keyword in keywords):
            return category

    return "Прочее"


def build_categories_report(entries: List[Entry]) -> str:
    expense_entries = [entry for entry in entries if entry.amount < 0]

    if not expense_entries:
        return "За текущий месяц расходов пока нет."

    totals: dict[str, float] = {}

    for entry in expense_entries:
        category = detect_category(entry.description)
        totals[category] = totals.get(category, 0) + abs(entry.amount)

    sorted_totals = sorted(totals.items(), key=lambda x: x[1], reverse=True)

    lines = ["Расходы по категориям за текущий месяц:", ""]

    for category, total in sorted_totals:
        lines.append(f"• {category}: {total:.2f} ₽")

    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            START_TEXT,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MAIN_KEYBOARD,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            START_TEXT,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MAIN_KEYBOARD,
        )


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    entries = filter_today(storage.list_entries(update.effective_user.id))
    await update.message.reply_text(build_period_summary(entries, "Сводка за сегодня"))


async def month_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    entries = filter_current_month(storage.list_entries(update.effective_user.id))
    await update.message.reply_text(build_period_summary(entries, "Сводка за текущий месяц"))


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    total = sum_amount(storage.list_entries(update.effective_user.id))
    await update.message.reply_text(f"Текущий баланс: {format_money(total)}")


async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    entries = filter_current_month(storage.list_entries(update.effective_user.id))
    await update.message.reply_text(build_categories_report(entries))


async def last_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    entries = storage.list_entries(update.effective_user.id)[-10:]
    if not entries:
        await update.message.reply_text("Операций пока нет.")
        return

    text_out = "Последние 10 операций:\n" + "\n".join(
        f"• {format_entry(item)}" for item in entries
    )
    await update.message.reply_text(text_out)


async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    entries = storage.list_entries(update.effective_user.id)
    if not entries:
        await update.message.reply_text("Удалять пока нечего.")
        return

    last = entries[-1]
    removed = storage.delete_entry(last.id, update.effective_user.id)

    if removed:
        await update.message.reply_text(
            f"Удалил последнюю операцию:\n{format_entry(removed)}"
        )
    else:
        await update.message.reply_text("Не удалось удалить последнюю операцию.")


async def add_entry_from_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message or not update.effective_user or not update.message.text:
        return

    parsed = parse_entry(update.message.text)
    if not parsed:
        await update.message.reply_text(
            "Не понял формат.\n\nПримеры:\n-350 кофе\n+50000 зарплата"
        )
        return

    amount, description = parsed

    entry = Entry(
        id=str(uuid.uuid4()),
        user_id=update.effective_user.id,
        amount=amount,
        description=description,
        created_at=datetime.now().isoformat(),
    )
    storage.add_entry(entry)

    category = detect_category(description)
    await update.message.reply_text(
        "Операция сохранена\n"
        f"{format_entry(entry)}\n"
        f"Категория: {category}"
    )


async def handle_menu_buttons(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message or not update.effective_user or not update.message.text:
        return

    text = update.message.text.strip()

    if text == "📅 Сегодня":
        entries = filter_today(storage.list_entries(update.effective_user.id))
        await update.message.reply_text(build_period_summary(entries, "Сводка за сегодня"))
        return

    if text == "📆 Месяц":
        entries = filter_current_month(storage.list_entries(update.effective_user.id))
        await update.message.reply_text(
            build_period_summary(entries, "Сводка за текущий месяц")
        )
        return

    if text == "💰 Баланс":
        total = sum_amount(storage.list_entries(update.effective_user.id))
        await update.message.reply_text(f"Текущий баланс: {format_money(total)}")
        return

    if text == "📊 Категории":
        entries = filter_current_month(storage.list_entries(update.effective_user.id))
        await update.message.reply_text(build_categories_report(entries))
        return

    if text == "🕘 Последние":
        entries = storage.list_entries(update.effective_user.id)[-10:]
        if not entries:
            await update.message.reply_text("Операций пока нет.")
            return

        text_out = "Последние 10 операций:\n" + "\n".join(
            f"• {format_entry(item)}" for item in entries
        )
        await update.message.reply_text(text_out)
        return

    if text == "↩️ Отменить":
        entries = storage.list_entries(update.effective_user.id)
        if not entries:
            await update.message.reply_text("Удалять пока нечего.")
            return

        last = entries[-1]
        removed = storage.delete_entry(last.id, update.effective_user.id)

        if removed:
            await update.message.reply_text(
                f"Удалил последнюю операцию:\n{format_entry(removed)}"
            )
        else:
            await update.message.reply_text("Не удалось удалить последнюю операцию.")
        return

    await add_entry_from_text(update, context)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не найден TG_BOT_API_KEY в .env файле или переменных окружения"
        )

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("month", month_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("categories", categories_command))
    application.add_handler(CommandHandler("last", last_command))
    application.add_handler(CommandHandler("undo", undo_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_buttons)
    )

    logger.info("Бот запущен")
    application.run_polling()


if __name__ == "__main__":
    main()
