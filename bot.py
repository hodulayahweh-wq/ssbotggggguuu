import os
import ast
import sys
import subprocess
import tempfile
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Güvenlik
BANNED_IMPORTS = {
    "os", "sys", "subprocess", "socket",
    "shutil", "threading", "multiprocessing",
    "asyncio", "pathlib"
}

logging.basicConfig(level=logging.INFO)

def is_safe(code: str):
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for n in node.names:
                    name = n.name.split(".")[0]
                    if name in BANNED_IMPORTS:
                        return False, f"❌ Yasaklı import: {name}"
        return True, "OK"
    except Exception as e:
        return False, str(e)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📂 Bana bir .py dosyası gönder\n"
        "• Paketler otomatik kurulur\n"
        "• 10 saniye timeout\n"
        "• Güvensiz kodlar engellenir"
    )

async def handle_py(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.endswith(".py"):
        await update.message.reply_text("❌ Sadece .py dosyası")
        return

    file = await doc.get_file()
    code = (await file.download_as_bytearray()).decode("utf-8", errors="ignore")

    ok, msg = is_safe(code)
    if not ok:
        await update.message.reply_text(msg)
        return

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "main.py")
        with open(path, "w") as f:
            f.write(code)

        await update.message.reply_text("▶️ Çalıştırılıyor...")

        try:
            r = subprocess.run(
                [sys.executable, path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            out = (r.stdout + r.stderr).strip()[:4000] or "Çıktı yok"
            await update.message.reply_text(f"```\n{out}\n```", parse_mode="Markdown")

        except subprocess.TimeoutExpired:
            await update.message.reply_text("⏱️ Süre aşıldı (10 sn)")

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable yok")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_py))

    app.run_polling(
        close_loop=False,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == "__main__":
    main()
