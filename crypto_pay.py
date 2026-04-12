"""
╔══════════════════════════════════════════════════════════════════╗
║     نظام الدفع crypto_pay.py — BEP20 + TRC20                   ║
║     v3.1 — إصلاح الرصيد المضاعف + تكامل تلقائي                  ║
╚══════════════════════════════════════════════════════════════════╝

BEP20 (USDT على BSC):
  المنصة: BSC Public RPC — مجاني 100%، بدون API Key
  Nodes:
    https://rpc.ankr.com/bsc          (أساسي — Ankr)
    https://bsc-dataseed.binance.org/  (fallback)
    https://bsc-dataseed1.binance.org/ (fallback)
  Method المستخدم (JSON-RPC POST):
    eth_getTransactionReceipt → حالة TX + logs
    eth_blockNumber           → عدد التأكيدات
  USDT Contract: 0x55d398326f99059ff775485246999027b3197955
  Decimals: 18

TRC20 (USDT على TRON):
  المنصة: TronGrid API (مجاني — من TRON الرسمي)
  Endpoint المستخدم:
    POST api.trongrid.io/wallet/gettransactioninfobyid → تفاصيل TX كاملة
    POST api.trongrid.io/wallet/gettransactionbyid    → تأكيد الـ to_address
  Header: TRON-PRO-API-KEY
  API Key: trongrid.io/dashboard (مجاني)
  USDT Contract: TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t
  Decimals: 6

هيكل الـ TXID:
  BEP20: 0x + 64 hex = 66 حرف
  TRC20: 64 hex (on-chain) أو رقم off-chain مثل: 361600985720
"""

import asyncio
import logging
import time

import aiohttp

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
#  ثوابت
# ══════════════════════════════════════════════════════════════════
API_TIMEOUT     = 20
SESSION_TIMEOUT = 600   # 10 دقائق

# BEP20 — BSC Public RPC (مجاني، بدون API Key)
BSC_RPC_NODES = [
    "https://rpc.ankr.com/bsc",
    "https://bsc-dataseed.binance.org/",   # fallback
    "https://bsc-dataseed1.binance.org/",  # fallback
]
USDT_BEP20       = "0x55d398326f99059ff775485246999027b3197955"
TRANSFER_TOPIC   = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# TRC20
TRONGRID_API     = "https://api.trongrid.io"
USDT_TRC20       = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# ══════════════════════════════════════════════════════════════════
#  جلسات المستخدمين
# ══════════════════════════════════════════════════════════════════
_SESSIONS:   dict[int, dict] = {}   # uid → {step, network, started}
_USED_TXIDS: set[str]        = set()


def _session_start(uid: int, network: str):
    _SESSIONS[uid] = {
        "step":    "waiting_txid",
        "network": network,
        "started": time.time(),
        "task":    None,
    }

def _session_get(uid: int):
    s = _SESSIONS.get(uid)
    if not s:
        return None
    if time.time() - s["started"] > SESSION_TIMEOUT:
        _session_clear(uid)
        return None
    return s

def _session_clear(uid: int):
    s = _SESSIONS.pop(uid, None)
    if s and s.get("task"):
        s["task"].cancel()


