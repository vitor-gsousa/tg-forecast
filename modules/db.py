import sqlite3
import os
import logging
import datetime

DB_PATH = os.environ.get("DB_PATH", "tg_forecast.db")

def get_db():
    # Aumentar o timeout de 5 para 15 segundos em caso de concorrência
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    # Ativar Write-Ahead Logging para permitir leitura e escrita em simultâneo
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS feeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            last_checked DATETIME,
            status TEXT DEFAULT 'active'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_id INTEGER,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            article_hash TEXT NOT NULL UNIQUE,
            published_at DATETIME,
            FOREIGN KEY (feed_id) REFERENCES feeds(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS ipma_warnings (
            warning_id TEXT PRIMARY KEY,
            expiry_ts REAL NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            level TEXT,
            message TEXT
        )
    ''')
    conn.commit()
    conn.close()

class DBLogHandler(logging.Handler):
    def emit(self, record):
        try:
            conn = get_db()
            c = conn.cursor()
            now_local = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                "INSERT INTO logs (timestamp, level, message) VALUES (?, ?, ?)",
                (now_local, record.levelname, self.format(record))
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
