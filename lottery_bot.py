import os
import sqlite3
import asyncio
import logging
from datetime import datetime
from typing import Optional
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, LabeledPrice
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, DiceEmoji
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN', '8285134993:AAG2KWUw-UEj7RqAv79PJgopKu1xueR5njU')
CRYPTO_BOT_TOKEN = os.getenv('CRYPTO_BOT_TOKEN', '512423:AAjvv90onLsaYycj668hryY9Mrkd9wjJoNT')
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x]

logger.info(f"BOT_TOKEN загружен: {BOT_TOKEN[:20]}...")
logger.info(f"CRYPTO_BOT_TOKEN загружен: {CRYPTO_BOT_TOKEN[:20]}...")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Курс: 50 Stars = 1 USDT
STARS_TO_USDT_RATE = 1 / 50  # = 0.02

class BetStates(StatesGroup):
    choosing_game = State()
    choosing_bet_type = State()
    entering_custom_amount = State()
    entering_custom_stars = State()
    waiting_payment = State()
    admin_entering_user_id = State()
    admin_entering_balance = State()
    entering_promocode = State()
    admin_creating_promo_code = State()
    admin_creating_promo_amount = State()
    admin_creating_promo_uses = State()


GAMES = {
    'dice': {'emoji': '🎲', 'name': 'Кубик', 'dice_emoji': DiceEmoji.DICE},
    'basketball': {'emoji': '🏀', 'name': 'Баскетбол', 'dice_emoji': DiceEmoji.BASKETBALL},
    'football': {'emoji': '⚽', 'name': 'Футбол', 'dice_emoji': DiceEmoji.FOOTBALL},
    'darts': {'emoji': '🎯', 'name': 'Дартс', 'dice_emoji': DiceEmoji.DART},
    'bowling': {'emoji': '🎳', 'name': 'Боулинг', 'dice_emoji': DiceEmoji.BOWLING}
}

BET_TYPES = {
    'dice': {
        'Четное': {'odds': 2.0, 'check': lambda x: x in [2, 4, 6]},
        'Нечетное': {'odds': 2.0, 'check': lambda x: x in [1, 3, 5]},
        'Больше 3': {'odds': 2.0, 'check': lambda x: x > 3},
        'Меньше 4': {'odds': 2.0, 'check': lambda x: x < 4},
    },
    'basketball': {
        'Гол': {'odds': 2.0, 'check': lambda x: x in [4, 5]},
        'Застрял': {'odds': 2.0, 'check': lambda x: x == 3},
        'Мимо': {'odds': 2.0, 'check': lambda x: x in [1, 2]},
    },
    'football': {
        'Гол': {'odds': 2.0, 'check': lambda x: x in [3, 4, 5]},
        'Мимо': {'odds': 2.0, 'check': lambda x: x in [1, 2]},
    },
    'darts': {
        'Центр': {'odds': 2.0, 'check': lambda x: x == 6},
        'Красное': {'odds': 2.0, 'check': lambda x: x == 5},
        'Белое': {'odds': 2.0, 'check': lambda x: x in [3, 4]},
        'Мимо': {'odds': 2.0, 'check': lambda x: x in [1, 2]},
    },
    'bowling': {
        'Страйк': {'odds': 2.0, 'check': lambda x: x == 6},
        'Мимо': {'odds': 2.0, 'check': lambda x: x in [1, 2, 3]},
    }
}


def init_db():
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0,
            total_deposited REAL DEFAULT 0,
            total_withdrawn REAL DEFAULT 0,
            total_wagered REAL DEFAULT 0,
            total_won REAL DEFAULT 0,
            total_lost REAL DEFAULT 0,
            games_played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
