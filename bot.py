"""
╔══════════════════════════════════════════════════════════╗
║         🤖 بوت بيع String Sessions - الإصدار 5.0        ║
║      ✅ نظام حجز عشوائي - Pyrogram فقط                  ║
║      ✅ فحص الاشتراك الإجباري عند /start والرسائل       ║
║      ✅ سجل المشتريات يظهر مشتريات اليوم فقط            ║
║      ✅ مكافأة الإحالة بعد التحقق من الاشتراك           ║
╚══════════════════════════════════════════════════════════╝
"""

import asyncio
import io
import logging
import random
import string
import time
from datetime import datetime

from telebot.async_telebot import AsyncTeleBot
from telebot import types

from config import BOT_TOKEN, ADMIN_ID, ADMIN_USERNAME, API_ID, API_HASH
from database import Database
from session_manager import SessionManager, get_phone_info, mask_phone
from payment_handler import PaymentHandler
from admin_panel import AdminPanel, set_wait, get_wait, clear_wait
from scheduler import BackupScheduler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

bot         = AsyncTeleBot(BOT_TOKEN, parse_mode='HTML')
db          = Database()
session_mgr = SessionManager(db, API_ID, API_HASH)
pay_handler = PaymentHandler(db, bot)
scheduler   = BackupScheduler(db, bot)
admin_panel = AdminPanel(db, bot, session_mgr, scheduler)

_otp_store: dict[str, dict] = {}
_pending_ref_bonus: dict[int, int] = {}  # user_id -> ref_by (مؤقت لحين تأكيد الاشتراك)

def otp_save(key: str, session_string: str, cid: int, mid: int,
             info: dict = None, price: float = 0.0, new_bal: float = 0.0):
    _otp_store[key] = {
        'session_string': session_string,
        'cid':            cid,
        'mid':            mid,
        'meta': {
            'info':    info or {},
            'price':   price,
            'new_bal': new_bal,
        }
    }

def otp_get(key: str) -> dict | None:
    return _otp_store.get(key)

def otp_del(key: str):
    _otp_store.pop(key, None)

def make_otp_key() -> str:
    suffix = ''.join(random.choices(string.digits, k=3))
    return str(int(time.time()) % 100000) + suffix

def build_initial_purchase_msg(info: dict) -> str:
    full_phone = info.get('with_code', '')
    return (
        f"📞 تم شراء رقم جديد بنجاح 👇\n\n"
        f"☎ Number :-  {full_phone}\n"
        f"🔢 Code: قيد الانتظار ⏳"
    )

def build_final_purchase_msg(info: dict, otp: str) -> str:
    full_phone = info.get('with_code', '')
    return (
        f"🎉 تم #إستلام الكود الجديد بنجاح!\n\n"
        f"<b>☎ Number:</b> {full_phone}\n"
        f"<b>🔢 Code:</b> <code>{otp}</code>"
    )

def reserve_specific_session(uid: int, session_id: int) -> bool:
    with db.get_conn() as conn:
        now = datetime.now().isoformat()
        cur = conn.execute(
            """UPDATE sessions SET status='reserved', reserved_by=?, reserved_at=?
               WHERE id=? AND status='available'""",
            (uid, now, session_id)
        )
        return cur.rowcount > 0

async def _auto_otp_watcher(otp_key: str, info: dict, price: float, uid: int):
    entry = otp_get(otp_key)
    if not entry:
        return
    ss = entry['session_string']
    session_id = entry.get('session_id')
    cid = entry['cid']
    mid = entry['mid']
    phone = entry['meta']['phone']

    for attempt in range(3):
        current = await session_mgr.fetch_otp(ss)
        if current:
            if session_id:
                db.mark_session_sold(session_id)
            otp_del(otp_key)

            new_text = build_final_purchase_msg(info, otp=current)
            try:
                await bot.edit_message_text(new_text, cid, mid, reply_markup=None)
            except Exception as e:
                logger.warning(f"auto otp edit failed: {e}")
                try:
                    await bot.send_message(cid, f"✅ <b>كود التحقق وصل تلقائياً:</b>\n<code>{current}</code>")
                except Exception:
                    pass

            await notify_sales_channel(phone, uid, "رقم")
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"💰 <b>بيع رقم — الكود وصل تلقائياً!</b>\n"
                    f"👤 <code>{uid}</code>\n"
                    f"📱 <code>{phone}</code>\n"
                    f"🌍 {info.get('country', '')}\n"
                    f"🔢 الكود: <code>{current}</code>\n"
                    f"💵 <code>${price:.2f}</code>\n"
                    f"🕐 {datetime.now().strftime('%H:%M | %d-%m-%Y')}"
                )
            except Exception:
                pass
            return

    if session_id:
        db.release_session(session_id)
    db.add_balance(uid, price)
    otp_del(otp_key)
    try:
        await bot.edit_message_text("⌛ انتهت صلاحية الحجز وأُعيد رصيدك.", cid, mid)
    except Exception:
        await bot.send_message(cid, "⌛ انتهت صلاحية الحجز وأُعيد رصيدك.")

