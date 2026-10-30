"""Relational backends: SQLite for local work and tests, any DB-API 2.0 connection for the rest."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from xgen_data_studio.backends.base import Backend, Capabilities, Result
from xgen_data_studio.compile.base import Compiled

_QMARK = re.compile(r"\?(?=(?:[^']*'[^']*')*[^']*$)")


class SqliteBackend(Backend):
    def __init__(self, path: str = ":memory:", *, conn: sqlite3.Connection | None = None, name: str = "sqlite"):
        self.conn = conn or sqlite3.connect(path, check_same_thread=False)
        self.name = name
        self.capabilities = Capabilities("sql", "sqlite", write=True)

    def script(self, sql: str) -> None:
        self.conn.executescript(sql)
        self.conn.commit()

    def execute(self, compiled: Compiled, values: dict[str, Any] | None = None) -> Result:
        text, args = compiled.bind(values)
        cur = self.conn.execute(text, args)
        return Result(compiled.columns, [tuple(r) for r in cur.fetchall()], self.name, compiled)

    def run(self, sql: str, args: tuple = ()) -> int:
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur.rowcount

    def fetch(self, sql: str, args: tuple = ()) -> list[tuple]:
        return [tuple(r) for r in self.conn.execute(sql, args).fetchall()]

    def columns(self, table: str) -> dict[str, str] | None:
        rows = self.conn.execute(f'PRAGMA table_info("{table.replace(chr(34), chr(34) * 2)}")').fetchall()
        return {r[1].lower(): (r[2] or "") for r in rows} if rows else None


class DbApiBackend(Backend):
    """Any DB-API connection; `paramstyle` follows the driver (psycopg: format, oracledb: numeric)."""

    def __init__(self, conn: Any, dialect: str = "postgres", *, paramstyle: str = "format", name: str = ""):
        self.conn = conn
        self.paramstyle = paramstyle
        self.name = name or dialect
        self.capabilities = Capabilities("sql", dialect, write=True)

    def _text(self, text: str) -> str:
        if self.paramstyle == "qmark":
            return text
        if self.paramstyle == "format":
            return _QMARK.sub("%s", text.replace("%", "%%"))
        if self.paramstyle == "numeric":
            n = iter(range(1, 10_000))
            return _QMARK.sub(lambda _: f":{next(n)}", text)
        raise ValueError(f"unsupported paramstyle '{self.paramstyle}'")

    def execute(self, compiled: Compiled, values: dict[str, Any] | None = None) -> Result:
        text, args = compiled.bind(values)
        cur = self.conn.cursor()
        try:
            cur.execute(self._text(text), args)
            rows = [tuple(r) for r in cur.fetchall()]
        finally:
            cur.close()
        return Result(compiled.columns, rows, self.name, compiled)

    def run(self, sql: str, args: tuple = ()) -> int:
        cur = self.conn.cursor()
        try:
            cur.execute(self._text(sql), args)
            n = cur.rowcount
        finally:
            cur.close()
        self.conn.commit()
        return n

    def fetch(self, sql: str, args: tuple = ()) -> list[tuple]:
        cur = self.conn.cursor()
        try:
            cur.execute(self._text(sql), args)
            return [tuple(r) for r in cur.fetchall()]
        finally:
            cur.close()

    def columns(self, table: str) -> dict[str, str] | None:
        dialect = self.capabilities.dialect
        if dialect == "sqlite":
            rows = self.fetch(f'PRAGMA table_info("{table}")')
            return {r[1].lower(): (r[2] or "") for r in rows} if rows else None
        if dialect == "oracle":
            rows = self.fetch("SELECT column_name, data_type FROM all_tab_columns WHERE table_name = ?",
                              (table.upper(),))
        else:
            rows = self.fetch("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ?",
                              (table,))
        return {str(r[0]).lower(): str(r[1] or "") for r in rows} if rows else None
