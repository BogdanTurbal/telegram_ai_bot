import logging
import sqlite3
import random
import asyncio
from io import BytesIO
from PIL import Image

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# Import the Gemini API client and types for configuration
from google import genai
from google.genai import types

import os

from dotenv import load_dotenv
load_dotenv()

# ---------------------------
# Configuration and Logging
# ---------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Replace with your Telegram bot token from BotFather
# TELEGRAM_BOT_TOKEN = "7731485158:AAG7HBXEMPG82Zo40g159xSnU2ALyemMQdY"

# A common instruction to add to each prompt.
HUMAN_SUFFIX = (
    "Ansver like real human would. Write short replies, make mistakes sometimes. Show proactivity towards the user. Without need dont't write replies longer then 1 sentence."
)

# Default system prompt (used as a fallback)
SYSTEM_PROMPT = "You are a helpful human. " + HUMAN_SUFFIX

# A dictionary mapping personality names to custom system prompts.
PERSONALITY_PROMPTS = {
    "Einstein": (
        "You are Albert Einstein, a brilliant physicist known for your unconventional genius. "
        "Answer with insight, curiosity, and playful wit, and always include a hint of wonder about the universe. "
        + HUMAN_SUFFIX
    ),
    "Oppenheimer": (
        "You are J. Robert Oppenheimer, known as the 'father of the atomic bomb.' "
        "Answer with thoughtful, reflective, and sometimes somber insights, aware of the weight of discovery. "
        + HUMAN_SUFFIX
    ),
    "Turing": (
        "You are Alan Turing, a pioneering computer scientist and mathematician. "
        "Answer logically, analytically, and with a touch of eccentricity as you explore problems and ideas. "
        + HUMAN_SUFFIX
    ),
    "Hinton": (
        "You are Geoffrey Hinton, a pioneer in deep learning and artificial intelligence. "
        "Answer with technical expertise, forward-thinking insights, and a calm, measured tone. "
        + HUMAN_SUFFIX
    ),
    "Leonardo": (
        "You are Leonardo da Vinci, a master of art, science, and invention. "
        "Answer creatively, with a visionary approach and a sense of wonder about all fields of knowledge. "
        + HUMAN_SUFFIX
    ),
    "Shakespeare": (
        "You are William Shakespeare, a master of language and drama. "
        "Answer in an eloquent, poetic, and dramatic style that reflects your timeless wisdom. "
        + HUMAN_SUFFIX
    ),
}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize the Gemini API client using your API key.
client = genai.Client(api_key=GEMINI_API_KEY)

# ---------------------------
# Set Up the SQLite Database
# ---------------------------
conn = sqlite3.connect("chat_history.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS chat (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_message TEXT,
        bot_response TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
)
conn.commit()

# ---------------------------
# Global Chat Conversations and Pending Followups
# ---------------------------
# Holds a Gemini chat object per Telegram user.
user_chats = {}
# Holds an asyncio.Task for any pending follow-up chain per user.
pending_followups = {}

def get_chat(user_id):
    """
    Retrieve the chat conversation for a given user.
    If the user has not yet chosen a personality (and thus no chat exists),
    return None.
    """
    return user_chats.get(user_id)

# ---------------------------
# Follow-Up Chain Function
# ---------------------------
async def followup_chain(user_id: int, chat, context: ContextTypes.DEFAULT_TYPE, chat_id: int, probability: float = 0.5) -> None:
    """
    Waits for a random delay (2–10 seconds) and then (with the given probability)
    sends a follow-up "Continue." message via Gemini. If sent, the probability is
    halved for the next follow-up. This chain stops as soon as a follow-up is not sent.
    
    If this task is cancelled (because the user sent a new message), the chain stops.
    """
    while True:
        try:
            delay = random.uniform(2, 10)
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            # If the task is cancelled, exit the chain.
            return

        if random.random() < probability:
            try:
                response = chat.send_message("System: write a continuation, follow up, or a new message, like real human would chat")
                followup_text = response.text
            except Exception as e:
                logger.error("Error sending follow-up to Gemini: %s", e)
                followup_text = "I'm still processing your request."
            # Log the follow-up in the SQLite database.
            cursor.execute(
                "INSERT INTO chat (user_id, user_message, bot_response) VALUES (?, ?, ?)",
                (user_id, "Follow-up", followup_text)
            )
            conn.commit()
            try:
                await context.bot.send_message(chat_id=chat_id, text=followup_text)
            except Exception as e:
                logger.error("Error sending follow-up message to Telegram: %s", e)
            # Halve the probability for the next follow-up.
            probability /= 2.0
        else:
            break

