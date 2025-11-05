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

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")

OPENAI_MODEL = os.environ.get("OPENAI_MODEL","gpt-4o-mini")


# Вытащим путь из полного URL, чтобы run_webhook слушал корректный url_path
parsed = urlparse(WEBHOOK_URL)
URL_PATH = parsed.path.lstrip("/") or "webhook"

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Привет! Я эхо-бот. Напиши что-нибудь — я повторю.")


async def echo_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.text:
        await update.message.reply_text(update.message.text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Доступные команды: /start, /help. Просто пришли текст — я его повторю.")


async def ai_generate(user_text: str) -> str:
    """
    Генерируем ответ через OpenAI Chat Completions (асинхронно).
    """
    try:
        resp = await ai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты дружелюбный и лаконичный Telegram-ассистент. "
                        "Отвечай по-русски, если пользователь пишет по-русски. "
                        "Дай ясный, по делу ответ. Если нужна структура — используй короткие списки."
                    ),
                },
                {"role": "user", "content": user_text},
            ],
            temperature=0.6,
            max_tokens=600,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.exception("OpenAI error: %s", e)
        return "Упс, не удалось получить ответ от модели. Попробуй ещё раз чуть позже."


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик обычного текста — отправляем запрос в OpenAI и отвечаем.
    """
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()

    # Небольшая защита от слишком длинных сообщений
    if len(user_text) > 5000:
        await update.message.reply_text("Сообщение слишком длинное. Пришли покороче, пожалуйста.")
        return

    # Сообщим, что «печатаем»
    try:
        await update.message.chat.send_action(action="typing")
    except Exception:
        pass

    reply = await ai_generate(user_text)
    await update.message.reply_text(reply or "Пустой ответ 🤔")


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
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