def main_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("🛒 شراء رقم"),
        types.KeyboardButton("💎 شراء جلسات"),
        types.KeyboardButton("💳 شحن رصيدك"),
        types.KeyboardButton("🎁 كود هدية"),
        types.KeyboardButton("🔗 رابط الدعوة"),
        types.KeyboardButton("📜 تعليمات البوت"),
        types.KeyboardButton("👤 حسابي"),
    )
    return kb

async def is_subscribed(user_id: int) -> bool:
    channels = db.get_force_channels()
    if not channels:
        return True
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status not in ('member', 'administrator', 'creator'):
                return False
        except Exception:
            return False
    return True

async def enforce_subscription(uid: int, cid: int, call_id=None) -> bool:
    if await is_subscribed(uid):
        return True
    channels = db.get_force_channels()
    names    = db.get_force_channel_names()
    if not channels:
        return True

    text = "⛔ <b>يجب الاشتراك في القنوات التالية أولاً:</b>\n\n"
    kb = types.InlineKeyboardMarkup(row_width=1)
    for i, ch in enumerate(channels):
        name = names[i] if i < len(names) else ch
        if ch.startswith('-100'):
            link = f"https://t.me/c/{ch[4:]}"
        elif ch.startswith('@'):
            link = f"https://t.me/{ch[1:]}"
        else:
            link = f"https://t.me/{ch}"
        text += f"{i+1}. <a href='{link}'>{name}</a>\n"
        kb.add(types.InlineKeyboardButton(f"📢 {name}", url=link))
    kb.add(types.InlineKeyboardButton("✅ تحققت من الاشتراك", callback_data="check_sub"))

    if call_id:
        await bot.answer_callback_query(call_id, "⛔ اشترك في جميع القنوات أولاً!", show_alert=True)
    await bot.send_message(cid, text, reply_markup=kb, disable_web_page_preview=True)
    return False

async def welcome_text(user) -> str:
    bal   = db.get_balance(user.id)
    count = db.get_available_count()
    name  = user.first_name or "عزيزي"
    return (
        f"┌─────────────────────────┐\n"
        f"│   🌟 أهلاً وسهلاً بك   │\n"
        f"└─────────────────────────┘\n\n"
        f"👤 <b>الاسم:</b> {name}\n"
        f"🆔 <b>معرفك:</b> <code>{user.id}</code>\n"
        f"💰 <b>رصيدك:</b> <code>${bal:.2f}</code>\n\n"
        f"📦 <b>الأرقام المتاحة:</b> {count}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔽 <i>اختر من القائمة:</i>"
    )

async def notify_sales_channel(phone: str, buyer_id: int, sale_type: str = "رقم"):
    notif_ch = db.get_setting('notify_channel', '').strip()
    if not notif_ch:
        return
    try:
        masked_phone = mask_phone(phone)
        masked_buyer = str(buyer_id)[:4] + "****"
        total_sales  = db.get_sales_count()
        now = datetime.now().strftime('%H:%M | %d-%m-%Y')
        text = (
            f"🛒 تمت عملية شراء الرقم بنجاح \n\n"
            f"🌐 المنصة: تيليجرام 📞\n"
            f"📱 الرقم: {masked_phone}\n"
            f"👤 المشتري: {masked_buyer}\n"
            f"🔢 إجمالي المبيعات: {total_sales}\n"
            f"🔑 تم وصول الكود بنجاح\n"
            f"🕐 {now}"
        )
        await bot.send_message(notif_ch, text)
    except Exception as e:
        logger.warning(f"notify error: {e}")

