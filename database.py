"""SQLite Database Management"""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from config import DATABASE_PATH
from logger_config import logger

class Database:
    """Thread-safe SQLite database wrapper"""
    
    def __init__(self, path: str = DATABASE_PATH):
        self.path = path
        self._lock = threading.RLock()
        self.init()
    
    def _get_connection(self):
        """Get SQLite connection with proper settings"""
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init(self):
        """Initialize database schema"""
        with self._lock:
            with self._get_connection() as con:
                # Users table
                con.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        joined_date TEXT,
                        total_pdfs INTEGER DEFAULT 0,
                        premium INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # User settings
                con.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        user_id INTEGER PRIMARY KEY,
                        font_name TEXT DEFAULT 'Auto',
                        font_size INTEGER DEFAULT 12,
                        page_size TEXT DEFAULT 'A4',
                        margin INTEGER DEFAULT 18,
                        line_spacing REAL DEFAULT 1.25,
                        alignment TEXT DEFAULT 'L',
                        bold_title INTEGER DEFAULT 1,
                        title_size INTEGER DEFAULT 16,
                        header TEXT DEFAULT '',
                        footer TEXT DEFAULT 'PDF Mitra Pro',
                        theme TEXT DEFAULT 'light'
                    )
                """)
                
                # Fonts registry
                con.execute("""
                    CREATE TABLE IF NOT EXISTS fonts (
                        font_name TEXT PRIMARY KEY,
                        font_path TEXT NOT NULL,
                        devanagari INTEGER DEFAULT 0,
                        language TEXT DEFAULT 'en',
                        font_hash TEXT UNIQUE,
                        font_family TEXT,
                        font_style TEXT DEFAULT 'Regular',
                        added_by INTEGER,
                        added_at TEXT,
                        UNIQUE(font_hash, language)
                    )
                """)
                
                # Daily usage tracking
                con.execute("""
                    CREATE TABLE IF NOT EXISTS daily_usage (
                        user_id INTEGER NOT NULL,
                        usage_date TEXT NOT NULL,
                        pdf_count INTEGER DEFAULT 0,
                        PRIMARY KEY (user_id, usage_date)
                    )
                """)
                
                # AI usage tracking
                con.execute("""
                    CREATE TABLE IF NOT EXISTS ai_usage (
                        user_id INTEGER NOT NULL,
                        usage_date TEXT NOT NULL,
                        request_count INTEGER DEFAULT 0,
                        fallback_count INTEGER DEFAULT 0,
                        PRIMARY KEY (user_id, usage_date)
                    )
                """)
                
                # Documents (PDFs)
                con.execute("""
                    CREATE TABLE IF NOT EXISTS documents (
                        id TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        filename TEXT NOT NULL,
                        sha256 TEXT NOT NULL,
                        page_count INTEGER DEFAULT 0,
                        language TEXT DEFAULT 'auto',
                        status TEXT DEFAULT 'ready',
                        created_at TEXT NOT NULL,
                        expires_at TEXT
                    )
                """)
                
                # Document chunks (for RAG)
                con.execute("""
                    CREATE TABLE IF NOT EXISTS document_chunks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        document_id TEXT NOT NULL,
                        user_id INTEGER NOT NULL,
                        page_number INTEGER NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        FOREIGN KEY (document_id) REFERENCES documents(id)
                    )
                """)
                
                # Operation history
                con.execute("""
                    CREATE TABLE IF NOT EXISTS history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        operation_type TEXT NOT NULL,
                        filename TEXT,
                        pages INTEGER DEFAULT 0,
                        status TEXT DEFAULT 'success',
                        error_message TEXT,
                        created_at TEXT NOT NULL
                    )
                """)
                
                # Configuration key-value store
                con.execute("""
                    CREATE TABLE IF NOT EXISTS config (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TEXT
                    )
                """)
                
                # Create indexes
                con.execute("CREATE INDEX IF NOT EXISTS idx_daily_usage ON daily_usage(user_id, usage_date)")
                con.execute("CREATE INDEX IF NOT EXISTS idx_document_chunks ON document_chunks(user_id, document_id)")
                con.execute("CREATE INDEX IF NOT EXISTS idx_documents ON documents(user_id, created_at)")
                con.execute("CREATE INDEX IF NOT EXISTS idx_history ON history(user_id, created_at)")
                
                con.commit()
                logger.info("Database initialized successfully")
    
    def user(self, user_id: int, username: Optional[str] = None, first_name: Optional[str] = None, last_name: Optional[str] = None) -> Dict:
        """Get or create user"""
        with self._lock:
            with self._get_connection() as con:
                row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
                if row:
                    return dict(row)
                
                # Create new user
                now = datetime.now().isoformat()
                con.execute(
                    "INSERT INTO users (user_id, username, first_name, last_name, joined_date) VALUES (?, ?, ?, ?, ?)",
                    (user_id, username, first_name, last_name, now)
                )
                con.execute("INSERT OR IGNORE INTO settings(user_id) VALUES (?)", (user_id,))
                con.commit()
                
                return {
                    "user_id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "joined_date": now,
                    "total_pdfs": 0,
                    "premium": 0,
                }
    
    def reserve_pdf_slot(self, user_id: int, is_premium: bool, is_owner: bool) -> Tuple[bool, int, int]:
        """Atomically reserve one PDF slot"""
        from config import FREE_DAILY_PDFS, PREMIUM_DAILY_PDFS
        
        limit = float('inf') if is_owner else (PREMIUM_DAILY_PDFS if is_premium else FREE_DAILY_PDFS)
        if is_owner:
            return True, 0, 999
        
        today = datetime.now().date().isoformat()
        with self._lock:
            with self._get_connection() as con:
                con.execute("BEGIN IMMEDIATE")
                try:
                    row = con.execute(
                        "SELECT pdf_count FROM daily_usage WHERE user_id=? AND usage_date=?",
                        (user_id, today)
                    ).fetchone()
                    used = int(row[0]) if row else 0
                    
                    if used >= limit:
                        con.rollback()
                        return False, used, int(limit)
                    
                    con.execute(
                        "INSERT INTO daily_usage(user_id,usage_date,pdf_count) VALUES (?,?,1) "
                        "ON CONFLICT(user_id,usage_date) DO UPDATE SET pdf_count=pdf_count+1",
                        (user_id, today),
                    )
                    con.commit()
                    return True, used + 1, int(limit)
                except Exception as e:
                    con.rollback()
                    logger.error(f"PDF slot reservation failed: {e}")
                    return False, 0, 0
    
    def release_pdf_slot(self, user_id: int):
        """Release reserved PDF slot"""
        today = datetime.now().date().isoformat()
        with self._lock:
            with self._get_connection() as con:
                con.execute("BEGIN IMMEDIATE")
                try:
                    con.execute(
                        "UPDATE daily_usage SET pdf_count=MAX(pdf_count-1,0) WHERE user_id=? AND usage_date=?",
                        (user_id, today),
                    )
                    con.commit()
                except Exception as e:
                    con.rollback()
                    logger.error(f"PDF slot release failed: {e}")
    
    def daily_usage(self, user_id: int) -> int:
        """Get today's PDF count"""
        today = datetime.now().date().isoformat()
        with self._lock:
            with self._get_connection() as con:
                row = con.execute(
                    "SELECT pdf_count FROM daily_usage WHERE user_id=? AND usage_date=?",
                    (user_id, today)
                ).fetchone()
                return int(row[0]) if row else 0
    
    def settings(self, user_id: int) -> Dict:
        """Get user settings"""
        with self._lock:
            with self._get_connection() as con:
                row = con.execute(
                    "SELECT * FROM settings WHERE user_id=?", (user_id,)
                ).fetchone()
                if not row:
                    con.execute("INSERT INTO settings(user_id) VALUES (?)", (user_id,))
                    con.commit()
                    row = con.execute(
                        "SELECT * FROM settings WHERE user_id=?", (user_id,)
                    ).fetchone()
                return dict(row) if row else {}
    
    def update_settings(self, user_id: int, **kwargs):
        """Update user settings"""
        with self._lock:
            with self._get_connection() as con:
                current = self.settings(user_id)
                current.update(kwargs)
                
                con.execute("""
                    INSERT OR REPLACE INTO settings(
                        user_id, font_name, font_size, page_size, margin, line_spacing,
                        alignment, bold_title, title_size, header, footer, theme
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    current.get("font_name", "Auto"),
                    current.get("font_size", 12),
                    current.get("page_size", "A4"),
                    current.get("margin", 18),
                    current.get("line_spacing", 1.25),
                    current.get("alignment", "L"),
                    current.get("bold_title", 1),
                    current.get("title_size", 16),
                    current.get("header", ""),
                    current.get("footer", "PDF Mitra Pro"),
                    current.get("theme", "light"),
                ))
                con.commit()
    
    def set_premium(self, user_id: int, enabled: bool):
        """Set premium status"""
        with self._lock:
            with self._get_connection() as con:
                con.execute(
                    "UPDATE users SET premium=? WHERE user_id=?",
                    (int(enabled), user_id)
                )
                con.commit()
    
    def increment_pdf_count(self, user_id: int):
        """Increment total PDFs created"""
        with self._lock:
            with self._get_connection() as con:
                con.execute(
                    "UPDATE users SET total_pdfs=total_pdfs+1 WHERE user_id=?",
                    (user_id,)
                )
                con.commit()
    
    def get_config(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get configuration value"""
        with self._lock:
            with self._get_connection() as con:
                row = con.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
                return row[0] if row else default
    
    def set_config(self, key: str, value: str):
        """Set configuration value"""
        now = datetime.now().isoformat()
        with self._lock:
            with self._get_connection() as con:
                con.execute(
                    "INSERT INTO config(key,value,updated_at) VALUES (?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, value, now),
                )
                con.commit()
    
    def user_counts(self) -> Tuple[int, int, int]:
        """Get total users, premium users, total PDFs"""
        with self._lock:
            with self._get_connection() as con:
                total = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                premium = con.execute("SELECT COUNT(*) FROM users WHERE premium=1").fetchone()[0]
                pdfs = con.execute("SELECT COALESCE(SUM(total_pdfs),0) FROM users").fetchone()[0]
                return int(total), int(premium), int(pdfs)

# Global database instance
db = Database()
