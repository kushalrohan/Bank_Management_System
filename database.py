import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'bank.db')
AUDIT_PATH = os.path.join(BASE_DIR, 'audit.db')


def get_db():
    """Open bank.db and ATTACH audit.db as 'audit'."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(f"ATTACH DATABASE '{AUDIT_PATH}' AS audit")
    except sqlite3.OperationalError:
        pass
    return conn


def init_db():
    """Create all tables and triggers."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f"ATTACH DATABASE '{AUDIT_PATH}' AS audit")
    conn.execute("PRAGMA foreign_keys = ON")
    c = conn.cursor()

    # ---------- bank.db tables ----------
    c.execute('''CREATE TABLE IF NOT EXISTS admin (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT NOT NULL,
        address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_number TEXT UNIQUE NOT NULL,
        customer_id INTEGER NOT NULL,
        account_type TEXT NOT NULL,
        balance REAL DEFAULT 0.0,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers(id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        amount REAL NOT NULL,
        balance_after REAL NOT NULL,
        description TEXT,
        related_account TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (account_id) REFERENCES accounts(id))''')

    # ---------- LOCAL audit tables (in bank.db so triggers can write) ----------
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_user TEXT NOT NULL,
        action TEXT NOT NULL,
        details TEXT,
        logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS deleted_customers (
        id INTEGER,
        name TEXT,
        email TEXT,
        phone TEXT,
        address TEXT,
        deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS deleted_accounts (
        id INTEGER,
        account_number TEXT,
        customer_id INTEGER,
        balance REAL,
        deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # ---------- audit.db mirror tables (populated by Python, not triggers) ----------
    c.execute('''CREATE TABLE IF NOT EXISTS audit.audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_user TEXT NOT NULL,
        action TEXT NOT NULL,
        details TEXT,
        logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS audit.deleted_customers (
        id INTEGER, name TEXT, email TEXT, phone TEXT, address TEXT,
        deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS audit.deleted_accounts (
        id INTEGER, account_number TEXT, customer_id INTEGER, balance REAL,
        deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # ---------- TRIGGERS (write to LOCAL tables only) ----------

    # 1. Log every balance change (UPDATE)
    c.execute('''CREATE TRIGGER IF NOT EXISTS trg_balance_update
    AFTER UPDATE OF balance ON accounts
    WHEN OLD.balance <> NEW.balance
    BEGIN
        INSERT INTO audit_log (admin_user, action, details)
        VALUES ('SYSTEM', 'BALANCE_CHANGED',
                'Account ' || NEW.account_number ||
                ': ' || OLD.balance || ' -> ' || NEW.balance);
    END;''')

    # 2. Log every account status change (UPDATE)
    c.execute('''CREATE TRIGGER IF NOT EXISTS trg_status_change
    AFTER UPDATE OF status ON accounts
    WHEN OLD.status <> NEW.status
    BEGIN
        INSERT INTO audit_log (admin_user, action, details)
        VALUES ('SYSTEM', 'STATUS_CHANGED',
                'Account ' || NEW.account_number ||
                ': ' || OLD.status || ' -> ' || NEW.status);
    END;''')

    # 3. Archive deleted customers (DELETE)
    c.execute('''CREATE TRIGGER IF NOT EXISTS trg_customer_delete
    AFTER DELETE ON customers
    BEGIN
        INSERT INTO deleted_customers (id, name, email, phone, address)
        VALUES (OLD.id, OLD.name, OLD.email, OLD.phone, OLD.address);
    END;''')

    # 4. Archive deleted accounts (DELETE)
    c.execute('''CREATE TRIGGER IF NOT EXISTS trg_account_delete
    AFTER DELETE ON accounts
    BEGIN
        INSERT INTO deleted_accounts (id, account_number, customer_id, balance)
        VALUES (OLD.id, OLD.account_number, OLD.customer_id, OLD.balance);
    END;''')

    # 5. Prevent negative balance (UPDATE safety)
    c.execute('''CREATE TRIGGER IF NOT EXISTS trg_prevent_negative
    BEFORE UPDATE OF balance ON accounts
    WHEN NEW.balance < 0
    BEGIN
        SELECT RAISE(ABORT, 'Balance cannot be negative');
    END;''')

    # ---------- Default admin ----------
    from werkzeug.security import generate_password_hash
    c.execute("SELECT * FROM admin WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO admin (username, password) VALUES (?, ?)",
                  ('admin', generate_password_hash('admin123')))

    conn.commit()
    conn.close()
    print("Database initialized: bank.db (with local audit tables) + audit.db (mirror).")


def log_action(admin_user, action, details=""):
    """Write to BOTH local audit_log (bank.db) and mirror audit.audit_log (audit.db).
    This demonstrates cross-database insertion via ATTACH."""
    conn = get_db()
    # Local copy (bank.db)
    conn.execute('''INSERT INTO audit_log (admin_user, action, details)
                    VALUES (?, ?, ?)''', (admin_user, action, details))
    # Mirror copy (audit.db) — cross-database INSERT via ATTACH
    conn.execute('''INSERT INTO audit.audit_log (admin_user, action, details)
                    VALUES (?, ?, ?)''', (admin_user, action, details))
    conn.commit()
    conn.close()


def sync_triggers_to_audit_db():
    """Copy local trigger-generated rows into the attached audit.db.
    Call this after any delete/status operation to keep audit.db in sync.
    This is what makes audit.db non-empty for the report screenshots."""
    conn = get_db()
    # Sync audit_log
    conn.execute('''INSERT INTO audit.audit_log (admin_user, action, details, logged_at)
                    SELECT admin_user, action, details, logged_at FROM audit_log
                    WHERE id NOT IN (SELECT id FROM audit.audit_log)''')
    # Sync deleted_customers
    conn.execute('''INSERT INTO audit.deleted_customers
                    (id, name, email, phone, address, deleted_at)
                    SELECT id, name, email, phone, address, deleted_at
                    FROM deleted_customers
                    WHERE id NOT IN (SELECT id FROM audit.deleted_customers)''')
    # Sync deleted_accounts
    conn.execute('''INSERT INTO audit.deleted_accounts
                    (id, account_number, customer_id, balance, deleted_at)
                    SELECT id, account_number, customer_id, balance, deleted_at
                    FROM deleted_accounts
                    WHERE id NOT IN (SELECT id FROM audit.deleted_accounts)''')
    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_db()