"""
╔══════════════════════════════════════════════════════════╗
║        لوحة تحكم الأدمن - admin_panel.py  v2            ║
║  التعديلات:                                              ║
║  ✅ إدارة أكثر من قناة للاشتراك الإجباري                  ║
║  ✅ إحصائيات أرصدة المستخدمين                             ║
║  ✅ أزرار تقارير المبيعات والإعدادات المتقدمة             ║
╚══════════════════════════════════════════════════════════╝
"""

import asyncio
import io
import logging
import random
import string
from datetime import datetime
from telebot import types
from config import ADMIN_ID

logger = logging.getLogger(__name__)

_WAITING: dict[int, str] = {}
_LOGIN_STATE: dict[int, dict] = {}


def set_wait(admin_id: int, state: str):
    _WAITING[admin_id] = state

def get_wait(admin_id: int) -> str:
    return _WAITING.get(admin_id, "")

def clear_wait(admin_id: int):
    _WAITING.pop(admin_id, None)


class AdminPanel:
    def __init__(self, db, bot, session_mgr, scheduler):
        self.db          = db
        self.bot         = bot
        self.session_mgr = session_mgr
        self.scheduler   = scheduler

    # ══════════════════════════════════════════════
    #  لوحة التحكم الرئيسية
    # ══════════════════════════════════════════════
    async def show_panel(self, chat_id):
        stats     = self.db.get_stats()
        channels  = self.db.get_force_channels()
        ch_count  = len(channels)
        ch_status = f"{ch_count} قناة" if ch_count else "غير مفعّل"

        text = (
            f"┌──────────────────────────────┐\n"
            f"│     🎛️ لوحة تحكم الأدمن      │\n"
            f"└──────────────────────────────┘\n\n"
            f"👥 المستخدمون:       <code>{stats['users']}</code>\n"
            f"📦 الأرقام المتاحة:  <code>{stats['sessions']}</code>\n"
            f"🛒 إجمالي المبيعات:  <code>{stats['sales_count']}</code>\n"
            f"💰 إجمالي الإيرادات: <code>${stats['total_revenue']:.2f}</code>\n"
            f"💳 إجمالي الأرصدة:  <code>${stats['total_balances']:.2f}</code>\n"
            f"📈 مبيعات اليوم:     <code>{stats['today_sales']}</code>\n"
            f"⏳ طلبات معلقة:     <code>{stats['pending_payments']}</code>\n"
            f"📢 قنوات إجبارية:   <code>{ch_status}</code>\n\n"
            f"🕐 <i>{datetime.now().strftime('%Y-%m-%d %H:%M')}</i>"
        )
        await self.bot.send_message(chat_id, text, reply_markup=self._main_kb())

    def _main_kb(self):
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📦 إدارة الجلسات",      callback_data="adm_sessions"),
            types.InlineKeyboardButton("💳 إعدادات الدفع",       callback_data="adm_payments"),
        )
        kb.add(
            types.InlineKeyboardButton("💰 إضافة رصيد",          callback_data="adm_add_bal"),
            types.InlineKeyboardButton("💸 خصم رصيد",             callback_data="adm_deduct_bal"),
        )
        kb.add(
            types.InlineKeyboardButton("🔍 معلومات مستخدم",      callback_data="adm_user_info"),
            types.InlineKeyboardButton("💵 أرصدة المستخدمين",    callback_data="adm_users_balances"),
        )
        kb.add(
            types.InlineKeyboardButton("⛔ حظر / ✅ رفع حظر",    callback_data="adm_ban_menu"),
            types.InlineKeyboardButton("🎟 إنشاء كود هدية",      callback_data="adm_make_code"),
        )
        kb.add(
            types.InlineKeyboardButton("🎟 إدارة الأكواد",        callback_data="adm_list_codes"),
            types.InlineKeyboardButton("📡 إذاعة",               callback_data="adm_broadcast"),
        )
        kb.add(
            types.InlineKeyboardButton("🔍 فحص كل الجلسات",      callback_data="adm_check_all"),
            types.InlineKeyboardButton("💵 سعر الرقم",           callback_data="adm_price_num"),
        )
        kb.add(
            types.InlineKeyboardButton("💵 سعر الجلسة",          callback_data="adm_price_ses"),
            types.InlineKeyboardButton("💵 مكافأة الإحالة",      callback_data="adm_price_ref"),
        )
        kb.add(
            types.InlineKeyboardButton("💾 نسخ احتياطي",         callback_data="adm_backup"),
            types.InlineKeyboardButton("📄 تصدير TXT",           callback_data="adm_export_txt"),
        )
        kb.add(
            types.InlineKeyboardButton("📢 الاشتراك الإجباري",   callback_data="adm_force_channels"),
        )
        kb.add(
            types.InlineKeyboardButton("📱 تسجيل دخول برقم",    callback_data="adm_login_phone"),
            types.InlineKeyboardButton("📥 استيراد DB",          callback_data="adm_import_db"),
        )
        kb.add(
            types.InlineKeyboardButton("💛 إعداد Binance Pay ⚡", callback_data="adm_binance_setup"),
        )
        kb.add(
            types.InlineKeyboardButton("💎 إعداد USDT BEP20 ⚡",  callback_data="adm_bep20_setup"),
        )
        kb.add(
            types.InlineKeyboardButton("🟣 إعداد USDT TRC20 ⚡",  callback_data="adm_trc20_setup"),
        )
        # 🆕 الزرين الجديدين
        kb.add(
            types.InlineKeyboardButton("📊 تقارير المبيعات", callback_data="adm_sales_report"),
            types.InlineKeyboardButton("⚙️ إعدادات متقدمة", callback_data="adm_advanced_settings"),
        )
        return kb

    # ══════════════════════════════════════════════
    #  معالجة Callbacks
    # ══════════════════════════════════════════════
    async def handle_callback(self, call):
        d   = call.data
        cid = call.message.chat.id
        mid = call.message.message_id

        await self.bot.answer_callback_query(call.id)

        # ── الجلسات ──────────────────────────────
        if d == "adm_sessions":
            await self._sessions_menu(cid, mid)

        elif d == "adm_check_all":
            await self.bot.edit_message_text("🔍 <b>جارٍ فحص الجلسات...</b> انتظر.", cid, mid)
            result = await self.session_mgr.bulk_check()
            text   = (
                f"✅ <b>اكتمل الفحص</b>\n\n"
                f"📊 الإجمالي: {result['total']}\n"
                f"✔️ صالحة:   {result['valid']}\n"
                f"🗑️ محذوفة:  {result['invalid']}\n"
            )
            if result['deleted']:
                text += "\n<b>أرقام محذوفة:</b>\n" + "\n".join(
                    f"• <code>{p}</code>" for p in result['deleted'][:10]
                )
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_sessions"))
            await self.bot.edit_message_text(text, cid, mid, reply_markup=kb)

        elif d == "adm_add_session":
            await self.bot.send_message(
                cid,
                "✍️ <b>أرسل الـ String Session:</b>\n\n"
                "<i>أو أرسل ملف .txt (صيغة: phone|session أو جلسة في كل سطر)</i>"
            )
            set_wait(ADMIN_ID, "add_session")

        elif d == "adm_login_phone":
            await self.bot.send_message(
                cid,
                "📱 <b>أرسل رقم الهاتف مع الكود الدولي:</b>\n"
                "مثال: <code>+201234567890</code>"
            )
            set_wait(ADMIN_ID, "login_phone")

        # ── إعدادات الدفع ────────────────────────
        elif d == "adm_payments":
            await self._payments_menu(cid, mid)

        elif d.startswith("adm_toggle_"):
            method  = d.replace("adm_toggle_", "")
            enabled = self.db.toggle_payment(method)
            status  = "✅ مفعّلة" if enabled else "⛔ معطّلة"
            await self.bot.answer_callback_query(call.id, status, show_alert=True)
            if method == "binance":
                await self._binance_setup_menu(cid, mid)
            else:
                await self._payments_menu(cid, mid)

        # ── الرصيد ───────────────────────────────
        elif d == "adm_add_bal":
            await self.bot.send_message(
                cid,
                "💰 <b>أرسل:</b> <code>user_id المبلغ</code>\n\n"
                "مثال: <code>123456789 5.00</code>"
            )
            set_wait(ADMIN_ID, "add_bal")

        elif d == "adm_deduct_bal":
            await self.bot.send_message(
                cid,
                "💸 <b>أرسل:</b> <code>user_id المبلغ</code>"
            )
            set_wait(ADMIN_ID, "deduct_bal")

        # ── أرصدة جميع المستخدمين ────────────────
        elif d == "adm_users_balances":
            await self._show_users_balances(cid, mid)

        # ── معلومات مستخدم ───────────────────────
        elif d == "adm_user_info":
            await self.bot.send_message(cid, "🔍 <b>أرسل ID المستخدم:</b>")
            set_wait(ADMIN_ID, "user_info")

        # ── الحظر ────────────────────────────────
        elif d == "adm_ban_menu":
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("⛔ حظر",      callback_data="adm_ban"),
                types.InlineKeyboardButton("✅ رفع حظر", callback_data="adm_unban"),
            )
            kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back"))
            await self.bot.edit_message_text("اختر:", cid, mid, reply_markup=kb)

        elif d == "adm_ban":
            await self.bot.send_message(cid, "⛔ <b>أرسل ID المستخدم للحظر:</b>")
            set_wait(ADMIN_ID, "ban")

        elif d == "adm_unban":
            await self.bot.send_message(cid, "✅ <b>أرسل ID المستخدم لرفع الحظر:</b>")
            set_wait(ADMIN_ID, "unban")

        # ── الأكواد ──────────────────────────────
        elif d == "adm_make_code":
            await self.bot.send_message(
                cid,
                "🎟 <b>أرسل:</b> <code>المبلغ عدد_الاستخدامات</code>\n\n"
                "مثال: <code>5.00 1</code>"
            )
            set_wait(ADMIN_ID, "make_code")

        elif d == "adm_list_codes":
            await self._list_codes(cid)

        elif d == "adm_delete_code":
            await self.bot.send_message(cid, "🗑 <b>أرسل الكود للحذف:</b>")
            set_wait(ADMIN_ID, "delete_code")

        # ── الإذاعة ──────────────────────────────
        elif d == "adm_broadcast":
            await self.bot.send_message(cid, "📡 <b>أرسل نص الإذاعة الآن:</b>")
            set_wait(ADMIN_ID, "broadcast")

        # ── الأسعار ──────────────────────────────
        elif d == "adm_price_num":
            cur = self.db.get_setting('number_price', '1.00')
            await self.bot.send_message(
                cid, f"💵 <b>سعر الرقم الحالي:</b> ${cur}\n\nأرسل السعر الجديد:"
            )
            set_wait(ADMIN_ID, "price_num")

        elif d == "adm_price_ses":
            cur = self.db.get_setting('session_price', '1.50')
            await self.bot.send_message(
                cid, f"💵 <b>سعر الجلسة الحالي:</b> ${cur}\n\nأرسل السعر الجديد:"
            )
            set_wait(ADMIN_ID, "price_ses")

        elif d == "adm_price_ref":
            cur = self.db.get_setting('ref_bonus', '0.50')
            await self.bot.send_message(
                cid, f"💵 <b>مكافأة الإحالة:</b> ${cur}\n\nأرسل القيمة الجديدة:"
            )
            set_wait(ADMIN_ID, "price_ref")

        # ── النسخ الاحتياطي ──────────────────────
        elif d == "adm_backup":
            await self.bot.edit_message_text(
                "⏳ <b>جارٍ إنشاء النسخة الاحتياطية...</b>", cid, mid
            )
            await self.scheduler.send_backup()
            await self.bot.send_message(cid, "✅ <b>تم إرسال النسخة الاحتياطية!</b>")

        elif d == "adm_export_txt":
            await self.scheduler.send_sessions_txt()
            await self.bot.send_message(cid, "✅ <b>تم تصدير الجلسات!</b>")

        # ══════════════════════════════════════════
        #  📢 إدارة قنوات الاشتراك الإجباري (متعدد)
        # ══════════════════════════════════════════
        elif d == "adm_force_channels":
            await self._force_channels_menu(cid, mid)

        elif d == "adm_add_channel":
            await self.bot.send_message(
                cid,
                "📢 <b>أرسل معرّف القناة المراد إضافتها:</b>\n\n"
                "مثال: <code>@mychannel</code> أو <code>-1001234567890</code>\n\n"
                "<i>تأكد أن البوت مشرف في القناة أولاً</i>"
            )
            set_wait(ADMIN_ID, "add_channel")

        elif d == "adm_remove_channel":
            channels = self.db.get_force_channels()
            if not channels:
                await self.bot.send_message(cid, "❌ لا توجد قنوات مضافة.")
                return
            await self.bot.send_message(
                cid,
                "🗑 <b>أرسل معرّف القناة المراد حذفها:</b>\n\n" +
                "\n".join(f"• <code>{ch}</code>" for ch in channels)
            )
            set_wait(ADMIN_ID, "remove_channel")

        elif d == "adm_set_notify":
            cur = self.db.get_setting('notify_channel', '') or '(غير محدد)'
            await self.bot.send_message(
                cid,
                f"📣 <b>قناة الإشعارات الحالية:</b> <code>{cur}</code>\n\n"
                "أرسل معرّف القناة الجديدة أو <code>disable</code> لتعطيلها:"
            )
            set_wait(ADMIN_ID, "set_notify_channel")

        elif d == "adm_clear_channels":
            self.db.set_force_channels([])
            self.db.set_force_channel_names([])
            await self.bot.send_message(cid, "✅ تم مسح جميع قنوات الاشتراك الإجباري.")

        # ── استيراد DB ───────────────────────────
        elif d == "adm_import_db":
            await self.bot.send_message(cid, "📥 <b>أرسل ملف قاعدة البيانات (.db):</b>")
            set_wait(ADMIN_ID, "import_db")

        # ══════════════════════════════════════════
        #  💛 Binance Pay
        # ══════════════════════════════════════════
        elif d == "adm_binance_setup":
            await self._binance_setup_menu(cid, mid)

        elif d == "adm_set_binance_key":
            await self.bot.send_message(cid, "🔑 <b>أرسل Binance API Key:</b>")
            set_wait(ADMIN_ID, "binance_api_key")

        elif d == "adm_set_binance_secret":
            await self.bot.send_message(cid, "🔐 <b>أرسل Binance API Secret:</b>")
            set_wait(ADMIN_ID, "binance_api_secret")

        elif d == "adm_set_binance_payid":
            await self.bot.send_message(cid, "🆔 <b>أرسل Binance Pay ID:</b>")
            set_wait(ADMIN_ID, "binance_pay_id")

        elif d == "adm_set_binance_min":
            cur = self.db.get_setting('binance_min_usdt', '1.00')
            await self.bot.send_message(cid, f"💵 الحد الأدنى الحالي: {cur} USDT\n\nأرسل القيمة الجديدة:")
            set_wait(ADMIN_ID, "binance_min_usdt")

        elif d == "adm_set_binance_rate":
            cur = self.db.get_setting('binance_usdt_rate', '1.00')
            await self.bot.send_message(cid, f"💱 سعر الصرف: 1 USDT = ${cur}\n\nأرسل القيمة الجديدة:")
            set_wait(ADMIN_ID, "binance_rate")

        elif d == "adm_test_binance":
            await self._test_binance(cid, mid)

        # ══════════════════════════════════════════
        #  💎 BEP20
        # ══════════════════════════════════════════
        elif d == "adm_bep20_setup":
            await self._bep20_setup_menu(cid, mid)

        elif d == "adm_set_bep20_address":
            await self.bot.send_message(cid, "📋 <b>أرسل عنوان محفظة USDT BEP20:</b>\n\nيبدأ بـ <code>0x</code> ويتكون من 42 حرفاً")
            set_wait(ADMIN_ID, "bep20_address")

        elif d == "adm_set_bep20_apikey":
            await self.bot.send_message(cid, "🔑 <b>أرسل BSCScan API Key:</b>\n\n<i>من: bscscan.com/myapikey</i>")
            set_wait(ADMIN_ID, "bep20_api_key")

        elif d == "adm_set_bep20_min":
            cur = self.db.get_setting('bep20_min_usdt', '1.00')
            await self.bot.send_message(cid, f"💵 الحد الأدنى: {cur} USDT\n\nأرسل القيمة الجديدة:")
            set_wait(ADMIN_ID, "bep20_min_usdt")

        elif d == "adm_set_bep20_rate":
            cur = self.db.get_setting('bep20_usdt_rate', '1.00')
            await self.bot.send_message(cid, f"💱 سعر الصرف: 1 USDT = ${cur}\n\nأرسل القيمة الجديدة:")
            set_wait(ADMIN_ID, "bep20_rate")

        elif d == "adm_set_bep20_confirms":
            cur = self.db.get_setting('bep20_confirmations', '3')
            await self.bot.send_message(cid, f"✅ عدد التأكيدات: {cur}\n\nأرسل العدد الجديد (الموصى به: 3):")
            set_wait(ADMIN_ID, "bep20_confirmations")

        elif d == "adm_toggle_bep20":
            cur = self.db.get_setting('pay_bep20', '0')
            new_val = '0' if cur == '1' else '1'
            self.db.set_setting('pay_bep20', new_val)
            status = "✅ مفعّل" if new_val == '1' else "⛔ معطّل"
            await self.bot.answer_callback_query(call.id, f"USDT BEP20 {status}", show_alert=True)
            await self._bep20_setup_menu(cid, mid)

        elif d == "adm_test_bep20":
            await self._test_bep20(cid, mid)

        # ══════════════════════════════════════════
        #  🟣 TRC20
        # ══════════════════════════════════════════
        elif d == "adm_trc20_setup":
            await self._trc20_setup_menu(cid, mid)

        elif d == "adm_set_trc20_address":
            await self.bot.send_message(cid, "📋 <b>أرسل عنوان محفظة USDT TRC20:</b>\n\nيبدأ بـ T ويتكون من 34 حرفاً")
            set_wait(ADMIN_ID, "trc20_address")

        elif d == "adm_set_trc20_apikey":
            await self.bot.send_message(cid, "🔑 <b>أرسل TronGrid API Key:</b>\n\n<i>من: trongrid.io/dashboard</i>")
            set_wait(ADMIN_ID, "trc20_api_key")

        elif d == "adm_set_trc20_min":
            cur = self.db.get_setting('trc20_min_usdt', '1.00')
            await self.bot.send_message(cid, f"💵 الحد الأدنى: {cur} USDT\n\nأرسل القيمة الجديدة:")
            set_wait(ADMIN_ID, "trc20_min_usdt")

        elif d == "adm_set_trc20_rate":
            cur = self.db.get_setting('trc20_usdt_rate', '1.00')
            await self.bot.send_message(cid, f"💱 سعر الصرف: 1 USDT = ${cur}\n\nأرسل القيمة الجديدة:")
            set_wait(ADMIN_ID, "trc20_rate")

        elif d == "adm_set_trc20_confirms":
            cur = self.db.get_setting('trc20_confirmations', '19')
            await self.bot.send_message(cid, f"✅ عدد التأكيدات: {cur}\n\nالموصى به: 19\nأرسل العدد الجديد:")
            set_wait(ADMIN_ID, "trc20_confirmations")

        elif d == "adm_toggle_trc20":
            cur = self.db.get_setting('pay_trc20', '0')
            new_val = '0' if cur == '1' else '1'
            self.db.set_setting('pay_trc20', new_val)
            status = "✅ مفعّل" if new_val == '1' else "⛔ معطّل"
            await self.bot.answer_callback_query(call.id, f"USDT TRC20 {status}", show_alert=True)
            await self._trc20_setup_menu(cid, mid)

        elif d == "adm_test_trc20":
            await self._test_trc20(cid, mid)

        # 🆕 تقارير المبيعات
        elif d == "adm_sales_report":
            await self._sales_report(cid, mid)

        # 🆕 الإعدادات المتقدمة
        elif d == "adm_advanced_settings":
            await self._advanced_settings_menu(cid, mid)

        elif d == "adm_set_max_buy":
            cur = self.db.get_setting('max_buy_sessions', '50')
            await self.bot.send_message(cid, f"🔢 أقصى عدد جلسات للشراء دفعة واحدة: {cur}\n\nأرسل القيمة الجديدة:")
            set_wait(ADMIN_ID, "max_buy_sessions")

        elif d == "adm_set_min_balance":
            cur = self.db.get_setting('min_balance', '0')
            await self.bot.send_message(cid, f"💰 الحد الأدنى للرصيد: ${cur}\n\nأرسل القيمة الجديدة:")
            set_wait(ADMIN_ID, "min_balance")

        elif d == "adm_toggle_maintenance":
            cur = self.db.get_setting('maintenance_mode', '0')
            new_val = '0' if cur == '1' else '1'
            self.db.set_setting('maintenance_mode', new_val)
            status = "مفعّل" if new_val == '1' else "معطّل"
            await self.bot.answer_callback_query(call.id, f"وضع الصيانة {status}", show_alert=True)
            await self._advanced_settings_menu(cid, mid)

        # ── موافقة / رفض دفع ──────────────────────
        elif d.startswith("adm_approv_"):
            req_id = int(d.split("_")[2])
            await self.bot.send_message(
                cid, f"💰 <b>أرسل المبلغ للموافقة على طلب #{req_id}:</b>"
            )
            set_wait(ADMIN_ID, f"approve_{req_id}")

        elif d.startswith("adm_reject_"):
            req_id = int(d.split("_")[2])
            uid    = self.db.reject_payment(req_id)
            await self.bot.edit_message_text(
                f"❌ <b>تم رفض طلب #{req_id}</b>", cid, mid
            )
            if uid:
                try:
                    await self.bot.send_message(
                        uid,
                        f"❌ <b>تم رفض طلب شحنك #{req_id}.</b>\n"
                        "تواصل مع الدعم إذا كان هذا خطأً."
                    )
                except Exception:
                    pass

    # ══════════════════════════════════════════════
    #  🆕 تقارير المبيعات
    # ══════════════════════════════════════════════
    async def _sales_report(self, cid, mid):
        stats = self.db.get_stats()
        today_sales = self.db.get_today_sales_details(limit=10)
        text = (
            f"┌──────────────────────────────┐\n"
            f"│     📊 تقارير المبيعات        │\n"
            f"└──────────────────────────────┘\n\n"
            f"🛒 إجمالي المبيعات: <b>{stats['sales_count']}</b>\n"
            f"💰 إجمالي الإيرادات: <b>${stats['total_revenue']:.2f}</b>\n"
            f"📈 مبيعات اليوم: <b>{stats['today_sales']}</b>\n\n"
            f"<b>آخر 10 مبيعات اليوم:</b>\n"
        )
        if today_sales:
            for i, sale in enumerate(today_sales, 1):
                text += f"{i}. <code>{sale['phone']}</code> — ${sale['price']:.2f} — {sale['type']}\n"
        else:
            text += "لا توجد مبيعات اليوم.\n"

        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back"))
        try:
            await self.bot.edit_message_text(text, cid, mid, reply_markup=kb)
        except Exception:
            await self.bot.send_message(cid, text, reply_markup=kb)

    # ══════════════════════════════════════════════
    #  🆕 الإعدادات المتقدمة
    # ══════════════════════════════════════════════
    async def _advanced_settings_menu(self, cid, mid):
        max_buy   = self.db.get_setting('max_buy_sessions', '50')
        min_bal   = self.db.get_setting('min_balance', '0')
        maint     = self.db.get_setting('maintenance_mode', '0')
        maint_txt = "✅ مفعّل" if maint == '1' else "⛔ معطّل"

        text = (
            f"┌──────────────────────────────┐\n"
            f"│      ⚙️ إعدادات متقدمة        │\n"
            f"└──────────────────────────────┘\n\n"
            f"🔢 أقصى عدد جلسات للشراء: <b>{max_buy}</b>\n"
            f"💰 الحد الأدنى للرصيد: <b>${min_bal}</b>\n"
            f"🛠️ وضع الصيانة: <b>{maint_txt}</b>\n"
        )

        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🔢 أقصى شراء", callback_data="adm_set_max_buy"),
            types.InlineKeyboardButton("💰 حد أدنى رصيد", callback_data="adm_set_min_balance"),
        )
        kb.add(
            types.InlineKeyboardButton("🛠️ تبديل وضع الصيانة", callback_data="adm_toggle_maintenance"),
        )
        kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back"))

        try:
            await self.bot.edit_message_text(text, cid, mid, reply_markup=kb)
        except Exception:
            await self.bot.send_message(cid, text, reply_markup=kb)

    # ══════════════════════════════════════════════
    #  صفحة أرصدة المستخدمين
    # ══════════════════════════════════════════════
    async def _show_users_balances(self, cid, mid):
        users = self.db.get_all_users_with_balance(limit=30)
        total = self.db.get_stats()['total_balances']

        text = (
            f"┌─────────────────────────────┐\n"
            f"│    💵 أرصدة المستخدمين       │\n"
            f"└─────────────────────────────┘\n\n"
            f"💰 <b>إجمالي الأرصدة:</b> <code>${total:.2f}</code>\n\n"
            f"<b>أعلى 30 مستخدم رصيداً:</b>\n"
            f"{'─'*30}\n"
        )

        for i, u in enumerate(users, 1):
            name  = u.get('first_name') or u.get('username') or '—'
            uname = f"@{u['username']}" if u.get('username') else ''
            bal   = u.get('balance', 0.0)
            if bal <= 0:
                continue
            text += (
                f"{i}. <code>{u['id']}</code> — <b>${bal:.2f}</b>\n"
                f"   {name} {uname}\n"
            )

        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back"))

        try:
            await self.bot.edit_message_text(text, cid, mid, reply_markup=kb)
        except Exception:
            await self.bot.send_message(cid, text, reply_markup=kb)

    # ══════════════════════════════════════════════
    #  قائمة إدارة القنوات الإجبارية
    # ══════════════════════════════════════════════
    async def _force_channels_menu(self, cid, mid):
        channels = self.db.get_force_channels()
        names    = self.db.get_force_channel_names()
        notify   = self.db.get_setting('notify_channel', '') or '(غير محدد)'

        text = (
            f"┌─────────────────────────────┐\n"
            f"│   📢 الاشتراك الإجباري       │\n"
            f"└─────────────────────────────┘\n\n"
        )

        if channels:
            text += f"<b>القنوات المضافة ({len(channels)}):</b>\n"
            for i, ch in enumerate(channels):
                name = names[i] if i < len(names) else ch
                text += f"• {name} — <code>{ch}</code>\n"
        else:
            text += "⚪ لا توجد قنوات مضافة حالياً.\n"

        text += (
            f"\n<b>قناة الإشعارات:</b> <code>{notify}</code>\n\n"
            f"<i>💡 يمكنك إضافة أكثر من قناة — يجب على المستخدم الاشتراك في الكل</i>"
        )

        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("➕ إضافة قناة",    callback_data="adm_add_channel"),
            types.InlineKeyboardButton("🗑 حذف قناة",     callback_data="adm_remove_channel"),
        )
        kb.add(
            types.InlineKeyboardButton("📣 قناة الإشعارات", callback_data="adm_set_notify"),
            types.InlineKeyboardButton("🔄 مسح الكل",       callback_data="adm_clear_channels"),
        )
        kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back"))

        try:
            await self.bot.edit_message_text(text, cid, mid, reply_markup=kb)
        except Exception:
            await self.bot.send_message(cid, text, reply_markup=kb)

    # ══════════════════════════════════════════════
    #  معالجة رسائل الأدمن النصية
    # ══════════════════════════════════════════════
    async def handle_message(self, message) -> bool:
        uid   = message.from_user.id
        text  = (message.text or "").strip()
        cid   = message.chat.id
        state = get_wait(uid)

        if not state:
            return False

        # ── تسجيل دخول برقم ──────────────────────
        if state == "login_phone":
            clear_wait(uid)
            phone = text if text.startswith('+') else '+' + text
            result = await self.session_mgr.login_with_phone(phone)
            if result['success']:
                _LOGIN_STATE[uid] = {
                    'client':          result['client'],
                    'phone':           phone,
                    'phone_code_hash': result['phone_code_hash'],
                }
                await self.bot.send_message(
                    cid, f"✅ <b>تم إرسال OTP إلى {phone}</b>\n\nأرسل الكود:"
                )
                set_wait(uid, "login_otp")
            else:
                await self.bot.send_message(cid, f"❌ <b>فشل:</b> {result['error']}")
            return True

        if state == "login_otp":
            clear_wait(uid)
            login = _LOGIN_STATE.get(uid, {})
            if not login:
                await self.bot.send_message(cid, "❌ انتهت جلسة التسجيل. ابدأ من جديد.")
                return True
            result = await self.session_mgr.complete_login(
                login['client'], login['phone'], login['phone_code_hash'], text
            )
            if result.get('error') == '2fa':
                _LOGIN_STATE[uid] = {**login, 'client': result['client']}
                await self.bot.send_message(cid, "🔐 <b>التحقق بخطوتين مفعّل!</b>\nأرسل كلمة المرور:")
                set_wait(uid, "login_2fa")
            elif result['success']:
                _LOGIN_STATE.pop(uid, None)
                await self.bot.send_message(
                    cid, f"✅ <b>تمت الإضافة بنجاح!</b>\n📱 <code>{result['phone']}</code>"
                )
            else:
                await self.bot.send_message(cid, f"❌ <b>فشل:</b> {result['error']}")
            return True

        if state == "login_2fa":
            clear_wait(uid)
            login = _LOGIN_STATE.pop(uid, {})
            if not login:
                await self.bot.send_message(cid, "❌ انتهت جلسة التسجيل.")
                return True
            result = await self.session_mgr.complete_login_2fa(login['client'], text)
            if result['success']:
                await self.bot.send_message(
                    cid, f"✅ <b>تمت الإضافة بنجاح!</b>\n📱 <code>{result['phone']}</code>"
                )
            else:
                await self.bot.send_message(cid, f"❌ <b>فشل:</b> {result['error']}")
            return True

        # ── إضافة جلسة ───────────────────────────
        if state == "add_session":
            clear_wait(uid)
            await self._process_single_session(cid, text)
            return True

        # ── الرصيد ───────────────────────────────
        if state == "add_bal":
            clear_wait(uid)
            try:
                parts  = text.split()
                target = int(parts[0])
                amount = float(parts[1])
                self.db.add_balance(target, amount)
                new_bal = self.db.get_balance(target)
                await self.bot.send_message(
                    cid,
                    f"✅ تمت إضافة <b>${amount:.2f}</b> للمستخدم <code>{target}</code>\n"
                    f"💳 رصيده الجديد: <code>${new_bal:.2f}</code>"
                )
                try:
                    await self.bot.send_message(
                        target,
                        f"🎉 <b>تم إضافة رصيد!</b>\n"
                        f"💰 المبلغ: <code>${amount:.2f}</code>\n"
                        f"💳 رصيدك: <code>${new_bal:.2f}</code>"
                    )
                except Exception:
                    pass
            except Exception:
                await self.bot.send_message(cid, "❌ صيغة خاطئة! مثال: <code>123456789 5.00</code>")
            return True

        if state == "deduct_bal":
            clear_wait(uid)
            try:
                parts  = text.split()
                target = int(parts[0])
                amount = float(parts[1])
                bal    = self.db.get_balance(target)
                if amount > bal:
                    await self.bot.send_message(
                        cid, f"⚠️ رصيد المستخدم <code>${bal:.2f}</code> أقل من المطلوب!"
                    )
                    return True
                self.db.deduct_balance(target, amount)
                new_bal = self.db.get_balance(target)
                await self.bot.send_message(
                    cid,
                    f"✅ تم خصم <b>${amount:.2f}</b> من <code>{target}</code>\n"
                    f"💳 رصيده الجديد: <code>${new_bal:.2f}</code>"
                )
                try:
                    await self.bot.send_message(
                        target,
                        f"⚠️ <b>تم خصم رصيد من حسابك.</b>\n"
                        f"💸 المخصوم: <code>${amount:.2f}</code>\n"
                        f"💳 رصيدك: <code>${new_bal:.2f}</code>"
                    )
                except Exception:
                    pass
            except Exception:
                await self.bot.send_message(cid, "❌ صيغة خاطئة!")
            return True

        # ── معلومات مستخدم ───────────────────────
        if state == "user_info":
            clear_wait(uid)
            try:
                target  = int(text.strip())
                user    = self.db.get_user(target)
                bal     = self.db.get_balance(target)
                buys    = self.db.get_user_purchases_count(target)
                if not user:
                    await self.bot.send_message(cid, f"❌ المستخدم <code>{target}</code> غير موجود.")
                    return True
                banned  = "⛔ محظور" if user.get('is_banned') else "✅ نشط"
                joined  = str(user.get('join_date', ''))[:10]
                await self.bot.send_message(
                    cid,
                    f"👤 <b>معلومات المستخدم</b>\n\n"
                    f"🆔 ID: <code>{target}</code>\n"
                    f"📛 الاسم: {user.get('first_name', '---')}\n"
                    f"👤 اليوزر: @{user.get('username', 'لا يوجد')}\n"
                    f"💰 الرصيد: <code>${bal:.2f}</code>\n"
                    f"🛒 المشتريات: {buys}\n"
                    f"📅 التسجيل: {joined}\n"
                    f"الحالة: {banned}"
                )
            except Exception:
                await self.bot.send_message(cid, "❌ ID غير صحيح!")
            return True

        # ── الحظر ────────────────────────────────
        if state == "ban":
            clear_wait(uid)
            try:
                target = int(text.strip())
                self.db.ban_user(target)
                await self.bot.send_message(cid, f"✅ تم حظر <code>{target}</code>")
                try:
                    await self.bot.send_message(target, "⛔ <b>تم حظرك من البوت.</b>")
                except Exception:
                    pass
            except Exception:
                await self.bot.send_message(cid, "❌ ID غير صحيح!")
            return True

        if state == "unban":
            clear_wait(uid)
            try:
                target = int(text.strip())
                self.db.unban_user(target)
                await self.bot.send_message(cid, f"✅ رُفع الحظر عن <code>{target}</code>")
                try:
                    await self.bot.send_message(target, "✅ <b>تم رفع الحظر عنك!</b>")
                except Exception:
                    pass
            except Exception:
                await self.bot.send_message(cid, "❌ ID غير صحيح!")
            return True

        # ── الأكواد ──────────────────────────────
        if state == "make_code":
            clear_wait(uid)
            try:
                parts    = text.split()
                amount   = float(parts[0])
                max_uses = int(parts[1]) if len(parts) > 1 else 1
                code     = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
                self.db.create_promo_code(code, amount, max_uses)
                await self.bot.send_message(
                    cid,
                    f"✅ <b>تم إنشاء الكود!</b>\n\n"
                    f"🎟 الكود: <code>{code}</code>\n"
                    f"💰 القيمة: ${amount:.2f}\n"
                    f"🔢 الاستخدامات: {max_uses}"
                )
            except Exception:
                await self.bot.send_message(cid, "❌ صيغة خاطئة! مثال: <code>5.00 1</code>")
            return True

        if state == "delete_code":
            clear_wait(uid)
            code = text.strip().upper()
            await self.bot.send_message(cid, f"✅ تم حذف الكود <code>{code}</code> (إذا كان موجوداً).")
            return True

        # ── الإذاعة ──────────────────────────────
        if state == "broadcast":
            clear_wait(uid)
            users    = self.db.get_all_users()
            ok, fail = 0, 0
            status   = await self.bot.send_message(
                cid, f"📡 <b>جارٍ الإرسال لـ {len(users)} مستخدم...</b>"
            )
            for u in users:
                try:
                    await self.bot.send_message(
                        u, f"📢 <b>رسالة من الإدارة:</b>\n\n{text}"
                    )
                    ok += 1
                except Exception:
                    fail += 1
                await asyncio.sleep(0.05)
            await self.bot.edit_message_text(
                f"✅ <b>اكتملت الإذاعة!</b>\n✔️ نجح: {ok}\n❌ فشل: {fail}",
                cid, status.message_id
            )
            return True

        # ── الأسعار ──────────────────────────────
        if state == "price_num":
            clear_wait(uid)
            try:
                self.db.set_setting('number_price', str(float(text)))
                await self.bot.send_message(cid, f"✅ سعر الرقم الجديد: <b>${float(text):.2f}</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ قيمة غير صحيحة!")
            return True

        if state == "price_ses":
            clear_wait(uid)
            try:
                self.db.set_setting('session_price', str(float(text)))
                await self.bot.send_message(cid, f"✅ سعر الجلسة الجديد: <b>${float(text):.2f}</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ قيمة غير صحيحة!")
            return True

        if state == "price_ref":
            clear_wait(uid)
            try:
                self.db.set_setting('ref_bonus', str(float(text)))
                await self.bot.send_message(cid, f"✅ مكافأة الإحالة الجديدة: <b>${float(text):.2f}</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ قيمة غير صحيحة!")
            return True

        # ══════════════════════════════════════════
        #  إدارة القنوات الإجبارية
        # ══════════════════════════════════════════
        if state == "add_channel":
            clear_wait(uid)
            channel = text.strip()
            if not channel:
                await self.bot.send_message(cid, "❌ معرّف القناة فارغ!")
                return True
            _LOGIN_STATE[uid] = {'pending_channel': channel}
            await self.bot.send_message(
                cid,
                f"✅ معرّف القناة: <code>{channel}</code>\n\n"
                "أرسل <b>اسم القناة</b> الذي سيظهر للمستخدمين:\n"
                "<i>مثال: قناة البوت الرسمية</i>"
            )
            set_wait(uid, "add_channel_name")
            return True

        if state == "add_channel_name":
            clear_wait(uid)
            name    = text.strip()
            pending = _LOGIN_STATE.pop(uid, {})
            channel = pending.get('pending_channel', '')
            if not channel:
                await self.bot.send_message(cid, "❌ حدث خطأ. أعد المحاولة.")
                return True
            added = self.db.add_force_channel(channel, name)
            if added:
                count = len(self.db.get_force_channels())
                await self.bot.send_message(
                    cid,
                    f"✅ <b>تمت إضافة القناة بنجاح!</b>\n\n"
                    f"📢 الاسم: <b>{name}</b>\n"
                    f"🆔 المعرف: <code>{channel}</code>\n\n"
                    f"إجمالي القنوات الإجبارية: <b>{count}</b>"
                )
            else:
                await self.bot.send_message(cid, f"⚠️ القناة <code>{channel}</code> مضافة مسبقاً!")
            return True

        if state == "remove_channel":
            clear_wait(uid)
            channel = text.strip()
            removed = self.db.remove_force_channel(channel)
            if removed:
                await self.bot.send_message(cid, f"✅ تم حذف القناة <code>{channel}</code>")
            else:
                await self.bot.send_message(cid, f"❌ القناة <code>{channel}</code> غير موجودة!")
            return True

        if state == "set_notify_channel":
            clear_wait(uid)
            val = text.strip()
            if val.lower() == "disable":
                self.db.set_setting('notify_channel', '')
                await self.bot.send_message(cid, "✅ تم تعطيل قناة الإشعارات.")
            else:
                self.db.set_setting('notify_channel', val)
                await self.bot.send_message(cid, f"✅ قناة الإشعارات: <code>{val}</code>")
            return True

        # ══════════════════════════════════════════
        #  إعدادات Binance
        # ══════════════════════════════════════════
        if state == "binance_api_key":
            clear_wait(uid)
            self.db.set_setting('binance_api_key', text)
            await self.bot.send_message(cid, "✅ <b>تم حفظ API Key!</b>")
            return True

        if state == "binance_api_secret":
            clear_wait(uid)
            self.db.set_setting('binance_api_secret', text)
            await self.bot.send_message(cid, "✅ <b>تم حفظ API Secret!</b>")
            return True

        if state == "binance_pay_id":
            clear_wait(uid)
            self.db.set_setting('binance_pay_id', text)
            await self.bot.send_message(cid, f"✅ <b>تم حفظ Pay ID:</b> <code>{text}</code>")
            return True

        if state == "binance_min_usdt":
            clear_wait(uid)
            try:
                val = float(text)
                self.db.set_setting('binance_min_usdt', str(val))
                await self.bot.send_message(cid, f"✅ الحد الأدنى الجديد: <b>{val} USDT</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ قيمة غير صحيحة!")
            return True

        if state == "binance_rate":
            clear_wait(uid)
            try:
                val = float(text)
                self.db.set_setting('binance_usdt_rate', str(val))
                await self.bot.send_message(cid, f"✅ سعر الصرف: 1 USDT = <b>${val:.4f}</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ قيمة غير صحيحة!")
            return True

        # ══════════════════════════════════════════
        #  إعدادات BEP20
        # ══════════════════════════════════════════
        if state == "bep20_address":
            clear_wait(uid)
            addr = text.strip()
            if not addr.startswith("0x") or len(addr) != 42:
                await self.bot.send_message(
                    cid,
                    "❌ <b>عنوان غير صحيح!</b>\n"
                    "يجب أن يبدأ بـ <code>0x</code> ويكون 42 حرفاً.\n"
                    "أعد الإرسال."
                )
                set_wait(uid, "bep20_address")
                return True
            self.db.set_setting('bep20_address', addr)
            await self.bot.send_message(cid, f"✅ <b>تم حفظ عنوان BEP20!</b>\n<code>{addr}</code>")
            return True

        if state == "bep20_api_key":
            clear_wait(uid)
            self.db.set_setting('bep20_api_key', text.strip())
            await self.bot.send_message(cid, "✅ <b>تم حفظ BSCScan API Key!</b>")
            return True

        if state == "bep20_min_usdt":
            clear_wait(uid)
            try:
                val = float(text)
                self.db.set_setting('bep20_min_usdt', str(val))
                await self.bot.send_message(cid, f"✅ الحد الأدنى: <b>{val} USDT</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ قيمة غير صحيحة!")
            return True

        if state == "bep20_rate":
            clear_wait(uid)
            try:
                val = float(text)
                self.db.set_setting('bep20_usdt_rate', str(val))
                await self.bot.send_message(cid, f"✅ سعر الصرف: 1 USDT = <b>${val:.4f}</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ قيمة غير صحيحة!")
            return True

        if state == "bep20_confirmations":
            clear_wait(uid)
            try:
                val = int(text)
                self.db.set_setting('bep20_confirmations', str(val))
                await self.bot.send_message(cid, f"✅ التأكيدات: <b>{val}</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ أدخل رقماً بين 1 و 20.")
            return True

        # ══════════════════════════════════════════
        #  إعدادات TRC20
        # ══════════════════════════════════════════
        if state == "trc20_address":
            clear_wait(uid)
            addr = text.strip()
            if not addr.startswith("T") or len(addr) != 34:
                await self.bot.send_message(
                    cid,
                    "❌ <b>عنوان TRC20 غير صحيح!</b>\n"
                    "يبدأ بـ T ويكون 34 حرفاً.\n"
                    "أعد الإرسال."
                )
                set_wait(uid, "trc20_address")
                return True
            self.db.set_setting('trc20_address', addr)
            await self.bot.send_message(cid, f"✅ <b>تم حفظ عنوان TRC20!</b>\n<code>{addr}</code>")
            return True

        if state == "trc20_api_key":
            clear_wait(uid)
            self.db.set_setting('trc20_api_key', text.strip())
            await self.bot.send_message(cid, "✅ <b>تم حفظ TronGrid API Key!</b>")
            return True

        if state == "trc20_min_usdt":
            clear_wait(uid)
            try:
                val = float(text)
                self.db.set_setting('trc20_min_usdt', str(val))
                await self.bot.send_message(cid, f"✅ الحد الأدنى: <b>{val} USDT</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ قيمة غير صحيحة!")
            return True

        if state == "trc20_rate":
            clear_wait(uid)
            try:
                val = float(text)
                self.db.set_setting('trc20_usdt_rate', str(val))
                await self.bot.send_message(cid, f"✅ سعر الصرف: 1 USDT = <b>${val:.4f}</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ قيمة غير صحيحة!")
            return True

        if state == "trc20_confirmations":
            clear_wait(uid)
            try:
                val = int(text)
                self.db.set_setting('trc20_confirmations', str(val))
                await self.bot.send_message(cid, f"✅ التأكيدات: <b>{val}</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ أدخل رقماً صحيحاً.")
            return True

        # 🆕 الإعدادات المتقدمة
        if state == "max_buy_sessions":
            clear_wait(uid)
            try:
                val = int(text)
                self.db.set_setting('max_buy_sessions', str(val))
                await self.bot.send_message(cid, f"✅ أقصى عدد جلسات للشراء: <b>{val}</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ قيمة غير صحيحة!")
            return True

        if state == "min_balance":
            clear_wait(uid)
            try:
                val = float(text)
                self.db.set_setting('min_balance', str(val))
                await self.bot.send_message(cid, f"✅ الحد الأدنى للرصيد: <b>${val:.2f}</b>")
            except Exception:
                await self.bot.send_message(cid, "❌ قيمة غير صحيحة!")
            return True

        # ── الموافقة على دفع ──────────────────────
        if state.startswith("approve_"):
            req_id = int(state.split("_")[1])
            clear_wait(uid)
            try:
                amount = float(text)
                target = self.db.approve_payment(req_id, amount)
                if target:
                    new_bal = self.db.get_balance(target)
                    await self.bot.send_message(
                        cid,
                        f"✅ تمت الموافقة على طلب #{req_id}\n"
                        f"💰 أضيف ${amount:.2f} للمستخدم <code>{target}</code>"
                    )
                    try:
                        await self.bot.send_message(
                            target,
                            f"✅ <b>تم قبول طلب الشحن!</b>\n"
                            f"💰 أضيف: <code>${amount:.2f}</code>\n"
                            f"💳 رصيدك: <code>${new_bal:.2f}</code>"
                        )
                    except Exception:
                        pass
            except Exception:
                await self.bot.send_message(cid, "❌ قيمة غير صحيحة!")
            return True

        return False

    # ══════════════════════════════════════════════
    #  معالجة ملفات TXT
    # ══════════════════════════════════════════════
    async def handle_file_upload(self, message) -> bool:
        if not message.document:
            return False
        fname = (message.document.file_name or "").lower()
        if not fname.endswith('.txt'):
            return False
        state = get_wait(message.from_user.id)
        if state != "add_session" and message.from_user.id != ADMIN_ID:
            return False
        clear_wait(message.from_user.id)
        await self._handle_session_file(message)
        return True

    async def _handle_session_file(self, message):
        cid    = message.chat.id
        status = await self.bot.send_message(cid, "⏳ <b>جارٍ معالجة الملف...</b>")
        try:
            file_info  = await self.bot.get_file(message.document.file_id)
            downloaded = await self.bot.download_file(file_info.file_path)
            content    = downloaded.decode('utf-8', errors='ignore')
            lines      = [l.strip() for l in content.splitlines() if l.strip()]

            added, failed, duplicate = 0, 0, 0
            for line in lines:
                session_str = line.split('|', 1)[1].strip() if '|' in line else line.strip()
                if not session_str or len(session_str) < 50:
                    failed += 1
                    continue
                result = await self.session_mgr.add_session(session_str)
                if result['success']:
                    added += 1
                elif 'موجودة' in result.get('error', ''):
                    duplicate += 1
                else:
                    failed += 1

            await self.bot.edit_message_text(
                f"✅ <b>اكتملت المعالجة!</b>\n\n"
                f"✔️ تمت الإضافة: <b>{added}</b>\n"
                f"🔁 مكررة:       <b>{duplicate}</b>\n"
                f"❌ فشل:         <b>{failed}</b>\n"
                f"📦 المتاح الآن: <b>{self.db.get_available_count()}</b>",
                cid, status.message_id
            )
        except Exception as e:
            await self.bot.edit_message_text(
                f"❌ <b>خطأ في معالجة الملف:</b>\n<code>{e}</code>",
                cid, status.message_id
            )

    async def _process_single_session(self, cid, session_str):
        if not session_str or len(session_str) < 50:
            await self.bot.send_message(cid, "❌ الجلسة قصيرة جداً أو غير صالحة!")
            return
        status = await self.bot.send_message(cid, "⏳ <b>جارٍ فحص الجلسة...</b>")
        result = await self.session_mgr.add_session(session_str)
        if result['success']:
            await self.bot.edit_message_text(
                f"✅ <b>تمت الإضافة بنجاح!</b>\n"
                f"📱 الرقم: <code>{result['phone']}</code>\n"
                f"📦 المتاح الآن: {self.db.get_available_count()}",
                cid, status.message_id
            )
        else:
            await self.bot.edit_message_text(
                f"❌ <b>فشل الإضافة!</b>\n{result['error']}",
                cid, status.message_id
            )

    # ══════════════════════════════════════════════
    #  قوائم مساعدة
    # ══════════════════════════════════════════════
    async def _sessions_menu(self, cid, mid):
        count    = self.db.get_available_count()
        sessions = self.db.get_all_sessions_list(limit=5)
        text     = (
            f"┌─────────────────────────┐\n"
            f"│     📦 إدارة الجلسات    │\n"
            f"└─────────────────────────┘\n\n"
            f"✅ المتاحة: <b>{count}</b>\n"
        )
        if sessions:
            text += "\n<b>آخر الإضافات:</b>\n"
            for s in sessions:
                stype = s.get('session_type', 'pyrogram')
                icon  = "🟡" if stype == 'telethon' else "🔵"
                text += f"{icon} <code>{s['phone']}</code>\n"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("➕ إضافة جلسة",  callback_data="adm_add_session"),
            types.InlineKeyboardButton("📱 تسجيل برقم",  callback_data="adm_login_phone"),
            types.InlineKeyboardButton("🔍 فحص الكل",    callback_data="adm_check_all"),
            types.InlineKeyboardButton("📄 تصدير TXT",   callback_data="adm_export_txt"),
            types.InlineKeyboardButton("🔙 رجوع",        callback_data="adm_back"),
        )
        await self.bot.edit_message_text(text, cid, mid, reply_markup=kb)

    async def _payments_menu(self, cid, mid):
        settings = self.db.get_payment_settings()
        methods  = {
            'vodafone': '📱 فودافون كاش',
            'crypto':   '🔐 كريبتو',
            'usdt':     '💎 USDT عنوان',
        }
        kb = types.InlineKeyboardMarkup(row_width=1)
        for key, label in methods.items():
            enabled = settings.get(key, True)
            icon    = "✅" if enabled else "⛔"
            state   = "مفعّل" if enabled else "معطّل"
            kb.add(types.InlineKeyboardButton(
                f"{icon} {label} — {state}",
                callback_data=f"adm_toggle_{key}"
            ))
        binance_on = self.db.get_setting('pay_binance', '0') == '1'
        kb.add(types.InlineKeyboardButton(
            f"{'✅' if binance_on else '⛔'} 💛 Binance Pay — {'مفعّل' if binance_on else 'معطّل'}",
            callback_data="adm_binance_setup"
        ))
        bep20_on = self.db.get_setting('pay_bep20', '0') == '1'
        kb.add(types.InlineKeyboardButton(
            f"{'✅' if bep20_on else '⛔'} 💎 USDT BEP20 — {'مفعّل' if bep20_on else 'معطّل'}",
            callback_data="adm_bep20_setup"
        ))
        trc20_on = self.db.get_setting('pay_trc20', '0') == '1'
        kb.add(types.InlineKeyboardButton(
            f"{'✅' if trc20_on else '⛔'} 🟣 USDT TRC20 — {'مفعّل' if trc20_on else 'معطّل'}",
            callback_data="adm_trc20_setup"
        ))
        kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back"))
        await self.bot.edit_message_text(
            "💳 <b>إعدادات طرق الدفع</b>\nاضغط لتفعيل/تعطيل:",
            cid, mid, reply_markup=kb
        )

    async def _binance_setup_menu(self, cid, mid):
        api_key    = self.db.get_setting('binance_api_key', '').strip()
        api_secret = self.db.get_setting('binance_api_secret', '').strip()
        pay_id     = self.db.get_setting('binance_pay_id', '').strip()
        min_usdt   = self.db.get_setting('binance_min_usdt', '1.00')
        rate       = self.db.get_setting('binance_usdt_rate', '1.00')
        enabled    = self.db.get_setting('pay_binance', '0') == '1'

        def mask(s):
            if not s: return "❌ غير محدد"
            return s[:4] + "••••" + s[-4:] if len(s) > 8 else "✅ محدد"

        ready       = bool(api_key and api_secret and pay_id)
        status_icon = "✅ مفعّل" if enabled else "⛔ معطّل"
        setup_icon  = "✅ مكتمل" if ready else "⚠️ ناقص"

        text = (
            f"┌──────────────────────────────┐\n"
            f"│     💛 إعداد Binance Pay ⚡   │\n"
            f"└──────────────────────────────┘\n\n"
            f"الحالة:    <b>{status_icon}</b>\n"
            f"الإعداد:   <b>{setup_icon}</b>\n\n"
            f"🔑 API Key:     {mask(api_key)}\n"
            f"🔐 API Secret:  {mask(api_secret)}\n"
            f"🆔 Pay ID:      {'✅ ' + pay_id[:6] + '...' if pay_id else '❌ غير محدد'}\n"
            f"💵 الحد الأدنى: {min_usdt} USDT\n"
            f"💱 سعر الصرف:   1 USDT = ${rate}"
        )

        toggle_label = "⛔ تعطيل" if enabled else "✅ تفعيل"
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🔑 API Key",          callback_data="adm_set_binance_key"),
            types.InlineKeyboardButton("🔐 API Secret",       callback_data="adm_set_binance_secret"),
        )
        kb.add(
            types.InlineKeyboardButton("🆔 Pay ID",           callback_data="adm_set_binance_payid"),
            types.InlineKeyboardButton("💵 الحد الأدنى",      callback_data="adm_set_binance_min"),
        )
        kb.add(
            types.InlineKeyboardButton("💱 سعر الصرف",        callback_data="adm_set_binance_rate"),
            types.InlineKeyboardButton("🧪 اختبار",           callback_data="adm_test_binance"),
        )
        kb.add(types.InlineKeyboardButton(f"{toggle_label} Binance Pay", callback_data="adm_toggle_binance"))
        kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back"))

        try:
            await self.bot.edit_message_text(text, cid, mid, reply_markup=kb)
        except Exception:
            await self.bot.send_message(cid, text, reply_markup=kb)

    async def _bep20_setup_menu(self, cid, mid):
        address  = self.db.get_setting('bep20_address',      '').strip()
        api_key  = self.db.get_setting('bep20_api_key',      '').strip()
        min_usdt = self.db.get_setting('bep20_min_usdt',     '1.00')
        rate     = self.db.get_setting('bep20_usdt_rate',    '1.00')
        confirms = self.db.get_setting('bep20_confirmations','3')
        enabled  = self.db.get_setting('pay_bep20', '0') == '1'

        mask_addr = lambda s: (s[:6] + "••••" + s[-4:]) if s else "❌ غير محدد"
        mask_key  = lambda s: (s[:4] + "••••" + s[-4:]) if s else "❌ غير محدد"

        ready       = bool(address and api_key)
        status_icon = "✅ مفعّل" if enabled else "⛔ معطّل"
        setup_icon  = "✅ مكتمل" if ready else "⚠️ ناقص"

        text = (
            f"┌──────────────────────────────┐\n"
            f"│    💎 إعداد USDT BEP20 ⚡     │\n"
            f"└──────────────────────────────┘\n\n"
            f"الحالة:  <b>{status_icon}</b> | الإعداد: <b>{setup_icon}</b>\n\n"
            f"📋 العنوان:     <code>{mask_addr(address)}</code>\n"
            f"🔑 API Key:    {mask_key(api_key)}\n"
            f"💵 الحد الأدنى: {min_usdt} USDT\n"
            f"💱 سعر الصرف:  1 USDT = ${rate}\n"
            f"✅ تأكيدات:    {confirms}"
        )

        toggle_label = "⛔ تعطيل" if enabled else "✅ تفعيل"
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📋 عنوان المحفظة",    callback_data="adm_set_bep20_address"),
            types.InlineKeyboardButton("🔑 BSCScan API Key",  callback_data="adm_set_bep20_apikey"),
        )
        kb.add(
            types.InlineKeyboardButton("💵 الحد الأدنى",      callback_data="adm_set_bep20_min"),
            types.InlineKeyboardButton("💱 سعر الصرف",        callback_data="adm_set_bep20_rate"),
        )
        kb.add(
            types.InlineKeyboardButton("✅ التأكيدات",         callback_data="adm_set_bep20_confirms"),
            types.InlineKeyboardButton("🧪 اختبار",           callback_data="adm_test_bep20"),
        )
        kb.add(types.InlineKeyboardButton(f"{toggle_label} BEP20", callback_data="adm_toggle_bep20"))
        kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back"))

        try:
            await self.bot.edit_message_text(text, cid, mid, reply_markup=kb)
        except Exception:
            await self.bot.send_message(cid, text, reply_markup=kb)

    async def _trc20_setup_menu(self, cid, mid):
        address  = self.db.get_setting('trc20_address',      '').strip()
        api_key  = self.db.get_setting('trc20_api_key',      '').strip()
        min_usdt = self.db.get_setting('trc20_min_usdt',     '1.00')
        rate     = self.db.get_setting('trc20_usdt_rate',    '1.00')
        confirms = self.db.get_setting('trc20_confirmations','19')
        enabled  = self.db.get_setting('pay_trc20', '0') == '1'

        mask_addr = lambda s: (s[:6] + "••••" + s[-4:]) if s else "❌ غير محدد"
        mask_key  = lambda s: (s[:4] + "••••" + s[-4:]) if s else "❌ غير محدد"

        ready       = bool(address and api_key)
        status_icon = "✅ مفعّل" if enabled else "⛔ معطّل"
        setup_icon  = "✅ مكتمل" if ready else "⚠️ ناقص"

        text = (
            f"┌──────────────────────────────┐\n"
            f"│    🟣 إعداد USDT TRC20 ⚡     │\n"
            f"└──────────────────────────────┘\n\n"
            f"الحالة:  <b>{status_icon}</b> | الإعداد: <b>{setup_icon}</b>\n\n"
            f"📋 العنوان:     <code>{mask_addr(address)}</code>\n"
            f"🔑 API Key:    {mask_key(api_key)}\n"
            f"💵 الحد الأدنى: {min_usdt} USDT\n"
            f"💱 سعر الصرف:  1 USDT = ${rate}\n"
            f"✅ تأكيدات:    {confirms}"
        )

        toggle_label = "⛔ تعطيل" if enabled else "✅ تفعيل"
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📋 عنوان المحفظة",    callback_data="adm_set_trc20_address"),
            types.InlineKeyboardButton("🔑 TronGrid API Key", callback_data="adm_set_trc20_apikey"),
        )
        kb.add(
            types.InlineKeyboardButton("💵 الحد الأدنى",      callback_data="adm_set_trc20_min"),
            types.InlineKeyboardButton("💱 سعر الصرف",        callback_data="adm_set_trc20_rate"),
        )
        kb.add(
            types.InlineKeyboardButton("✅ التأكيدات",         callback_data="adm_set_trc20_confirms"),
            types.InlineKeyboardButton("🧪 اختبار",           callback_data="adm_test_trc20"),
        )
        kb.add(types.InlineKeyboardButton(f"{toggle_label} TRC20", callback_data="adm_toggle_trc20"))
        kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="adm_back"))

        try:
            await self.bot.edit_message_text(text, cid, mid, reply_markup=kb)
        except Exception:
            await self.bot.send_message(cid, text, reply_markup=kb)

    async def _list_codes(self, cid):
        codes = self.db.get_all_promo_codes()
        if not codes:
            await self.bot.send_message(cid, "📭 لا توجد أكواد.")
            return
        text = "🎟 <b>الأكواد النشطة:</b>\n\n"
        for c in codes:
            rem  = c['max_uses'] - c['used_count']
            text += f"• <code>{c['code']}</code>  ${c['amount']:.2f}  متبقي: {rem}\n"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🗑 حذف كود", callback_data="adm_delete_code"))
        await self.bot.send_message(cid, text, reply_markup=kb)

    async def handle_back(self, call):
        await self.show_panel(call.message.chat.id)

    # ══════════════════════════════════════════════
    #  اختبار الاتصالات
    # ══════════════════════════════════════════════
    async def _test_binance(self, cid, mid):
        await self.bot.edit_message_text("⏳ <b>جارٍ اختبار Binance API...</b>", cid, mid)
        api_key    = self.db.get_setting('binance_api_key', '').strip()
        api_secret = self.db.get_setting('binance_api_secret', '').strip()
        if not api_key or not api_secret:
            await self.bot.edit_message_text("❌ API Key أو Secret غير محدد!", cid, mid)
            return
        try:
            from binance_pay import BinancePay
            client = BinancePay(api_key, api_secret)
            result = await client.query_order("TEST_CONNECTIVITY_PROBE")
            err    = result.get('error', '').lower()
            if result.get('success') or any(k in err for k in ['not found', 'invalid', 'order']):
                await self.bot.edit_message_text(
                    "✅ <b>Binance API يعمل!</b>\nالمصادقة ناجحة ✔️", cid, mid
                )
            else:
                await self.bot.edit_message_text(
                    f"❌ <b>فشل!</b> {result.get('error')}", cid, mid
                )
        except Exception as e:
            await self.bot.edit_message_text(f"❌ <b>خطأ:</b> <code>{e}</code>", cid, mid)

    async def _test_bep20(self, cid, mid):
        await self.bot.edit_message_text("⏳ <b>جارٍ اختبار BSCScan API...</b>", cid, mid)
        api_key = self.db.get_setting('bep20_api_key', '').strip()
        address = self.db.get_setting('bep20_address', '').strip()
        if not api_key or not address:
            await self.bot.edit_message_text("❌ API Key أو العنوان غير محدد!", cid, mid)
            return
        try:
            import aiohttp
            url    = "https://api.bscscan.com/api"
            params = {
                "module": "account", "action": "tokenbalance",
                "contractaddress": "0x55d398326f99059ff775485246999027b3197955",
                "address": address, "apikey": api_key,
            }
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json(content_type=None)
            if data.get("status") == "1":
                balance = int(data.get("result", 0)) / (10**18)
                await self.bot.edit_message_text(
                    f"✅ <b>BSCScan API يعمل!</b>\n"
                    f"📋 العنوان: <code>{address[:10]}...{address[-6:]}</code>\n"
                    f"💵 رصيد USDT: <b>{balance:.4f}</b>",
                    cid, mid
                )
            else:
                await self.bot.edit_message_text(
                    f"❌ <b>خطأ:</b> {data.get('message', 'غير معروف')}", cid, mid
                )
        except Exception as e:
            await self.bot.edit_message_text(f"❌ <b>خطأ:</b> <code>{e}</code>", cid, mid)

    async def _test_trc20(self, cid, mid):
        await self.bot.edit_message_text("⏳ <b>جارٍ اختبار TronGrid API...</b>", cid, mid)
        api_key = self.db.get_setting('trc20_api_key', '').strip()
        address = self.db.get_setting('trc20_address', '').strip()
        if not api_key or not address:
            await self.bot.edit_message_text("❌ API Key أو العنوان غير محدد!", cid, mid)
            return
        try:
            import aiohttp
            url = "https://api.trongrid.io/v1/accounts/" + address
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    url,
                    headers={"TRON-PRO-API-KEY": api_key},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json(content_type=None)
            if data.get("success") is False:
                err = data.get("error", "خطأ")
                await self.bot.edit_message_text(f"❌ <b>TronGrid خطأ:</b> {err}", cid, mid)
            else:
                trc20_list    = data.get("data", [{}])[0].get("trc20", [])
                usdt_balance  = 0.0
                for token_dict in trc20_list:
                    for contract, bal in token_dict.items():
                        if contract == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t":
                            try:
                                usdt_balance = int(bal) / 1e6
                            except Exception:
                                pass
                await self.bot.edit_message_text(
                    f"✅ <b>TronGrid API يعمل!</b>\n"
                    f"📋 العنوان: <code>{address[:8]}...{address[-6:]}</code>\n"
                    f"💵 رصيد USDT TRC20: <b>{usdt_balance:.4f}</b>",
                    cid, mid
                )
        except Exception as e:
            await self.bot.edit_message_text(f"❌ <b>خطأ:</b> <code>{e}</code>", cid, mid)