# ══════════════════════════════════════════════════════════════════
#  ① عميل BEP20 — BSC Public RPC (مجاني، بدون API Key)
# ══════════════════════════════════════════════════════════════════
class BEP20Client:
    """
    يتحقق من USDT BEP20 عبر BSC Public RPC الرسمي من Binance.
    مجاني 100% — لا يحتاج API Key.
    يستخدم JSON-RPC مباشرةً: eth_getTransactionReceipt + eth_blockNumber.
    """

    def __init__(self, wallet: str, min_confirms: int = 3):
        self.wallet       = wallet.strip().lower()
        self.min_confirms = min_confirms

    async def _rpc(self, method: str, params: list) -> dict:
        """يرسل JSON-RPC POST ويجرب الـ nodes بالترتيب عند الفشل."""
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        for node in BSC_RPC_NODES:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(
                        node,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
                    ) as r:
                        data = await r.json(content_type=None)
                logger.debug(f"[BEP20] {node} → {str(data)[:200]}")
                if "result" in data:
                    return data
            except Exception as e:
                logger.warning(f"[BEP20] {node} failed: {e}")
        return {"result": None}

    async def verify(self, txid: str) -> dict:
        txid = txid.strip().lower()

        # ─── صيغة TXID ───────────────────────────
        if not txid.startswith("0x") or len(txid) != 66:
            return {
                "success": False,
                "error":   "❌ TXID خاطئ\nيجب أن يبدأ بـ 0x ويكون 66 حرفاً"
            }

        # ─── Step 1: eth_getTransactionReceipt ────
        receipt_data = await self._rpc("eth_getTransactionReceipt", [txid])
        result = receipt_data.get("result")

        if result is None or not isinstance(result, dict):
            return {
                "success": False,
                "error":   "❌ TXID غير موجود على الشبكة\nانتظر دقيقة أو تأكد من النسخ"
            }

        # ─── Step 2: هل المعاملة ناجحة؟ ─────────
        if result.get("status") != "0x1":
            return {
                "success": False,
                "error":   "❌ المعاملة فاشلة على الشبكة"
            }

        # ─── Step 3: عدد التأكيدات ───────────────
        block_hex = result.get("blockNumber", "0x0") or "0x0"
        tx_block  = int(block_hex, 16) if block_hex != "0x0" else 0

        latest_data = await self._rpc("eth_blockNumber", [])
        try:
            latest_block = int(latest_data.get("result", "0x0"), 16)
        except Exception:
            latest_block = tx_block

        confirms = max(0, latest_block - tx_block)
        if confirms < self.min_confirms:
            return {
                "success": False,
                "error":   f"⏳ التأكيدات غير كافية ({confirms}/{self.min_confirms})\nانتظر دقيقة وأعد المحاولة"
            }

        # ─── Step 4: تحليل logs → USDT transfer ──
        logs = result.get("logs", [])
        usdt_logs = [
            lg for lg in logs
            if lg.get("address", "").lower() == USDT_BEP20
            and len(lg.get("topics", [])) >= 3
            and lg["topics"][0].lower() == TRANSFER_TOPIC
        ]

        if not usdt_logs:
            return {
                "success": False,
                "error":   "❌ لا يوجد تحويل USDT BEP20 في هذه المعاملة\nتأكد من العملة والشبكة"
            }

        lg      = usdt_logs[0]
        to_raw  = lg["topics"][2]
        to_addr = "0x" + to_raw[-40:]

        # ─── Step 5: المستلِم هو عنوانك؟ ─────────
        if to_addr.lower() != self.wallet:
            return {
                "success": False,
                "error":   "❌ المعاملة لم تُرسَل إلى العنوان الصحيح"
            }

        # ─── Step 6: المبلغ ──────────────────────
        try:
            amount = int(lg.get("data", "0x0"), 16) / (10 ** 18)
        except Exception:
            return {"success": False, "error": "❌ تعذّر قراءة المبلغ"}

        if amount <= 0:
            return {"success": False, "error": "❌ مبلغ المعاملة صفر"}

        logger.info(f"[BEP20] ✅ {amount} USDT | confirms={confirms} | txid={txid[:20]}...")
        return {
            "success":  True,
            "amount":   round(amount, 6),
            "confirms": confirms,
            "network":  "BEP20",
        }


