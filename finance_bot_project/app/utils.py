from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Iterable

from .storage import Entry

ENTRY_RE = re.compile(
    r'^\s*(?P<sign>[+-])\s*(?P<amount>\d+(?:[.,]\d{1,2})?)\s*(?P<rest>.*)$',
    re.IGNORECASE,
)


def parse_entry_text(text: str) -> tuple[float, str, str] | None:
    match = ENTRY_RE.match(text.strip())
    if not match:
        return None

    sign = -1 if match.group('sign') == '-' else 1
    amount = float(match.group('amount').replace(',', '.')) * sign
    rest = match.group('rest').strip()

    category = 'прочее'
    note = ''
    if rest:
        parts = [part.strip() for part in re.split(r'\s*[—\-–|/]\s*', rest, maxsplit=1)]
        if len(parts) == 2:
            category, note = parts[0], parts[1]
        else:
            category = parts[0]
    return amount, category or 'прочее', note


def filter_today(entries: Iterable[Entry]) -> list[Entry]:
    today = date.today()
    return [e for e in entries if datetime.fromisoformat(e.created_at).date() == today]


def filter_current_month(entries: Iterable[Entry]) -> list[Entry]:
    today = date.today()
    return [
        e for e in entries
        if (dt := datetime.fromisoformat(e.created_at)).year == today.year and dt.month == today.month
    ]


def sum_amount(entries: Iterable[Entry]) -> float:
    return round(sum(item.amount for item in entries), 2)


def build_categories_report(entries: Iterable[Entry]) -> str:
    grouped: dict[str, float] = defaultdict(float)
    expenses_total = 0.0
    for entry in entries:
        if entry.amount < 0:
            value = abs(entry.amount)
            grouped[entry.category] += value
            expenses_total += value

    if not grouped:
        return 'Пока нет расходов по категориям.'

    lines = ['Расходы по категориям:']
    for category, amount in sorted(grouped.items(), key=lambda x: x[1], reverse=True):
        share = (amount / expenses_total * 100) if expenses_total else 0
        lines.append(f'• {category}: {amount:.2f} ₽ ({share:.0f}%)')
    return '\n'.join(lines)


def format_entry(entry: Entry) -> str:
    sign = '+' if entry.amount > 0 else ''
    note = f' | {entry.note}' if entry.note else ''
    dt = datetime.fromisoformat(entry.created_at).strftime('%d.%m %H:%M')
    return f'{dt} | {sign}{entry.amount:.2f} ₽ | {entry.category}{note} | id: {entry.id}'


def build_period_summary(entries: list[Entry], title: str) -> str:
    income = round(sum(e.amount for e in entries if e.amount > 0), 2)
    expenses = round(sum(abs(e.amount) for e in entries if e.amount < 0), 2)
    balance = round(income - expenses, 2)

    lines = [
        title,
        f'Доходы: {income:.2f} ₽',
        f'Расходы: {expenses:.2f} ₽',
        f'Баланс: {balance:.2f} ₽',
    ]

    if entries:
        lines.append('')
        lines.append('Последние операции:')
        for item in entries[-5:]:
            lines.append(f'• {format_entry(item)}')
    else:
        lines.append('')
        lines.append('Операций пока нет.')

    return '\n'.join(lines)
