#!/usr/bin/env python3
"""
Hermes Telegram Bot — connected to Claude Haiku
"""

import os
import logging
import anthropic
from pathlib import Path

# Load .env file if present
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN environment variable is not set")
MODEL = "claude-haiku-4-5-20251001"

client = anthropic.Anthropic()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

conversations = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversations[update.effective_user.id] = []
    await update.message.reply_text("שלום! אני Hermes, מחובר ל-Claude. איך אפשר לעזור?")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversations[update.effective_user.id] = []
    await update.message.reply_text("השיחה אופסה.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    if user_id not in conversations:
        conversations[user_id] = []

    conversations[user_id].append({"role": "user", "content": user_text})

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system="אתה עוזר אישי בשם Hermes. ענה בעברית.",
            messages=conversations[user_id],
        )
        reply = response.content[0].text
        conversations[user_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"שגיאה: {str(e)[:200]}")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Hermes רץ על טלגרם...")
    app.run_polling()


if __name__ == "__main__":
    main()
