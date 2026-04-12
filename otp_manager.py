"""
╔══════════════════════════════════════════════════════════╗
║        مدير OTP - جلسة مفتوحة + مراقبة حية             ║
╚══════════════════════════════════════════════════════════╝
الفكرة:
  بعد شراء الرقم — نفتح الجلسة مرة واحدة ونظل مراقبين
  رسائل 42777 / 777000 بشكل دوري حتى يصل كود جديد أو
  ينتهي الوقت المحدد (OTP_TIMEOUT).
"""

import asyncio
import logging
import re
from datetime import datetime, timezone

from config import API_ID, API_HASH, OTP_TIMEOUT

logger = logging.getLogger(__name__)

# أنماط استخراج OTP (5 أرقام فقط)
OTP_PATTERNS = [
    r'(?<!\d)(\d{5})(?!\d)',
    r'code[:\s]+(\d{5})',
    r'код[:\s]+(\d{5})',
    r'(?:login|confirmation)[^:]*:\s*(\d{5})',
]

# مصادر رسائل OTP
OTP_SENDERS = [777000, 42777]


def extract_otp(text: str) -> str | None:
    if not text:
        return None
    for p in OTP_PATTERNS:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


class OTPWatcher:
    """
    يفتح جلسة تيليجرام مرة واحدة ويظل مراقباً رسائل OTP
    حتى يصل كود جديد أو ينتهي الوقت.
    """

    def __init__(self, session_string: str, session_type: str):
        self.session_string = session_string
        self.session_type   = session_type
        self._client        = None
        self._started       = False

    # ── بناء العميل ──────────────────────────────────────
    def _build_pyrogram(self):
        from pyrogram import Client
        return Client(
            name="otp_watcher",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=self.session_string,
            in_memory=True,
            no_updates=True,
        )

    def _build_telethon(self):
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        return TelegramClient(
            StringSession(self.session_string),
            API_ID,
            API_HASH,
        )

    # ── تشغيل وإيقاف ─────────────────────────────────────
    async def start(self):
        try:
            if self.session_type == 'pyrogram':
                self._client = self._build_pyrogram()
                await self._client.start()
            else:
                self._client = self._build_telethon()
                await self._client.connect()
                if not await self._client.is_user_authorized():
                    raise Exception("Telethon session not authorized")
            self._started = True
            logger.info(f"OTPWatcher started [{self.session_type}]")
        except Exception as e:
            logger.error(f"OTPWatcher start error: {e}")
            self._started = False
            raise

    async def stop(self):
        if not self._client:
            return
        try:
            if self.session_type == 'pyrogram':
                await self._client.stop()
            else:
                await self._client.disconnect()
        except Exception as e:
            logger.warning(f"OTPWatcher stop error: {e}")
        finally:
            self._client  = None
            self._started = False
            logger.info("OTPWatcher stopped")

    # ── قراءة آخر OTP الآن ────────────────────────────────
    async def fetch_latest_otp(self) -> tuple[str | None, datetime | None]:
        """
        يعيد (otp_code, message_date) من آخر رسالة OTP
        أو (None, None) إذا لم يجد.
        """
        if not self._started or not self._client:
            return None, None
        try:
            if self.session_type == 'pyrogram':
                return await self._fetch_pyrogram()
            return await self._fetch_telethon()
        except Exception as e:
            logger.error(f"fetch_latest_otp error: {e}")
            return None, None

    async def _fetch_pyrogram(self) -> tuple[str | None, datetime | None]:
        for sender_id in OTP_SENDERS:
            try:
                async for msg in self._client.get_chat_history(sender_id, limit=5):
                    code = extract_otp(msg.text or "")
                    if code:
                        msg_date = msg.date
                        if msg_date and msg_date.tzinfo is None:
                            msg_date = msg_date.replace(tzinfo=timezone.utc)
                        return code, msg_date
            except Exception:
                continue
        return None, None

    async def _fetch_telethon(self) -> tuple[str | None, datetime | None]:
        for sender_id in OTP_SENDERS:
            try:
                msgs = await self._client.get_messages(sender_id, limit=5)
                for msg in msgs:
                    code = extract_otp(getattr(msg, 'text', '') or "")
                    if code:
                        msg_date = getattr(msg, 'date', None)
                        if msg_date and msg_date.tzinfo is None:
                            msg_date = msg_date.replace(tzinfo=timezone.utc)
                        return code, msg_date
            except Exception:
                continue
        return None, None

    # ── المراقبة الحية ────────────────────────────────────
    async def watch(
        self,
        on_code: callable,          # async (code: str) → None
        on_timeout: callable = None, # async () → None
        poll_interval: int = 5,
        timeout: int = OTP_TIMEOUT,
    ):
        """
        يراقب رسائل OTP بجلسة مفتوحة.
        - يتجاهل الرسائل الأقدم من وقت البدء
        - يستدعي on_code(code) عند وصول كود جديد
        - يستدعي on_timeout() إذا انتهى الوقت
        """
        start_time = datetime.now(timezone.utc)
        elapsed    = 0

        # نحفظ آخر كود موجود الآن كنقطة بداية
        baseline_code, _ = await self.fetch_latest_otp()
        logger.info(f"OTP baseline: {baseline_code}")

        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            code, msg_date = await self.fetch_latest_otp()
            if not code:
                continue

            # تجاهل الأكواد القديمة (قبل بدء المراقبة)
            if msg_date and msg_date < start_time:
                continue

            # كود جديد مختلف عن الـ baseline
            if code and code != baseline_code:
                logger.info(f"OTP received: {code}")
                await on_code(code)
                return

        # انتهى الوقت
        logger.info("OTP watch timeout")
        if on_timeout:
            await on_timeout()


# ══════════════════════════════════════════════════════════
#  مخزن المراقبين النشطين
#  key = otp_key (str)  →  value = dict
# ══════════════════════════════════════════════════════════
_active_watchers: dict[str, dict] = {}


def store_watcher(key: str, data: dict):
    _active_watchers[key] = data


def get_watcher(key: str) -> dict | None:
    return _active_watchers.get(key)


def remove_watcher(key: str):
    _active_watchers.pop(key, None)


def get_user_watcher_key(uid: int) -> str | None:
    """يجد مفتاح المراقب الخاص بمستخدم معين"""
    for key, data in _active_watchers.items():
        if data.get('uid') == uid:
            return key
    return None
