"""
╔══════════════════════════════════════════════════════════╗
║         جدولة النسخ الاحتياطي - scheduler.py            ║
╚══════════════════════════════════════════════════════════╝
"""

import asyncio
import io
import logging
from datetime import datetime
from config import BACKUP_INTERVAL_HOURS, ADMIN_ID

logger = logging.getLogger(__name__)


class BackupScheduler:
    def __init__(self, db, bot):
        self.db       = db
        self.bot      = bot
        self.interval = BACKUP_INTERVAL_HOURS * 3600

    async def start(self):
        logger.info(f"⏰ النسخ الاحتياطي كل {BACKUP_INTERVAL_HOURS}h")
        while True:
            await asyncio.sleep(self.interval)
            await self.send_backup()

    async def send_backup(self):
        try:
            stats   = self.db.get_stats()
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
            caption = (
                f"💾 <b>نسخة احتياطية تلقائية</b>\n\n"
                f"🕐 {now_str}\n"
                f"👥 المستخدمون: {stats['users']}\n"
                f"📦 الجلسات المتاحة: {stats['sessions']}\n"
                f"💰 الإيرادات: ${stats['total_revenue']:.2f}"
            )
            with open(self.db.db_path, 'rb') as f:
                await self.bot.send_document(
                    ADMIN_ID, f,
                    caption=caption,
                    visible_file_name=f"backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db"
                )
            await self.send_sessions_txt("📄 جلسات النسخة الاحتياطية")
        except Exception as e:
            logger.error(f"backup error: {e}")

    async def send_sessions_txt(self, caption_prefix="📄 ملف الجلسات"):
        try:
            sessions = self.db.get_all_sessions_list(limit=5000, status='available')
            if not sessions:
                await self.bot.send_message(ADMIN_ID, "📭 لا توجد جلسات للتصدير.")
                return
            lines   = [f"{s['phone']}|{s['session_string']}" for s in sessions]
            content = "\n".join(lines).encode('utf-8')
            buf     = io.BytesIO(content)
            buf.name = f"sessions_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
            await self.bot.send_document(
                ADMIN_ID, buf,
                caption=(
                    f"{caption_prefix}\n"
                    f"📊 عدد الجلسات: {len(sessions)}\n"
                    f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"<i>الصيغة: phone|session_string</i>"
                ),
                visible_file_name=buf.name
            )
        except Exception as e:
            logger.error(f"send_sessions_txt error: {e}")
