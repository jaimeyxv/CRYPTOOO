"""Persistencia SQLite para posicion, operaciones y eventos de Aurum."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Iterator

from .config import config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 5000")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as con:
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS position (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    symbol TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    quote_spent REAL NOT NULL,
                    opened_at TEXT NOT NULL,
                    order_id TEXT
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    quote_quantity REAL NOT NULL,
                    realized_pnl REAL,
                    realized_pnl_pct REAL,
                    reason TEXT NOT NULL,
                    order_id TEXT,
                    mode TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at DESC);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC);
                CREATE TABLE IF NOT EXISTS runtime_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
        self._migrate_json()

    def _migrate_json(self) -> None:
        legacy = self.path.parent / "posicion.json"
        if not legacy.exists() or self.position()["en_posicion"]:
            return
        try:
            old = json.loads(legacy.read_text(encoding="utf-8"))
            if old.get("en_posicion"):
                self.set_position({
                    "symbol": old.get("symbol", config.symbol),
                    "cantidad": float(old.get("cantidad", 0)),
                    "precio_entrada": float(old.get("precio_entrada", 0)),
                    "quote_spent": float(old.get("cantidad", 0)) * float(old.get("precio_entrada", 0)),
                    "hora": old.get("hora") or utc_now(),
                    "order_id": "legacy-json",
                })
                self.add_event("INFO", "storage", "Posicion migrada desde posicion.json")
            legacy.rename(legacy.with_suffix(".json.migrated"))
        except (OSError, ValueError, TypeError):
            self.add_event("WARNING", "storage", "No se pudo migrar posicion.json")

    @staticmethod
    def empty_position(symbol: str | None = None) -> dict:
        return {
            "en_posicion": False, "cantidad": 0.0, "precio_entrada": 0.0,
            "quote_spent": 0.0, "hora": None, "symbol": symbol or config.symbol,
            "order_id": None,
        }

    def position(self) -> dict:
        with self._lock, self._connect() as con:
            row = con.execute("SELECT * FROM position WHERE id = 1").fetchone()
        if row is None:
            return self.empty_position()
        return {
            "en_posicion": True,
            "cantidad": row["quantity"],
            "precio_entrada": row["entry_price"],
            "quote_spent": row["quote_spent"],
            "hora": row["opened_at"],
            "symbol": row["symbol"],
            "order_id": row["order_id"],
        }

    def set_position(self, position: dict) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                """INSERT OR REPLACE INTO position
                   (id, symbol, quantity, entry_price, quote_spent, opened_at, order_id)
                   VALUES (1, ?, ?, ?, ?, ?, ?)""",
                (position["symbol"], position["cantidad"], position["precio_entrada"],
                 position.get("quote_spent", 0), position["hora"], position.get("order_id")),
            )

    def clear_position(self) -> None:
        with self._lock, self._connect() as con:
            con.execute("DELETE FROM position WHERE id = 1")

    @staticmethod
    def _insert_trade(con: sqlite3.Connection, trade: dict) -> None:
        con.execute(
            """INSERT INTO trades
               (symbol, side, quantity, price, quote_quantity, realized_pnl,
                realized_pnl_pct, reason, order_id, mode, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trade["symbol"], trade["side"], trade["quantity"], trade["price"],
             trade["quote_quantity"], trade.get("realized_pnl"),
             trade.get("realized_pnl_pct"), trade["reason"], trade.get("order_id"),
             trade["mode"], trade.get("created_at", utc_now())),
        )

    def record_buy(self, position: dict, trade: dict) -> None:
        """Guarda orden y posicion en una sola transaccion."""
        with self._lock, self._connect() as con:
            self._insert_trade(con, trade)
            con.execute(
                """INSERT OR REPLACE INTO position
                   (id, symbol, quantity, entry_price, quote_spent, opened_at, order_id)
                   VALUES (1, ?, ?, ?, ?, ?, ?)""",
                (position["symbol"], position["cantidad"], position["precio_entrada"],
                 position["quote_spent"], position["hora"], position.get("order_id")),
            )

    def record_sell(self, trade: dict, remaining_position: dict | None = None) -> None:
        """Guarda la salida y actualiza o cierra la posicion atomicamente."""
        with self._lock, self._connect() as con:
            self._insert_trade(con, trade)
            if remaining_position:
                con.execute(
                    """INSERT OR REPLACE INTO position
                       (id, symbol, quantity, entry_price, quote_spent, opened_at, order_id)
                       VALUES (1, ?, ?, ?, ?, ?, ?)""",
                    (remaining_position["symbol"], remaining_position["cantidad"],
                     remaining_position["precio_entrada"], remaining_position["quote_spent"],
                     remaining_position["hora"], remaining_position.get("order_id")),
                )
            else:
                con.execute("DELETE FROM position WHERE id = 1")

    def trades(self, limit: int = 100) -> list[dict]:
        limit = max(1, min(limit, 500))
        with self._lock, self._connect() as con:
            rows = con.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def add_event(self, level: str, category: str, message: str) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                "INSERT INTO events(level, category, message, created_at) VALUES (?, ?, ?, ?)",
                (level.upper(), category, message[:1000], utc_now()),
            )
            con.execute(
                "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 5000)"
            )

    def events(self, limit: int = 50) -> list[dict]:
        limit = max(1, min(limit, 200))
        with self._lock, self._connect() as con:
            rows = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def set_runtime_state(self, key: str, value: str) -> None:
        """Persiste una preferencia operativa que debe sobrevivir reinicios."""
        if not key or len(key) > 100:
            raise ValueError("runtime state key invalida")
        with self._lock, self._connect() as con:
            con.execute(
                """INSERT INTO runtime_state(key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, value, utc_now()),
            )

    def get_runtime_state(self, key: str) -> str | None:
        with self._lock, self._connect() as con:
            row = con.execute("SELECT value FROM runtime_state WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row is not None else None

    def performance(self) -> dict:
        with self._lock, self._connect() as con:
            row = con.execute(
                """SELECT COUNT(*) AS closed,
                          COALESCE(SUM(realized_pnl), 0) AS pnl,
                          COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                          COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END), 0) AS gross_profit,
                          ABS(COALESCE(SUM(CASE WHEN realized_pnl < 0 THEN realized_pnl ELSE 0 END), 0)) AS gross_loss
                   FROM trades WHERE side = 'SELL'"""
            ).fetchone()
            volume = con.execute("SELECT COALESCE(SUM(quote_quantity), 0) FROM trades").fetchone()[0]
            equity_rows = con.execute(
                "SELECT created_at, realized_pnl FROM trades WHERE side = 'SELL' ORDER BY id"
            ).fetchall()
        closed, wins = int(row["closed"]), int(row["wins"])
        gross_loss = float(row["gross_loss"])
        acumulado = 0.0
        curve = []
        for item in equity_rows:
            acumulado += float(item["realized_pnl"] or 0)
            curve.append({"time": item["created_at"], "value": round(acumulado, 4)})
        return {
            "operaciones_cerradas": closed,
            "ganadoras": wins,
            "win_rate": round(wins / closed * 100, 2) if closed else 0.0,
            "pnl_realizado": round(float(row["pnl"]), 4),
            "volumen": round(float(volume), 4),
            "profit_factor": round(float(row["gross_profit"]) / gross_loss, 2) if gross_loss else None,
            "curva": curve,
        }

    def daily_activity(self) -> dict:
        with self._lock, self._connect() as con:
            row = con.execute(
                """SELECT COALESCE(SUM(CASE WHEN side = 'BUY' THEN 1 ELSE 0 END), 0) AS buys,
                          COALESCE(SUM(CASE WHEN side = 'SELL' THEN realized_pnl ELSE 0 END), 0) AS pnl,
                          MAX(CASE WHEN side = 'BUY' THEN created_at END) AS last_buy
                   FROM trades WHERE date(created_at) = date('now')"""
            ).fetchone()
        return {"compras": int(row["buys"]), "pnl": float(row["pnl"]), "ultima_compra": row["last_buy"]}

    def healthy(self) -> bool:
        try:
            with self._connect() as con:
                return con.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False


storage = Storage(config.database_path)
