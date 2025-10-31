import os
import io
import logging
from typing import List
from openai import OpenAI
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from pydub import AudioSegment

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ALLOWED_USER_IDS = os.getenv("ALLOWED_USER_IDS", "")
PORT = int(os.getenv("PORT", "8080"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # пример: https://yourapp.up.railway.app

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("Не заданы TELEGRAM_BOT_TOKEN или OPENAI_API_KEY")
if not WEBHOOK_URL:
    raise RuntimeError("Не задан WEBHOOK_URL (например, https://yourapp.up.railway.app)")

client = OpenAI(api_key=OPENAI_API_KEY)

# --- Разрешённые пользователи ---
ALLOWED: List[int] = []
for part in [x.strip() for x in ALLOWED_USER_IDS.split(",") if x.strip()]:
    try:
        ALLOWED.append(int(part))
    except ValueError:
        logging.warning(f"Пропущен некорректный user_id: {part}")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Проверка доступа ---
def user_allowed(update: Update) -> bool:
    if not ALLOWED:
        return True
    uid = update.effective_user.id if update.effective_user else None
    return uid in ALLOWED

async def deny_if_needed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if user_allowed(update):
        return False
    await update.effective_chat.send_message("⛔️ Доступ запрещён.")
    return True

async def send_typing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception:
        pass

# --- Команды ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_needed(update, context):
        return
    await update.message.reply_text(
        "Привет! Я бот-интерфейс к OpenAI.\n\n"
        "• Текст → текстовый ответ.\n"
        "• Голос → голосовой ответ.\n"
        "• Команда /image <описание> — сгенерирую изображение."
    )

async def image_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_needed(update, context):
        return
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Использование: /image <описание>")
        return

    await send_typing(update, context)
    try:
        resp = client.images.generate(model="gpt-image-1", prompt=prompt, size="1024x1024")
        import base64
        img_bytes = io.BytesIO(base64.b64decode(resp.data[0].b64_json))
        img_bytes.seek(0)
        await update.message.reply_photo(photo=img_bytes, caption=f"Промпт: {prompt}")
    except Exception as e:
        logger.exception("/image failed")
        await update.message.reply_text(f"Не удалось сгенерировать изображение: {e}")

# --- Текст ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_needed(update, context):
        return
    user_text = update.message.text
    await send_typing(update, context)
    try:
        chat_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Reply in the user's language."},
                {"role": "user", "content": user_text},
            ],
            temperature=0.6,
        )
        answer = chat_resp.choices[0].message.content
        await update.message.reply_text(answer)
    except Exception as e:
        logger.exception("text handler failed")
        await update.message.reply_text(f"Ошибка ответа: {e}")

# --- Голос ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_needed(update, context):
        return
    voice = update.message.voice or update.message.audio
    if not voice:
        await update.message.reply_text("Не нашёл голосовой файл.")
        return

    tg_file = await context.bot.get_file(voice.file_id)
    ogg_buf = io.BytesIO()
    await tg_file.download_to_memory(out=ogg_buf)
    ogg_buf.seek(0)

    await send_typing(update, context)
    try:
        tr = client.audio.transcriptions.create(
            model="whisper-1",
            file=("audio.ogg", ogg_buf, "audio/ogg"),
            response_format="text",
        )
        text = tr
    except Exception as e:
        logger.exception("Transcription failed")
        await update.message.reply_text(f"Не удалось распознать аудио: {e}")
        return

    try:
        chat_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Reply concisely in the language of the user's message."},
                {"role": "user", "content": text},
            ],
            temperature=0.6,
        )
        answer_text = chat_resp.choices[0].message.content
    except Exception as e:
        logger.exception("Chat failed")
        await update.message.reply_text(f"Ошибка генерации ответа: {e}")
        return

    try:
        tts = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            format="mp3",
            input=answer_text,
        )
        mp3_bytes = io.BytesIO(tts.read())
        mp3_bytes.seek(0)
        mp3_audio = AudioSegment.from_file(mp3_bytes, format="mp3")
        ogg_out = io.BytesIO()
        mp3_audio.export(ogg_out, format="ogg", codec="libopus", parameters=["-ac", "1", "-b:a", "32k"])
        ogg_out.seek(0)
        await update.message.reply_voice(voice=ogg_out, caption=text[:200] + ("…" if len(text) > 200 else ""))
    except Exception as e:
        logger.exception("TTS or send failed")
        await update.message.reply_text(answer_text)

# --- Ошибки ---
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Exception while handling update: %s", context.error)

# --- Запуск ---
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("image", image_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler((filters.VOICE | filters.AUDIO) & ~filters.COMMAND, handle_voice))

    webhook_path = f"/{TELEGRAM_BOT_TOKEN}"
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}{webhook_path}",
    )

if __name__ == "__main__":
    main()
