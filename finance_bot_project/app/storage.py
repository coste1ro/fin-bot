from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
DATA_FILE = DATA_DIR / 'finance_data.json'


@dataclass(slots=True)
class Entry:
    id: str
    user_id: int
    amount: float
    category: str
    note: str
    created_at: str


class Storage:
    def __init__(self, data_file: Path = DATA_FILE) -> None:
        self.data_file = data_file
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.data_file.exists():
            self._write({'entries': []})

    def _read(self) -> dict[str, Any]:
        with self.data_file.open('r', encoding='utf-8') as f:
            return json.load(f)

    def _write(self, payload: dict[str, Any]) -> None:
        with self.data_file.open('w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def add_entry(self, user_id: int, amount: float, category: str, note: str) -> Entry:
        payload = self._read()
        entry = Entry(
            id=str(uuid4())[:8],
            user_id=user_id,
            amount=round(amount, 2),
            category=category.strip().lower() or 'прочее',
            note=note.strip(),
            created_at=datetime.now().isoformat(timespec='seconds'),
        )
        payload['entries'].append(asdict(entry))
        self._write(payload)
        return entry

    def list_entries(self, user_id: int) -> list[Entry]:
        payload = self._read()
        items = [Entry(**item) for item in payload.get('entries', []) if item['user_id'] == user_id]
        items.sort(key=lambda item: item.created_at)
        return items

    def delete_entry(self, entry_id: str, user_id: int) -> Entry | None:
        payload = self._read()
        removed = None
        kept = []
        for item in payload.get('entries', []):
            if item['id'] == entry_id and item['user_id'] == user_id and removed is None:
                removed = Entry(**item)
                continue
            kept.append(item)
        payload['entries'] = kept
        self._write(payload)
        return removed
