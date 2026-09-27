"""Small, synchronous SQLite operations; no network work in transactions."""

import copy
import json
import sqlite3
from pathlib import Path

SEED = {
    "id": "repatha-001",
    "patient": "Morgan Ellis",
    "date_of_birth": "1978-04-16",
    "member_id": "DEMO-482719",
    "provider": "Dr. Avery Chen",
    "provider_npi": "DEMO-NPI",
    "practice": "Northline Cardiology",
    "medication": "Repatha",
    "dose": "140 mg every two weeks",
    "payer": "Meridian Benefits · simulated",
    "diagnosis": "Familial hypercholesterolemia",
    "request": "Check the prior authorization requirements and arrange clinical review if required.",
    "evidence": "SYNTHETIC DEMO ONLY. The supplied chart states familial hypercholesterolemia and prior trials of atorvastatin and ezetimibe. No LDL value, dates of therapy, or intolerance details have been supplied. Ask the doctor if these are needed. Never invent them.",
}


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.db.commit()
        if self.get("case") is None:
            self.put("case", copy.deepcopy(SEED))

    def get(self, key: str):
        row = self.db.execute("SELECT body FROM documents WHERE id=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO documents VALUES (?,?)", (key, json.dumps(value)))

    def calls(self):
        rows = self.db.execute(
            "SELECT body FROM documents WHERE id LIKE 'call:%' ORDER BY rowid DESC LIMIT 30"
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def close(self):
        self.db.close()
