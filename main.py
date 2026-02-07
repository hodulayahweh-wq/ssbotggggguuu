# bot.py veya main.py (dosya adın neyse)

import os
import asyncio
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Logging – Render logları için
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# AYARLAR – Environment Variables'tan al
# ──────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable eksik!")

ADMIN_ID = int(os.environ.get("ADMIN_ID", "8444268448"))

PORT = int(os.environ.get("PORT", "10000"))
HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "localhost")
WEBHOOK_PATH = f"/webhook_{BOT_TOKEN[-10:]}"
WEBHOOK_URL = f"https://{HOSTNAME}{WEBHOOK_PATH}"

# Klasörler
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "user_files"
for folder in [DATA_DIR]:
    folder.mkdir(exist_ok=True)

# Basit kullanıcı verisi (kalıcı yapmak istersen json ekle)
user_data = {}  # user_id: {'approved': bool, 'files': list, ...}

# ──────────────────────────────────────────────
# Basit handler örnekleri (sen kendi kodunu buraya entegre et)
# ──────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"Merhaba {user.first_name}! VEXORP Sanal VDS'e hoş geldin 🚀\n"
        "Python scriptlerini yükle → admin onaylasın → otomatik çalışsın"
    )


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Echo: {update.message.text}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    if not document.file_name.lower().endswith('.py'):
        await update.message.reply_text("Sadece .py dosyası yükleyebilirsin!")
        return

    file = await document.get_file()
    file_path = DATA_DIR / f"{update.effective_user.id}_{document.file_name}"
    await file.download_to_drive(file_path)

    await update.message.reply_text(
        f"Dosya yüklendi: {document.file_name}\nAdmin onayı bekleniyor..."
    )


# ──────────────────────────────────────────────
# Ana fonksiyon – Webhook ile başlat
# ──────────────────────────────────────────────

async def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    # Handler'ları ekle
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Webhook kur
    await application.bot.set_webhook(
        url=WEBHOOK_URL,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )
    logger.info(f"Webhook ayarlandı: {WEBHOOK_URL}")

    # Render'ın beklediği web sunucusunu başlat
    await application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_URL,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot durduruldu (KeyboardInterrupt)")
    except Exception as e:
        logger.exception("Kritik hata:", exc_info=e)ame__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown sinyali alındı")
        asyncio.run(stop_all_scripts())
    except Exception as e:
        logger.critical(f"Critical error: {e}", exc_info=True)
