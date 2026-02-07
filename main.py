import os
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ──────────────────────────────────────────────
# Logging – Render logları için çok önemli
# ──────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Environment & Constants
# ──────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable eksik!")

ADMIN_ID = int(os.environ.get("ADMIN_ID", "8444268448"))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "Suhuttershot")

MAX_FILES_PER_USER = 5

BASE_DIR = Path(__file__).parent
DATA_DIR    = BASE_DIR / "user_data"
PENDING_DIR = BASE_DIR / "pending"
RUNNING_DIR = BASE_DIR / "running"

for d in (DATA_DIR, PENDING_DIR, RUNNING_DIR):
    d.mkdir(exist_ok=True)

# ──────────────────────────────────────────────
# Global State
# ──────────────────────────────────────────────
user_data: Dict[int, dict] = {}  # user_id → {lang, approved, files:list, pending:list, banned, username}

# Aktif çalışan scriptler: user_id → {filename: asyncio.subprocess.Process}
running_processes: Dict[int, Dict[str, asyncio.subprocess.Process]] = {}

# ──────────────────────────────────────────────
# Dil Sistemi (kısaltılmış – sen genişletebilirsin)
# ──────────────────────────────────────────────
LANGUAGES = {
    "tr": {
        "welcome": "Merhaba {name}! VEXORP Sanal VDS'e hoş geldin 🚀\n.py yükle → onay → otomatik çalışsın",
        "rules": "Kurallar:\n• Sadece .py\n• Max {max} dosya\n• Admin onayı gerekli",
        "upload_btn": "📤 Dosya Yükle",
        "myfiles_btn": "📂 Dosyalarım",
        "file_approved": "✅ {file} onaylandı ve çalışıyor!",
        "file_rejected": "❌ {file} reddedildi.",
        "only_py": "❌ Yalnızca .py dosyası kabul edilir!",
        "max_files": f"⚠️ Maksimum {MAX_FILES_PER_USER} dosya hakkın var!",
        # ... diğer metinler
    },
    # "en": { ... }
}

def get_text(user_id: int, key: str, **kwargs) -> str:
    lang = user_data.get(user_id, {}).get("lang", "tr")
    texts = LANGUAGES.get(lang, LANGUAGES["tr"])
    return texts.get(key, key).format(**kwargs, max=MAX_FILES_PER_USER, admin=ADMIN_USERNAME)

# ──────────────────────────────────────────────
# Render Webhook Settings
# ──────────────────────────────────────────────
PORT = int(os.environ.get("PORT", "10000"))
HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{HOSTNAME}{WEBHOOK_PATH}" if HOSTNAME else f"http://localhost:{PORT}{WEBHOOK_PATH}"

# ──────────────────────────────────────────────
# Script Çalıştırma / Yönetimi
# ──────────────────────────────────────────────

async def start_user_script(user_id: int, filename: str) -> bool:
    """Kullanıcının onaylanmış .py dosyasını başlatır"""
    file_path = DATA_DIR / f"{user_id}_{filename}"
    if not file_path.is_file():
        logger.error(f"Dosya bulunamadı: {file_path}")
        return False

    log_prefix = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] USER:{user_id} FILE:{filename}"

    try:
        # python3 -u → unbuffered output (loglar anında gelsin)
        proc = await asyncio.create_subprocess_exec(
            "python3", "-u", str(file_path),
            cwd=str(DATA_DIR),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True
        )

        running_processes.setdefault(user_id, {})[filename] = proc

        # Arka planda log toplayıcı task başlat
        asyncio.create_task(_log_subprocess_output(user_id, filename, proc))

        logger.info(f"{log_prefix} STARTED – PID: {proc.pid}")
        return True

    except Exception as e:
        logger.exception(f"{log_prefix} START FAILED")
        return False


