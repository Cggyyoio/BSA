"""
╔══════════════════════════════════════════════════════════════╗
║        نظام الدفع بينانس - binance_pay.py  v3.1             ║
║  متوافق بالكامل مع البوت الحالي - بدون تعديلات خارجية       ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid

import aiohttp

logger = logging.getLogger(__name__)

SESSION_TIMEOUT_SECONDS = 300
API_RETRY_COUNT         = 2
API_RETRY_DELAY         = 2
API_TIMEOUT_SECONDS     = 15

_BINANCE_SESSIONS: dict[int, dict] = {}
_USED_ORDER_IDS: set[str] = set()


def _session_start(uid: int, step: str, amount: float = 0.0):
    _BINANCE_SESSIONS[uid] = {
        "step":    step,
        "amount":  amount,
        "started": time.time(),
    }


def _session_get(uid: int):
    s = _BINANCE_SESSIONS.get(uid)
    if not s:
        return None
    if time.time() - s["started"] > SESSION_TIMEOUT_SECONDS:
        del _BINANCE_SESSIONS[uid]
        return None
    return s


def _session_clear(uid: int):
    _BINANCE_SESSIONS.pop(uid, None)


# ══════════════════════════════════════════════════════════════
#  عميل Binance API
# ══════════════════════════════════════════════════════════════
class BinancePay:
    BASE_URL = "https://bpay.binanceapi.com"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key    = api_key.strip()
        self.api_secret = api_secret.strip()

    def _sign(self, payload: str, timestamp: str, nonce: str) -> str:
        message = f"{timestamp}\n{nonce}\n{payload}\n"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest().upper()

    def _headers(self, payload: str) -> dict:
        timestamp = str(int(time.time() * 1000))
        nonce     = uuid.uuid4().hex
        return {
            "Content-Type":              "application/json",
            "BinancePay-Timestamp":      timestamp,
            "BinancePay-Nonce":          nonce,
            "BinancePay-Certificate-SN": self.api_key,
            "BinancePay-Signature":      self._sign(payload, timestamp, nonce),
        }

    async def _query_raw(self, body_dict: dict) -> dict:
        body    = json.dumps(body_dict, separators=(",", ":"))
        headers = self._headers(body)
        url     = f"{self.BASE_URL}/binancepay/openapi/v2/order/query"
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    url, headers=headers, data=body,
                    timeout=aiohttp.ClientTimeout(total=API_TIMEOUT_SECONDS),
                ) as resp:
                    raw = await resp.json(content_type=None)

            if raw.get("status") != "SUCCESS":
                err_msg = raw.get("errorMessage", raw.get("message", "استجابة غير متوقعة"))
                return {"success": False, "error": err_msg,
                        "error_code": raw.get("code", "")}

            order  = raw.get("data") or {}
            amount = (
                float(order.get("orderAmount") or 0)
                or float(order.get("transactionAmount") or 0)
                or float(order.get("totalFee") or 0)
            )
            return {
                "success":  True,
                "status":   order.get("status", "UNKNOWN"),
                "amount":   amount,
                "currency": order.get("currency") or order.get("fiatCurrency") or "USDT",
                "trade_no": order.get("transactionId", ""),
                "raw":      order,
            }
        except aiohttp.ClientError as e:
            return {"success": False, "error": f"خطأ شبكة: {e}"}
        except Exception as e:
            logger.error(f"[Binance API] خطأ: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def query_with_retry(self, order_id: str) -> dict:
        methods = [
            ("prepayId",        {"prepayId":        order_id}),
            ("merchantTradeNo", {"merchantTradeNo": order_id}),
            ("transactionId",   {"transactionId":   order_id}),
        ]
        last = {"success": False, "error": "لم يتم الاستعلام"}
        for attempt in range(API_RETRY_COUNT):
            for name, body in methods:
                result = await self._query_raw(body)
                if result.get("success"):
                    return result
                last = result
            if attempt < API_RETRY_COUNT - 1:
                await asyncio.sleep(API_RETRY_DELAY)
        return last


# ══════════════════════════════════════════════════════════════
#  معالج Binance Pay
# ══════════════════════════════════════════════════════════════
class BinancePayHandler:
    def __init__(self, db, bot):
        self.db  = db
        self.bot = bot

    def _get_client(self):
        key    = self.db.get_setting("binance_api_key",    "").strip()
        secret = self.db.get_setting("binance_api_secret", "").strip()
        if not key or not secret:
            return None
        return BinancePay(key, secret)

    def is_enabled(self) -> bool:
        return (
            self.db.get_setting("pay_binance",     "0") == "1"
            and bool(self.db.get_setting("binance_api_key",    "").strip())
            and bool(self.db.get_setting("binance_api_secret", "").strip())
        )

    def in_session(self, uid: int) -> bool:
        return _session_get(uid) is not None

    def _is_order_used(self, order_id: str) -> bool:
        """فحص مزدوج: ذاكرة + قاعدة بيانات"""
        if order_id in _USED_ORDER_IDS:
            return True
        # استخدام دالة get_binance_payment من database.py
        if hasattr(self.db, 'get_binance_payment') and self.db.get_binance_payment(order_id):
            _USED_ORDER_IDS.add(order_id)
            return True
        return False

    def _mark_order_used(self, uid: int, order_id: str, paid: float, credit: float):
        """تسجيل Order ID فقط — بدون إضافة رصيد"""
        _USED_ORDER_IDS.add(order_id)
        if hasattr(self.db, 'save_binance_payment'):
            self.db.save_binance_payment(uid, order_id, paid, credit)

    # ══════════════════════════════════════════════════════════
    #  واجهة المستخدم
    # ══════════════════════════════════════════════════════════
    async def show_binance_pay(self, cid: int, uid: int):
        pay_id   = self.db.get_setting("binance_pay_id", "").strip()
        min_usdt = self.db.get_setting("binance_min_usdt", "1.00")
        rate     = self.db.get_setting("binance_usdt_rate", "1.00")
        _session_start(uid, step="amount")
        await self.bot.send_message(
            cid,
            f"💛 <b>Binance Pay — تلقائي ⚡</b>\n\n"
            f"🆔 Binance Pay ID: <code>{pay_id}</code>\n\n"
            f"💵 الحد الأدنى: <b>{min_usdt} USDT</b>\n"
            f"💱 السعر: <b>1 USDT = ${rate}</b>\n\n"
            f"1️⃣ افتح تطبيق Binance → Pay\n"
            f"2️⃣ اضغط Send وأدخل Pay ID أعلاه\n"
            f"3️⃣ أرسل المبلغ\n"
            f"4️⃣ أرسل هنا المبلغ الذي أرسلته:"
        )

    async def prompt_amount(self, call):
        uid = call.from_user.id
        _session_start(uid, step="amount")
        await self.bot.answer_callback_query(call.id)
        await self.bot.send_message(
            call.message.chat.id,
            "💵 <b>أرسل المبلغ بـ USDT الذي أرسلته عبر Binance Pay:</b>"
        )

    async def handle_binance_message(self, message) -> bool:
        uid   = message.from_user.id
        state = _session_get(uid)
        if not state:
            return False
        step = state.get("step", "")
        if step == "amount":
            return await self._handle_amount_input(message, state)
        elif step == "order_id":
            return await self._handle_order_id_input(message, state)
        return False

    async def _handle_amount_input(self, message, state: dict) -> bool:
        uid      = message.from_user.id
        cid      = message.chat.id
        raw_text = (message.text or "").strip().replace(",", ".")
        min_usdt = float(self.db.get_setting("binance_min_usdt", "1.00"))
        try:
            amount = float(raw_text)
            if amount <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            await self.bot.send_message(
                cid, "❌ <b>صيغة خاطئة!</b> أدخل رقماً — مثال: <code>10</code>"
            )
            return True
        if amount < min_usdt:
            await self.bot.send_message(
                cid,
                f"⚠️ <b>المبلغ أقل من الحد الأدنى!</b>\n"
                f"أدخلت: <b>{amount} USDT</b> | الحد الأدنى: <b>{min_usdt} USDT</b>"
            )
            return True
        _session_start(uid, step="order_id", amount=amount)
        await self.bot.send_message(
            cid,
            f"✅ <b>المبلغ: {amount} USDT</b>\n\n"
            "🔢 <b>أرسل الآن رقم العملية (Order ID / Transaction ID):</b>\n"
            "<i>ستجده في: Binance → Pay → History → تفاصيل العملية</i>\n"
            "⚠️ كل رقم عملية يُقبل مرة واحدة فقط"
        )
        return True

    async def _handle_order_id_input(self, message, state: dict) -> bool:
        uid      = message.from_user.id
        cid      = message.chat.id
        order_id = (message.text or "").strip()
        amount   = float(state.get("amount", 0))

        _session_clear(uid)

        if not order_id or len(order_id) < 3:
            await self.bot.send_message(cid, "❌ <b>رقم العملية غير صحيح!</b>")
            return True

        if self._is_order_used(order_id):
            await self.bot.send_message(
                cid,
                "⛔ <b>هذا الـ Order ID مستخدم مسبقاً!</b>\n"
                "كل رقم عملية يُقبل مرة واحدة فقط."
            )
            return True

        check_msg = await self.bot.send_message(
            cid, "⏳ <b>جارٍ التحقق من العملية عبر Binance...</b>"
        )

        client = self._get_client()
        if not client:
            await self.bot.edit_message_text(
                "❌ <b>Binance Pay غير مضبوط!</b> تواصل مع الدعم.",
                cid, check_msg.message_id
            )
            return True

        result = await client.query_with_retry(order_id)

        if not result.get("success"):
            err      = result.get("error", "غير معروف")
            err_code = result.get("error_code", "")
            ip_hint  = ""
            if any(x in str(err) for x in ("Invalid API", "permission", "IP")) \
               or err_code in ("400202", "400500"):
                ip_hint = (
                    "\n\n⚠️ <b>تلميح:</b> IP السيرفر غير مُضاف في Binance API.\n"
                    "<b>Binance → API Management → Edit → Unrestricted</b>"
                )
            await self.bot.edit_message_text(
                f"❌ <b>تعذّر التحقق!</b>\n\n"
                f"• تأكد من نسخ رقم العملية كاملاً\n"
                f"• تأكد أن العملية تمت من Binance\n"
                f"<i>التفاصيل: {err}</i>{ip_hint}",
                cid, check_msg.message_id
            )
            return True

        status      = result.get("status",   "UNKNOWN")
        paid_amount = result.get("amount",   0.0)
        currency    = result.get("currency", "USDT")

        status_ar = {
            "INITIAL": "في الانتظار ⏳", "PENDING":  "قيد المعالجة 🔄",
            "CANCELED": "ملغية ❌",       "ERROR":    "خطأ ⚠️",
            "EXPIRED":  "منتهية ⏰",
        }

        if status != "PAID":
            await self.bot.edit_message_text(
                f"⚠️ <b>الدفع لم يكتمل!</b>\n"
                f"حالة العملية: <b>{status_ar.get(status, status)}</b>",
                cid, check_msg.message_id
            )
            return True

        if currency.upper() not in ("USDT", "USD"):
            await self.bot.edit_message_text(
                f"⚠️ <b>العملة غير مدعومة:</b> <b>{currency}</b>. المقبول: USDT فقط.",
                cid, check_msg.message_id
            )
            return True

        if amount > 0 and abs(paid_amount - amount) > 0.01:
            await self.bot.edit_message_text(
                f"⚠️ <b>المبلغ غير متطابق!</b>\n"
                f"أدخلت: <b>{amount} USDT</b> | المُرسَل: <b>{paid_amount} USDT</b>\n"
                f"أدخل المبلغ الفعلي الذي أرسلته.",
                cid, check_msg.message_id
            )
            return True

        min_usdt = float(self.db.get_setting("binance_min_usdt", "1.00"))
        if paid_amount < min_usdt:
            await self.bot.edit_message_text(
                f"⚠️ المبلغ {paid_amount} USDT أقل من الحد الأدنى {min_usdt} USDT.",
                cid, check_msg.message_id
            )
            return True

        # ✅ إضافة الرصيد مرة واحدة فقط
        rate   = float(self.db.get_setting("binance_usdt_rate", "1.00"))
        credit = round(paid_amount * rate, 4)

        self._mark_order_used(uid, order_id, paid_amount, credit)

        try:
            req_id = self.db.create_payment_request(uid, "binance_auto", paid_amount)
            self.db.approve_payment(req_id, credit)
            new_bal = self.db.get_balance(uid)
        except Exception as e:
            logger.error(f"[Binance] فشل تسجيل الدفع: {e}", exc_info=True)
            await self.bot.edit_message_text(
                "❌ حدث خطأ أثناء تسجيل العملية. تواصل مع الدعم.",
                cid, check_msg.message_id
            )
            return True

        logger.info(f"[Binance] ✅ شحن ناجح | uid={uid} | USDT={paid_amount} | credit=${credit:.4f}")

        await self.bot.edit_message_text(
            f"✅ <b>تم شحن رصيدك بنجاح!</b>\n\n"
            f"💛 <b>Binance Pay</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 المبلغ المُستلَم:  <b>{paid_amount} USDT</b>\n"
            f"💰 الرصيد المضاف:   <code>${credit:.2f}</code>\n"
            f"💳 رصيدك الجديد:    <code>${new_bal:.2f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔢 Order ID: <code>{order_id}</code>",
            cid, check_msg.message_id
        )

        await self._notify_admin(uid, order_id, paid_amount, credit)
        return True

    async def _notify_admin(self, uid: int, order_id: str, usdt: float, credit: float):
        from config import ADMIN_ID
        try:
            await self.bot.send_message(
                ADMIN_ID,
                f"💛 <b>شحن تلقائي — Binance Pay</b>\n\n"
                f"👤 المستخدم: <code>{uid}</code>\n"
                f"💵 USDT: <b>{usdt}</b>\n"
                f"💰 رصيد مضاف: <code>${credit:.2f}</code>\n"
                f"🔢 Order ID: <code>{order_id}</code>"
            )
        except Exception as e:
            logger.warning(f"[Binance] فشل إشعار الأدمن: {e}")

    # دوال للتوافق مع PaymentHandler
    async def handle_order_id(self, message) -> bool:
        return await self.handle_binance_message(message)

    async def prompt_order_id(self, call):
        await self.prompt_amount(call)
