"""
╔══════════════════════════════════════════════════════════╗
║             قاعدة البيانات - Production Level           ║
╚══════════════════════════════════════════════════════════╝
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from config import DB_PATH

logger = logging.getLogger(__name__)


class Database:
    def __init__(self):
        self.db_path = DB_PATH

    def get_conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ══════════════════════════════════════════════════════
    def init_db(self):
        with self.get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY,
                    username      TEXT    DEFAULT '',
                    first_name    TEXT    DEFAULT '',
                    balance       REAL    DEFAULT 0.0,
                    is_banned     INTEGER DEFAULT 0,
                    ref_by        INTEGER DEFAULT NULL,
                    total_charged REAL    DEFAULT 0.0,
                    join_date     TEXT    DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_string TEXT    NOT NULL UNIQUE,
                    phone          TEXT    NOT NULL,
                    session_type   TEXT    DEFAULT 'pyrogram',
                    status         TEXT    DEFAULT 'available',
                    reserved_by    INTEGER DEFAULT NULL,
                    reserved_at    TEXT    DEFAULT NULL,
                    added_at       TEXT    DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sales (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    session_id INTEGER,
                    phone      TEXT    NOT NULL,
                    price      REAL    NOT NULL,
                    otp_code   TEXT    DEFAULT NULL,
                    type       TEXT    DEFAULT 'number',
                    sale_date  TEXT    DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    session_id INTEGER NOT NULL,
                    phone      TEXT    NOT NULL,
                    created_at TEXT    DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(session_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS promo_codes (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    code       TEXT    NOT NULL UNIQUE,
                    amount     REAL    NOT NULL,
                    max_uses   INTEGER DEFAULT 1,
                    used_count INTEGER DEFAULT 0,
                    created_at TEXT    DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT    DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS promo_uses (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    code_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    used_at TEXT    DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(code_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS payment_requests (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    method     TEXT    NOT NULL,
                    amount     REAL    DEFAULT 0,
                    status     TEXT    DEFAULT 'pending',
                    created_at TEXT    DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS force_channels (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id   TEXT NOT NULL UNIQUE,
                    channel_name TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS crypto_payments (
                    txid      TEXT PRIMARY KEY,
                    user_id   INTEGER NOT NULL,
                    network   TEXT    NOT NULL,
                    amount    REAL    NOT NULL,
                    credit    REAL    NOT NULL,
                    timestamp TEXT    DEFAULT CURRENT_TIMESTAMP
                );

                INSERT OR IGNORE INTO settings VALUES ('number_price',       '1.00');
                INSERT OR IGNORE INTO settings VALUES ('session_price',      '1.50');
                INSERT OR IGNORE INTO settings VALUES ('ref_bonus',          '0.50');
                INSERT OR IGNORE INTO settings VALUES ('pay_vodafone',       '1');
                INSERT OR IGNORE INTO settings VALUES ('pay_crypto',         '1');
                INSERT OR IGNORE INTO settings VALUES ('pay_usdt',           '1');
                INSERT OR IGNORE INTO settings VALUES ('vodafone_number',    '01000000000');
                INSERT OR IGNORE INTO settings VALUES ('crypto_address',     'YOUR_CRYPTO_ADDRESS');
                INSERT OR IGNORE INTO settings VALUES ('usdt_address',       'YOUR_USDT_ADDRESS');
                INSERT OR IGNORE INTO settings VALUES ('force_channel',      '');
                INSERT OR IGNORE INTO settings VALUES ('force_channel_name', '');
                INSERT OR IGNORE INTO settings VALUES ('notify_channel',     '');
                INSERT OR IGNORE INTO settings VALUES ('reserve_timeout',    '300');
            """)

    # ══════════════════════════════════════════════════════
    # المستخدمون
    # ══════════════════════════════════════════════════════
    def register_user(self, uid, username, first_name, ref_by=None):
        with self.get_conn() as conn:
            existing = conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE users SET username=?, first_name=? WHERE id=?",
                    (username, first_name, uid)
                )
                return False
            conn.execute(
                "INSERT INTO users (id, username, first_name, ref_by) VALUES (?,?,?,?)",
                (uid, username, first_name, ref_by)
            )
            return True

    def get_user(self, uid):
        with self.get_conn() as conn:
            r = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            return dict(r) if r else None

    def get_all_users(self):
        with self.get_conn() as conn:
            rows = conn.execute("SELECT id FROM users WHERE is_banned=0").fetchall()
            return [r['id'] for r in rows]

    def get_users_count(self):
        with self.get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def get_balance(self, uid):
        with self.get_conn() as conn:
            r = conn.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()
            return r['balance'] if r else 0.0

    def add_balance(self, uid, amount):
        with self.get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (uid,))
            conn.execute(
                "UPDATE users SET balance=balance+?, total_charged=total_charged+? WHERE id=?",
                (amount, amount, uid)
            )

    def deduct_balance(self, uid, amount):
        with self.get_conn() as conn:
            conn.execute("UPDATE users SET balance=balance-? WHERE id=?", (amount, uid))

    def refund_balance(self, uid, amount):
        with self.get_conn() as conn:
            conn.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, uid))

    def is_banned(self, uid):
        with self.get_conn() as conn:
            r = conn.execute("SELECT is_banned FROM users WHERE id=?", (uid,)).fetchone()
            return bool(r['is_banned']) if r else False

    def ban_user(self, uid):
        with self.get_conn() as conn:
            conn.execute("UPDATE users SET is_banned=1 WHERE id=?", (uid,))

    def unban_user(self, uid):
        with self.get_conn() as conn:
            conn.execute("UPDATE users SET is_banned=0 WHERE id=?", (uid,))

    def get_referrals_count(self, uid):
        with self.get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM users WHERE ref_by=?", (uid,)
            ).fetchone()[0]

    def get_user_info_full(self, uid):
        with self.get_conn() as conn:
            user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not user:
                return None
            u = dict(user)
            u['purchases_count'] = conn.execute(
                "SELECT COUNT(*) FROM sales WHERE user_id=?", (uid,)
            ).fetchone()[0]
            u['total_spent'] = conn.execute(
                "SELECT COALESCE(SUM(price),0) FROM sales WHERE user_id=?", (uid,)
            ).fetchone()[0]
            return u

    def get_total_balances(self):
        with self.get_conn() as conn:
            return conn.execute(
                "SELECT COALESCE(SUM(balance),0) FROM users"
            ).fetchone()[0]

    def get_all_users_with_balance(self, limit=30):
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT id, username, first_name, balance
                   FROM users
                   WHERE is_banned=0 AND balance > 0
                   ORDER BY balance DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════════
    # الجلسات
    # ══════════════════════════════════════════════════════
    def add_session(self, session_string, phone, session_type='pyrogram'):
        with self.get_conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO sessions (session_string,phone,session_type,status) VALUES (?,?,?,'available')",
                    (session_string, phone, session_type)
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def get_available_count(self):
        with self.get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE status='available'"
            ).fetchone()[0]

    def get_reserved_count(self):
        with self.get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE status='reserved'"
            ).fetchone()[0]

    def reserve_session(self, uid: int) -> dict | None:
        with self.get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM sessions WHERE status='reserved' AND reserved_by=?", (uid,)
            ).fetchone()
            if existing:
                return None

            row = conn.execute(
                "SELECT id FROM sessions WHERE status='available' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if not row:
                return None

            now = datetime.now().isoformat()
            updated = conn.execute(
                "UPDATE sessions SET status='reserved', reserved_by=?, reserved_at=? "
                "WHERE id=? AND status='available'",
                (uid, now, row['id'])
            ).rowcount
            if updated == 0:
                return None

            r = conn.execute("SELECT * FROM sessions WHERE id=?", (row['id'],)).fetchone()
            return dict(r) if r else None

    def release_session(self, session_id: int):
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE sessions SET status='available', reserved_by=NULL, reserved_at=NULL WHERE id=?",
                (session_id,)
            )

    def mark_session_sold(self, session_id: int):
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE sessions SET status='sold', reserved_by=NULL, reserved_at=NULL WHERE id=?",
                (session_id,)
            )

    def delete_session(self, sid):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM sessions WHERE id=?", (sid,))

    def get_session_by_id(self, sid):
        with self.get_conn() as conn:
            r = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
            return dict(r) if r else None

    def get_user_reserved_session(self, uid: int) -> dict | None:
        with self.get_conn() as conn:
            r = conn.execute(
                "SELECT * FROM sessions WHERE status='reserved' AND reserved_by=?", (uid,)
            ).fetchone()
            return dict(r) if r else None

    def get_next_session(self) -> dict | None:
        with self.get_conn() as conn:
            r = conn.execute(
                "SELECT * FROM sessions WHERE status='available' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            return dict(r) if r else None

    def get_all_sessions_list(self, limit=500, status='available'):
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE status=? ORDER BY id ASC LIMIT ?",
                (status, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_available_sessions_list(self, limit=30):
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE status='available' ORDER BY RANDOM() LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def release_expired_reservations(self, timeout_seconds: int = 300) -> list:
        cutoff = (datetime.now() - timedelta(seconds=timeout_seconds)).isoformat()
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT id, reserved_by FROM sessions WHERE status='reserved' AND reserved_at < ?",
                (cutoff,)
            ).fetchall()
            if rows:
                conn.execute(
                    "UPDATE sessions SET status='available', reserved_by=NULL, reserved_at=NULL "
                    "WHERE status='reserved' AND reserved_at < ?",
                    (cutoff,)
                )
            return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════════
    # المبيعات
    # ══════════════════════════════════════════════════════
    def record_sale(self, uid, phone, price, sale_type='number', session_id=None, otp_code=None):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT INTO sales (user_id,session_id,phone,price,type,otp_code) VALUES (?,?,?,?,?,?)",
                (uid, session_id, phone, price, sale_type, otp_code)
            )

    def get_total_sales_amount(self):
        with self.get_conn() as conn:
            return conn.execute("SELECT COALESCE(SUM(price),0) FROM sales").fetchone()[0]

    def get_sales_count(self):
        with self.get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]

    def get_user_purchases_count(self, uid):
        with self.get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM sales WHERE user_id=?", (uid,)
            ).fetchone()[0]

    def get_user_purchases(self, uid, limit=10):
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sales WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit)
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d['date'] = d['sale_date'][:10] if d.get('sale_date') else '---'
                result.append(d)
            return result

    def get_today_sales_count(self):
        with self.get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM sales WHERE sale_date >= date('now')"
            ).fetchone()[0]

    def get_today_sales_details(self, limit=10):
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT phone, price, type, sale_date
                   FROM sales
                   WHERE sale_date >= date('now')
                   ORDER BY id DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_user_purchases_today(self, uid, limit=10):
        """جلب مشتريات المستخدم لليوم الحالي فقط"""
        today = datetime.now().strftime('%Y-%m-%d')
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sales WHERE user_id=? AND sale_date LIKE ? ORDER BY id DESC LIMIT ?",
                (uid, f"{today}%", limit)
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d['date'] = d['sale_date'][:10] if d.get('sale_date') else '---'
                result.append(d)
            return result

    # ══════════════════════════════════════════════════════
    # البلاغات
    # ══════════════════════════════════════════════════════
    def add_report(self, user_id: int, session_id: int, phone: str) -> bool:
        with self.get_conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO reports (user_id,session_id,phone) VALUES (?,?,?)",
                    (user_id, session_id, phone)
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def get_reports(self, limit=50):
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT phone, session_id, COUNT(*) as report_count, MAX(created_at) as last_report
                   FROM reports GROUP BY session_id ORDER BY report_count DESC LIMIT ?""",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_reports_export(self) -> str:
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT r.phone, s.session_string
                   FROM reports r
                   LEFT JOIN sessions s ON r.session_id=s.id
                   GROUP BY r.session_id"""
            ).fetchall()
            lines = [f"{r['phone']}|{r['session_string'] or 'N/A'}" for r in rows]
            return "\n".join(lines)

    # ══════════════════════════════════════════════════════
    # أكواد الخصم
    # ══════════════════════════════════════════════════════
    def create_promo_code(self, code, amount, max_uses=1, expires_at=None):
        with self.get_conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO promo_codes (code,amount,max_uses,expires_at) VALUES (?,?,?,?)",
                    (code.upper(), amount, max_uses, expires_at)
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def use_promo_code(self, code, uid):
        with self.get_conn() as conn:
            promo = conn.execute(
                "SELECT * FROM promo_codes WHERE code=?", (code.upper().strip(),)
            ).fetchone()
            if not promo:
                return {'success': False, 'reason': 'الكود غير موجود.'}
            promo = dict(promo)
            if promo['used_count'] >= promo['max_uses']:
                return {'success': False, 'reason': 'تم استنفاد هذا الكود.'}
            if promo['expires_at'] and datetime.now().isoformat() > promo['expires_at']:
                return {'success': False, 'reason': 'انتهت صلاحية الكود.'}
            used = conn.execute(
                "SELECT id FROM promo_uses WHERE code_id=? AND user_id=?",
                (promo['id'], uid)
            ).fetchone()
            if used:
                return {'success': False, 'reason': 'لقد استخدمت هذا الكود من قبل.'}
            conn.execute(
                "UPDATE promo_codes SET used_count=used_count+1 WHERE id=?", (promo['id'],)
            )
            conn.execute(
                "INSERT INTO promo_uses (code_id,user_id) VALUES (?,?)", (promo['id'], uid)
            )
            conn.execute(
                "UPDATE users SET balance=balance+? WHERE id=?", (promo['amount'], uid)
            )
            return {'success': True, 'amount': promo['amount']}

    def get_all_promo_codes(self):
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM promo_codes ORDER BY id DESC LIMIT 30"
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_promo_code(self, code: str) -> bool:
        with self.get_conn() as conn:
            r = conn.execute("DELETE FROM promo_codes WHERE code=?", (code.upper(),))
            return r.rowcount > 0

    def delete_expired_promo_codes(self) -> int:
        now = datetime.now().isoformat()
        with self.get_conn() as conn:
            r = conn.execute(
                "DELETE FROM promo_codes WHERE expires_at IS NOT NULL AND expires_at < ?", (now,)
            )
            return r.rowcount

    def get_promo_used_history(self, code: str):
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT pu.user_id, pu.used_at, u.username, u.first_name
                   FROM promo_uses pu
                   LEFT JOIN users u ON pu.user_id=u.id
                   JOIN promo_codes pc ON pu.code_id=pc.id
                   WHERE pc.code=?
                   ORDER BY pu.used_at DESC""",
                (code.upper(),)
            ).fetchall()
            return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════════
    # طلبات الدفع
    # ══════════════════════════════════════════════════════
    def create_payment_request(self, uid, method, amount=0):
        with self.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO payment_requests (user_id,method,amount) VALUES (?,?,?)",
                (uid, method, amount)
            )
            return cur.lastrowid

    def approve_payment(self, req_id, amount):
        with self.get_conn() as conn:
            req = conn.execute(
                "SELECT * FROM payment_requests WHERE id=?", (req_id,)
            ).fetchone()
            if not req:
                return None
            req = dict(req)
            conn.execute(
                "UPDATE payment_requests SET status='approved', amount=? WHERE id=?",
                (amount, req_id)
            )
            conn.execute(
                "UPDATE users SET balance=balance+?, total_charged=total_charged+? WHERE id=?",
                (amount, amount, req['user_id'])
            )
            return req['user_id']

    def reject_payment(self, req_id):
        with self.get_conn() as conn:
            req = conn.execute(
                "SELECT user_id FROM payment_requests WHERE id=?", (req_id,)
            ).fetchone()
            conn.execute(
                "UPDATE payment_requests SET status='rejected' WHERE id=?", (req_id,)
            )
            return req['user_id'] if req else None

    def get_pending_payments_count(self):
        with self.get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM payment_requests WHERE status='pending'"
            ).fetchone()[0]

    # ══════════════════════════════════════════════════════
    # الإعدادات
    # ══════════════════════════════════════════════════════
    def get_setting(self, key, default=None):
        with self.get_conn() as conn:
            r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return r['value'] if r else default

    def set_setting(self, key, value):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                (key, str(value))
            )

    def get_payment_settings(self):
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM settings WHERE key LIKE 'pay_%'"
            ).fetchall()
            return {r['key'].replace('pay_', ''): (r['value'] == '1') for r in rows}

    def toggle_payment(self, method):
        key = f"pay_{method}"
        cur = self.get_setting(key, '1')
        new = '0' if cur == '1' else '1'
        self.set_setting(key, new)
        return new == '1'

    # ══════════════════════════════════════════════════════
    # قنوات الاشتراك الإجباري (متعدد)
    # ══════════════════════════════════════════════════════
    def get_force_channels(self) -> list:
        with self.get_conn() as conn:
            rows = conn.execute("SELECT channel_id FROM force_channels ORDER BY id").fetchall()
            return [r['channel_id'] for r in rows]

    def get_force_channel_names(self) -> list:
        with self.get_conn() as conn:
            rows = conn.execute("SELECT channel_name FROM force_channels ORDER BY id").fetchall()
            return [r['channel_name'] for r in rows]

    def set_force_channels(self, channels: list):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM force_channels")
            for ch in channels:
                conn.execute(
                    "INSERT INTO force_channels (channel_id, channel_name) VALUES (?, ?)",
                    (ch, ch)
                )

    def set_force_channel_names(self, names: list):
        with self.get_conn() as conn:
            channels = self.get_force_channels()
            for i, name in enumerate(names):
                if i < len(channels):
                    conn.execute(
                        "UPDATE force_channels SET channel_name=? WHERE channel_id=?",
                        (name, channels[i])
                    )

    def add_force_channel(self, channel_id: str, channel_name: str) -> bool:
        with self.get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM force_channels WHERE channel_id=?", (channel_id,)
            ).fetchone()
            if existing:
                return False
            conn.execute(
                "INSERT INTO force_channels (channel_id, channel_name) VALUES (?, ?)",
                (channel_id, channel_name)
            )
            return True

    def remove_force_channel(self, channel_id: str) -> bool:
        with self.get_conn() as conn:
            cur = conn.execute("DELETE FROM force_channels WHERE channel_id=?", (channel_id,))
            return cur.rowcount > 0

    # ══════════════════════════════════════════════════════
    # مدفوعات الكريبتو
    # ══════════════════════════════════════════════════════
    def is_txid_used(self, txid: str) -> bool:
        with self.get_conn() as conn:
            r = conn.execute("SELECT txid FROM crypto_payments WHERE txid=?", (txid.lower(),))
            return r.fetchone() is not None

    def save_crypto_payment(self, user_id: int, txid: str, network: str, amount: float, credit: float):
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO crypto_payments (txid, user_id, network, amount, credit)
                   VALUES (?, ?, ?, ?, ?)""",
                (txid.lower(), user_id, network, amount, credit)
            )

    def get_bep20_payment(self, txid: str):
        return self.is_txid_used(txid)

    def save_bep20_payment(self, user_id: int, txid: str, amount: float, credit: float):
        self.save_crypto_payment(user_id, txid, 'bep20', amount, credit)

    # 🆕🆕🆕 دوال Binance Pay (تستخدم جدول crypto_payments مع network='binance')
    def save_binance_payment(self, user_id: int, order_id: str, amount: float, credit: float):
        """تسجيل عملية دفع Binance Pay لمنع تكرارها"""
        self.save_crypto_payment(user_id, order_id, 'binance', amount, credit)

    def get_binance_payment(self, order_id: str):
        """التحقق مما إذا كان Order ID قد استخدم سابقاً"""
        with self.get_conn() as conn:
            r = conn.execute(
                "SELECT * FROM crypto_payments WHERE txid=? AND network='binance'",
                (order_id,)
            ).fetchone()
            return dict(r) if r else None

    # ══════════════════════════════════════════════════════
    # الإحصائيات
    # ══════════════════════════════════════════════════════
    def get_stats(self):
        with self.get_conn() as conn:
            users     = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            available = conn.execute("SELECT COUNT(*) FROM sessions WHERE status='available'").fetchone()[0]
            reserved  = conn.execute("SELECT COUNT(*) FROM sessions WHERE status='reserved'").fetchone()[0]
            sales_c   = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            revenue   = conn.execute("SELECT COALESCE(SUM(price),0) FROM sales").fetchone()[0]
            today     = conn.execute(
                "SELECT COUNT(*) FROM sales WHERE sale_date >= date('now')"
            ).fetchone()[0]
            pending   = conn.execute(
                "SELECT COUNT(*) FROM payment_requests WHERE status='pending'"
            ).fetchone()[0]
            total_bal = conn.execute(
                "SELECT COALESCE(SUM(balance),0) FROM users"
            ).fetchone()[0]
            return {
                'users':          users,
                'sessions':       available,
                'reserved':       reserved,
                'sales_count':    sales_c,
                'total_revenue':  revenue,
                'today_sales':    today,
                'pending_payments': pending,
                'total_balances': total_bal,
            }
