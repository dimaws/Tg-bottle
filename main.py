import os
import logging
from urllib.parse import urlparse
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

PORT = int(os.environ.get("PORT", "8080"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # e.g. https://app.up.railway.app/webhook
if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL is not set (e.g. https://<project>.up.railway.app/webhook)")

# Вытащим путь из полного URL, чтобы run_webhook слушал корректный url_path
parsed = urlparse(WEBHOOK_URL)
URL_PATH = parsed.path.lstrip("/") or "webhook"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Привет! Я эхо-бот. Напиши что-нибудь — я повторю.")


async def echo_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.text:
        await update.message.reply_text(update.message.text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Доступные команды: /start, /help. Просто пришли текст — я его повторю.")


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_text))
    return app


def main() -> None:
    app = build_app()
    logger.info("Starting webhook server on 0.0.0.0:%s path=/%s", PORT, URL_PATH)

    # Поднимем HTTP-сервер и сразу поставим webhook
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=URL_PATH,
        webhook_url=WEBHOOK_URL,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
