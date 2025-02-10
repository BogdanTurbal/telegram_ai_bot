# AI Personalities Telegram Bot

A Telegram bot that lets you chat with historical personalities powered by Google's Gemini AI. Each personality (Einstein, Oppenheimer, Turing, Hinton, Leonardo, and Shakespeare) has its unique characteristics and response style.

## Features

- Chat with different historical personalities
- Handles text and image messages
- Natural conversation flow with follow-up responses
- SQLite database for chat history
- Personality-specific response styles

## Setup

1. Clone the repository
2. Install requirements:
```bash
pip install -r requirements.txt
```
3. Create `.env` file with your tokens:
```
TELEGRAM_BOT_TOKEN=your_telegram_token
GEMINI_API_KEY=your_gemini_api_key
```
4. Run the bot:
```bash
python main.py
```

## Usage

- `/start` - Choose a personality to chat with
- `/clear` - Clear your chat history
- Send text or images to interact with your chosen personality

## Technologies

- Python
- python-telegram-bot
- Google Gemini API
- SQLite
- PIL (Python Imaging Library)

## License

MIT
