"""
Run this ONCE to populate sample data for your project demonstration.
Command: python seed_data.py
"""
from database import get_db, init_db

def seed():
    init_db()
    conn = get_db()

    # Skip if already seeded
    if conn.execute("SELECT COUNT(*) c FROM customers").fetchone()['c'] > 0:
        print("Data already exists. Skipping seed.")
        conn.close()
        return

    customers = [
        ('Alice Kumar', 'alice@example.com', '9876543210', 'Chennai'),
        ('Bob Raj',     'bob@example.com',   '9876543211', 'Mumbai'),
        ('Carol Devi',  'carol@example.com', '9876543212', 'Delhi'),
    ]
    for c in customers:
        conn.execute("INSERT INTO customers (name,email,phone,address) VALUES (?,?,?,?)", c)

    accounts = [
        ('1000000001', 1, 'savings', 5000.0),
        ('1000000002', 2, 'current', 12000.0),
        ('1000000003', 3, 'savings', 800.0),
    ]
    for a in accounts:
        cur = conn.execute(
            "INSERT INTO accounts (account_number,customer_id,account_type,balance) VALUES (?,?,?,?)",
            a)
        acc_id = cur.lastrowid
        conn.execute('''INSERT INTO transactions
            (account_id,type,amount,balance_after,description)
            VALUES (?,?,?,?,?)''',
            (acc_id, 'deposit', a[3], a[3], 'Initial deposit'))

    # A transfer example
    conn.execute("UPDATE accounts SET balance=balance-500 WHERE account_number='1000000001'")
    conn.execute("UPDATE accounts SET balance=balance+500 WHERE account_number='1000000002'")
    conn.execute('''INSERT INTO transactions
        (account_id,type,amount,balance_after,description,related_account)
        VALUES (1,'transfer_out',500,4500,'Transfer to 1000000002','1000000002')''')
    conn.execute('''INSERT INTO transactions
        (account_id,type,amount,balance_after,description,related_account)
        VALUES (2,'transfer_in',500,12500,'Transfer from 1000000001','1000000001')''')

    conn.commit()
    conn.close()
    print("Seed data inserted: 3 customers, 3 accounts, 5 transactions.")


if __name__ == '__main__':
    seed()