async def _log_subprocess_output(user_id: int, filename: str, proc: asyncio.subprocess.Process):
    """Script'in stdout/stderr'ını logla + opsiyonel kullanıcıya forward et"""
    prefix = f"[{filename}] "
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip()
            logger.info(f"{prefix}{decoded}")
            # İstersen kullanıcıya da gönderebilirsin:
            # await application.bot.send_message(user_id, f"[{filename}] {decoded}")
    except Exception as e:
        logger.error(f"Log task error {user_id}/{filename}: {e}")

    # stderr de topla
    stderr = await proc.stderr.read()
    if stderr:
        logger.warning(f"{prefix} STDERR: {stderr.decode('utf-8', errors='replace')}")

    # Bittiğinde temizle
    if user_id in running_processes and filename in running_processes[user_id]:
        del running_processes[user_id][filename]
    logger.info(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] USER:{user_id} FILE:{filename} EXITED (rc={proc.returncode})")


async def stop_user_script(user_id: int, filename: str) -> bool:
    if user_id not in running_processes or filename not in running_processes[user_id]:
        return False

    proc = running_processes[user_id].pop(filename)
    try:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        logger.info(f"Stopped {user_id}/{filename}")
        return True
    except Exception as e:
        logger.error(f"Stop error {user_id}/{filename}: {e}")
        return False


async def stop_all_scripts():
    """Tüm çalışan scriptleri durdur (shutdown veya admin komutu için)"""
    tasks = []
    for uid, procs in list(running_processes.items()):
        for fname, proc in list(procs.items()):
            tasks.append(stop_user_script(uid, fname))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    running_processes.clear()

# ──────────────────────────────────────────────
# Örnek Handler'lar (senin mantığına göre genişlet)
# ──────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.first_name
    await update.message.reply_text(
        get_text(uid, "welcome", name=name) + "\n\n" + get_text(uid, "rules"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(uid, "upload_btn"), callback_data="upload")],
            [InlineKeyboardButton(get_text(uid, "myfiles_btn"), callback_data="myfiles")],
        ])
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data == "upload":
        await query.edit_message_text("Lütfen .py dosyanızı gönderin...")
        # → sonraki adımda document handler yakalayacak

    elif data == "myfiles":
        # dosyaları listele + her biri için start/stop butonu vs.
        text = "Dosyalarınız:\n"
        keyboard = []
        # ... senin mantığın
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    # Admin onaylama örneği
    elif data.startswith("approve_"):
        target_uid = int(data.split("_")[1])
        filename = data.split("_")[2]  # örnek
        user_data.setdefault(target_uid, {})["approved"] = True
        if await start_user_script(target_uid, filename):
            await context.bot.send_message(target_uid, get_text(target_uid, "file_approved", file=filename))
        await query.edit_message_text(f"Onaylandı: {target_uid} – {filename}")

# ──────────────────────────────────────────────
# Dosya Yükleme Handler
# ──────────────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    doc = update.message.document

    if not doc.file_name.lower().endswith(".py"):
        await update.message.reply_text(get_text(uid, "only_py"))
        return

    total = len(user_data.get(uid, {}).get("files", [])) + len(user_data.get(uid, {}).get("pending", []))
    if total >= MAX_FILES_PER_USER:
        await update.message.reply_text(get_text(uid, "max_files"))
        return

    file_path = PENDING_DIR / f"{uid}_{doc.file_name}"
    await doc.get_file().download_to_drive(file_path)

    user_data.setdefault(uid, {}).setdefault("pending", []).append(doc.file_name)
    await update.message.reply_text(f"{doc.file_name} yüklendi → onay bekliyor")


# ──────────────────────────────────────────────
# Ana Fonksiyon – Webhook
# ──────────────────────────────────────────────

async def main():
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN yok!")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Handler'lar
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Webhook kur
    await application.bot.set_webhook(
        url=WEBHOOK_URL,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )
    logger.info(f"Webhook set → {WEBHOOK_URL}")

    # Render web sunucusu
    await application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_URL,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown sinyali alındı")
        asyncio.run(stop_all_scripts())
    except Exception as e:
        logger.critical(f"Critical error: {e}", exc_info=True)
