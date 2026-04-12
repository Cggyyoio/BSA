"""
╔══════════════════════════════════════════════════════════╗
║    مدير الجلسات - Pyrogram فقط - session_manager        ║
║    ✅ إصلاح جلب OTP + اختيار عشوائي وسريع للجلسات       ║
╚══════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import re
import random
import phonenumbers

logger = logging.getLogger(__name__)

# ─── خريطة الدول ─────────────────────────────────────────
COUNTRY_AR = {
    "EG": "مصر 🇪🇬",      "SA": "السعودية 🇸🇦", "AE": "الإمارات 🇦🇪",
    "KW": "الكويت 🇰🇼",    "QA": "قطر 🇶🇦",      "BH": "البحرين 🇧🇭",
    "OM": "عُمان 🇴🇲",     "JO": "الأردن 🇯🇴",    "IQ": "العراق 🇮🇶",
    "SY": "سوريا 🇸🇾",     "LB": "لبنان 🇱🇧",     "MA": "المغرب 🇲🇦",
    "TN": "تونس 🇹🇳",      "DZ": "الجزائر 🇩🇿",   "LY": "ليبيا 🇱🇾",
    "SD": "السودان 🇸🇩",   "YE": "اليمن 🇾🇪",     "TR": "تركيا 🇹🇷",
    "RU": "روسيا 🇷🇺",     "US": "أمريكا 🇺🇸",    "GB": "بريطانيا 🇬🇧",
    "DE": "ألمانيا 🇩🇪",   "FR": "فرنسا 🇫🇷",     "IN": "الهند 🇮🇳",
    "PK": "باكستان 🇵🇰",   "ID": "إندونيسيا 🇮🇩", "NG": "نيجيريا 🇳🇬",
    "UA": "أوكرانيا 🇺🇦",  "KZ": "كازاخستان 🇰🇿", "UZ": "أوزبكستان 🇺🇿",
    "GH": "غانا 🇬🇭",      "ET": "إثيوبيا 🇪🇹",   "PH": "الفلبين 🇵🇭",
    "BR": "البرازيل 🇧🇷",  "MX": "المكسيك 🇲🇽",   "CN": "الصين 🇨🇳",
}


def get_phone_info(phone: str) -> dict:
    """استخراج معلومات رقم الهاتف"""
    try:
        if not phone.startswith('+'):
            phone = '+' + phone
        parsed      = phonenumbers.parse(phone)
        cc          = phonenumbers.region_code_for_number(parsed)
        dial        = f"+{parsed.country_code}"
        country     = COUNTRY_AR.get(cc, f"({cc}) 🌍")
        national    = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
        without_cc  = re.sub(r'\D', '', national)
        return {
            'country':      country,
            'dial_code':    dial,
            'with_code':    phone,
            'without_code': without_cc,
        }
    except Exception:
        return {
            'country':      '🌍 غير معروف',
            'dial_code':    '',
            'with_code':    phone,
            'without_code': phone,
        }


def mask_phone(phone: str) -> str:
    """إخفاء جزء من الرقم للإشعارات"""
    p = phone.lstrip('+')
    if len(p) >= 8:
        return phone[:4] + '***' + phone[-3:]
    return phone[:3] + '***'


# ══════════════════════════════════════════════════════════
#  مدير الجلسات - Pyrogram فقط
# ══════════════════════════════════════════════════════════
class SessionManager:
    def __init__(self, db, api_id: int, api_hash: str):
        self.db       = db
        self.api_id   = api_id
        self.api_hash = api_hash

    # ─── بناء عميل Pyrogram ───────────────────────
    def _pyrogram_client(self, session_string: str):
        from pyrogram import Client
        return Client(
            name="sess",
            api_id=self.api_id,
            api_hash=self.api_hash,
            session_string=session_string,
            in_memory=True,
            # no_updates=False افتراضيًا — يسمح باستقبال الرسائل
        )

    # ══════════════════════════════════════════════
    #  إضافة جلسة (Pyrogram فقط)
    # ══════════════════════════════════════════════
    async def add_session(self, session_string: str) -> dict:
        try:
            from pyrogram.errors import (
                AuthKeyUnregistered, UserDeactivated, UserDeactivatedBan,
                SessionExpired, SessionRevoked, FloodWait
            )
            client = self._pyrogram_client(session_string)
            await client.start()
            try:
                me    = await client.get_me()
                phone = me.phone_number or str(me.id)
                if not phone.startswith('+'):
                    phone = '+' + phone
            finally:
                await client.stop()

            saved = self.db.add_session(session_string, phone, 'pyrogram')
            if not saved:
                return {'success': False, 'error': 'الجلسة موجودة مسبقاً!'}
            return {'success': True, 'phone': phone, 'type': 'pyrogram'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ══════════════════════════════════════════════
    #  فحص جلسة (Pyrogram فقط)
    # ══════════════════════════════════════════════
    async def check_session(self, sd: dict) -> bool:
        try:
            from pyrogram.errors import (
                AuthKeyUnregistered, UserDeactivated, UserDeactivatedBan,
                SessionExpired, SessionRevoked, FloodWait
            )
            client = self._pyrogram_client(sd['session_string'])
            await client.start()
            await client.get_me()
            await client.stop()
            return True
        except Exception:
            return False

    # ══════════════════════════════════════════════
    #  جلب جلسة صالحة (اختيار عشوائي وسريع)
    # ══════════════════════════════════════════════
    async def get_valid_session(self) -> dict | None:
        """
        يختار جلسة عشوائية من الجلسات المتاحة ويفحصها.
        عدد المحاولات = 5، مع إزالة الفاسدة فوراً.
        """
        max_attempts = 5
        for _ in range(max_attempts):
            available = self.db.get_available_sessions_list(limit=30)
            if not available:
                return None
            sd = random.choice(available)
            if await self.check_session(sd):
                return sd
            else:
                logger.warning(f"حذف جلسة فاسدة (عشوائية): {sd['phone']}")
                self.db.delete_session(sd['id'])
            await asyncio.sleep(0.2)
        return None

    async def get_n_valid_sessions(self, n: int) -> list:
        valid = []
        seen = set()
        for _ in range(n * 4):
            if len(valid) >= n:
                break
            available = self.db.get_available_sessions_list(limit=50)
            if not available:
                break
            available = [s for s in available if s['id'] not in seen]
            if not available:
                break
            sd = random.choice(available)
            seen.add(sd['id'])
            if await self.check_session(sd):
                valid.append(sd)
            else:
                logger.warning(f"حذف جلسة فاسدة: {sd['phone']}")
                self.db.delete_session(sd['id'])
            await asyncio.sleep(0.2)
        return valid

    # ══════════════════════════════════════════════════════
    #  جلب OTP باستخدام Pyrogram فقط
    # ══════════════════════════════════════════════════════
    async def fetch_otp(self, session_string: str, session_type: str = None) -> str | None:
        """
        يراقب الرسائل الجديدة من 42777 و 777000 لمدة 40 ثانية.
        عند وصول كود يعيده مباشرة.
        """
        logger.info(f"🔍 بدء جلب OTP - Pyrogram")
        return await self._fetch_otp_pyrogram_events(session_string)

    async def _fetch_otp_pyrogram_events(self, ss: str) -> str | None:
        try:
            from pyrogram import filters
            client = self._pyrogram_client(ss)
            await client.start()

            logger.info("✅ Pyrogram متصل، في انتظار رسالة الكود (40 ثانية)...")
            code = None
            got_code = asyncio.Event()

            @client.on_message(filters.user([42777, 777000]))
            async def handler(_, msg):
                nonlocal code
                text = msg.text or ""
                logger.info(f"📨 Pyrogram: استقبلت رسالة من {msg.from_user.id}: {text[:100]}")
                extracted = self._extract_code(text)
                if extracted:
                    code = extracted
                    logger.info(f"🎯 Pyrogram: تم استخراج الكود: {code}")
                    got_code.set()

            try:
                await asyncio.wait_for(got_code.wait(), timeout=40)
            except asyncio.TimeoutError:
                logger.info("⏰ Pyrogram: انتهت المهلة (40 ثانية) دون استقبال كود")

            await client.stop()
            return code

        except Exception as e:
            logger.error(f"❌ Pyrogram events error: {e}")
            return None

    @staticmethod
    def _extract_code(text: str) -> str | None:
        """
        استخراج كود OTP من النص.
        - يبحث في السطر الأول عن أي 5 أرقام متتالية.
        - إذا لم يجد، يبحث في النص بالكامل عن 5 أرقام.
        """
        if not text:
            return None

        text = text.strip()
        lines = text.splitlines()
        if not lines:
            return None

        first_line = ""
        for line in lines:
            line = line.strip()
            if line:
                first_line = line
                break

        logger.info(f"🔎 تحليل السطر الأول: {first_line[:100]}")

        # 1) البحث عن 5 أرقام متتالية غير محاطة بأرقام أخرى
        pattern = r'(?<!\d)\d{5}(?!\d)'
        match = re.search(pattern, first_line)
        if match:
            code = match.group(0)
            logger.info(f"✅ تم استخراج 5 أرقام من السطر الأول: {code}")
            return code

        # 2) إذا لم نجد في السطر الأول، نبحث في النص بالكامل
        logger.info("⚠️ لم يتم العثور على 5 أرقام في السطر الأول، البحث في النص بالكامل...")
        match = re.search(pattern, text)
        if match:
            code = match.group(0)
            logger.info(f"✅ تم استخراج 5 أرقام من النص الكامل: {code}")
            return code

        # 3) بحث فضفاض عن أي 5 أرقام متجاورة
        match = re.search(r'\d{5}', text)
        if match:
            code = match.group(0)
            logger.info(f"✅ تم استخراج 5 أرقام (بحث فضفاض): {code}")
            return code

        logger.warning("❌ لم يتم العثور على أي 5 أرقام في الرسالة")
        return None

    # ══════════════════════════════════════════════════════
    #  مراقب OTP التلقائي (يُستخدم في _auto_otp_watcher)
    # ══════════════════════════════════════════════════════
    async def watch_otp(
        self,
        session_string: str,
        session_type: str,
        on_otp_received,          # دالة callback(otp: str)
        timeout: int = 120,
        poll_interval: int = 5,
    ) -> None:
        """
        يراقب رسائل 42777 / 777000 كل poll_interval ثانية لمدة timeout.
        عند وصول كود جديد يستدعي on_otp_received(otp).
        """
        last_seen = None
        elapsed   = 0

        last_seen = await self.fetch_otp(session_string, session_type)

        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            current = await self.fetch_otp(session_string, session_type)
            if current and current != last_seen:
                await on_otp_received(current)
                return

    # ══════════════════════════════════════════════
    #  فحص جماعي
    # ══════════════════════════════════════════════
    async def bulk_check(self) -> dict:
        sessions = self.db.get_all_sessions_list(limit=100)
        valid, invalid, deleted = 0, 0, []
        for sd in sessions:
            ok = await self.check_session(sd)
            if ok:
                valid += 1
            else:
                invalid += 1
                deleted.append(sd['phone'])
                self.db.delete_session(sd['id'])
            await asyncio.sleep(0.5)
        return {
            'total': len(sessions), 'valid': valid,
            'invalid': invalid, 'deleted': deleted
        }