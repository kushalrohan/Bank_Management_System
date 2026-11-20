from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from functools import wraps
from database import get_db, init_db, log_action, sync_triggers_to_audit_db
import random
import string

app = Flask(__name__)
app.secret_key = 'change-this-secret-key-in-production'


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin' not in session:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def generate_account_number():
    conn = get_db()
    while True:
        num = ''.join(random.choices(string.digits, k=10))
        if not conn.execute("SELECT id FROM accounts WHERE account_number=?",
                            (num,)).fetchone():
            conn.close()
            return num


# ---------- Auth ----------
@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        admin = conn.execute("SELECT * FROM admin WHERE username=?",
                             (username,)).fetchone()
        conn.close()
        if admin and check_password_hash(admin['password'], password):
            session['admin'] = admin['username']
            log_action(username, 'LOGIN', 'Admin logged in')
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    if session.get('admin'):
        log_action(session['admin'], 'LOGOUT', 'Admin logged out')
    session.pop('admin', None)
    flash('Logged out.', 'success')
    return redirect(url_for('login'))


# ---------- Dashboard ----------
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    total_customers = conn.execute("SELECT COUNT(*) c FROM customers").fetchone()['c']
    total_accounts = conn.execute("SELECT COUNT(*) c FROM accounts").fetchone()['c']
    active_accounts = conn.execute("SELECT COUNT(*) c FROM accounts WHERE status='active'").fetchone()['c']
    total_balance = conn.execute("SELECT COALESCE(SUM(balance),0) s FROM accounts").fetchone()['s']
    recent = conn.execute('''SELECT t.*, a.account_number FROM transactions t
                             JOIN accounts a ON a.id=t.account_id
                             ORDER BY t.id DESC LIMIT 10''').fetchall()
    conn.close()
    return render_template('dashboard.html',
                           total_customers=total_customers,
                           total_accounts=total_accounts,
                           active_accounts=active_accounts,
                           total_balance=total_balance,
                           recent=recent)