# ---------------------------
# Telegram Bot Handlers
# ---------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler for the /start command.
    Shows an inline keyboard so the user can choose a historical personality.
    """
    personality_names = list(PERSONALITY_PROMPTS.keys())
    keyboard = [
        [InlineKeyboardButton(name, callback_data=name) for name in personality_names[:3]],
        [InlineKeyboardButton(name, callback_data=name) for name in personality_names[3:]],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome! Please choose a historical personality to chat with:",
        reply_markup=reply_markup,
    )

async def personality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the callback query when the user selects a personality.
    Creates a new Gemini chat conversation using the chosen personality's system prompt.
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query

    personality = query.data  # the personality name selected
    system_prompt = PERSONALITY_PROMPTS.get(personality, SYSTEM_PROMPT)
    user_id = query.from_user.id

    try:
        chat = client.chats.create(
            model="gemini-2.0-flash",
            config=types.GenerateContentConfig(system_instruction=system_prompt)
        )
        user_chats[user_id] = chat
        context.user_data["personality"] = personality
        text = f"You are now chatting with {personality}. How can I help you today?"
    except Exception as e:
        logger.error("Error creating chat conversation for personality %s: %s", personality, e)
        text = "Sorry, I'm unable to set up the conversation with that personality right now."
    await query.edit_message_text(text=text)

async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler for the /clear command.
    Clears the user's conversation history from the database and resets the Gemini chat.
    """
    user_id = update.message.from_user.id

    cursor.execute("DELETE FROM chat WHERE user_id = ?", (user_id,))
    conn.commit()

    if user_id in user_chats:
        del user_chats[user_id]
    # Cancel any pending follow-up chain for this user.
    if user_id in pending_followups:
        pending_followups[user_id].cancel()
        del pending_followups[user_id]

    await update.message.reply_text("Your conversation history has been cleared.")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles text messages.
    Logs the message in the database, sends it to Gemini (using the personality context),
    logs the response, and replies back to the user.
    After replying, a follow-up chain is scheduled with diminishing probability.
    If the user sends a new message while waiting, any pending follow-ups are canceled.
    """
    user_message = update.message.text
    user_id = update.message.from_user.id
    chat_id = update.effective_chat.id

    # Cancel any pending follow-up chain.
    if user_id in pending_followups:
        pending_followups[user_id].cancel()
        del pending_followups[user_id]

    chat = get_chat(user_id)
    if chat is None:
        await update.message.reply_text("Please choose a personality first by using /start.")
        return

    # Log the user's message in the SQLite database.
    cursor.execute(
        "INSERT INTO chat (user_id, user_message) VALUES (?, ?)",
        (user_id, user_message)
    )
    conn.commit()

    try:
        response = chat.send_message(user_message)
        bot_response = response.text
    except Exception as e:
        logger.error("Error sending text message to Gemini API: %s", e)
        bot_response = "I'm having trouble processing your request right now."

    cursor.execute(
        "UPDATE chat SET bot_response = ? WHERE id = (SELECT MAX(id) FROM chat)",
        (bot_response,)
    )
    conn.commit()

    await update.message.reply_text(bot_response)

    # Schedule the follow-up chain with an initial probability of 0.5.
    pending_followups[user_id] = asyncio.create_task(
        followup_chain(user_id, chat, context, chat_id, probability=0.5)
    )

async def handle_image_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles image messages.
    Downloads the image, opens it with Pillow, and sends it along with an optional caption
    (or a default prompt) to Gemini.
    Logs both the receipt of the image and Gemini's response in the database.
    After replying, a follow-up chain is scheduled.
    If the user sends a new message while waiting, any pending follow-ups are canceled.
    """
    user_id = update.message.from_user.id
    chat_id = update.effective_chat.id

    # Cancel any pending follow-up chain.
    if user_id in pending_followups:
        pending_followups[user_id].cancel()
        del pending_followups[user_id]

    chat = get_chat(user_id)
    if chat is None:
        await update.message.reply_text("Please choose a personality first by using /start.")
        return

    caption = update.message.caption if update.message.caption else "Describe this image."
    log_message = f"Image message with caption: {caption}" if update.message.caption else "Image message"
    cursor.execute(
        "INSERT INTO chat (user_id, user_message) VALUES (?, ?)",
        (user_id, log_message)
    )
    conn.commit()

    try:
        photo = update.message.photo[-1]
        file_id = photo.file_id
        file = await context.bot.get_file(file_id)
        file_bytes = await file.download_as_bytearray()
        image = Image.open(BytesIO(file_bytes))
    except Exception as e:
        logger.error("Error processing the image: %s", e)
        await update.message.reply_text("Sorry, I couldn't process your image.")
        return

    try:
        response = chat.send_message([image, caption])
        bot_response = response.text
    except Exception as e:
        logger.error("Error sending image message to Gemini API: %s", e)
        bot_response = "I'm having trouble processing your image right now."

    cursor.execute(
        "UPDATE chat SET bot_response = ? WHERE id = (SELECT MAX(id) FROM chat)",
        (bot_response,)
    )
    conn.commit()

    await update.message.reply_text(bot_response)

    # Schedule the follow-up chain with an initial probability of 0.5.
    pending_followups[user_id] = asyncio.create_task(
        followup_chain(user_id, chat, context, chat_id, probability=0.5)
    )

# ---------------------------
# Main Function to Start the Bot
# ---------------------------
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_history))
    # Callback query handler for personality selection
    app.add_handler(CallbackQueryHandler(personality_selection))
    # Message handlers
    app.add_handler(MessageHandler(filters.PHOTO, handle_image_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Start polling for updates from Telegram.
    app.run_polling()

if __name__ == "__main__":
    main()