# ══════════════════════════════════════════════════════════════════
#  ② عميل TRC20 — TronGrid API (مجاني رسمي)
# ══════════════════════════════════════════════════════════════════
class TRC20Client:
    """
    يتحقق من USDT TRC20 عبر TronGrid API الرسمي المجاني.
    
    Endpoints المستخدمة (من المستندات الرسمية):
      POST /wallet/gettransactioninfobyid
        → يجيب: fee, blockNumber, contract_address, log[]
        → log[].topics[1] = to_address (hex)
        → log[].data = amount (hex uint256)
        
      POST /wallet/gettransactionbyid  
        → يجيب: txID, raw_data (contract, to, owner)
        → للتأكد من الحالة: ret[0].contractRet == "SUCCESS"
        
    Header: TRON-PRO-API-KEY: <your_key>
    API Key: trongrid.io/dashboard → Create API Key (مجاني)
    """

    def __init__(self, api_key: str, wallet: str, min_confirms: int = 19):
        self.api_key      = api_key.strip()
        self.wallet       = wallet.strip()   # Base58 مثل TXyz...
        self.min_confirms = min_confirms     # TRON: block كل 3 ثواني → 19 = ~1 دقيقة

    def _headers(self) -> dict:
        return {
            "Content-Type":    "application/json",
            "TRON-PRO-API-KEY": self.api_key,
        }

    async def _post(self, endpoint: str, body: dict) -> dict:
        url = f"{TRONGRID_API}{endpoint}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    url,
                    json=body,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
                ) as r:
                    data = await r.json(content_type=None)
            logger.debug(f"[TRC20] {endpoint} → {str(data)[:300]}")
            return data
        except Exception as e:
            logger.error(f"[TRC20] {endpoint} error: {e}")
            return {}

    async def verify(self, txid: str) -> dict:
        txid = txid.strip()

        # ─── صيغة TXID ───────────────────────────
        # لو المستخدم كتب 0x في الأول نحذفه (on-chain hex)
        if txid.startswith("0x") or txid.startswith("0X"):
            txid = txid[2:]

        if not txid:
            return {
                "success": False,
                "error":   "❌ TXID فارغ"
            }

        # ─── Step 1: gettransactionbyid → الحالة ──
        tx_data = await self._post(
            "/wallet/gettransactionbyid",
            {"value": txid, "visible": True}
        )

        if not tx_data or "txID" not in tx_data:
            return {
                "success": False,
                "error":   "❌ TXID غير موجود\nتأكد من النسخ أو انتظر دقيقة"
            }

        # ret[0].contractRet == "SUCCESS" = ناجحة
        ret_list    = tx_data.get("ret", [{}])
        contract_ret = ret_list[0].get("contractRet", "") if ret_list else ""
        if contract_ret != "SUCCESS":
            return {
                "success": False,
                "error":   f"❌ المعاملة فاشلة على الشبكة ({contract_ret})"
            }

        # ─── Step 2: gettransactioninfobyid → logs ──
        info_data = await self._post(
            "/wallet/gettransactioninfobyid",
            {"value": txid, "visible": True}
        )

        if not info_data or "id" not in info_data:
            return {
                "success": False,
                "error":   "❌ تعذّر جلب تفاصيل المعاملة"
            }

        # ─── Step 3: تأكيد USDT contract ────────
        contract_addr = info_data.get("contract_address", "")
        if contract_addr != USDT_TRC20:
            return {
                "success": False,
                "error":   "❌ هذه المعاملة ليست USDT TRC20\nتأكد من العملة والشبكة"
            }

        # ─── Step 4: عدد التأكيدات ───────────────
        block_number = info_data.get("blockNumber", 0)
        confirms     = await self._get_confirmations(block_number)

        if confirms < self.min_confirms:
            return {
                "success": False,
                "error":   f"⏳ التأكيدات غير كافية ({confirms}/{self.min_confirms})\nانتظر دقيقة وأعد المحاولة"
            }

        # ─── Step 5: استخراج المبلغ والمستلِم من log ─
        logs = info_data.get("log", [])
        usdt_log = None
        for lg in logs:
            # Transfer event في TRON: topics[0] = event hash
            # topics[1] = from, topics[2] = to (كل منهم 32 bytes hex)
            topics = lg.get("topics", [])
            if (len(topics) >= 3
                    and topics[0].lower() == "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"):
                usdt_log = lg
                break

        if not usdt_log:
            return {
                "success": False,
                "error":   "❌ لا يوجد تحويل USDT في هذه المعاملة"
            }

        # to address في TRON: آخر 40 حرف من topics[2] → نحوله لـ Base58
        to_hex_raw = usdt_log["topics"][2]   # 64 hex
        # أول 24 حرف padding (0000...41) ثم 40 حرف العنوان
        to_hex = "41" + to_hex_raw[-40:]     # TRON hex addresses تبدأ بـ 41
        to_base58 = self._hex_to_base58(to_hex)

        if to_base58 != self.wallet:
            return {
                "success": False,
                "error":   "❌ المعاملة لم تُرسَل إلى العنوان الصحيح"
            }

        # المبلغ من data (hex uint256، USDT TRC20 = 6 decimals)
        try:
            amount = int(usdt_log.get("data", "0"), 16) / (10 ** 6)
        except Exception:
            return {"success": False, "error": "❌ تعذّر قراءة المبلغ"}

        if amount <= 0:
            return {"success": False, "error": "❌ مبلغ المعاملة صفر"}

        logger.info(f"[TRC20] ✅ {amount} USDT | confirms={confirms} | txid={txid[:20]}...")
        return {
            "success":  True,
            "amount":   round(amount, 6),
            "confirms": confirms,
            "network":  "TRC20",
        }

    async def _get_confirmations(self, block_number: int) -> int:
        """يحسب عدد التأكيدات من آخر block"""
        if not block_number:
            return 0
        try:
            data = await self._post("/wallet/getnowblock", {"visible": True})
            latest = data.get("block_header", {}).get("raw_data", {}).get("number", block_number)
            return max(0, latest - block_number)
        except Exception:
            return 0

    @staticmethod
    def _hex_to_base58(hex_str: str) -> str:
        """
        يحوّل عنوان TRON من hex (41...) إلى Base58Check.
        مثل: 41abc123... → TXyz...
        """
        import hashlib

        alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

        try:
            payload = bytes.fromhex(hex_str)
            checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
            full     = payload + checksum
            n        = int.from_bytes(full, "big")
            result   = ""
            while n:
                result = alphabet[n % 58] + result
                n //= 58
            # leading zeros
            for byte in full:
                if byte == 0:
                    result = "1" + result
                else:
                    break
            return result
        except Exception:
            return ""