# ═══════════════════════════════════════════════════════════════════════
# 🛡️ /start مع تأجيل مكافأة الإحالة حتى تأكيد الاشتراك
# ═══════════════════════════════════════════════════════════════════════
@bot.message_handler(commands=['start'])
async def cmd_start(message):
    user   = message.from_user
    cid    = message.chat.id
    ref_id = None
    parts  = message.text.split()
    if len(parts) > 1:
        try:
            ref_id = int(parts[1])
            if ref_id == user.id:
                ref_id = None
        except Exception:
            pass

    is_new = db.register_user(user.id, user.username or "", user.first_name or "", ref_id)
    
    # إذا كان المستخدم جديداً وجاء عبر رابط دعوة، نؤجل المكافأة
    if is_new and ref_id:
        # نخزن المرجع مؤقتاً حتى يثبت الاشتراك
        _pending_ref_bonus[user.id] = ref_id

    # فحص الاشتراك الإجباري (للمستخدمين الجدد والقدامى)
    if not await is_subscribed(user.id):
        await enforce_subscription(user.id, cid)
        return

    # إذا كان مشتركاً بالفعل، نرحب به مباشرة
    await bot.send_message(cid, await welcome_text(user), reply_markup=main_kb())

@bot.message_handler(commands=['admin'])
async def cmd_admin(message):
    if message.from_user.id != ADMIN_ID:
        await bot.send_message(message.chat.id, "⛔ غير مصرح!")
        return
    await admin_panel.show_panel(message.chat.id)

