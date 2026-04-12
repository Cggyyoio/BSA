"""
╔══════════════════════════════════════════════════════════════╗
║           نظام الدفع - payment_handler.py  v3.1             ║
║           يدعم: BEP20/TRC20 تلقائي + يدوي + هدايا           ║
╚══════════════════════════════════════════════════════════════╝
"""

import logging
from telebot import types
from config import ADMIN_ID, ADMIN_USERNAME

logger = logging.getLogger(__name__)

_WAITING_PROOF: dict[int, dict] = {}

class PaymentHandler:
    def __init__(self, db, bot):
        self.db       = db
        self.bot      = bot
        self._binance = None
        self._crypto  = None

    def _get_binance(self):
        if self._binance is None:
            try:
                from binance_pay import BinancePayHandler
                self._binance = BinancePayHandler(self.db, self.bot)
            except ImportError:
                self._binance = False
        return self._binance if self._binance is not False else None

    def _get_crypto(self):
        if self._crypto is None:
            from crypto_pay import CryptoPayHandler
            self._crypto = CryptoPayHandler(self.db, self.bot)
        return self._crypto

    async def show_charge_menu(self, chat_id: int):
        settings = self.db.get_payment_settings()
        kb       = types.InlineKeyboardMarkup(row_width=2)

        manual_methods = [
            ("vodafone", "📱 فودافون كاش"),
            ("crypto",   "🔐 طرق دفع اخري"),
            ("usdt",     "💎 USDT (يدوي)"),
        ]
        btns = []
        for key, label in manual_methods:
            enabled = settings.get(key, True)
            suffix  = " ⛔" if not enabled else ""
            btns.append(types.InlineKeyboardButton(
                f"{label}{suffix}", callback_data=f"pay_{key}"
            ))
        kb.add(*btns)

        cr = self._get_crypto()
        if cr.is_bep20_enabled():
            kb.add(types.InlineKeyboardButton("💎 USDT BEP20 — تلقائي ⚡", callback_data="pay_bep20_auto"))
        else:
            kb.add(types.InlineKeyboardButton("💎 USDT BEP20 ⛔", callback_data="pay_bep20_auto"))

        if cr.is_trc20_enabled():
            kb.add(types.InlineKeyboardButton("🟣 USDT TRC20 — تلقائي ⚡", callback_data="pay_trc20_auto"))
        else:
            kb.add(types.InlineKeyboardButton("🟣 USDT TRC20 ⛔", callback_data="pay_trc20_auto"))

        bp = self._get_binance()
        if bp and bp.is_enabled():
            kb.add(types.InlineKeyboardButton("💛 Binance Pay — تلقائي ⚡", callback_data="pay_binance_auto"))
        elif bp is not None:
            kb.add(types.InlineKeyboardButton("💛 Binance Pay ⛔", callback_data="pay_binance_auto"))

        kb.add(types.InlineKeyboardButton("🎁 كود هدية", callback_data="pay_gift"))
        kb.add(types.InlineKeyboardButton("👨‍💼 التواصل مع الأدمن", url=f"https://t.me/{ADMIN_USERNAME}"))

        await self.bot.send_message(
            chat_id,
            "┌─────────────────────────────┐\n"
            "│       💳 شحن الرصيد          │\n"
            "└─────────────────────────────┘\n\n"
            "اختر طريقة الدفع:\n"
            "⚡ = تلقائي فوري | ⛔ = متوقف مؤقتاً",
            reply_markup=kb
        )

    async def handle_pay_callback(self, call):
        method = call.data.replace("pay_", "")
        cid    = call.message.chat.id
        uid    = call.from_user.id

        if method == "binance_auto":
            await self.bot.answer_callback_query(call.id)
            bp = self._get_binance()
            if not bp or not bp.is_enabled():
                await self.bot.answer_callback_query(call.id, "⛔ Binance Pay متوقف حالياً.", show_alert=True)
                return
            await bp.show_binance_pay(cid, uid)
            return

        if method == "bep20_auto":
            await self.bot.answer_callback_query(call.id)
            cr = self._get_crypto()
            if not cr.is_bep20_enabled():
                await self.bot.answer_callback_query(call.id, "⛔ USDT BEP20 غير مفعّل.", show_alert=True)
                return
            await cr.show_pay_page(cid, uid, "bep20")
            return

        if method == "trc20_auto":
            await self.bot.answer_callback_query(call.id)
            cr = self._get_crypto()
            if not cr.is_trc20_enabled():
                await self.bot.answer_callback_query(call.id, "⛔ USDT TRC20 غير مفعّل.", show_alert=True)
                return
            await cr.show_pay_page(cid, uid, "trc20")
            return

        if method == "gift":
            await self.bot.answer_callback_query(call.id)
            await self.bot.send_message(cid, "🎁 <b>أرسل كود الهدية:</b>")
            _WAITING_PROOF[uid] = {"type": "gift"}
            return

        settings = self.db.get_payment_settings()
        enabled  = settings.get(method, True)
        if not enabled:
            await self.bot.answer_callback_query(call.id, "⛔ هذه الطريقة متوقفة حالياً!", show_alert=True)
            return
        await self.bot.answer_callback_query(call.id)
        await self._show_payment_details(cid, call.message.message_id, method)

    async def handle_send_proof_callback(self, call):
        d = call.data
        try:
            await self.bot.answer_callback_query(call.id)
        except Exception:
            pass

        if d.startswith("crypto_sent_"):
            net = "bep20" if d.endswith("bep20") else "trc20"
            await self._get_crypto().prompt_txid(call, net)
        elif d.startswith("crypto_copy_"):
            net = "bep20" if d.endswith("bep20") else "trc20"
            await self._get_crypto().handle_copy_address(call, net)
        elif d in ("binance_enter_amount", "binance_enter_order"):
