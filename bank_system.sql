-- ============================================================
-- Bank Management System - SQL Source File
-- Name: <Your Name>
-- Register No: <Your Reg No>
-- ============================================================

-- ---------- ATTACH SECOND DATABASE ----------
ATTACH DATABASE 'audit.db' AS audit;

-- ---------- PRAGMA ----------
PRAGMA database_list;
PRAGMA foreign_keys = ON;

-- ---------- DDL: CREATE TABLES ----------
CREATE TABLE IF NOT EXISTS admin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT NOT NULL,
    address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_number TEXT UNIQUE NOT NULL,
    customer_id INTEGER NOT NULL,
    account_type TEXT NOT NULL,
    balance REAL DEFAULT 0.0,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    amount REAL NOT NULL,
    balance_after REAL NOT NULL,
    description TEXT,
    related_account TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS audit.audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_user TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit.deleted_customers (
    id INTEGER, name TEXT, email TEXT, phone TEXT, address TEXT,
    deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit.deleted_accounts (
    id INTEGER, account_number TEXT, customer_id INTEGER, balance REAL,
    deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------- TRIGGERS ----------
CREATE TRIGGER IF NOT EXISTS trg_balance_update
AFTER UPDATE OF balance ON accounts
WHEN OLD.balance <> NEW.balance
BEGIN
    INSERT INTO audit.audit_log (admin_user, action, details)
    VALUES ('SYSTEM', 'BALANCE_CHANGED',
            'Account ' || NEW.account_number || ': ' || OLD.balance || ' -> ' || NEW.balance);
END;

CREATE TRIGGER IF NOT EXISTS trg_status_change
AFTER UPDATE OF status ON accounts
WHEN OLD.status <> NEW.status
BEGIN
    INSERT INTO audit.audit_log (admin_user, action, details)
    VALUES ('SYSTEM', 'STATUS_CHANGED',
            'Account ' || NEW.account_number || ': ' || OLD.status || ' -> ' || NEW.status);
END;

CREATE TRIGGER IF NOT EXISTS trg_customer_delete
AFTER DELETE ON customers
BEGIN
    INSERT INTO audit.deleted_customers (id, name, email, phone, address)
    VALUES (OLD.id, OLD.name, OLD.email, OLD.phone, OLD.address);
END;

CREATE TRIGGER IF NOT EXISTS trg_account_delete
AFTER DELETE ON accounts
BEGIN
    INSERT INTO audit.deleted_accounts (id, account_number, customer_id, balance)
    VALUES (OLD.id, OLD.account_number, OLD.customer_id, OLD.balance);
END;

CREATE TRIGGER IF NOT EXISTS trg_prevent_negative
BEFORE UPDATE OF balance ON accounts
WHEN NEW.balance < 0
BEGIN
    SELECT RAISE(ABORT, 'Balance cannot be negative');
END;

-- ---------- SAMPLE DATA ----------
INSERT INTO customers (name, email, phone, address) VALUES
('Alice Kumar', 'alice@example.com', '9876543210', 'Chennai'),
('Bob Raj',     'bob@example.com',   '9876543211', 'Mumbai'),
('Carol Devi',  'carol@example.com', '9876543212', 'Delhi');

INSERT INTO accounts (account_number, customer_id, account_type, balance) VALUES
('1000000001', 1, 'savings', 5000),
('1000000002', 2, 'current', 12000),
('1000000003', 3, 'savings', 800);

INSERT INTO transactions (account_id, type, amount, balance_after, description) VALUES
(1, 'deposit',  5000, 5000, 'Initial deposit'),
(2, 'deposit', 12000, 12000, 'Initial deposit'),
(3, 'deposit',   800,   800, 'Initial deposit');

-- ---------- UTILITY COMMANDS (run from CLI) ----------
-- .tables
-- .schema
-- .database
-- .headers on
-- .mode column
-- .exit

-- ---------- DML DEMOS ----------
-- UPDATE (fires trigger)
UPDATE accounts SET balance = balance + 100 WHERE account_number = '1000000001';

-- DELETE (fires trigger → archived)
INSERT INTO customers (name, email, phone) VALUES ('Test', 'test@test.com', '0000000000');
DELETE FROM customers WHERE email = 'test@test.com';

-- ---------- SELECT DEMOS ----------
-- Simple
SELECT * FROM customers;
SELECT account_number, balance FROM accounts WHERE status = 'active';
SELECT * FROM accounts WHERE balance > 5000 ORDER BY balance DESC;

-- LIKE
SELECT * FROM customers WHERE name LIKE 'A%';

-- Aggregates
SELECT COUNT(*) FROM customers;
SELECT SUM(balance) FROM accounts;
SELECT AVG(balance) FROM accounts;
SELECT MAX(balance), MIN(balance) FROM accounts;

-- GROUP BY + HAVING
SELECT type, COUNT(*) AS cnt, SUM(amount) AS total
FROM transactions GROUP BY type;

SELECT c.name, COUNT(a.id) AS accounts, SUM(a.balance) AS total
FROM customers c JOIN accounts a ON a.customer_id = c.id
GROUP BY c.id HAVING COUNT(a.id) >= 1;

-- JOINS
SELECT a.account_number, c.name, a.balance
FROM accounts a JOIN customers c ON c.id = a.customer_id;

SELECT t.id, a.account_number, c.name, t.type, t.amount, t.created_at
FROM transactions t
JOIN accounts a ON a.id = t.account_id
JOIN customers c ON c.id = a.customer_id
ORDER BY t.id DESC;

-- Cross-database JOIN (bank.db + audit.db)
SELECT a.username, l.action, l.details, l.logged_at
FROM admin a
JOIN audit.audit_log l ON l.admin_user = a.username
ORDER BY l.id DESC;

-- LEFT JOIN (customers with no accounts)
SELECT c.name, c.email
FROM customers c LEFT JOIN accounts a ON a.customer_id = c.id
WHERE a.id IS NULL;

-- Subquery
SELECT account_number, balance FROM accounts
WHERE balance > (SELECT AVG(balance) FROM accounts);

-- Date / Time
SELECT * FROM transactions WHERE DATE(created_at) = DATE('now');
SELECT strftime('%Y-%m', created_at) AS month, COUNT(*), SUM(amount)
FROM transactions GROUP BY month;
SELECT datetime(created_at, 'localtime') FROM transactions LIMIT 5;

-- ---------- PRAGMA (screenshots for report) ----------
PRAGMA database_list;
PRAGMA table_info(accounts);
PRAGMA foreign_key_list(accounts);
PRAGMA integrity_check;
PRAGMA journal_mode;

-- ---------- DETACH ----------
DETACH DATABASE audit;