@bot.message_handler(commands=['make_code'])
async def cmd_make_code(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await bot.send_message(message.chat.id, "⚠️ الاستخدام: /make_code [مبلغ] [استخدامات]")
        return
    try:
        amount   = float(parts[1])
        max_uses = int(parts[2]) if len(parts) > 2 else 1
        code     = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        db.create_promo_code(code, amount, max_uses)
        await bot.send_message(message.chat.id,
            f"✅ <b>الكود:</b> <code>{code}</code>\n"
            f"💰 القيمة: ${amount:.2f} | الاستخدامات: {max_uses}"
        )
    except Exception:
        await bot.send_message(message.chat.id, "❌ خطأ في الصيغة!")

@bot.message_handler(commands=['add_balance'])
async def cmd_add_balance(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 3:
        await bot.send_message(message.chat.id, "⚠️ الاستخدام: /add_balance [user_id] [amount]")
        return
    try:
        db.add_balance(int(parts[1]), float(parts[2]))
        await bot.send_message(message.chat.id, "✅ تمت الإضافة!")
    except Exception:
        await bot.send_message(message.chat.id, "❌ خطأ!")

@bot.message_handler(commands=['ban'])
async def cmd_ban(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        return
    try:
        target = int(parts[1])
        db.ban_user(target)
        await bot.send_message(message.chat.id, f"✅ تم حظر {target}")
        try:
            await bot.send_message(target, "⛔ تم حظرك.")
        except Exception:
            pass
    except Exception:
        pass

@bot.message_handler(commands=['unban'])
async def cmd_unban(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        return
    try:
        target = int(parts[1])
        db.unban_user(target)
        await bot.send_message(message.chat.id, f"✅ رُفع الحظر عن {target}")
        try:
            await bot.send_message(target, "✅ تم رفع الحظر!")
        except Exception:
            pass
    except Exception:
        pass

@bot.message_handler(content_types=['text', 'photo', 'document'])
async def universal_handler(message):
    uid  = message.from_user.id
    text = (message.text or "").strip()
    cid  = message.chat.id

    if db.is_banned(uid):
        await bot.send_message(cid, "⛔ أنت محظور من استخدام البوت.")
        return

    if not await is_subscribed(uid):
        await enforce_subscription(uid, cid)
        return

    if uid == ADMIN_ID and message.document:
        fname = (message.document.file_name or "").lower()
        if fname.endswith('.db') and get_wait(uid) == "import_db":
            clear_wait(uid)
            await _import_database(message)
            return
        if fname.endswith('.txt'):
            if await admin_panel.handle_file_upload(message):
                return

    if uid == ADMIN_ID:
        if await admin_panel.handle_message(message):
            return

    if await pay_handler.handle_incoming(message):
        return

    if get_wait(uid) == "buy_ses_custom":
        clear_wait(uid)
        try:
            n = int(text)
            if n < 1:
                raise ValueError
            await _do_buy_sessions(uid, cid, n)
        except Exception:
            await bot.send_message(cid, "❌ أدخل رقماً صحيحاً أكبر من 0!")
        return

    if text == "🔙 القائمة الرئيسية":
        await bot.send_message(cid, await welcome_text(message.from_user), reply_markup=main_kb())
    elif text == "👤 حسابي":
        await show_account(message)
    elif text == "🛒 شراء رقم":
        await show_buy_number(message)
    elif text == "💎 شراء جلسات":
        await show_buy_sessions(message)
    elif text == "💳 شحن رصيدك":
        await pay_handler.show_charge_menu(cid)
    elif text == "🎁 كود هدية":
        await bot.send_message(cid, "🎁 <b>أرسل كود الهدية:</b>")
        from payment_handler import _WAITING_PROOF
        _WAITING_PROOF[uid] = {'type': 'gift'}
    elif text == "🔗 رابط الدعوة":
        await show_referral(message)
    elif text == "📜 تعليمات البوت":
        await show_instructions(message)

async def _import_database(message):
    cid = message.chat.id
    msg = await bot.send_message(cid, "⏳ <b>جارٍ استيراد قاعدة البيانات...</b>")
    try:
        from config import DB_PATH
        import shutil, os
        backup_path = DB_PATH + ".bak"
        if os.path.exists(DB_PATH):
            shutil.copy2(DB_PATH, backup_path)
        file_info  = await bot.get_file(message.document.file_id)
        downloaded = await bot.download_file(file_info.file_path)
        with open(DB_PATH, 'wb') as f:
            f.write(downloaded)
        db.init_db()
        stats = db.get_stats()
        await bot.edit_message_text(
            f"✅ <b>تم استيراد قاعدة البيانات بنجاح!</b>\n\n"
            f"👥 المستخدمون: {stats['users']}\n"
            f"📦 الجلسات: {stats['sessions']}\n"
            f"🛒 المبيعات: {stats['sales_count']}\n"
            f"💰 الإيرادات: ${stats['total_revenue']:.2f}\n\n"
            f"<i>تم حفظ نسخة احتياطية تلقائياً</i>",
            cid, msg.message_id
        )
    except Exception as e:
        await bot.edit_message_text(f"❌ <b>فشل الاستيراد!</b>\n<code>{e}</code>", cid, msg.message_id)

async def show_account(message):
    uid    = message.from_user.id
    user   = db.get_user(uid)
    bal    = db.get_balance(uid)
    buys   = db.get_user_purchases_count(uid)
    refs   = db.get_referrals_count(uid)
    joined = (user.get('join_date', '')[:10]) if user else '---'
    text   = (
        f"┌─────────────────────────┐\n"
        f"│       👤 حسابي          │\n"
        f"└─────────────────────────┘\n\n"
        f"🆔 <b>المعرف:</b>   <code>{uid}</code>\n"
        f"📛 <b>الاسم:</b>    {message.from_user.first_name or '---'}\n"
        f"👤 <b>اليوزر:</b>   @{message.from_user.username or 'لا يوجد'}\n\n"
        f"💰 <b>الرصيد:</b>   <code>${bal:.2f}</code>\n"
        f"🛒 <b>المشتريات:</b> {buys}\n"
        f"👥 <b>الدعوات:</b>  {refs}\n"
        f"📅 <b>التسجيل:</b>  {joined}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📋 سجل مشترياتي", callback_data="my_purchases"))
    await bot.send_message(message.chat.id, text, reply_markup=kb)

async def show_buy_number(message):
    uid   = message.from_user.id
    price = float(db.get_setting('number_price', '1.00'))
    bal   = db.get_balance(uid)
    count = db.get_available_count()
    text  = (
        f"┌─────────────────────────┐\n"
        f"│       🛒 شراء رقم       │\n"
        f"└─────────────────────────┘\n\n"
        f"📦 <b>الأرقام المتاحة:</b> {count}\n"
        f"💵 <b>السعر:</b> <code>${price:.2f}</code>\n"
        f"💰 <b>رصيدك:</b> <code>${bal:.2f}</code>\n\n"
    )
    if count == 0:
        text += "❌ <b>لا توجد أرقام متاحة حالياً.</b>"
        await bot.send_message(message.chat.id, text, reply_markup=main_kb())
        return
    if bal < price:
        needed = price - bal
        text  += f"⚠️ <b>رصيدك غير كافٍ!</b>\nتحتاج: <code>${needed:.2f}</code> إضافية."
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 شحن الرصيد الآن", callback_data="goto_charge"))
        await bot.send_message(message.chat.id, text, reply_markup=kb)
        return
    text += "✅ <b>رصيدك كافٍ.</b> اضغط تأكيد."
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ تأكيد الشراء", callback_data="confirm_buy_number"),
        types.InlineKeyboardButton("❌ إلغاء",         callback_data="cancel_action"),
    )
    await bot.send_message(message.chat.id, text, reply_markup=kb)

async def show_buy_sessions(message):
    uid       = message.from_user.id
    ses_price = float(db.get_setting('session_price', '1.50'))
    bal       = db.get_balance(uid)
    count     = db.get_available_count()
    max_can   = int(bal // ses_price) if ses_price > 0 else 0
    text      = (
        f"┌─────────────────────────┐\n"
        f"│     💎 شراء جلسات       │\n"
        f"└─────────────────────────┘\n\n"
        f"📦 <b>الجلسات المتاحة:</b> {count}\n"
        f"💵 <b>سعر الجلسة:</b> <code>${ses_price:.2f}</code>\n"
        f"💰 <b>رصيدك:</b> <code>${bal:.2f}</code>\n"
        f"🔢 <b>يمكنك شراء حتى:</b> {min(max_can, count)} جلسة\n\n"
    )
    if count == 0:
        text += "❌ <b>لا توجد جلسات متاحة حالياً.</b>"
        await bot.send_message(message.chat.id, text, reply_markup=main_kb())
        return
    if bal < ses_price:
        text += "⚠️ <b>رصيدك غير كافٍ!</b>"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 شحن الرصيد الآن", callback_data="goto_charge"))
        await bot.send_message(message.chat.id, text, reply_markup=kb)
        return
    text += "كم جلسة تريد؟"
    kb   = types.InlineKeyboardMarkup(row_width=3)
    btns = []
    for n in [1, 3, 5, 10, 20, 50]:
        if n <= min(max_can, count):
            btns.append(types.InlineKeyboardButton(
                f"{n} = ${n * ses_price:.2f}", callback_data=f"buy_ses_{n}"
            ))
    if btns:
        kb.add(*btns)
    kb.add(types.InlineKeyboardButton("✏️ كمية مخصصة", callback_data="buy_ses_custom"))
    kb.add(types.InlineKeyboardButton("❌ إلغاء",        callback_data="cancel_action"))
    await bot.send_message(message.chat.id, text, reply_markup=kb)

async def show_referral(message):
    uid      = message.from_user.id
    me       = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start={uid}"
    bonus    = db.get_setting('ref_bonus', '0.50')
    refs     = db.get_referrals_count(uid)
    text     = (
        f"┌─────────────────────────┐\n"
        f"│      🔗 رابط الدعوة     │\n"
        f"└─────────────────────────┘\n\n"
        f"💰 <b>مكافأة كل دعوة:</b> ${bonus}\n"
        f"👥 <b>دعواتك:</b> {refs} شخص\n\n"
        f"🔗 رابطك:\n<code>{ref_link}</code>"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        "📤 مشاركة",
        url=f"https://t.me/share/url?url={ref_link}&text=انضم%20للبوت%20واحصل%20على%20أرقام%20تليجرام!"
    ))
    await bot.send_message(message.chat.id, text, reply_markup=kb)

async def show_instructions(message):
    await bot.send_message(
        message.chat.id,
        "┌─────────────────────────┐\n"
        "│      📜 تعليمات البوت   │\n"
        "└─────────────────────────┘\n\n"
        "<b>🛒 شراء رقم:</b>\n"
        "1️⃣ شحن الرصيد أولاً\n"
        "2️⃣ اضغط <b>شراء رقم</b> ثم <b>تأكيد</b>\n"
        "3️⃣ يظهر الرقم مع حقل الكود ← <i>قيد الانتظار ⏳</i>\n"
        "4️⃣ الكود يصل تلقائياً أو اضغط <b>📩 طلب الكود</b>\n\n"
        "<b>💎 شراء جلسات:</b>\n"
        "اضغط <b>شراء جلسات</b> واختر الكمية\n\n"
        "<b>💳 طرق الشحن:</b>\n"
        "📱 فودافون كاش | 🔐 كريبتو | 💎 USDT | 🎁 كود هدية\n\n"
        "<b>⚠️ ملاحظات:</b>\n"
        "• الأرقام مفحوصة قبل التسليم\n"
        "• لا استرجاع بعد استلام الرقم\n\n"
        f"<b>📞 الدعم:</b> @{ADMIN_USERNAME}",
        reply_markup=main_kb()
    )

@bot.callback_query_handler(func=lambda c: True)
async def callback_router(call):
    d   = call.data
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.message_id

    if d.startswith("adm_"):
        if uid != ADMIN_ID:
            await bot.answer_callback_query(call.id, "⛔ غير مصرح!")
            return
        if d == "adm_back":
            await bot.answer_callback_query(call.id)
            await admin_panel.show_panel(cid)
        else:
            await admin_panel.handle_callback(call)
        return

    if d == "check_sub":
        if await is_subscribed(uid):
            await bot.answer_callback_query(call.id, "✅ تم التحقق! أهلاً بك.")
            try:
                await bot.delete_message(cid, mid)
            except Exception:
                pass
            
            # ✅ إذا كان المستخدم مدعواً، نضيف مكافأة الإحالة الآن بعد تأكيد الاشتراك
            if uid in _pending_ref_bonus:
                ref_id = _pending_ref_bonus.pop(uid)
                bonus = float(db.get_setting('ref_bonus', '0.50'))
                db.add_balance(ref_id, bonus)
                try:
                    await bot.send_message(
                        ref_id,
                        f"🎉 <b>مبروك!</b> انضم شخص عبر رابطك وأكد اشتراكه!\n"
                        f"💰 تمت إضافة <b>${bonus:.2f}</b> لرصيدك!"
                    )
                except Exception:
                    pass

            await bot.send_message(cid, await welcome_text(call.from_user), reply_markup=main_kb())
        else:
            await bot.answer_callback_query(call.id, "❌ لم تشترك بعد! اشترك ثم اضغط مجدداً.", show_alert=True)
        return

    if not await enforce_subscription(uid, cid, call_id=call.id):
        return

    if d.startswith("pay_"):
        await pay_handler.handle_pay_callback(call)
        return
    if d.startswith("send_proof_") or d.startswith("crypto_sent_") or d.startswith("crypto_copy_") or d in ("binance_enter_amount", "binance_enter_order"):
        await pay_handler.handle_send_proof_callback(call)
        return
    if d in ("charge_back", "goto_charge"):
        await bot.answer_callback_query(call.id)
        await pay_handler.show_charge_menu(cid)
        return

    if d == "confirm_buy_number":
        await bot.answer_callback_query(call.id, "⏳ جارٍ البحث عن رقم...")
        await _process_buy_number(call)
        return

    if d.startswith("otp_"):
        key   = d[4:]
        entry = otp_get(key)
        if not entry:
            await bot.answer_callback_query(call.id, "⏰ انتهت صلاحية الزر أو وصل الكود تلقائياً.", show_alert=True)
            return

        await bot.answer_callback_query(call.id, "⏳ جارٍ جلب كود التحقق من تيليجرام...")
        ss    = entry['session_string']
        meta  = entry.get('meta', {})
        info  = meta.get('info', {})
        session_id = entry.get('session_id')
        phone = meta.get('phone', info.get('with_code', ''))
        price = meta.get('price', 0.0)
        uid = meta.get('uid', uid)

        try:
            await bot.edit_message_reply_markup(cid, mid, reply_markup=None)
        except Exception:
            pass

        otp = await session_mgr.fetch_otp(ss)
        if otp:
            if session_id:
                db.mark_session_sold(session_id)
            otp_del(key)
            new_text = build_final_purchase_msg(info, otp)
            try:
                await bot.edit_message_text(new_text, cid, mid, reply_markup=None)
            except Exception:
                await bot.send_message(cid, f"✅ <b>كود التحقق:</b>\n<code>{otp}</code>")

            await notify_sales_channel(phone, uid, "رقم")
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"💰 <b>بيع رقم — الكود وصل يدوياً!</b>\n"
                    f"👤 <code>{uid}</code>\n"
                    f"📱 <code>{phone}</code>\n"
                    f"🌍 {info.get('country', '')}\n"
                    f"🔢 الكود: <code>{otp}</code>\n"
                    f"🕐 {datetime.now().strftime('%H:%M | %d-%m-%Y')}"
                )
            except Exception:
                pass
        else:
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("🔄 إعادة المحاولة", callback_data=d),
                types.InlineKeyboardButton("❌ إلغاء الرقم",     callback_data=f"cancel_number_{key}"),
            )
            try:
                await bot.edit_message_reply_markup(cid, mid, reply_markup=kb)
            except Exception:
                pass
            await bot.answer_callback_query(call.id, "❌ الكود لم يصل بعد!\nانتظر قليلاً ثم اضغط إعادة المحاولة.", show_alert=True)
        return

    if d.startswith("buy_ses_"):
        part = d[8:]
        if part == "custom":
            await bot.answer_callback_query(call.id)
            await bot.send_message(cid, "✏️ <b>أرسل عدد الجلسات المطلوبة:</b>")
            set_wait(uid, "buy_ses_custom")
        else:
            try:
                n = int(part)
                await bot.answer_callback_query(call.id, "⏳ جارٍ المعالجة...")
                await _do_buy_sessions(uid, cid, n, edit_msg=(cid, mid))
            except Exception as e:
                logger.error(f"buy_ses error: {e}")
                await bot.answer_callback_query(call.id, "❌ حدث خطأ!", show_alert=True)
        return

    if d == "my_purchases":
        await bot.answer_callback_query(call.id)
        purchases = db.get_user_purchases_today(uid, limit=10)
        if not purchases:
            await bot.send_message(cid, "📭 لا توجد مشتريات اليوم.")
            return
        text = "📋 <b>سجل مشترياتك اليوم:</b>\n\n"
        for i, p in enumerate(purchases, 1):
            ptype = "جلسة" if p.get('type') == 'session' else "رقم"
            text += f"{i}. <code>{p['phone']}</code> — ${p['price']:.2f} — {ptype} — {p['date']}\n"
        await bot.send_message(cid, text)
        return

    if d.startswith("cancel_number_"):
        key = d[len("cancel_number_"):]
        entry = otp_get(key)
        await bot.answer_callback_query(call.id)
        if not entry:
            try:
                await bot.edit_message_reply_markup(cid, mid, reply_markup=None)
            except Exception:
                pass
            return
        meta = entry.get('meta', {})
        price = meta.get('price', 0.0)
        session_id = entry.get('session_id')
        uid = meta.get('uid', uid)
        otp_del(key)
        db.add_balance(uid, price)
        if session_id:
            db.release_session(session_id)
        try:
            await bot.edit_message_text(
                f"❌ تم إلغاء العملية وإعادة الرصيد.\n"
                f"💰 أُعيد: <code>${price:.2f}</code>",
                cid, mid, reply_markup=None
            )
        except Exception:
            await bot.send_message(cid, f"❌ تم إلغاء العملية وإعادة <code>${price:.2f}</code> لرصيدك.")
        return

    if d == "cancel_action":
        await bot.answer_callback_query(call.id, "تم الإلغاء")
        try:
            await bot.delete_message(cid, mid)
        except Exception:
            pass
        return

    await bot.answer_callback_query(call.id)