cursor.execute('''
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            game_type TEXT,
            bet_type TEXT,
            bet_amount REAL,
            result_value INTEGER,
            win BOOLEAN,
            payout REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount REAL,
            status TEXT,
            invoice_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
cursor.execute('''
        CREATE TABLE IF NOT EXISTS promocodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            amount REAL,
            max_uses INTEGER,
            current_uses INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
cursor.execute('''
        CREATE TABLE IF NOT EXISTS promocode_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            code TEXT,
            amount REAL,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
conn.commit()
conn.close()


def get_user(user_id: int):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user


def create_user(user_id: int, username: str, first_name: str):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
                   (user_id, username, first_name))
    conn.commit()
    conn.close()


def update_balance(user_id: int, amount: float):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()


def get_balance(user_id: int) -> float:
    user = get_user(user_id)
    return user[3] if user else 0


def set_balance(user_id: int, amount: float):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()


def record_game(user_id: int, game_type: str, bet_type: str, bet_amount: float,
                result_value: int, win: bool, payout: float):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO games (user_id, game_type, bet_type, bet_amount, result_value, win, payout)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, game_type, bet_type, bet_amount, result_value, win, payout))

    if win:
        cursor.execute('''
            UPDATE users SET 
                balance = balance + ?,
                total_wagered = total_wagered + ?,
                total_won = total_won + ?,
                games_played = games_played + 1,
                wins = wins + 1
            WHERE user_id = ?
        ''', (payout - bet_amount, bet_amount, payout, user_id))
    else:
        cursor.execute('''
            UPDATE users SET 
                balance = balance - ?,
                total_wagered = total_wagered + ?,
                total_lost = total_lost + ?,
                games_played = games_played + 1,
                losses = losses + 1
            WHERE user_id = ?
        ''', (bet_amount, bet_amount, bet_amount, user_id))

    conn.commit()
    conn.close()


def get_user_stats(user_id: int):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    stats = cursor.fetchone()
    conn.close()
    return stats


def get_all_users():
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users ORDER BY balance DESC')
    users = cursor.fetchall()
    conn.close()
    return users
    
def create_promocode(code: str, amount: float, max_uses: int):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO promocodes (code, amount, max_uses)
            VALUES (?, ?, ?)
        ''', (code, amount, max_uses))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def get_promocode(code: str):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM promocodes WHERE code = ?', (code,))
    promo = cursor.fetchone()
    conn.close()
    return promo


def use_promocode(user_id: int, code: str):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    

    cursor.execute('SELECT * FROM promocode_uses WHERE user_id = ? AND code = ?', (user_id, code))
    if cursor.fetchone():
        conn.close()
        return False, "Вы уже использовали этот промокод!"
    
    
    cursor.execute('SELECT * FROM promocodes WHERE code = ?', (code,))
    promo = cursor.fetchone()
    
    if not promo:
        conn.close()
        return False, "Промокод не найден!"
    
    promo_id, promo_code, amount, max_uses, current_uses, created_at = promo
    
    if current_uses >= max_uses:
        conn.close()
        return False, "Промокод исчерпан!"
    
 
    cursor.execute('UPDATE promocodes SET current_uses = current_uses + 1 WHERE code = ?', (code,))
    cursor.execute('''
        INSERT INTO promocode_uses (user_id, code, amount)
        VALUES (?, ?, ?)
    ''', (user_id, code, amount))
    
    update_balance(user_id, amount)
    
    cursor.execute('''
        INSERT INTO transactions (user_id, type, amount, status, invoice_id)
        VALUES (?, 'promocode', ?, 'completed', ?)
    ''', (user_id, amount, f"promo_{code}"))
    
    conn.commit()
    conn.close()
    return True, amount


def get_all_promocodes():
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM promocodes ORDER BY created_at DESC')
    promos = cursor.fetchall()
    conn.close()
    return promos


def delete_promocode(code: str):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM promocodes WHERE code = ?', (code,))
    conn.commit()
    conn.close()

def main_keyboard():
    keyboard = [
        [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="➕ Пополнить"), KeyboardButton(text="🎁 Промокод")],
        [KeyboardButton(text="📊 Статистика")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def admin_keyboard():
    keyboard = [
        [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="➕ Пополнить"), KeyboardButton(text="🎁 Промокод")],
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="⚙️ Админ панель")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def games_keyboard():
    buttons = []
    for game_id, game_data in GAMES.items():
        emoji = game_data['emoji']
        name = game_data['name']
        buttons.append([InlineKeyboardButton(text=f"{emoji} {name}", callback_data=f"game_{game_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def bet_types_keyboard(game_id: str):
    buttons = []
    for bet_type, data in BET_TYPES[game_id].items():
        odds = data['odds']
        buttons.append([InlineKeyboardButton(
            text=f"{bet_type} (x{odds})",
            callback_data=f"bettype_{game_id}_{bet_type}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_games")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_method_keyboard(amount: float, purpose: str):
    buttons = [
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay_stars_{amount}_{purpose}")],
        [InlineKeyboardButton(text="💎 Crypto (USDT)", callback_data=f"pay_crypto_{amount}_{purpose}")],
        [InlineKeyboardButton(text="✖️ Отменить", callback_data="cancel_payment")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_panel_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="💰 Управление балансами", callback_data="admin_balances")],
        [InlineKeyboardButton(text="🎁 Управление промокодами", callback_data="admin_promocodes")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_balance_keyboard():
    buttons = [
        [InlineKeyboardButton(text="🔍 Проверить баланс", callback_data="admin_check_balance")],
        [InlineKeyboardButton(text="➕ Добавить баланс", callback_data="admin_add_balance")],
        [InlineKeyboardButton(text="➖ Вычесть баланс", callback_data="admin_subtract_balance")],
        [InlineKeyboardButton(text="💰 Установить баланс", callback_data="admin_set_balance")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_admin_panel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
    
def admin_promocode_keyboard():
    buttons = [
        [InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin_create_promo")],
        [InlineKeyboardButton(text="📋 Список промокодов", callback_data="admin_list_promos")],
        [InlineKeyboardButton(text="🗑 Удалить промокод", callback_data="admin_delete_promo")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_admin_panel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def create_invoice(amount: float, description: str):
    import aiohttp
    import ssl
    import certifi

    if not CRYPTO_BOT_TOKEN:
        logger.error("❌ CRYPTO_BOT_TOKEN не установлен!")
        return None

    logger.info(f"🔄 Создание Crypto инвойса: {amount} USDT")

    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {
        "Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN,
        "Content-Type": "application/json"
    }
    data = {
        "asset": "USDT",
        "amount": str(amount),
        "description": description
    }

    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)

        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(url, headers=headers, json=data) as resp:
                logger.info(f"📡 Статус ответа API: {resp.status}")
                result = await resp.json()
                logger.info(f"📦 Ответ API: {result}")

                if resp.status == 200 and result.get('ok'):
                    logger.info(f"✅ Crypto инвойс создан: {result['result']['invoice_id']}")
                    return result['result']
                else:
                    logger.error(f"❌ Ошибка создания инвойса: {result}")
    except Exception as e:
        logger.error(f"❌ Исключение при создании инвойса: {e}")

    return None


async def check_invoice(invoice_id: str):
    import aiohttp
    import ssl
    import certifi

    logger.info(f"🔍 Проверка Crypto инвойса: {invoice_id}")

    url = f"https://pay.crypt.bot/api/getInvoices"
    headers = {
        "Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN
    }
    params = {
        "invoice_ids": invoice_id
    }

    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)

        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, headers=headers, params=params) as resp:
                logger.info(f"📡 Статус проверки: {resp.status}")

                if resp.status == 200:
                    result = await resp.json()

                    if result.get('ok') and result.get('result', {}).get('items'):
                        invoice = result['result']['items'][0]
                        logger.info(f"💳 Статус инвойса: {invoice.get('status')}")
                        return invoice
                    else:
                        logger.warning(f"⚠️ Инвойс не найден")
                else:
                    error_text = await resp.text()
                    logger.error(f"❌ Ошибка API ({resp.status}): {error_text}")
    except Exception as e:
        logger.error(f"❌ Исключение при проверке: {e}")

    return None


async def auto_check_payment(message: types.Message, user_id: int, invoice_id: str, state: FSMContext):
    logger.info(f"⏳ Запуск автопроверки Crypto платежа для инвойса {invoice_id}")

    max_attempts = 100
    attempt = 0

    while attempt < max_attempts:
        await asyncio.sleep(3)
        attempt += 1

        invoice = await check_invoice(invoice_id)

        if invoice and invoice.get('status') == 'paid':
            logger.info(f"✅ Crypto платеж получен!")
            amount = float(invoice['amount'])

            update_balance(user_id, amount)

            conn = sqlite3.connect('lottery_bot.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO transactions (user_id, type, amount, status, invoice_id)
                VALUES (?, 'deposit', ?, 'completed', ?)
            ''', (user_id, amount, invoice_id))
            cursor.execute(
                'UPDATE users SET total_deposited = total_deposited + ? WHERE user_id = ?',
                (amount, user_id)
            )
            conn.commit()
            conn.close()

            data = await state.get_data()
            is_deposit_only = data.get('is_deposit_only', False)

            if is_deposit_only:
                try:
                    await message.edit_text(
                        f"✔️ <b>Оплата получена!</b>\n\n"
                        f"На ваш баланс зачислено <b>{amount} USDT</b>\n"
                        f"Текущий баланс: <b>{get_balance(user_id):.2f} USDT</b>"
                    )
                except:
                    await message.answer(
                        f"✔️ <b>Оплата получена!</b>\n\n"
                        f"На ваш баланс зачислено <b>{amount} USDT</b>\n"
                        f"Текущий баланс: <b>{get_balance(user_id):.2f} USDT</b>"
                    )
                await state.clear()
            else:
                game_id = data.get('game_id')
                bet_type = data.get('bet_type')
                bet_amount = data.get('bet_amount')

                if game_id and bet_type and bet_amount:
                    await process_game(message, user_id, game_id, bet_type, bet_amount, state)

            return

    logger.warning(f"⏰ Время ожидания Crypto оплаты истекло для инвойса {invoice_id}")
    try:
        await message.edit_text(
            "⏰ Время ожидания оплаты истекло.\n"
            "Если вы оплатили счет, средства будут зачислены автоматически."
        )
    except:
        pass
    await state.clear()


async def create_stars_invoice(user_id: int, stars_amount: int, title: str, description: str, payload: str):
    try:
        logger.info(f"⭐ Создание Stars инвойса: {stars_amount} Stars для user {user_id}")

        await bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=description,
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label="Пополнение", amount=stars_amount)],
            provider_token=""
        )
        logger.info(f"✅ Stars инвойс отправлен")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка Stars инвойса: {e}")
        return False


async def process_game(message: types.Message, user_id: int, game_id: str, bet_type: str, bet_amount: float, state: FSMContext):
    game_data = GAMES[game_id]
    dice_emoji = game_data['dice_emoji']
    
    dice_msg = await bot.send_dice(user_id, emoji=dice_emoji)
    result_value = dice_msg.dice.value
    
    await asyncio.sleep(4)
    
    bet_config = BET_TYPES[game_id][bet_type]
    is_win = bet_config['check'](result_value)
    
    if is_win:
        payout = bet_amount * bet_config['odds']
        profit = payout - bet_amount
        record_game(user_id, game_id, bet_type, bet_amount, result_value, True, payout)
        
        await bot.send_message(
            user_id,
            f"🎉 <b>ПОБЕДА!</b>\n\n"
            f"🎮 Игра: {game_data['name']}\n"
            f"🎯 Ставка: {bet_type}\n"
            f"🎲 Результат: {result_value}\n"
            f"💰 Ставка: {bet_amount:.2f} USDT\n"
            f"✅ Выигрыш: <b>+{profit:.2f} USDT</b>\n\n"
            f"💵 Ваш баланс: <b>{get_balance(user_id):.2f} USDT</b>"
        )
    else:
        record_game(user_id, game_id, bet_type, bet_amount, result_value, False, 0)
        
        await bot.send_message(
            user_id,
            f"😔 <b>Проигрыш</b>\n\n"
            f"🎮 Игра: {game_data['name']}\n"
            f"🎯 Ставка: {bet_type}\n"
            f"🎲 Результат: {result_value}\n"
            f"💰 Ставка: {bet_amount:.2f} USDT\n"
            f"❌ Потеря: <b>-{bet_amount:.2f} USDT</b>\n\n"
            f"💵 Ваш баланс: <b>{get_balance(user_id):.2f} USDT</b>"
        )
    
    await state.clear()


@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    logger.info(f"🔍 Pre-checkout: {pre_checkout_query.invoice_payload}")
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.content_type == types.ContentType.SUCCESSFUL_PAYMENT)
async def process_successful_payment(message: types.Message, state: FSMContext):
    successful_payment = message.successful_payment
    payload = successful_payment.invoice_payload
    user_id = message.from_user.id

    logger.info(f"✅ Успешный платеж Stars: {payload}, сумма: {successful_payment.total_amount}")

    try:
        parts = payload.split("_")
        if len(parts) >= 3:
            stars_amount = int(parts[1])
            purpose = parts[2]

            if successful_payment.currency == "XTR" and successful_payment.total_amount == stars_amount:
                amount_usdt = stars_amount * STARS_TO_USDT_RATE
                amount_usdt = round(amount_usdt, 2)

                update_balance(user_id, amount_usdt)

                conn = sqlite3.connect('lottery_bot.db')
                cursor = conn.cursor()
                invoice_id = f"stars_{user_id}_{datetime.now().timestamp()}"
                cursor.execute('''
                    INSERT INTO transactions (user_id, type, amount, status, invoice_id)
                    VALUES (?, 'deposit', ?, 'completed', ?)
                ''', (user_id, amount_usdt, invoice_id))
                cursor.execute(
                    'UPDATE users SET total_deposited = total_deposited + ? WHERE user_id = ?',
                    (amount_usdt, user_id)
                )
                conn.commit()
                conn.close()

                data = await state.get_data()

                if purpose == "deposit":
                    await message.answer(
                        f"✅ <b>Оплата успешна!</b>\n\n"
                        f"💫 Оплачено: {stars_amount} Stars\n"
                        f"💰 Зачислено: <b>{amount_usdt} USDT</b>\n"
                        f"💵 Ваш баланс: <b>{get_balance(user_id):.2f} USDT</b>"
                    )
                    await state.clear()
                else:
                    game_id = data.get('game_id')
                    bet_type = data.get('bet_type')
                    bet_amount = data.get('bet_amount')

                    if game_id and bet_type and bet_amount:
                        await process_game(message, user_id, game_id, bet_type, bet_amount, state)
            else:
                logger.error(f"❌ Несоответствие суммы")
                await message.answer("❌ Ошибка: несоответствие суммы платежа.")
        else:
            logger.error(f"❌ Неверный формат payload: {payload}")
            await message.answer("❌ Ошибка обработки платежа.")
    except Exception as e:
        logger.error(f"❌ Ошибка обработки успешного платежа: {e}")
        await message.answer("❌ Ошибка обработки платежа.")


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""

    create_user(user_id, username, first_name)

    keyboard = admin_keyboard() if user_id in ADMIN_IDS else main_keyboard()

    await message.answer(
        f"<b>🎰 Добро пожаловать в Лотерейного Бота!</b>\n\n"
        f"Привет, {first_name}! 👋\n\n"
        f"<b>Доступные игры:</b>\n"
        f"🎲 Кубик\n🏀 Баскетбол\n⚽ Футбол\n🎯 Дартс\n🎳 Боулинг\n\n"
        f"<b>Способы оплаты:</b>\n"
        f"⭐️ Telegram Stars (50 Stars = 1 USDT)\n"
        f"💎 Криптовалюта (USDT)\n\n"
        f"Выбери действие из меню ниже ⬇️",
        reply_markup=keyboard
    )


@dp.message(Command("myid"))
async def cmd_my_id(message: types.Message):
    await message.answer(
        f"<b>🆔 Ваш Telegram ID:</b>\n\n"
        f"<code>{message.from_user.id}</code>\n\n"
        f"<i>Нажмите чтобы скопировать</i>"
    )


@dp.message(F.text == "🎮 Играть")
async def menu_play(message: types.Message, state: FSMContext):
    await state.set_state(BetStates.choosing_game)
    await message.answer("<b>🎮 Выбери игру:</b>", reply_markup=games_keyboard())


@dp.message(F.text == "👤 Мой профиль")
async def menu_profile(message: types.Message):
    user_id = message.from_user.id
    stats = get_user_stats(user_id)

    if not stats:
        await message.answer("❌ Ошибка получения профиля!")
        return

    balance = stats[3]
    total_wagered = stats[6]
    total_won = stats[7]
    total_lost = stats[8]
    games_played = stats[9]
    wins = stats[10]
    losses = stats[11]

    win_rate = (wins / games_played * 100) if games_played > 0 else 0
    profit = total_won - total_lost

    await message.answer(
        f"<b>👤 Твой профиль</b>\n\n"
        f"💰 <b>Баланс:</b> {balance:.2f} USDT\n"
        f"📊 <b>Всего ставок:</b> {total_wagered:.2f} USDT\n"
        f"✔️ <b>Выиграно:</b> {total_won:.2f} USDT\n"
        f"✖️ <b>Проиграно:</b> {total_lost:.2f} USDT\n"
        f"💵 <b>Профит:</b> {profit:+.2f} USDT\n\n"
        f"🎮 <b>Игр сыграно:</b> {games_played}\n"
        f"✔️ <b>Побед:</b> {wins}\n"
        f"✖️ <b>Поражений:</b> {losses}\n"
        f"📈 <b>Винрейт:</b> {win_rate:.1f}%"
    )


@dp.message(F.text == "➕ Пополнить")
async def menu_deposit(message: types.Message, state: FSMContext):
    await state.clear()
    await state.update_data(is_deposit_only=True)
    await state.set_state(BetStates.entering_custom_amount)

    await message.answer(
        "<b>➕ Пополнение баланса</b>\n\n"
        "💰 <b>Введите сумму пополнения (от 1 USDT):</b>\n\n"
        "<i>Примеры: 1 или 5 или 10 или 25</i>"
    )
    
@dp.message(F.text == "🎁 Промокод")
async def menu_promocode(message: types.Message, state: FSMContext):
    await state.set_state(BetStates.entering_promocode)
    await message.answer(
        "<b>🎁 Активация промокода</b>\n\n"
        "Введите промокод:"
    )

@dp.message(F.text == "📊 Статистика")
async def menu_stats(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT game_type, bet_type, bet_amount, win, payout, created_at
        FROM games WHERE user_id = ? ORDER BY created_at DESC LIMIT 10
    ''', (user_id,))
    recent_games = cursor.fetchall()
    conn.close()
    
    if not recent_games:
        await message.answer("📊 <b>Статистика</b>\n\nУ вас еще нет сыгранных игр.")
        return

    text = "<b>📊 Последние 10 игр:</b>\n\n"
    for game in recent_games:
        game_type, bet_type, bet_amount, win, payout, created_at = game
        result_emoji = "✔️" if win else "✖️"
        profit = payout - bet_amount if win else -bet_amount
        text += (
            f"{result_emoji} <b>{game_type} - {bet_type}</b>\n"
            f"   Ставка: {bet_amount:.2f} USDT | "
            f"Результат: {profit:+.2f} USDT\n\n"
        )
    await message.answer(text)


@dp.message(F.text == "⚙️ Админ панель")
async def menu_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔️ У вас нет доступа к админ панели!")
        return
    
    await message.answer(
        "<b>⚙️ Админ панель</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_panel_keyboard()
    )


@dp.callback_query(F.data == "back_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.answer()


@dp.callback_query(F.data == "back_games")
async def back_to_games(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BetStates.choosing_game)
    await callback.message.edit_text("<b>🎮 Выбери игру:</b>", reply_markup=games_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "back_admin_panel")
async def back_to_admin_panel(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "<b>⚙️ Админ панель</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_panel_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("game_"))
async def select_game(callback: types.CallbackQuery, state: FSMContext):
    game_id = callback.data.split("_")[1]
    await state.update_data(game_id=game_id)
    await state.set_state(BetStates.choosing_bet_type)
    
    game_name = GAMES[game_id]['name']
    await callback.message.edit_text(
        f"<b>🎮 {game_name}</b>\n\n"
        f"Выбери тип ставки:",
        reply_markup=bet_types_keyboard(game_id)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("bettype_"))
async def select_bet_type(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 2)
    game_id = parts[1]
    bet_type = parts[2]
    
    await state.update_data(bet_type=bet_type)
    
    game_name = GAMES[game_id]['name']
    odds = BET_TYPES[game_id][bet_type]['odds']
    
    await callback.message.edit_text(
        f"<b>🎮 {game_name}</b>\n"
        f"<b>🎯 Ставка:</b> {bet_type} (x{odds})\n\n"
        f"Выбери сумму ставки:",
        reply_markup=bet_amount_keyboard(game_id, bet_type)
    )
    await callback.answer()


@dp.message(BetStates.entering_custom_amount)
async def process_custom_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount < 1:
            await message.answer("❌ Минимальная сумма - 1 USDT")
            return
        
        data = await state.get_data()
        is_deposit_only = data.get('is_deposit_only', False)
        
        if is_deposit_only:
            await state.update_data(deposit_amount=amount)
            await message.answer(
                f"💰 <b>Пополнение на {amount} USDT</b>\n\n"
                f"Выберите способ оплаты:",
                reply_markup=payment_method_keyboard(amount, "deposit")
            )
        else:
            game_id = data.get('game_id')
            bet_type = data.get('bet_type')
            user_id = message.from_user.id
            balance = get_balance(user_id)
            
            if balance >= amount:
                await state.update_data(bet_amount=amount)
                await process_game(message, user_id, game_id, bet_type, amount, state)
            else:
                need_amount = amount - balance
                await state.update_data(bet_amount=amount)
                await message.answer(
                    f"💰 <b>Недостаточно средств!</b>\n\n"
                    f"Ваш баланс: <b>{balance:.2f} USDT</b>\n"
                    f"Нужно: <b>{amount:.2f} USDT</b>\n"
                    f"Не хватает: <b>{need_amount:.2f} USDT</b>\n\n"
                    f"Выберите способ пополнения:",
                    reply_markup=payment_method_keyboard(need_amount, "bet")
                )
    except ValueError:
        await message.answer("❌ Неверный формат! Введите число, например: 5 или 10.5")
        
@dp.message(BetStates.entering_promocode)
async def process_promocode(message: types.Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    
    success, result = use_promocode(user_id, code)
    
    if success:
        await message.answer(
            f"✅ <b>Промокод активирован!</b>\n\n"
            f"🎁 Код: <code>{code}</code>\n"
            f"💰 Начислено: <b>{result} USDT</b>\n"
            f"💵 Ваш баланс: <b>{get_balance(user_id):.2f} USDT</b>"
        )
    else:
        await message.answer(f"❌ <b>Ошибка!</b>\n\n{result}")
    
    await state.clear()

@dp.callback_query(F.data.startswith("pay_stars_"))
async def process_stars_payment(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    amount = float(parts[2])
    purpose = parts[3]
    
    user_id = callback.from_user.id
    stars_amount = int(amount / STARS_TO_USDT_RATE)
    
    await callback.message.delete()
    
    success = await create_stars_invoice(
        user_id=user_id,
        stars_amount=stars_amount,
        title="Пополнение баланса",
        description=f"Пополнение на {amount} USDT",
        payload=f"stars_{stars_amount}_{purpose}"
    )
    
    if success:
        await callback.message.answer(
            f"⭐ <b>Счет на оплату создан!</b>\n\n"
            f"💰 Сумма: {stars_amount} Stars (= {amount} USDT)\n"
            f"📝 Нажмите кнопку 'Pay' чтобы оплатить"
        )
    else:
        await callback.message.answer("❌ Ошибка создания счета")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("pay_crypto_"))
async def process_crypto_payment(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    amount = float(parts[2])
    purpose = parts[3]
    
    user_id = callback.from_user.id
    
    invoice = await create_invoice(amount, f"Пополнение баланса {amount} USDT")
    
    if invoice:
        invoice_id = invoice['invoice_id']
        pay_url = invoice['pay_url']
        
        await callback.message.edit_text(
            f"💎 <b>Криптовалютный платеж</b>\n\n"
            f"💰 Сумма: <b>{amount} USDT</b>\n"
            f"🔗 Ссылка для оплаты:\n{pay_url}\n\n"
            f"⏳ Ожидаем оплату...",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
                [InlineKeyboardButton(text="✖️ Отменить", callback_data="cancel_payment")]
            ])
        )
        
        asyncio.create_task(auto_check_payment(callback.message, user_id, invoice_id, state))
    else:
        await callback.message.edit_text("❌ Ошибка создания инвойса")
    
    await callback.answer()


@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer("❌ Оплата отменена")
    await state.clear()
    await callback.answer()


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    users = get_all_users()
    total_users = len(users)
    total_balance = sum(u[3] for u in users)
    total_deposited = sum(u[4] for u in users)
    total_wagered = sum(u[6] for u in users)
    total_won = sum(u[7] for u in users)
    total_lost = sum(u[8] for u in users)
    
    await callback.message.edit_text(
        f"<b>📊 Общая статистика</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"💰 Общий баланс: {total_balance:.2f} USDT\n"
        f"➕ Всего пополнено: {total_deposited:.2f} USDT\n"
        f"📊 Всего ставок: {total_wagered:.2f} USDT\n"
        f"✔️ Выиграно: {total_won:.2f} USDT\n"
        f"✖️ Проиграно: {total_lost:.2f} USDT",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_admin_panel")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    users = get_all_users()
    
    text = "<b>👥 Список пользователей:</b>\n\n"
    for user in users[:20]:
        user_id, username, first_name, balance = user[0], user[1], user[2], user[3]
        text += f"ID: <code>{user_id}</code>\n"
        text += f"👤 {first_name} (@{username or 'нет'})\n"
        text += f"💰 {balance:.2f} USDT\n\n"
    
    if len(users) > 20:
        text += f"<i>... и еще {len(users) - 20} пользователей</i>"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_admin_panel")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_balances")
async def admin_balances(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "<b>💰 Управление балансами</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_balance_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_promocodes")
async def admin_promocodes(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "<b>🎁 Управление промокодами</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_promocode_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_create_promo")
async def admin_create_promo(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    await state.set_state(BetStates.admin_creating_promo_code)
    await callback.message.edit_text(
        "<b>➕ Создание промокода</b>\n\n"
        "Введите код промокода (например: BONUS100):"
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_list_promos")
async def admin_list_promos(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    promos = get_all_promocodes()
    
    if not promos:
        await callback.message.edit_text(
            "<b>📋 Список промокодов</b>\n\n"
            "Промокодов пока нет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promocodes")]
            ])
        )
        await callback.answer()
        return
    
    text = "<b>📋 Активные промокоды:</b>\n\n"
    for promo in promos:
        promo_id, code, amount, max_uses, current_uses, created_at = promo
        text += (
            f"🎁 <code>{code}</code>\n"
            f"   💰 Сумма: {amount} USDT\n"
            f"   📊 Использовано: {current_uses}/{max_uses}\n\n"
        )
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promocodes")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_delete_promo")
async def admin_delete_promo(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    promos = get_all_promocodes()
    
    if not promos:
        await callback.answer("Промокодов нет!", show_alert=True)
        return
    
    buttons = []
    for promo in promos:
        code = promo[1]
        buttons.append([InlineKeyboardButton(
            text=f"🗑 {code}",
            callback_data=f"delete_promo_{code}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promocodes")])
    
    await callback.message.edit_text(
        "<b>🗑 Удаление промокода</b>\n\n"
        "Выберите промокод для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delete_promo_"))
async def confirm_delete_promo(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    code = callback.data.replace("delete_promo_", "")
    delete_promocode(code)
    
    await callback.message.edit_text(
        f"✅ <b>Промокод удален!</b>\n\n"
        f"🗑 Код: <code>{code}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promocodes")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_add_balance")
async def admin_add_balance(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    await state.set_state(BetStates.admin_entering_user_id)
    await state.update_data(action="add")
    await callback.message.edit_text(
        "<b>➕ Добавление баланса</b>\n\n"
        "Введите Telegram ID пользователя:"
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_subtract_balance")
async def admin_subtract_balance(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    await state.set_state(BetStates.admin_entering_user_id)
    await state.update_data(action="subtract")
    await callback.message.edit_text(
        "<b>➖ Вычитание баланса</b>\n\n"
        "Введите Telegram ID пользователя:"
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_reset_balance")
async def admin_reset_balance(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    await state.set_state(BetStates.admin_entering_user_id)
    await state.update_data(action="reset")
    await callback.message.edit_text(
        "<b>0️⃣ Обнуление баланса</b>\n\n"
        "Введите Telegram ID пользователя:"
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_set_balance")
async def admin_set_balance(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    await state.set_state(BetStates.admin_entering_user_id)
    await state.update_data(action="set")
    await callback.message.edit_text(
        "<b>💰 Установка баланса</b>\n\n"
        "Введите Telegram ID пользователя:"
    )
    await callback.answer()


@dp.message(BetStates.admin_entering_user_id)
async def process_admin_user_id(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        target_user_id = int(message.text)
        data = await state.get_data()
        action = data.get('action')
        
        user = get_user(target_user_id)
        if not user:
            await message.answer("❌ Пользователь не найден!")
            await state.clear()
            return
        
        await state.update_data(target_user_id=target_user_id)
        
        if action == "check":
            balance = get_balance(target_user_id)
            await message.answer(
                f"<b>🔍 Баланс пользователя</b>\n\n"
                f"ID: <code>{target_user_id}</code>\n"
                f"💰 Баланс: {balance:.2f} USDT"
            )
            await state.clear()
        elif action == "reset":
            set_balance(target_user_id, 0)
            await message.answer(
                f"<b>✅ Баланс обнулен</b>\n\n"
                f"ID: <code>{target_user_id}</code>\n"
                f"💰 Новый баланс: 0.00 USDT"
            )
        elif action == "add":
            await state.set_state(BetStates.admin_entering_balance)
            await message.answer(
                f"<b>➕ Добавление баланса</b>\n\n"
                f"ID: <code>{target_user_id}</code>\n"
                f"💰 Текущий баланс: {get_balance(target_user_id):.2f} USDT\n\n"
                f"Введите сумму для добавления:"
            )
        elif action == "subtract":
            await state.set_state(BetStates.admin_entering_balance)
            await message.answer(
                f"<b>➖ Вычитание баланса</b>\n\n"
                f"ID: <code>{target_user_id}</code>\n"
                f"💰 Текущий баланс: {get_balance(target_user_id):.2f} USDT\n\n"
                f"Введите сумму для вычитания:"
            )
            await state.clear()
        elif action == "set":
            await state.set_state(BetStates.admin_entering_balance)
            await message.answer(
                f"<b>💰 Установка баланса</b>\n\n"
                f"ID: <code>{target_user_id}</code>\n\n"
                f"Введите новую сумму баланса:"
            )
    except ValueError:
        await message.answer("❌ Неверный формат ID! Введите число.")


@dp.message(BetStates.admin_entering_balance)
async def process_admin_balance(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        amount = float(message.text.replace(',', '.'))
        data = await state.get_data()
        target_user_id = data.get('target_user_id')
        action = data.get('action')
        
        current_balance = get_balance(target_user_id)
        
        if action == "set":
            set_balance(target_user_id, amount)
            await message.answer(
                f"<b>✅ Баланс установлен</b>\n\n"
                f"ID: <code>{target_user_id}</code>\n"
                f"💰 Новый баланс: {amount:.2f} USDT"
            )
        elif action == "add":
            new_balance = current_balance + amount
            set_balance(target_user_id, new_balance)
            await message.answer(
                f"<b>✅ Баланс добавлен</b>\n\n"
                f"ID: <code>{target_user_id}</code>\n"
                f"➕ Добавлено: {amount:.2f} USDT\n"
                f"💰 Новый баланс: {new_balance:.2f} USDT"
            )
        elif action == "subtract":
            new_balance = current_balance - amount
            set_balance(target_user_id, new_balance)
            await message.answer(
                f"<b>✅ Баланс вычтен</b>\n\n"
                f"ID: <code>{target_user_id}</code>\n"
                f"➖ Вычтено: {amount:.2f} USDT\n"
                f"💰 Новый баланс: {new_balance:.2f} USDT"
            )
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный формат суммы! Введите число.")

@dp.message(BetStates.admin_creating_promo_code)
async def process_promo_code(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    code = message.text.strip().upper()
    
    if len(code) < 3:
        await message.answer("❌ Код должен быть минимум 3 символа!")
        return
    
    await state.update_data(promo_code=code)
    await state.set_state(BetStates.admin_creating_promo_amount)
    await message.answer(
        f"<b>➕ Создание промокода</b>\n\n"
        f"🎁 Код: <code>{code}</code>\n\n"
        f"Введите сумму начисления (USDT):"
    )


@dp.message(BetStates.admin_creating_promo_amount)
async def process_promo_amount(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0!")
            return
        
        await state.update_data(promo_amount=amount)
        await state.set_state(BetStates.admin_creating_promo_uses)
        
        data = await state.get_data()
        code = data.get('promo_code')
        
        await message.answer(
            f"<b>➕ Создание промокода</b>\n\n"
            f"🎁 Код: <code>{code}</code>\n"
            f"💰 Сумма: {amount} USDT\n\n"
            f"Введите максимальное количество активаций:"
        )
    except ValueError:
        await message.answer("❌ Неверный формат суммы! Введите число.")


@dp.message(BetStates.admin_creating_promo_uses)
async def process_promo_uses(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        max_uses = int(message.text)
        if max_uses <= 0:
            await message.answer("❌ Количество должно быть больше 0!")
            return
        
        data = await state.get_data()
        code = data.get('promo_code')
        amount = data.get('promo_amount')
        
        success = create_promocode(code, amount, max_uses)
        
        if success:
            await message.answer(
                f"✅ <b>Промокод создан!</b>\n\n"
                f"🎁 Код: <code>{code}</code>\n"
                f"💰 Сумма: {amount} USDT\n"
                f"📊 Активаций: 0/{max_uses}"
            )
        else:
            await message.answer(f"❌ Промокод <code>{code}</code> уже существует!")
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный формат! Введите целое число.")

async def main():
    init_db()
    logger.info("🚀 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
   