# ---------- Customer Registration ----------
@app.route('/register_customer', methods=['GET', 'POST'])
@login_required
def register_customer():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        phone = request.form['phone'].strip()
        address = request.form.get('address', '').strip()
        conn = get_db()
        try:
            conn.execute("INSERT INTO customers (name,email,phone,address) VALUES (?,?,?,?)",
                         (name, email, phone, address))
            conn.commit()
            log_action(session['admin'], 'REGISTER_CUSTOMER', f"{name} / {email}")
            flash(f'Customer "{name}" registered successfully.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        finally:
            conn.close()
        return redirect(url_for('register_customer'))

    conn = get_db()
    customers = conn.execute("SELECT * FROM customers ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('register_customer.html', customers=customers)


@app.route('/delete_customer/<int:cid>')
@login_required
def delete_customer(cid):
    conn = get_db()
    accs = conn.execute("SELECT COUNT(*) c FROM accounts WHERE customer_id=?",
                        (cid,)).fetchone()['c']
    if accs > 0:
        conn.close()
        flash('Cannot delete — customer still has accounts.', 'danger')
        return redirect(url_for('register_customer'))
    cust = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    if not cust:
        conn.close()
        flash('Customer not found.', 'danger')
        return redirect(url_for('register_customer'))
    conn.execute("DELETE FROM customers WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    log_action(session['admin'], 'DELETE_CUSTOMER', f"{cust['name']} / {cust['email']}")
    sync_triggers_to_audit_db()
    flash('Customer deleted (archived in audit.db via trigger).', 'success')
    return redirect(url_for('register_customer'))


# ---------- Account Creation ----------
@app.route('/create_account', methods=['GET', 'POST'])
@login_required
def create_account():
    conn = get_db()
    if request.method == 'POST':
        customer_id = request.form['customer_id']
        account_type = request.form['account_type']
        initial = float(request.form.get('initial_deposit', 0) or 0)
        acc_no = generate_account_number()
        try:
            cur = conn.execute(
                "INSERT INTO accounts (account_number,customer_id,account_type,balance) VALUES (?,?,?,?)",
                (acc_no, customer_id, account_type, initial))
            acc_id = cur.lastrowid
            if initial > 0:
                conn.execute('''INSERT INTO transactions
                    (account_id,type,amount,balance_after,description)
                    VALUES (?,?,?,?,?)''',
                    (acc_id, 'deposit', initial, initial, 'Initial deposit'))
            conn.commit()
            log_action(session['admin'], 'CREATE_ACCOUNT',
                       f"{acc_no} for customer_id={customer_id} initial={initial}")
            flash(f'Account created: {acc_no}', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        return redirect(url_for('create_account'))

    customers = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    accounts = conn.execute('''SELECT a.*, c.name FROM accounts a
                               JOIN customers c ON c.id=a.customer_id
                               ORDER BY a.id DESC''').fetchall()
    conn.close()
    return render_template('create_account.html',
                           customers=customers, accounts=accounts)


def get_account(acc_no):
    conn = get_db()
    acc = conn.execute('''SELECT a.*, c.name, c.email FROM accounts a
                          JOIN customers c ON c.id=a.customer_id
                          WHERE a.account_number=?''', (acc_no,)).fetchone()
    conn.close()
    return acc


# ---------- Deposit ----------
@app.route('/deposit', methods=['GET', 'POST'])
@login_required
def deposit():
    if request.method == 'POST':
        acc_no = request.form['account_number'].strip()
        amount = float(request.form['amount'])
        if amount <= 0:
            flash('Amount must be positive.', 'danger')
            return redirect(url_for('deposit'))
        conn = get_db()
        acc = conn.execute("SELECT * FROM accounts WHERE account_number=?",
                           (acc_no,)).fetchone()
        if not acc:
            conn.close()
            flash('Account not found.', 'danger')
            return redirect(url_for('deposit'))
        if acc['status'] != 'active':
            conn.close()
            flash('Account is inactive.', 'danger')
            return redirect(url_for('deposit'))
        new_balance = acc['balance'] + amount
        conn.execute("UPDATE accounts SET balance=? WHERE id=?",
                     (new_balance, acc['id']))
        conn.execute('''INSERT INTO transactions (account_id,type,amount,balance_after,description)
                        VALUES (?,?,?,?,?)''',
                     (acc['id'], 'deposit', amount, new_balance, 'Deposit'))
        conn.commit()
        conn.close()
        log_action(session['admin'], 'DEPOSIT',
                   f"{amount} to {acc_no}, new balance {new_balance}")
        flash(f'Deposited ₹{amount:.2f}. New balance: ₹{new_balance:.2f}', 'success')
        return redirect(url_for('deposit'))
    return render_template('deposit.html')


# ---------- Withdraw ----------
@app.route('/withdraw', methods=['GET', 'POST'])
@login_required
def withdraw():
    if request.method == 'POST':
        acc_no = request.form['account_number'].strip()
        amount = float(request.form['amount'])
        if amount <= 0:
            flash('Amount must be positive.', 'danger')
            return redirect(url_for('withdraw'))
        conn = get_db()
        acc = conn.execute("SELECT * FROM accounts WHERE account_number=?",
                           (acc_no,)).fetchone()
        if not acc:
            conn.close()
            flash('Account not found.', 'danger')
            return redirect(url_for('withdraw'))
        if acc['status'] != 'active':
            conn.close()
            flash('Account is inactive.', 'danger')
            return redirect(url_for('withdraw'))
        if acc['balance'] < amount:
            conn.close()
            flash('Insufficient balance.', 'danger')
            return redirect(url_for('withdraw'))
        new_balance = acc['balance'] - amount
        conn.execute("UPDATE accounts SET balance=? WHERE id=?",
                     (new_balance, acc['id']))
        conn.execute('''INSERT INTO transactions (account_id,type,amount,balance_after,description)
                        VALUES (?,?,?,?,?)''',
                     (acc['id'], 'withdraw', amount, new_balance, 'Withdrawal'))
        conn.commit()
        conn.close()
        log_action(session['admin'], 'WITHDRAW',
                   f"{amount} from {acc_no}, new balance {new_balance}")
        flash(f'Withdrew ₹{amount:.2f}. New balance: ₹{new_balance:.2f}', 'success')
        return redirect(url_for('withdraw'))
    return render_template('withdraw.html')


# ---------- Transfer ----------
@app.route('/transfer', methods=['GET', 'POST'])
@login_required
def transfer():
    if request.method == 'POST':
        from_acc_no = request.form['from_account'].strip()
        to_acc_no = request.form['to_account'].strip()
        amount = float(request.form['amount'])
        if amount <= 0:
            flash('Amount must be positive.', 'danger')
            return redirect(url_for('transfer'))
        if from_acc_no == to_acc_no:
            flash('Cannot transfer to the same account.', 'danger')
            return redirect(url_for('transfer'))
        conn = get_db()
        src = conn.execute("SELECT * FROM accounts WHERE account_number=?",
                           (from_acc_no,)).fetchone()
        dst = conn.execute("SELECT * FROM accounts WHERE account_number=?",
                           (to_acc_no,)).fetchone()
        if not src or not dst:
            conn.close()
            flash('One or both accounts not found.', 'danger')
            return redirect(url_for('transfer'))
        if src['status'] != 'active' or dst['status'] != 'active':
            conn.close()
            flash('Both accounts must be active.', 'danger')
            return redirect(url_for('transfer'))
        if src['balance'] < amount:
            conn.close()
            flash('Insufficient balance.', 'danger')
            return redirect(url_for('transfer'))
        new_src = src['balance'] - amount
        new_dst = dst['balance'] + amount
        conn.execute("UPDATE accounts SET balance=? WHERE id=?", (new_src, src['id']))
        conn.execute("UPDATE accounts SET balance=? WHERE id=?", (new_dst, dst['id']))
        conn.execute('''INSERT INTO transactions (account_id,type,amount,balance_after,description,related_account)
                        VALUES (?,?,?,?,?,?)''',
                     (src['id'], 'transfer_out', amount, new_src,
                      f'Transfer to {to_acc_no}', to_acc_no))
        conn.execute('''INSERT INTO transactions (account_id,type,amount,balance_after,description,related_account)
                        VALUES (?,?,?,?,?,?)''',
                     (dst['id'], 'transfer_in', amount, new_dst,
                      f'Transfer from {from_acc_no}', from_acc_no))
        conn.commit()
        conn.close()
        log_action(session['admin'], 'TRANSFER',
                   f"{amount} from {from_acc_no} to {to_acc_no}")
        flash(f'Transferred ₹{amount:.2f} from {from_acc_no} to {to_acc_no}.', 'success')
        return redirect(url_for('transfer'))
    return render_template('transfer.html')


# ---------- Balance Enquiry ----------
@app.route('/balance', methods=['GET', 'POST'])
@login_required
def balance():
    acc = None
    if request.method == 'POST':
        acc_no = request.form['account_number'].strip()
        acc = get_account(acc_no)
        if not acc:
            flash('Account not found.', 'danger')
    return render_template('balance.html', acc=acc)


# ---------- Transactions ----------
@app.route('/transactions')
@login_required
def transactions():
    q = request.args.get('q', '').strip()
    conn = get_db()
    if q:
        rows = conn.execute('''SELECT t.*, a.account_number, c.name FROM transactions t
                               JOIN accounts a ON a.id=t.account_id
                               JOIN customers c ON c.id=a.customer_id
                               WHERE a.account_number LIKE ?
                               ORDER BY t.id DESC LIMIT 200''',
                            (f'%{q}%',)).fetchall()
    else:
        rows = conn.execute('''SELECT t.*, a.account_number, c.name FROM transactions t
                               JOIN accounts a ON a.id=t.account_id
                               JOIN customers c ON c.id=a.customer_id
                               ORDER BY t.id DESC LIMIT 200''').fetchall()
    conn.close()
    return render_template('transactions.html', rows=rows, q=q)


# ---------- Account Management ----------
@app.route('/manage_accounts')
@login_required
def manage_accounts():
    conn = get_db()
    accounts = conn.execute('''SELECT a.*, c.name, c.email FROM accounts a
                               JOIN customers c ON c.id=a.customer_id
                               ORDER BY a.id DESC''').fetchall()
    conn.close()
    return render_template('manage_accounts.html', accounts=accounts)


@app.route('/toggle_account/<int:acc_id>')
@login_required
def toggle_account(acc_id):
    conn = get_db()
    acc = conn.execute("SELECT * FROM accounts WHERE id=?", (acc_id,)).fetchone()
    if acc:
        new_status = 'inactive' if acc['status'] == 'active' else 'active'
        conn.execute("UPDATE accounts SET status=? WHERE id=?", (new_status, acc_id))
        conn.commit()
        log_action(session['admin'], 'ACCOUNT_STATUS',
                   f"{acc['account_number']} -> {new_status}")
        flash(f'Account {acc["account_number"]} is now {new_status}.', 'success')
    conn.close()
    sync_triggers_to_audit_db()
    return redirect(url_for('manage_accounts'))


# ---------- Statement ----------
@app.route('/statement', methods=['GET', 'POST'])
@login_required
def statement():
    acc = None
    rows = []
    if request.method == 'POST':
        acc_no = request.form['account_number'].strip()
        acc = get_account(acc_no)
        if acc:
            conn = get_db()
            rows = conn.execute('''SELECT * FROM transactions WHERE account_id=?
                                   ORDER BY id DESC''', (acc['id'],)).fetchall()
            conn.close()
        else:
            flash('Account not found.', 'danger')
    return render_template('statement.html', acc=acc, rows=rows)


# ---------- System Info (PRAGMA) ----------
@app.route('/system_info')
@login_required
def system_info():
    conn = get_db()
    pragmas = {}
    pragma_list = [
        'database_list',
        'table_info(accounts)',
        'table_info(transactions)',
        'foreign_key_list(accounts)',
        'foreign_key_list(transactions)',
        'index_list(customers)',
        'integrity_check',
        'journal_mode',
        'page_size',
        'user_version',
    ]
    for p in pragma_list:
        try:
            rows = conn.execute(f"PRAGMA {p}").fetchall()
            pragmas[p] = [dict(r) for r in rows]
        except Exception as e:
            pragmas[p] = [{'error': str(e)}]

    objects = conn.execute("""SELECT name, type, tbl_name FROM sqlite_master
                              WHERE type IN ('table','trigger','index')
                              ORDER BY type, name""").fetchall()
    audit_objects = conn.execute("""SELECT name, type, tbl_name FROM audit.sqlite_master
                                    WHERE type IN ('table','trigger','index')
                                    ORDER BY type, name""").fetchall()
    conn.close()
    return render_template('system_info.html',
                           pragmas=pragmas,
                           objects=objects,
                           audit_objects=audit_objects)


# ---------- Reports ----------
@app.route('/reports')
@login_required
def reports():
    conn = get_db()
    data = {}

    data['by_type'] = conn.execute('''
        SELECT type, COUNT(*) AS count, SUM(amount) AS total
        FROM transactions GROUP BY type ORDER BY total DESC''').fetchall()

    data['multi_accounts'] = conn.execute('''
        SELECT c.name, COUNT(a.id) AS num_accounts, SUM(a.balance) AS total_balance
        FROM customers c JOIN accounts a ON a.customer_id = c.id
        GROUP BY c.id HAVING COUNT(a.id) >= 1
        ORDER BY total_balance DESC''').fetchall()

    data['monthly'] = conn.execute('''
        SELECT strftime('%Y-%m', created_at) AS month,
               COUNT(*) AS tx_count, SUM(amount) AS volume
        FROM transactions GROUP BY month ORDER BY month DESC''').fetchall()

    data['top5'] = conn.execute('''
        SELECT t.id, a.account_number, t.type, t.amount, t.created_at
        FROM transactions t JOIN accounts a ON a.id = t.account_id
        ORDER BY t.amount DESC LIMIT 5''').fetchall()

    data['above_avg'] = conn.execute('''
        SELECT account_number, balance FROM accounts
        WHERE balance > (SELECT AVG(balance) FROM accounts)
        ORDER BY balance DESC''').fetchall()

    data['no_accounts'] = conn.execute('''
        SELECT c.name, c.email FROM customers c
        LEFT JOIN accounts a ON a.customer_id = c.id
        WHERE a.id IS NULL''').fetchall()

    data['today_tx'] = conn.execute('''
        SELECT * FROM transactions
        WHERE DATE(created_at) = DATE('now')
        ORDER BY id DESC''').fetchall()

    data['last7'] = conn.execute('''
        SELECT * FROM transactions
        WHERE created_at >= DATE('now', '-7 days')
        ORDER BY id DESC''').fetchall()

    data['accounts_age'] = conn.execute('''
        SELECT account_number,
               CAST(julianday('now') - julianday(created_at) AS INTEGER) AS days_old
        FROM accounts ORDER BY days_old DESC''').fetchall()

    conn.close()
    return render_template('reports.html', data=data)


# ---------- Audit Log ----------
@app.route('/audit_log')
@login_required
def audit_log():
    conn = get_db()
    local_logs = conn.execute('''SELECT * FROM audit_log
                                 ORDER BY id DESC LIMIT 100''').fetchall()
    local_del_c = conn.execute('''SELECT * FROM deleted_customers
                                  ORDER BY deleted_at DESC''').fetchall()
    local_del_a = conn.execute('''SELECT * FROM deleted_accounts
                                  ORDER BY deleted_at DESC''').fetchall()
    mirror_logs = conn.execute('''SELECT * FROM audit.audit_log
                                  ORDER BY id DESC LIMIT 100''').fetchall()

    cross_join = conn.execute('''
        SELECT a.username, l.action, l.details, l.logged_at
        FROM admin a
        JOIN audit.audit_log l ON l.admin_user = a.username
        ORDER BY l.id DESC LIMIT 20''').fetchall()

    conn.close()
    return render_template('audit_log.html',
                           logs=local_logs,
                           mirror_logs=mirror_logs,
                           deleted_c=local_del_c,
                           deleted_a=local_del_a,
                           cross_join=cross_join)


if __name__ == '__main__':
    init_db()
    app.run(debug=True)