async def _process_buy_number(call):
    uid   = call.from_user.id
    cid   = call.message.chat.id
    mid   = call.message.message_id
    price = float(db.get_setting('number_price', '1.00'))

    if db.get_balance(uid) < price:
        await bot.edit_message_text("❌ <b>رصيدك غير كافٍ!</b>", cid, mid)
        return

    try:
        await bot.edit_message_text("🔍 <b>جارٍ البحث عن رقم وفحصه...</b>\n<i>يرجى الانتظار 🔄</i>", cid, mid)
    except Exception:
        pass

    available_sessions = db.get_available_sessions_list(limit=30)
    if not available_sessions:
        await bot.edit_message_text(
            f"❌ <b>لا توجد أرقام متاحة الآن!</b>\nتواصل مع الدعم: @{ADMIN_USERNAME}",
            cid, mid
        )
        return

    reserved = None
    for sd in available_sessions:
        if not await session_mgr.check_session(sd):
            db.delete_session(sd['id'])
            continue
        if reserve_specific_session(uid, sd['id']):
            reserved = sd
            break

    if not reserved:
        await bot.edit_message_text(
            f"❌ <b>لا توجد أرقام متاحة الآن!</b>\nتواصل مع الدعم: @{ADMIN_USERNAME}",
            cid, mid
        )
        return

    session_id = reserved['id']
    phone = reserved['phone']
    ss = reserved['session_string']
    info = get_phone_info(phone)

    db.deduct_balance(uid, price)
    db.record_sale(uid, phone, price, 'number', session_id=session_id)
    new_bal = db.get_balance(uid)

    first_text = build_initial_purchase_msg(info)

    key = make_otp_key()
    _otp_store[key] = {
        'session_string': ss,
        'cid':            cid,
        'mid':            0,
        'session_id':     session_id,
        'meta': {
            'info':       info,
            'price':      price,
            'new_bal':    new_bal,
            'uid':        uid,
            'phone':      phone,
        }
    }

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📩 طلب الكود يدوياً", callback_data=f"otp_{key}"),
        types.InlineKeyboardButton("❌ إلغاء الرقم",       callback_data=f"cancel_number_{key}"),
    )

    sent_mid = mid
    try:
        await bot.edit_message_text(first_text, cid, mid, reply_markup=kb)
    except Exception:
        try:
            await bot.delete_message(cid, mid)
        except Exception:
            pass
        sent = await bot.send_message(cid, first_text, reply_markup=kb)
        sent_mid = sent.message_id

    if key in _otp_store:
        _otp_store[key]['mid'] = sent_mid

    asyncio.create_task(_auto_otp_watcher(key, info, price, uid))