"""
╔══════════════════════════════════════════════════════════════╗
║           نظام الدفع - payment_handler.py  v3.1             ║
║           يدعم: BEP20/TRC20 تلقائي + يدوي + هدايا           ║
╚══════════════════════════════════════════════════════════════╝
"""

import logging
from telebot import types
from config import ADMIN_ID, ADMIN_USERNAME

logger = logging.getLogger(__name__)

_WAITING_PROOF: dict[int, dict] = {}

class PaymentHandler:
    def __init__(self, db, bot):
        self.db       = db
        self.bot      = bot
        self._binance = None
        self._crypto  = None

    def _get_binance(self):
        if self._binance is None:
            try:
                from binance_pay import BinancePayHandler
                self._binance = BinancePayHandler(self.db, self.bot)
            except ImportError:
                self._binance = False
        return self._binance if self._binance is not False else None

    def _get_crypto(self):
        if self._crypto is None:
            from crypto_pay import CryptoPayHandler
            self._crypto = CryptoPayHandler(self.db, self.bot)
        return self._crypto

    async def show_charge_menu(self, chat_id: int):
        settings = self.db.get_payment_settings()
        kb       = types.InlineKeyboardMarkup(row_width=2)

        manual_methods = [
            ("vodafone", "📱 فودافون كاش"),
            ("crypto",   "🔐 طرق دفع اخري"),
            ("usdt",     "💎 USDT (يدوي)"),
        ]
        btns = []
        for key, label in manual_methods:
            enabled = settings.get(key, True)
            suffix  = " ⛔" if not enabled else ""
            btns.append(types.InlineKeyboardButton(
                f"{label}{suffix}", callback_data=f"pay_{key}"
            ))
        kb.add(*btns)

        cr = self._get_crypto()
        if cr.is_bep20_enabled():
            kb.add(types.InlineKeyboardButton("💎 USDT BEP20 — تلقائي ⚡", callback_data="pay_bep20_auto"))
        else:
            kb.add(types.InlineKeyboardButton("💎 USDT BEP20 ⛔", callback_data="pay_bep20_auto"))

        if cr.is_trc20_enabled():
            kb.add(types.InlineKeyboardButton("🟣 USDT TRC20 — تلقائي ⚡", callback_data="pay_trc20_auto"))
        else:
            kb.add(types.InlineKeyboardButton("🟣 USDT TRC20 ⛔", callback_data="pay_trc20_auto"))

        bp = self._get_binance()
        if bp and bp.is_enabled():
            kb.add(types.InlineKeyboardButton("💛 Binance Pay — تلقائي ⚡", callback_data="pay_binance_auto"))
        elif bp is not None:
            kb.add(types.InlineKeyboardButton("💛 Binance Pay ⛔", callback_data="pay_binance_auto"))

        kb.add(types.InlineKeyboardButton("🎁 كود هدية", callback_data="pay_gift"))
        kb.add(types.InlineKeyboardButton("👨‍💼 التواصل مع الأدمن", url=f"https://t.me/{ADMIN_USERNAME}"))

        await self.bot.send_message(
            chat_id,
            "┌─────────────────────────────┐\n"
            "│       💳 شحن الرصيد          │\n"
            "└─────────────────────────────┘\n\n"
            "اختر طريقة الدفع:\n"
            "⚡ = تلقائي فوري | ⛔ = متوقف مؤقتاً",
            reply_markup=kb
        )

    async def handle_pay_callback(self, call):
        method = call.data.replace("pay_", "")
        cid    = call.message.chat.id
        uid    = call.from_user.id

        if method == "binance_auto":
            await self.bot.answer_callback_query(call.id)
            bp = self._get_binance()
            if not bp or not bp.is_enabled():
                await self.bot.answer_callback_query(call.id, "⛔ Binance Pay متوقف حالياً.", show_alert=True)
                return
            await bp.show_binance_pay(cid, uid)
            return

        if method == "bep20_auto":
            await self.bot.answer_callback_query(call.id)
            cr = self._get_crypto()
            if not cr.is_bep20_enabled():
                await self.bot.answer_callback_query(call.id, "⛔ USDT BEP20 غير مفعّل.", show_alert=True)
                return
            await cr.show_pay_page(cid, uid, "bep20")
            return

        if method == "trc20_auto":
            await self.bot.answer_callback_query(call.id)
            cr = self._get_crypto()
            if not cr.is_trc20_enabled():
                await self.bot.answer_callback_query(call.id, "⛔ USDT TRC20 غير مفعّل.", show_alert=True)
                return
            await cr.show_pay_page(cid, uid, "trc20")
            return

        if method == "gift":
            await self.bot.answer_callback_query(call.id)
            await self.bot.send_message(cid, "🎁 <b>أرسل كود الهدية:</b>")
            _WAITING_PROOF[uid] = {"type": "gift"}
            return

        settings = self.db.get_payment_settings()
        enabled  = settings.get(method, True)
        if not enabled:
            await self.bot.answer_callback_query(call.id, "⛔ هذه الطريقة متوقفة حالياً!", show_alert=True)
            return
        await self.bot.answer_callback_query(call.id)
        await self._show_payment_details(cid, call.message.message_id, method)

    async def handle_send_proof_callback(self, call):
        d = call.data
        try:
            await self.bot.answer_callback_query(call.id)
        except Exception:
            pass

        if d.startswith("crypto_sent_"):
            net = "bep20" if d.endswith("bep20") else "trc20"
            await self._get_crypto().prompt_txid(call, net)
        elif d.startswith("crypto_copy_"):
            net = "bep20" if d.endswith("bep20") else "trc20"
            await self._get_crypto().handle_copy_address(call, net)
        elif d in ("binance_enter_amount", "binance_enter_order"):
            bp = self._get_binance()
            if bp:
                await bp.prompt_amount(call)
        elif d.startswith("send_proof_"):
            method = d.replace("send_proof_", "")
            _WAITING_PROOF[call.from_user.id] = {"type": "proof", "method": method}
            await self.bot.send_message(call.message.chat.id, "📸 <b>أرسل صورة الإيصال أو نص TXID:</b>")

    async def _show_payment_details(self, cid, mid, method):
        details = {
            "vodafone": (
                "📱 <b>فودافون كاش</b>\n\n"
                f"📲 رقم التحويل: <code>{self.db.get_setting('vodafone_number','01002495127')}</code>\n\n"
                "1️⃣ قم بنسخ الرقم\n"
                "2️⃣ قم بتحويل المبلغ للرقم\n"
                "3️⃣ اكد العمليه\n"
                "4️⃣ اضغط <b>إرسال الإيصال</b> وأرسل الصورة ورقم الهاتف  المحول منه وانتظر تاكيد الدفع يدويا"
            ),
            "crypto": (
                "🔐 <b>كريبتو (يدوي)</b>\n\n"
                f"📋 العنوان: <code>{self.db.get_setting('crypto_address','...')}</code>\n"
                "الشبكة: TRC20 / ERC20\n\n"
                "بعد الإرسال اضغط <b>إرسال الإيصال</b> وأرسل TXID أو صورة."
            ),
            "usdt": (
                "💎 <b>USDT TRC20 (يدوي)</b>\n\n"
                f"📋 العنوان: <code>{self.db.get_setting('usdt_address','...')}</code>\n"
                "الشبكة: <b>TRC20</b>\n\n"
                "بعد الإرسال اضغط <b>إرسال الإيصال</b>."
            ),
        }
        text = details.get(method, "غير معروف")
        kb   = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("📸 إرسال الإيصال", callback_data=f"send_proof_{method}"),
            types.InlineKeyboardButton("🔙 رجوع",           callback_data="charge_back"),
        )
        try:
            await self.bot.edit_message_text(text, cid, mid, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await self.bot.send_message(cid, text, reply_markup=kb, parse_mode="HTML")

    async def handle_incoming(self, message) -> bool:
        uid = message.from_user.id

        cr = self._get_crypto()
        if cr.in_session(uid):
            if await cr.handle_crypto_message(message):
                return True

        bp = self._get_binance()
        if bp and bp.in_session(uid):
            if await bp.handle_binance_message(message):
                return True

        state = _WAITING_PROOF.get(uid)
        if not state:
            return False

        del _WAITING_PROOF[uid]
        cid = message.chat.id

        if state["type"] == "gift":
            code   = (message.text or "").strip().upper()
            result = self.db.use_promo_code(code, uid)
            if result["success"]:
                new_bal = self.db.get_balance(uid)
                await self.bot.send_message(
                    cid,
                    f"✅ <b>تم تفعيل كود الهدية!</b>\n"
                    f"💰 أضيف: <code>${result['amount']:.2f}</code>\n"
                    f"💳 رصيدك: <code>${new_bal:.2f}</code>"
                )
            else:
                await self.bot.send_message(cid, f"❌ <b>الكود غير صالح!</b>\n{result.get('reason','')}")
            return True

        method     = state.get("method", "unknown")
        req_id     = self.db.create_payment_request(uid, method, 0)
        methods_ar = {"vodafone": "فودافون كاش", "crypto": "كريبتو", "usdt": "USDT TRC20"}

        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ قبول", callback_data=f"adm_approv_{req_id}"),
            types.InlineKeyboardButton("❌ رفض",  callback_data=f"adm_reject_{req_id}"),
        )
        caption = (
            f"💳 <b>طلب شحن يدوي جديد!</b>\n\n"
            f"👤 المستخدم: <code>{uid}</code>\n"
            f"💳 الطريقة: {methods_ar.get(method, method)}\n"
            f"🔢 رقم الطلب: #{req_id}"
        )
        try:
            if message.photo:
                await self.bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, reply_markup=kb)
            elif message.document:
                await self.bot.send_document(ADMIN_ID, message.document.file_id, caption=caption, reply_markup=kb)
            else:
                await self.bot.send_message(ADMIN_ID, caption + f"\n\n📝 <code>{message.text}</code>", reply_markup=kb)
        except Exception as e:
            logger.error(f"proof forward error: {e}")

        await self.bot.send_message(
            cid,
            f"✅ <b>تم إرسال طلبك للمراجعة!</b>\n"
            f"🔢 رقم طلبك: <code>#{req_id}</code>\n"
            f"⏳ سيتم الرد خلال دقائق."
        )
        return True
