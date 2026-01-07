import asyncio
from aiogram import Bot

async def main():
    bot = Bot(token="8285134993:AAG2KWUw-UEj7RqAv79PJgopKu1xueR5njU")
    result = await bot.delete_webhook(drop_pending_updates=True)
    print(f"✅ Webhook удален: {result}")
    await bot.session.close()

asyncio.run(main())