async def _do_buy_sessions(uid: int, cid: int, n: int, edit_msg=None):
    ses_price = float(db.get_setting('session_price', '1.50'))
    total     = n * ses_price
    bal       = db.get_balance(uid)
    available = db.get_available_count()

    async def reply(text, kb=None):
        if edit_msg:
            try:
                await bot.edit_message_text(text, edit_msg[0], edit_msg[1], reply_markup=kb)
                return
            except Exception:
                pass
        await bot.send_message(cid, text, reply_markup=kb)

    if n > available:
        await reply(f"❌ <b>الكمية المطلوبة ({n}) غير متاحة!</b>\nالمتاح: {available}")
        return
    if bal < total:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 شحن الرصيد", callback_data="goto_charge"))
        await reply(
            f"❌ <b>رصيدك غير كافٍ!</b>\n"
            f"تحتاج: <code>${total:.2f}</code> | رصيدك: <code>${bal:.2f}</code>", kb
        )
        return

    await reply(f"🔍 <b>جارٍ فحص {n} جلسة...</b>")
    sessions = await session_mgr.get_n_valid_sessions(n)
    if len(sessions) == 0:
        await bot.send_message(cid, "❌ <b>لا توجد جلسات صالحة حالياً!</b>")
        return

    if len(sessions) < n:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton(
                f"✅ شراء {len(sessions)} بـ ${len(sessions)*ses_price:.2f}",
                callback_data=f"buy_ses_{len(sessions)}"
            ),
            types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_action"),
        )
        await bot.send_message(cid, f"⚠️ <b>يوجد فقط {len(sessions)} جلسة صالحة!</b>", reply_markup=kb)
        return

    actual = len(sessions) * ses_price
    db.deduct_balance(uid, actual)
    for sd in sessions:
        db.record_sale(uid, sd['phone'], ses_price, 'session', session_id=sd['id'])
        db.mark_session_sold(sd['id'])
    new_bal = db.get_balance(uid)

    if len(sessions) == 1:
        sd   = sessions[0]
        info = get_phone_info(sd['phone'])
        await bot.send_message(
            cid,
            f"✅ <b>تم الشراء بنجاح!</b>\n\n"
            f"🌍 <b>الدولة:</b> {info['country']}\n"
            f"📱 <b>الرقم:</b> <code>{info['with_code']}</code>\n\n"
            f"🔑 <b>String Session:</b>\n<code>{sd['session_string']}</code>\n\n"
            f"💸 خُصم: <code>${ses_price:.2f}</code>\n"
            f"💳 رصيدك: <code>${new_bal:.2f}</code>"
        )
        await notify_sales_channel(sd['phone'], uid, "جلسة")
    else:
        lines = [f"{sd['phone']}|{sd['session_string']}" for sd in sessions]
        buf   = io.BytesIO("\n".join(lines).encode('utf-8'))
        fname = f"sessions_{len(sessions)}_{datetime.now().strftime('%H%M%S')}.txt"
        buf.name = fname
        await bot.send_document(
            cid, buf,
            caption=(
                f"✅ <b>تم الشراء بنجاح!</b>\n\n"
                f"🔢 عدد الجلسات: {len(sessions)}\n"
                f"💸 المدفوع: <code>${actual:.2f}</code>\n"
                f"💳 رصيدك: <code>${new_bal:.2f}</code>\n\n"
                f"<i>الصيغة: phone|session_string</i>"
            ),
            visible_file_name=fname
        )
        for sd in sessions:
            await notify_sales_channel(sd['phone'], uid, "جلسة")

    try:
        await bot.send_message(
            ADMIN_ID,
            f"💰 <b>بيع جلسات!</b>\n👤 <code>{uid}</code>\n"
            f"🔢 {len(sessions)} جلسة\n💵 <code>${actual:.2f}</code>"
        )
    except Exception:
        pass

async def release_expired_task():
    while True:
        await asyncio.sleep(60)
        try:
            released = db.release_expired_reservations(timeout_seconds=300)
            if released:
                logger.info(f"🔄 تم تحرير {len(released)} حجز منتهي الصلاحية.")
        except Exception as e:
            logger.error(f"release_expired_task error: {e}")

async def main():
    logger.info("🚀 جارٍ تشغيل البوت...")
    db.init_db()
    asyncio.create_task(scheduler.start())
    asyncio.create_task(release_expired_task())
    logger.info("✅ البوت يعمل!")
    await bot.infinity_polling(timeout=60, request_timeout=90)

if __name__ == '__main__':
    asyncio.run(main())