# ══════════════════════════════════════════════════════════════════
#  المعالج الرئيسي — يدعم BEP20 + TRC20
# ══════════════════════════════════════════════════════════════════
class CryptoPayHandler:
    """
    يستبدل BEP20PayHandler القديم.
    يدعم BEP20 و TRC20 من نفس الواجهة.
    """

    def __init__(self, db, bot):
        self.db  = db
        self.bot = bot

    # ── اسم الشبكة → label ──────────────────────
    LABELS = {
        "bep20": "💎 USDT BEP20 (BSC)",
        "trc20": "🟣 USDT TRC20 (TRON)",
    }

    def _get_bep20_client(self):
        addr = self.db.get_setting("bep20_address",      "").strip()
        conf = int(self.db.get_setting("bep20_confirmations", "3"))
        if not addr:
            return None
        return BEP20Client(addr, conf)

    def _get_trc20_client(self):
        key  = self.db.get_setting("trc20_api_key",      "").strip()
        addr = self.db.get_setting("trc20_address",      "").strip()
        conf = int(self.db.get_setting("trc20_confirmations", "19"))
        if not key or not addr:
            return None
        return TRC20Client(key, addr, conf)

    def is_bep20_enabled(self) -> bool:
        return (
            self.db.get_setting("pay_bep20",     "0") == "1"
            and bool(self.db.get_setting("bep20_address", "").strip())
        )

    def is_trc20_enabled(self) -> bool:
        return (
            self.db.get_setting("pay_trc20",     "0") == "1"
            and bool(self.db.get_setting("trc20_api_key", "").strip())
            and bool(self.db.get_setting("trc20_address", "").strip())
        )

    def in_session(self, uid: int) -> bool:
        return _session_get(uid) is not None

    def _is_txid_used(self, txid: str) -> bool:
        t = txid.lower()
        if t in _USED_TXIDS:
            return True
        try:
            # افترض وجود دالة في db للتحقق من TXID
            if hasattr(self.db, 'is_txid_used') and self.db.is_txid_used(t):
                _USED_TXIDS.add(t)
                return True
        except Exception:
            pass
        return False

    def _mark_used(self, uid, txid, amount, credit, network):
        t = txid.lower()
        _USED_TXIDS.add(t)
        try:
            if hasattr(self.db, 'save_crypto_payment'):
                self.db.save_crypto_payment(uid, t, network, amount, credit)
        except Exception as e:
            logger.error(f"[Crypto] فشل حفظ TXID في DB: {e}")

    # ══════════════════════════════════════════════
    #  عرض صفحة الدفع لشبكة معينة
    # ══════════════════════════════════════════════
    async def show_pay_page(self, chat_id: int, user_id: int, network: str):
        from telebot import types as tg

        if network == "bep20":
            if not self.is_bep20_enabled():
                await self.bot.send_message(chat_id, "⛔ BEP20 متوقف حالياً.")
                return
            address = self.db.get_setting("bep20_address",   "")
            min_u   = float(self.db.get_setting("bep20_min_usdt",  "1.00"))
            rate    = float(self.db.get_setting("bep20_usdt_rate", "1.00"))
            net_label = "BEP20 (BSC)"
            cb_sent   = "crypto_sent_bep20"
            cb_copy   = "crypto_copy_bep20"

        elif network == "trc20":
            if not self.is_trc20_enabled():
                await self.bot.send_message(chat_id, "⛔ TRC20 متوقف حالياً.")
                return
            address = self.db.get_setting("trc20_address",   "")
            min_u   = float(self.db.get_setting("trc20_min_usdt",  "1.00"))
            rate    = float(self.db.get_setting("trc20_usdt_rate", "1.00"))
            net_label = "TRC20 (TRON)"
            cb_sent   = "crypto_sent_trc20"
            cb_copy   = "crypto_copy_trc20"
        else:
            return

        text = (
            f"قم بإرسال المبلغ إلى العنوان التالي، ثم اضغط على \"ارسلت المبلغ\":\n\n"
            f"العنوان:\n<code>{address}</code>\n\n"
            f"الشبكة: <b>{net_label}</b>\n"
            f"الحد الأدنى: <b>{min_u} USDT</b>\n"
            f"سعر الصرف: <b>1 USDT = ${rate:.2f}</b>"
        )

        kb = tg.InlineKeyboardMarkup(row_width=1)
        kb.add(
            tg.InlineKeyboardButton("✅ ارسلت المبلغ", callback_data=cb_sent),
            tg.InlineKeyboardButton("📋 نسخ العنوان",  callback_data=cb_copy),
            tg.InlineKeyboardButton("🔙 رجوع",          callback_data="charge_back"),
        )
        await self.bot.send_message(chat_id, text, reply_markup=kb)

    # ── زر "ارسلت المبلغ" ─────────────────────────
    async def prompt_txid(self, call, network: str):
        uid = call.from_user.id
        cid = call.message.chat.id
        await self.bot.answer_callback_query(call.id)
        _session_start(uid, network)

        def _fmt_time(secs: int) -> str:
            return f"{secs // 60:02d}:{secs % 60:02d}"

        msg = await self.bot.send_message(
            cid,
            f"أرسل معرف المعاملة (TxID) لـ USDT {network.upper()}.\n\n"
            f"الوقت المتبقي: <b>{_fmt_time(SESSION_TIMEOUT)}</b>"
        )

        # countdown task يحدّث الرسالة كل 5 ثواني
        async def _countdown():
            for remaining in range(SESSION_TIMEOUT - 5, 0, -5):
                await asyncio.sleep(5)
                if not _session_get(uid):
                    return   # المستخدم أرسل أو انتهت الجلسة
                try:
                    await self.bot.edit_message_text(
                        f"أرسل معرف المعاملة (TxID) لـ USDT {network.upper()}.\n\n"
                        f"الوقت المتبقي: <b>{_fmt_time(remaining)}</b>",
                        cid, msg.message_id
                    )
                except Exception:
                    pass
            # انتهى الوقت
            if _session_get(uid):
                _session_clear(uid)
                try:
                    await self.bot.edit_message_text(
                        "⌛ انتهى الوقت. اضغط «ارسلت المبلغ» مجدداً.",
                        cid, msg.message_id
                    )
                except Exception:
                    pass

        task = asyncio.create_task(_countdown())
        if uid in _SESSIONS:
            _SESSIONS[uid]["task"] = task

    async def handle_copy_address(self, call, network: str):
        setting = "bep20_address" if network == "bep20" else "trc20_address"
        label   = "BEP20" if network == "bep20" else "TRC20"
        address = self.db.get_setting(setting, "")
        await self.bot.answer_callback_query(call.id)
        await self.bot.send_message(
            call.message.chat.id,
            f"📋 <b>عنوان المحفظة USDT {label}:</b>\n\n"
            f"<code>{address}</code>\n\n"
            f"<i>اضغط لنسخه</i>"
        )

    # ══════════════════════════════════════════════
    #  نقطة الدخول من handle_incoming
    # ══════════════════════════════════════════════
    async def handle_crypto_message(self, message) -> bool:
        uid   = message.from_user.id
        state = _session_get(uid)
        if not state or state.get("step") != "waiting_txid":
            return False
        return await self._handle_txid(message, state["network"])

    # ══════════════════════════════════════════════
    #  التحقق الكامل (مع إصلاح الرصيد المضاعف)
    # ══════════════════════════════════════════════
    async def _handle_txid(self, message, network: str) -> bool:
        uid  = message.from_user.id
        cid  = message.chat.id
        txid = (message.text or "").strip()
        _session_clear(uid)

        # تحقق من التكرار
        if self._is_txid_used(txid):
            await self.bot.send_message(
                cid,
                "⛔ <b>هذا الـ TXID مستخدم مسبقاً!</b>\n"
                "كل معاملة تُقبل مرة واحدة فقط."
            )
            return True

        check_msg = await self.bot.send_message(
            cid,
            f"🔍 <b>جارٍ التحقق من المعاملة...</b>\n"
            f"<i>10-20 ثانية</i>"
        )

        # اختيار العميل
        if network == "bep20":
            client = self._get_bep20_client()
        else:
            client = self._get_trc20_client()

        if not client:
            await self.bot.edit_message_text(
                "❌ <b>النظام غير مضبوط!</b>\nتواصل مع الأدمن.",
                cid, check_msg.message_id
            )
            return True

        result = await client.verify(txid)

        if not result.get("success"):
            await self.bot.edit_message_text(
                f"❌ {result.get('error', 'خطأ غير معروف')}. تأكد من TXID وأعد المحاولة.",
                cid, check_msg.message_id
            )
            return True

        # ── شحن الرصيد (مرة واحدة فقط) ──────────────────────────
        paid  = result["amount"]
        net   = result["network"]
        confirms = result["confirms"]

        rate_key = "bep20_usdt_rate" if network == "bep20" else "trc20_usdt_rate"
        min_key  = "bep20_min_usdt"  if network == "bep20" else "trc20_min_usdt"
        rate     = float(self.db.get_setting(rate_key, "1.00"))
        min_u    = float(self.db.get_setting(min_key,  "1.00"))

        if paid < min_u:
            await self.bot.edit_message_text(
                f"⚠️ <b>المبلغ أقل من الحد الأدنى!</b>\n\n"
                f"المُرسَل: <b>{paid} USDT</b>\n"
                f"الأدنى:  <b>{min_u} USDT</b>\n\n"
                f"تواصل مع الدعم.",
                cid, check_msg.message_id
            )
            return True

        credit  = round(paid * rate, 4)

        # ══════════════════════════════════════════════
        #  إصلاح: استخدام approve_payment فقط (بدون add_balance إضافي)
        # ══════════════════════════════════════════════
        try:
            # إنشاء طلب دفع
            req_id = self.db.create_payment_request(uid, f"{network}_auto", paid)
            # الموافقة عليه - تضيف الرصيد تلقائياً
            self.db.approve_payment(req_id, credit)
        except Exception as e:
            logger.error(f"[Crypto] فشل في approve_payment: {e}")
            # خطة احتياطية: إضافة الرصيد يدوياً (مرة واحدة فقط)
            self.db.add_balance(uid, credit)

        # تسجيل TXID كمستخدم
        self._mark_used(uid, txid, paid, credit, network)

        new_bal = self.db.get_balance(uid)
        icon = self.LABELS.get(network, network.upper())

        await self.bot.edit_message_text(
            f"✅ <b>تم شحن رصيدك بنجاح!</b>\n\n"
            f"💵 المبلغ المُستلَم: <b>{paid} USDT</b>\n"
            f"💰 الرصيد المضاف:  <code>${credit:.2f}</code>\n"
            f"💳 رصيدك الجديد:   <code>${new_bal:.2f}</code>",
            cid, check_msg.message_id
        )

        # إشعار الأدمن
        from config import ADMIN_ID
        try:
            await self.bot.send_message(
                ADMIN_ID,
                f"{icon}\n\n"
                f"👤 المستخدم: <code>{uid}</code>\n"
                f"💵 USDT: <b>{paid}</b>\n"
                f"💰 رصيد مضاف: <code>${credit:.2f}</code>\n"
                f"🔗 TXID: <code>{txid}</code>"
            )
        except Exception:
            pass

        return True

    # للتوافق مع الكود القديم
    async def show_bep20_pay(self, chat_id, user_id):
        await self.show_pay_page(chat_id, user_id, "bep20")

    async def prompt_txid_bep20(self, call):
        await self.prompt_txid(call, "bep20")

    async def handle_bep20_message(self, message):
        return await self.handle_crypto_message(message)