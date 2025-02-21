# bot.py (aiogram 3.x)
import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# В реальном проекте лучше через os.getenv
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7804957581:AAGUJJ0Jngz4KW8MnpJChXVj8S7VOZIidQE")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    # HTTPS-ссылка на ваш Flask-сервер, например через ngrok
    web_app_url = "https://3b00-141-101-19-66.ngrok-free.app"  # поменяйте тут
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="Відкрити міні‑аплікацію",
                    web_app=types.WebAppInfo(url=web_app_url)
                )
            ]
        ]
    )
    await message.reply(
        "Ласкаво просимо! Натисніть кнопку нижче для роботи з міні‑аплікацією.",
        reply_markup=keyboard
    )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
