import os
import sqlite3
import asyncio
import logging
from datetime import datetime
from typing import Optional
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, DiceEmoji
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ИСПРАВЛЕНО: Токены правильно загружаются
BOT_TOKEN = os.getenv('BOT_TOKEN', '8509674494:AAE3NZ_WP_Ha8z0EvRRnFQKunrskioQWorU')
CRYPTO_BOT_TOKEN = os.getenv('CRYPTO_BOT_TOKEN', '512423:AAjvv90onLsaYycj668hryY9Mrkd9wjJoNT')
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x]

# ВАЖНО: Telegram Stars платежи
# Все Telegram Stars платежи автоматически начисляются на баланс владельца бота.
# Владелец бота - это Telegram аккаунт, который создал бота через @BotFather.
# Чтобы получать Stars на нужный аккаунт, убедитесь что бот создан этим аккаунтом.
# Stars можно вывести или использовать на другие цели через Telegram.

logger.info(f"BOT_TOKEN загружен: {BOT_TOKEN[:20]}...")
logger.info(f"CRYPTO_BOT_TOKEN загружен: {CRYPTO_BOT_TOKEN[:20]}...")

# Инициализация бота
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# Состояния FSM
class BetStates(StatesGroup):
    choosing_game = State()
    choosing_bet_type = State()
    choosing_amount = State()
    entering_custom_amount = State()  
    entering_custom_stars = State()
    waiting_payment = State()


# Константы игр
GAMES = {
    'dice': {'emoji': '🎲', 'name': 'Кубик', 'dice_emoji': DiceEmoji.DICE},
    'basketball': {'emoji': '🏀', 'name': 'Баскетбол', 'dice_emoji': DiceEmoji.BASKETBALL},
    'football': {'emoji': '⚽', 'name': 'Футбол', 'dice_emoji': DiceEmoji.FOOTBALL},
    'darts': {'emoji': '🎯', 'name': 'Дартс', 'dice_emoji': DiceEmoji.DART},
    'bowling': {'emoji': '🎳', 'name': 'Боулинг', 'dice_emoji': DiceEmoji.BOWLING}
}

# Типы ставок и коэффициенты
BET_TYPES = {
    'dice': {
        'Четное': {'odds': 1.9, 'check': lambda x: x in [2, 4, 6]},
        'Нечетное': {'odds': 1.9, 'check': lambda x: x in [1, 3, 5]},
        'Больше 3': {'odds': 1.9, 'check': lambda x: x > 3},
        'Меньше 4': {'odds': 1.9, 'check': lambda x: x <= 3},
    },
    'basketball': {
        'Гол': {'odds': 1.9, 'check': lambda x: x in [4, 5]},
        'Застрял': {'odds': 1.9, 'check': lambda x: x == 3},
        'Мимо': {'odds': 1.9, 'check': lambda x: x in [1, 2]},
    },
    'football': {
        'Гол': {'odds': 1.9, 'check': lambda x: x in [3, 4, 5]},
        'Мимо': {'odds': 1.9, 'check': lambda x: x in [1, 2]},
    },
    'darts': {
        'Центр': {'odds': 1.9, 'check': lambda x: x == 6},
        'Красное': {'odds': 1.9, 'check': lambda x: x in [4, 5]},
        'Белое': {'odds': 1.9, 'check': lambda x: x in [2, 3]},
        'Мимо': {'odds': 1.9, 'check': lambda x: x == 1},
    },
    'bowling': {
        'Страйк': {'odds': 1.9, 'check': lambda x: x == 6},
        'Мимо': {'odds': 1.9, 'check': lambda x: x in [1, 2, 3, 4, 5]},
    }
}

# Суммы ставок
BET_AMOUNTS = [1, 5, 10, 25, 50, 100]

# Суммы Telegram Stars (для пополнения) - в Stars
STAR_AMOUNTS = [50, 100, 200, 500, 1000, 2500, 5000, 10000]

# Курс: 100 Stars = 2 USDT, значит 1 Star = 0.02 USDT
STARS_TO_USDT_RATE = 0.02

# Инициализация БД
def init_db():
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()

    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS users
                   (
                       user_id
                       INTEGER
                       PRIMARY
                       KEY,
                       username
                       TEXT,
                       first_name
                       TEXT,
                       balance
                       REAL
                       DEFAULT
                       0,
                       total_deposited
                       REAL
                       DEFAULT
                       0,
                       total_withdrawn
                       REAL
                       DEFAULT
                       0,
                       total_wagered
                       REAL
                       DEFAULT
                       0,
                       total_won
                       REAL
                       DEFAULT
                       0,
                       total_lost
                       REAL
                       DEFAULT
                       0,
                       games_played
                       INTEGER
                       DEFAULT
                       0,
                       wins
                       INTEGER
                       DEFAULT
                       0,
                       losses
                       INTEGER
                       DEFAULT
                       0,
                       created_at
                       TIMESTAMP
                       DEFAULT
                       CURRENT_TIMESTAMP
                   )
                   ''')

    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS games
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       user_id
                       INTEGER,
                       game_type
                       TEXT,
                       bet_type
                       TEXT,
                       bet_amount
                       REAL,
                       result_value
                       INTEGER,
                       win
                       BOOLEAN,
                       payout
                       REAL,
                       created_at
                       TIMESTAMP
                       DEFAULT
                       CURRENT_TIMESTAMP,
                       FOREIGN
                       KEY
                   (
                       user_id
                   ) REFERENCES users
                   (
                       user_id
                   )
                       )
                   ''')

    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS transactions
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       user_id
                       INTEGER,
                       type
                       TEXT,
                       amount
                       REAL,
                       status
                       TEXT,
                       invoice_id
                       TEXT,
                       payment_method
                       TEXT
                       DEFAULT
                       'cryptobot',
                       created_at
                       TIMESTAMP
                       DEFAULT
                       CURRENT_TIMESTAMP,
                       FOREIGN
                       KEY
                   (
                       user_id
                   ) REFERENCES users
                   (
                       user_id
                   )
                       )
                   ''')
    
    # Add payment_method column if it doesn't exist (for existing databases)
    cursor.execute('''
                   PRAGMA table_info(transactions)
                   ''')
    columns = [column[1] for column in cursor.fetchall()]
    if 'payment_method' not in columns:
        cursor.execute('''
                       ALTER TABLE transactions ADD COLUMN payment_method TEXT DEFAULT 'cryptobot'
                       ''')

    conn.commit()
    conn.close()


# Функции для работы с БД
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
    cursor.execute('''
                   INSERT
                   OR IGNORE INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
                   ''', (user_id, username, first_name))
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
                       UPDATE users
                       SET balance       = balance + ?,
                           total_wagered = total_wagered + ?,
                           total_won     = total_won + ?,
                           games_played  = games_played + 1,
                           wins          = wins + 1
                       WHERE user_id = ?
                       ''', (payout - bet_amount, bet_amount, payout, user_id))
    else:
        cursor.execute('''
                       UPDATE users
                       SET balance       = balance - ?,
                           total_wagered = total_wagered + ?,
                           total_lost    = total_lost + ?,
                           games_played  = games_played + 1,
                           losses        = losses + 1
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


# Клавиатуры
def main_keyboard():
    keyboard = [
        [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="➕ Пополнить"), KeyboardButton(text="📊 Статистика")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def admin_keyboard():
    keyboard = [
        [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="➕ Пополнить"), KeyboardButton(text="📊 Статистика")],
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


def bet_amounts_keyboard():
    buttons = []
    row = []
    for i, amount in enumerate(BET_AMOUNTS):
        row.append(InlineKeyboardButton(text=f"{amount} USDT", callback_data=f"amount_{amount}"))
        if (i + 1) % 3 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_bettypes")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_method_keyboard(amount: float, purpose: str = "deposit"):
    """
    Creates keyboard for selecting payment method
    purpose: 'deposit' or 'bet'
    """
    buttons = [
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"paymethod_stars_{amount}_{purpose}")],
        [InlineKeyboardButton(text="💵 CryptoBot (USDT)", callback_data=f"paymethod_cryptobot_{amount}_{purpose}")],
        [InlineKeyboardButton(text="✖️ Отменить", callback_data="cancel_payment")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_panel_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Функции для работы с CryptoBot - С ЛОГИРОВАНИЕМ
async def create_invoice(amount: float, description: str):
    import aiohttp
    import ssl
    import certifi

    if not CRYPTO_BOT_TOKEN:
        logger.error("❌ CRYPTO_BOT_TOKEN не установлен!")
        return None

    logger.info(f"🔄 Создание инвойса: {amount} USDT")

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
                    logger.info(f"✅ Инвойс создан: {result['result']['invoice_id']}")
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

    logger.info(f"🔍 Проверка инвойса: {invoice_id}")

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
    logger.info(f"⏳ Запуск автопроверки платежа для инвойса {invoice_id}")

    max_attempts = 100
    attempt = 0

    while attempt < max_attempts:
        await asyncio.sleep(3)
        attempt += 1

        invoice = await check_invoice(invoice_id)

        if invoice and invoice.get('status') == 'paid':
            logger.info(f"✅ Платеж получен!")
            amount = float(invoice['amount'])

            update_balance(user_id, amount)

            conn = sqlite3.connect('lottery_bot.db')
            cursor = conn.cursor()
            cursor.execute('''
                           INSERT INTO transactions (user_id, type, amount, status, invoice_id, payment_method)
                           VALUES (?, 'deposit', ?, 'completed', ?, 'cryptobot')
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

    logger.warning(f"⏰ Время ожидания оплаты истекло для инвойса {invoice_id}")
    try:
        await message.edit_text(
            "⏰ Время ожидания оплаты истекло.\n"
            "Если вы оплатили счет, средства будут зачислены автоматически."
        )
    except:
        pass
    await state.clear()


# Функции для работы с Telegram Stars
async def create_stars_invoice(user_id: int, stars_amount: int, title: str, description: str, payload: str):
    """Создание инвойса Telegram Stars. Курс: 100 Stars = 2 USDT"""
    try:
        logger.info(f"⭐ Создание Stars инвойса: {stars_amount} Stars для user {user_id}")
        
        await bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=description,
            payload=payload,
            currency="XTR",
            prices=[types.LabeledPrice(label="Пополнение", amount=stars_amount)],
            provider_token=""  # Для Stars пустая строка
        )
        logger.info(f"✅ Stars инвойс отправлен")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка Stars инвойса: {e}")
        return False
        
        # Send invoice using bot.send_invoice
        # Telegram Stars автоматически начисляются на баланс владельца бота
        await bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",  # Не требуется для Telegram Stars
            currency="XTR",  # XTR - код валюты для Telegram Stars
            prices=[types.LabeledPrice(label=title, amount=stars_amount)],
            start_parameter=payload,
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            send_phone_number_to_provider=False,
            send_email_to_provider=False,
            is_flexible=False
        )
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка создания инвойса Telegram Stars: {e}")
        return False


async def process_stars_payment(user_id: int, stars_amount: int, state: FSMContext, purpose: str = "deposit", message: types.Message = None):
    """
    Process successful Telegram Stars payment
    stars_amount: amount paid in stars
    """
    # Convert stars to USDT
    amount_usdt = stars_amount * STARS_TO_USDT_RATE
    
    logger.info(f"✅ Обработка платежа Telegram Stars: {stars_amount} stars (${amount_usdt:.2f})")
    
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    invoice_id = f"stars_{user_id}_{datetime.now().timestamp()}"
    
    if purpose == "deposit":
        # Add to balance
        update_balance(user_id, amount_usdt)
        
        cursor.execute('''
                       INSERT INTO transactions (user_id, type, amount, status, invoice_id, payment_method)
                       VALUES (?, 'deposit', ?, 'completed', ?, 'stars')
                       ''', (user_id, amount_usdt, invoice_id))
        cursor.execute(
            'UPDATE users SET total_deposited = total_deposited + ? WHERE user_id = ?',
            (amount_usdt, user_id)
        )
        conn.commit()
        conn.close()
        
        response_text = (
            f"✔️ <b>Оплата получена!</b>\n\n"
            f"На ваш баланс зачислено <b>${amount_usdt:.2f}</b> ({stars_amount} ⭐)\n"
            f"Текущий баланс: <b>${get_balance(user_id):.2f}</b>"
        )
        if message:
            try:
                await message.edit_text(response_text)
            except:
                await message.answer(response_text)
        await state.clear()
        return True
    else:
        # Bet payment - check if amount is sufficient
        data = await state.get_data()
        game_id = data.get('game_id')
        bet_type = data.get('bet_type')
        bet_amount = data.get('bet_amount')
        
        if not game_id or not bet_type or not bet_amount:
            logger.error(f"❌ Отсутствуют данные игры для платежа: game_id={game_id}, bet_type={bet_type}, bet_amount={bet_amount}")
            conn.close()
            if message:
                await message.answer("❌ Ошибка: данные игры не найдены. Обратитесь к администратору.")
            await state.clear()
            return False
        
        # Check if payment is sufficient
        if amount_usdt < bet_amount:
            # Payment insufficient
            remaining = bet_amount - amount_usdt
            conn.close()
            if message:
                await message.answer(
                    f"❌ Недостаточно Stars! Зачислено ${amount_usdt:.2f}, нужно ${bet_amount:.2f}.\n"
                    f"Недостает: ${remaining:.2f}"
                )
            await state.clear()
            return False
        
        # Payment is sufficient - add full amount to balance, then deduct bet amount
        update_balance(user_id, amount_usdt)
        
        cursor.execute('''
                       INSERT INTO transactions (user_id, type, amount, status, invoice_id, payment_method)
                       VALUES (?, 'deposit', ?, 'completed', ?, 'stars')
                       ''', (user_id, amount_usdt, invoice_id))
        cursor.execute(
            'UPDATE users SET total_deposited = total_deposited + ? WHERE user_id = ?',
            (amount_usdt, user_id)
        )
        conn.commit()
        conn.close()
        
        # Now deduct the bet amount (excess will remain in balance)
        update_balance(user_id, -bet_amount)
        
        # Process the game
        if message:
            await process_game(message, user_id, game_id, bet_type, bet_amount, state)
        return True


# Обработчики команд
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
        f"🎲 Кубик - четное/нечетное/больше/меньше\n"
        f"🏀 Баскетбол - гол/застрял/мимо\n"
        f"⚽ Футбол - гол/мимо\n"
        f"🎯 Дартс - центр/красное/белое/мимо\n"
        f"🎳 Боулинг - страйк/мимо\n\n"
        f"Выбери действие из меню ниже ⬇️",
        reply_markup=keyboard
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
    
    # Show payment method selection with inline buttons
    buttons = [
        [InlineKeyboardButton(text="⭐ Пополнить Stars", callback_data="deposit_method_stars")],
        [InlineKeyboardButton(text="💵 Пополнить USDT", callback_data="deposit_method_usdt")],
    ]
    
    await message.answer(
        "<b>➕ Пополнение баланса</b>\n\n"
        "Выберите способ пополнения:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.message(F.text == "📊 Статистика")
async def menu_stats(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT game_type, bet_type, bet_amount, win, payout, created_at
                   FROM games
                   WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT 10
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


@dp.callback_query(F.data.startswith("game_"))
async def callback_choose_game(callback: types.CallbackQuery, state: FSMContext):
    game_id = callback.data.split("_")[1]
    await state.update_data(game_id=game_id)
    await state.set_state(BetStates.choosing_bet_type)

    game_emoji = GAMES[game_id]['emoji']
    game_name = GAMES[game_id]['name']

    await callback.message.edit_text(
        f"<b>{game_emoji} {game_name}</b>\n\nВыбери тип ставки:",
        reply_markup=bet_types_keyboard(game_id)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("bettype_"))
async def callback_choose_bet_type(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 2)
    game_id = parts[1]
    bet_type = parts[2]

    await state.update_data(bet_type=bet_type)
    await state.set_state(BetStates.entering_custom_amount)  # Сразу переходим к вводу суммы

    game_emoji = GAMES[game_id]['emoji']
    game_name = GAMES[game_id]['name']
    odds = BET_TYPES[game_id][bet_type]['odds']

    await callback.message.edit_text(
        f"<b>{game_emoji} {game_name}</b>\n"
        f"<b>Ставка:</b> {bet_type} (x{odds})\n\n"
        f"💰 <b>Введите сумму ставки (от 1 USDT):</b>\n\n"
        f"<i>Примеры: 5 или 10.5 или 25</i>"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("amount_"))
async def callback_choose_amount(callback: types.CallbackQuery, state: FSMContext):
    amount = float(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    data = await state.get_data()
    is_deposit_only = data.get('is_deposit_only', False)
    
    # ТОЛЬКО ДЛЯ ПОПОЛНЕНИЯ БАЛАНСА
    if is_deposit_only:
        await state.update_data(deposit_amount=amount, is_deposit_only=True)
        await state.set_state(BetStates.waiting_payment)
        
        await callback.message.edit_text(
            f"<b>💳 Пополнение баланса</b>\n\n"
            f"Сумма: <b>{amount} USDT</b>\n\n"
            f"Выберите способ оплаты:",
            reply_markup=payment_method_keyboard(amount, "deposit")
        )
        await callback.answer()
    else:
        await callback.answer("❌ Используйте ввод суммы текстом", show_alert=True)

@dp.callback_query(F.data.startswith("paymethod_"))
async def callback_choose_payment_method(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    method = parts[1]  # 'stars' or 'cryptobot'
    amount = float(parts[2])
    purpose = parts[3]  # 'deposit' or 'bet'
    
    user_id = callback.from_user.id
    
    if method == "stars":
        # Show star amounts selection
        await state.update_data(
            deposit_amount=amount,
            payment_purpose=purpose,
            required_usdt_amount=amount if purpose == "bet" else None
        )
        
        if purpose == "deposit":
            await callback.message.edit_text(
                f"<b>⭐ Telegram Stars</b>\n\n"
                f"Выберите количество Stars для пополнения:\n"
                f"<b>Курс:</b> 100 Stars = $2 USDT",
                reply_markup=stars_amounts_keyboard("deposit")
            )
        else:
            data = await state.get_data()
            game_id = data.get('game_id')
            bet_type = data.get('bet_type')
            game_emoji = GAMES[game_id]['emoji'] if game_id else "🎮"
            game_name = GAMES[game_id]['name'] if game_id else "Игра"
            
            # Calculate minimum stars needed
            min_stars = int(amount / STARS_TO_USDT_RATE)
            if min_stars % 100 != 0:
                min_stars = ((min_stars // 100) + 1) * 100
            
            await callback.message.edit_text(
                f"<b>⭐ Telegram Stars</b>\n\n"
                f"Игра: {game_emoji} {game_name}\n"
                f"Ставка: {bet_type}\n"
                f"Нужно: <b>{amount} USDT</b> (минимум {min_stars} Stars)\n\n"
                f"<b>Курс:</b> 100 Stars = $2 USDT\n"
                f"Выберите количество Stars для оплаты:",
                reply_markup=stars_amounts_keyboard("bet", required_usdt=amount)
            )
    
    elif method == "cryptobot":
        # Create CryptoBot invoice
        if purpose == "deposit":
            description = f"Пополнение баланса {amount} USDT"
        else:
            data = await state.get_data()
            game_id = data.get('game_id')
            bet_type = data.get('bet_type')
            game_emoji = GAMES[game_id]['emoji'] if game_id else "🎮"
            description = f"Ставка {amount} USDT на {game_emoji} {bet_type}"
        
        invoice = await create_invoice(amount, description)
        
        if invoice:
            await state.update_data(invoice_id=invoice['invoice_id'])
            await callback.message.edit_text(
                f"<b>💵 CryptoBot (USDT)</b>\n\n"
                f"Сумма: <b>{amount} USDT</b>\n\n"
                f"Нажмите кнопку ниже для оплаты.\n"
                f"После оплаты баланс будет автоматически зачислен.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Оплатить", url=invoice['pay_url'])],
                    [InlineKeyboardButton(text="✖️ Отменить", callback_data="cancel_payment")]
                ])
            )
            asyncio.create_task(auto_check_payment(callback.message, user_id, invoice['invoice_id'], state))
        else:
            await callback.message.edit_text("❌ Ошибка создания платежа. Попробуйте позже.")
            await state.clear()
    
    await callback.answer()

@dp.callback_query(F.data.startswith("paymethod_stars_"))
async def callback_payment_stars(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    usdt_amount = float(parts[2])
    purpose = parts[3]  # 'deposit' or 'bet'
    
    user_id = callback.from_user.id
    
    await state.update_data(
        payment_method="stars",
        required_usdt_amount=usdt_amount,
        payment_purpose=purpose
    )
    await state.set_state(BetStates.entering_custom_stars)
    
    if purpose == "deposit":
        min_stars = 50
        await callback.message.edit_text(
            f"<b>⭐ Telegram Stars</b>\n\n"
            f"Сумма пополнения: <b>{usdt_amount} USDT</b>\n\n"
            f"💫 <b>Введите количество Stars (от {min_stars}):</b>\n\n"
            f"<b>Курс:</b> 50 Stars = 1 USDT\n\n"
            f"<i>Примеры:\n"
            f"• 50 Stars = 1 USDT\n"
            f"• 100 Stars = 2 USDT\n"
            f"• 250 Stars = 5 USDT\n"
            f"• 500 Stars = 10 USDT</i>"
        )
    else:
        min_stars = int(usdt_amount / STARS_TO_USDT_RATE)
        if min_stars < 50:
            min_stars = 50
        
        data = await state.get_data()
        game_id = data.get('game_id')
        bet_type = data.get('bet_type')
        game_emoji = GAMES[game_id]['emoji'] if game_id else "🎮"
        game_name = GAMES[game_id]['name'] if game_id else "Игра"
        
        await callback.message.edit_text(
            f"<b>⭐ Telegram Stars</b>\n\n"
            f"Игра: {game_emoji} {game_name}\n"
            f"Ставка: {bet_type}\n"
            f"Нужно: <b>{usdt_amount} USDT</b>\n\n"
            f"💫 <b>Введите количество Stars (минимум {min_stars}):</b>\n\n"
            f"<b>Курс:</b> 50 Stars = 1 USDT\n\n"
            f"<i>Например: {min_stars} или {min_stars + 50} Stars</i>"
        )
    
    await callback.answer()


@dp.callback_query(F.data == "back_payment_method")
async def callback_back_payment_method(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    amount = data.get('deposit_amount') or data.get('bet_amount', 0)
    purpose = data.get('payment_purpose', 'deposit')
    is_deposit_only = data.get('is_deposit_only', False)
    
    # If it's a direct deposit without a specific amount (direct stars deposit), go back to deposit method selection
    if is_deposit_only and purpose == "deposit" and (amount == 0 or not amount):
        buttons = [
            [InlineKeyboardButton(text="⭐ Пополнить Stars", callback_data="deposit_method_stars")],
            [InlineKeyboardButton(text="💵 Пополнить USDT", callback_data="deposit_method_usdt")],
        ]
        await callback.message.edit_text(
            "<b>➕ Пополнение баланса</b>\n\n"
            "Выберите способ пополнения:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    else:
        # For bet payments or deposits with specific USDT amount, show payment method selection
        if amount > 0:
            await callback.message.edit_text(
                f"<b>💳 {'Пополнение баланса' if purpose == 'deposit' else 'Оплата ставки'}</b>\n\n"
                f"Сумма: <b>{amount} USDT</b>\n\n"
                f"Выберите способ оплаты:",
                reply_markup=payment_method_keyboard(amount, purpose)
            )
        else:
            # Fallback to deposit method selection
            buttons = [
                [InlineKeyboardButton(text="⭐ Пополнить Stars", callback_data="deposit_method_stars")],
                [InlineKeyboardButton(text="💵 Пополнить USDT", callback_data="deposit_method_usdt")],
            ]
            await callback.message.edit_text(
                "<b>➕ Пополнение баланса</b>\n\n"
                "Выберите способ пополнения:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
    await callback.answer()


@dp.callback_query(F.data == "deposit_method_stars")
async def callback_deposit_method_stars(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(is_deposit_only=True, payment_purpose="deposit")
    await callback.message.edit_text(
        f"<b>⭐ Пополнение Telegram Stars</b>\n\n"
        f"Выберите количество Stars для пополнения:\n"
        f"<b>Курс:</b> 100 Stars = $2 USDT",
        reply_markup=stars_amounts_keyboard("deposit")
    )
    await callback.answer()


@dp.callback_query(F.data == "deposit_method_usdt")
async def callback_deposit_method_usdt(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(is_deposit_only=True)
    await callback.message.edit_text(
        "<b>➕ Пополнение баланса USDT</b>\n\n"
        "Выберите сумму пополнения:",
        reply_markup=bet_amounts_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "cancel_payment")
async def callback_cancel_payment(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("✖️ Платеж отменен.")
    await callback.answer()


@dp.callback_query(F.data == "back_main")
async def callback_back_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    keyboard = admin_keyboard() if callback.from_user.id in ADMIN_IDS else main_keyboard()
    await callback.message.delete()
    await callback.message.answer("🏠 Главное меню", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "back_games")
async def callback_back_games(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BetStates.choosing_game)
    await callback.message.edit_text("<b>🎮 Выбери игру:</b>", reply_markup=games_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "back_bettypes")
async def callback_back_bettypes(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    game_id = data.get('game_id')

    if not game_id:
        await callback_back_games(callback, state)
        return

    await state.set_state(BetStates.choosing_bet_type)
    game_emoji = GAMES[game_id]['emoji']
    game_name = GAMES[game_id]['name']

    await callback.message.edit_text(
        f"<b>{game_emoji} {game_name}</b>\n\nВыбери тип ставки:",
        reply_markup=bet_types_keyboard(game_id)
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Доступ запрещен!", show_alert=True)
        return

    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]

    cursor.execute('SELECT SUM(balance) FROM users')
    total_balance = cursor.fetchone()[0] or 0

    cursor.execute('SELECT SUM(total_deposited) FROM users')
    total_deposited = cursor.fetchone()[0] or 0

    cursor.execute('SELECT SUM(total_wagered) FROM users')
    total_wagered = cursor.fetchone()[0] or 0

    cursor.execute('SELECT COUNT(*) FROM games')
    total_games = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM games WHERE win = 1')
    total_wins = cursor.fetchone()[0]

    conn.close()

    house_profit = total_deposited - total_balance
    win_rate = (total_wins / total_games * 100) if total_games > 0 else 0

    await callback.message.edit_text(
        f"<b>📊 Общая статистика</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"💰 Общий баланс: {total_balance:.2f} USDT\n"
        f"📥 Всего депозитов: {total_deposited:.2f} USDT\n"
        f"🎮 Всего ставок: {total_wagered:.2f} USDT\n"
        f"📊 Игр сыграно: {total_games}\n"
        f"✔️ Выигрышей: {total_wins}\n"
        f"📈 Винрейт игроков: {win_rate:.1f}%\n"
        f"💵 Профит казино: {house_profit:.2f} USDT",
        reply_markup=admin_panel_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_users")
async def callback_admin_users(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Доступ запрещен!", show_alert=True)
        return

    users = get_all_users()

    if not users:
        await callback.message.edit_text("👥 Пользователи не найдены.", reply_markup=admin_panel_keyboard())
        await callback.answer()
        return

    text = "<b>👥 Топ-10 пользователей по балансу:</b>\n\n"
    for i, user in enumerate(users[:10], 1):
        user_id, username, first_name, balance = user[0], user[1], user[2], user[3]
        username_display = f"@{username}" if username else first_name
        text += f"{i}. {username_display}\n   💰 {balance:.2f} USDT\n\n"

    await callback.message.edit_text(text, reply_markup=admin_panel_keyboard())
    await callback.answer()

@dp.message(BetStates.entering_custom_amount)
async def process_custom_amount(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    try:
        # Преобразуем в число
        amount = float(message.text.replace(',', '.').strip())
        
        # Проверяем минимум
        if amount < 1:
            await message.answer("❌ Минимальная сумма - 1 USDT\n\nВведите снова:")
            return
        
        # Проверяем максимум
        if amount > 10000:
            await message.answer("❌ Максимальная сумма - 10,000 USDT\n\nВведите снова:")
            return
        
        # Округляем до 2 знаков
        amount = round(amount, 2)
        
        # Получаем данные игры
        data = await state.get_data()
        game_id = data.get('game_id')
        bet_type = data.get('bet_type')
        balance = get_balance(user_id)
        
        if balance >= amount:
            # Баланса достаточно - играем
            await process_game(message, user_id, game_id, bet_type, amount, state)
        else:
            # Нужно пополнить
            await state.update_data(bet_amount=amount)
            await state.set_state(BetStates.waiting_payment)
            
            game_emoji = GAMES[game_id]['emoji']
            game_name = GAMES[game_id]['name']
            
            await message.answer(
                f"<b>💳 Оплата ставки</b>\n\n"
                f"Сумма: <b>{amount} USDT</b>\n"
                f"Игра: {game_emoji} {game_name}\n"
                f"Ставка: {bet_type}\n\n"
                f"Выберите способ оплаты:",
                reply_markup=payment_method_keyboard(amount, "bet")
            )
    
    except ValueError:
        await message.answer(
            "❌ Неверный формат!\n\n"
            "Введите число. Примеры:\n"
            "• 5\n"
            "• 10.5\n"
            "• 25"
        )

@dp.message(BetStates.entering_custom_stars)
async def process_custom_stars(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    try:
        # Преобразуем в целое число Stars
        stars_amount = int(message.text.strip())
        
        # Проверяем минимум
        if stars_amount < 50:
            await message.answer("❌ Минимум 50 Stars\n\nВведите снова:")
            return
        
        # Проверяем что кратно 50 (опционально, можно убрать)
        # if stars_amount % 50 != 0:
        #     await message.answer("❌ Сумма должна быть кратна 50 Stars\n\nВведите снова:")
        #     return
        
        # Проверяем максимум
        if stars_amount > 500000:
            await message.answer("❌ Максимум 500,000 Stars\n\nВведите снова:")
            return
        
        # Конвертируем в USDT
        amount_usdt = stars_amount * STARS_TO_USDT_RATE
        amount_usdt = round(amount_usdt, 2)
        
        # Получаем данные
        data = await state.get_data()
        purpose = data.get('payment_purpose', 'deposit')
        required_amount = data.get('required_usdt_amount', 0)
        
        # Для ставки проверяем что хватает
        if purpose == "bet" and amount_usdt < required_amount:
            shortage = required_amount - amount_usdt
            min_stars_needed = int(required_amount / STARS_TO_USDT_RATE)
            await message.answer(
                f"❌ Недостаточно!\n\n"
                f"Вы ввели: {stars_amount} Stars ({amount_usdt} USDT)\n"
                f"Нужно минимум: {min_stars_needed} Stars ({required_amount} USDT)\n"
                f"Не хватает: {shortage} USDT\n\n"
                f"Введите больше Stars:"
            )
            return
        
        # Создаем payload
        payload = f"{user_id}_{stars_amount}_{purpose}_{datetime.now().timestamp()}"
        
        await state.update_data(
            stars_payload=payload,
            stars_amount=stars_amount,
            stars_amount_usdt=amount_usdt
        )
        
        # Создаем инвойс
        if purpose == "deposit":
            title = "Пополнение баланса"
            description = f"Пополнение {amount_usdt} USDT ({stars_amount} Stars)"
        else:
            game_id = data.get('game_id')
            bet_type = data.get('bet_type')
            game_emoji = GAMES[game_id]['emoji'] if game_id else "🎮"
            game_name = GAMES[game_id]['name'] if game_id else "Игра"
            title = f"Ставка {game_emoji}"
            description = f"Ставка {amount_usdt} USDT на {game_name} - {bet_type}"
        
        success = await create_stars_invoice(user_id, stars_amount, title, description, payload)
        
        if success:
            await message.answer(
                f"<b>⭐ Telegram Stars</b>\n\n"
                f"Сумма: <b>{stars_amount} Stars</b> ({amount_usdt} USDT)\n\n"
                f"Проверьте Telegram для оплаты.\n"
                f"После оплаты {'баланс будет зачислен' if purpose == 'deposit' else 'игра запустится'} автоматически! 🎮",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✖️ Отменить", callback_data="cancel_payment")]
                ])
            )
        else:
            await message.answer("❌ Ошибка создания платежа Stars. Попробуйте позже.")
            await state.clear()
    
    except ValueError:
        await message.answer(
            "❌ Неверный формат!\n\n"
            "Введите целое число Stars.\n\n"
            "Примеры:\n"
            "• 50\n"
            "• 100\n"
            "• 250\n"
            "• 500"
        )



Примеры:
- 50 Stars = 1 USDT
- 100 Stars = 2 USDT
- 250 Stars = 5 USDT
- 500 Stars = 10 USDT
        
@dp.message(F.text == "⚙️ Админ панель")
async def menu_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔️ У вас нет доступа к админ-панели!")
        return

    await message.answer("<b>⚙️ Админ панель</b>\n\nВыберите действие:", reply_markup=admin_panel_keyboard())


async def process_game(message: types.Message, user_id: int, game_id: str, bet_type: str, bet_amount: float,
                       state: FSMContext):
    if game_id not in GAMES:
        await message.answer("❌ Ошибка: неизвестная игра!")
        await state.clear()
        return

    game_emoji = GAMES[game_id]['emoji']
    game_name = GAMES[game_id]['name']
    dice_emoji_type = GAMES[game_id]['dice_emoji']

    dice_message = await message.answer_dice(emoji=dice_emoji_type)
    result_value = dice_message.dice.value

    await asyncio.sleep(4)

    check_func = BET_TYPES[game_id][bet_type]['check']
    win = check_func(result_value)
    odds = BET_TYPES[game_id][bet_type]['odds']
    payout = bet_amount * odds if win else 0

    record_game(user_id, game_emoji, bet_type, bet_amount, result_value, win, payout)

    if win:
        profit = payout - bet_amount
        result_text = (
            f"✔️ <b>ПОБЕДА!</b> ✔️\n\n"
            f"{game_emoji} Выпало: <b>{result_value}</b>\n"
            f"Твоя ставка: {bet_type}\n"
            f"Коэффициент: x{odds}\n\n"
            f"💰 Выигрыш: <b>+{profit:.2f} USDT</b>\n"
            f"💵 Баланс: {get_balance(user_id):.2f} USDT"
        )
    else:
        result_text = (
            f"✖️ <b>ПРОИГРЫШ</b> ✖️\n\n"
            f"{game_emoji} Выпало: <b>{result_value}</b>\n"
            f"Твоя ставка: {bet_type}\n\n"
            f"💸 Потеря: <b>-{bet_amount:.2f} USDT</b>\n"
            f"💵 Баланс: {get_balance(user_id):.2f} USDT"
        )

    buttons = [
        [InlineKeyboardButton(text="🔄 Играть еще", callback_data="back_games")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_main")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(result_text, reply_markup=keyboard)
    await state.clear()


# Обработчики платежей Telegram Stars
@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    logger.info(f"🔍 Pre-checkout: {pre_checkout_query.invoice_payload}")
    
    # ВСЕГДА подтверждаем
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    
    try:
        # Разбираем payload: user_id_stars_amount_purpose_timestamp
        parts = payload.split("_")
        if len(parts) >= 3:
            user_id = int(parts[0])
            stars_amount = int(parts[1])
            purpose = parts[2]
            
            # Проверяем, что пользователь существует и сумма корректна
            if stars_amount in STAR_AMOUNTS and user_id == pre_checkout_query.from_user.id:
                await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
                logger.info(f"✅ Pre-checkout подтвержден: {stars_amount} stars от пользователя {user_id}")
                return
        
        # Если проверка не прошла
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Ошибка проверки платежа")
        logger.error(f"❌ Pre-checkout отклонен: {payload}")
    except Exception as e:
        logger.error(f"❌ Ошибка обработки pre-checkout: {e}")
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Ошибка обработки платежа")


@dp.message(F.content_type == types.ContentType.SUCCESSFUL_PAYMENT)
async def process_successful_payment(message: types.Message, state: FSMContext):
    """
    Обработчик успешного платежа Telegram Stars
    """
    successful_payment = message.successful_payment
    payload = successful_payment.invoice_payload
    user_id = message.from_user.id
    
    logger.info(f"✅ Успешный платеж: {payload}, сумма: {successful_payment.total_amount} {successful_payment.currency}")
    
    try:
        # Разбираем payload: user_id_stars_amount_purpose_timestamp
        parts = payload.split("_")
        if len(parts) >= 3:
            stars_amount = int(parts[1])
            purpose = parts[2]
            
            # Проверяем, что сумма совпадает
            if successful_payment.currency == "XTR" and successful_payment.total_amount == stars_amount:
                # Обрабатываем платеж (process_stars_payment уже вызывает process_game для bet payments)
                success = await process_stars_payment(user_id, stars_amount, state, purpose, message)
                if not success:
                    await message.answer("❌ Ошибка обработки платежа. Обратитесь к администратору.")
            else:
                logger.error(f"❌ Несоответствие суммы: ожидалось {stars_amount}, получено {successful_payment.total_amount}")
                await message.answer("❌ Ошибка: несоответствие суммы платежа. Обратитесь к администратору.")
        else:
            logger.error(f"❌ Неверный формат payload: {payload}")
            await message.answer("❌ Ошибка обработки платежа. Обратитесь к администратору.")
    except Exception as e:
        logger.error(f"❌ Ошибка обработки успешного платежа: {e}")
        await message.answer("❌ Ошибка обработки платежа. Обратитесь к администратору.")

# ============= АДМИНСКИЕ КОМАНДЫ =============

@dp.message(Command("balance"))
async def cmd_check_balance(message: types.Message):
    """Проверить баланс игрока: /balance <user_id>"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔️ У вас нет доступа к этой команде!")
        return
    
    # Парсим команду
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "❌ Неверный формат!\n\n"
            "<b>Использование:</b>\n"
            "<code>/balance USER_ID</code>\n\n"
            "Пример: <code>/balance 123456789</code>"
        )
        return
    
    try:
        target_user_id = int(parts[1])
    except ValueError:
        await message.answer("❌ USER_ID должен быть числом!")
        return
    
    # Получаем данные пользователя
    user = get_user(target_user_id)
    
    if not user:
        await message.answer(f"❌ Пользователь с ID {target_user_id} не найден!")
        return
    
    # Распаковываем данные
    user_id, username, first_name, balance, total_deposited, total_withdrawn, total_wagered, total_won, total_lost, games_played, wins, losses, created_at = user
    
    win_rate = (wins / games_played * 100) if games_played > 0 else 0
    profit = total_won - total_lost
    
    await message.answer(
        f"<b>👤 Информация о пользователе</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Имя: {first_name}\n"
        f"📱 Username: @{username if username else 'нет'}\n\n"
        f"💰 <b>Баланс: {balance:.2f} USDT</b>\n\n"
        f"📊 Всего депозитов: {total_deposited:.2f} USDT\n"
        f"📤 Всего выводов: {total_withdrawn:.2f} USDT\n"
        f"🎮 Всего ставок: {total_wagered:.2f} USDT\n"
        f"✔️ Выиграно: {total_won:.2f} USDT\n"
        f"✖️ Проиграно: {total_lost:.2f} USDT\n"
        f"💵 Профит: {profit:+.2f} USDT\n\n"
        f"🎲 Игр сыграно: {games_played}\n"
        f"✔️ Побед: {wins}\n"
        f"✖️ Поражений: {losses}\n"
        f"📈 Винрейт: {win_rate:.1f}%\n\n"
        f"📅 Регистрация: {created_at}"
    )


@dp.message(Command("reset"))
async def cmd_reset_balance(message: types.Message):
    """Обнулить баланс игрока: /reset <user_id>"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔️ У вас нет доступа к этой команде!")
        return
    
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "❌ Неверный формат!\n\n"
            "<b>Использование:</b>\n"
            "<code>/reset USER_ID</code>\n\n"
            "Пример: <code>/reset 123456789</code>"
        )
        return
    
    try:
        target_user_id = int(parts[1])
    except ValueError:
        await message.answer("❌ USER_ID должен быть числом!")
        return
    
    user = get_user(target_user_id)
    
    if not user:
        await message.answer(f"❌ Пользователь с ID {target_user_id} не найден!")
        return
    
    old_balance = user[3]
    username = user[1]
    first_name = user[2]
    
    # Обнуляем баланс
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = 0 WHERE user_id = ?', (target_user_id,))
    conn.commit()
    conn.close()
    
    logger.info(f"⚠️ Админ {message.from_user.id} обнулил баланс пользователя {target_user_id} ({old_balance} → 0 USDT)")
    
    await message.answer(
        f"✅ <b>Баланс обнулен!</b>\n\n"
        f"👤 Пользователь: {first_name} (@{username if username else 'нет'})\n"
        f"🆔 ID: <code>{target_user_id}</code>\n\n"
        f"💰 Старый баланс: {old_balance:.2f} USDT\n"
        f"💰 Новый баланс: 0.00 USDT"
    )


@dp.message(Command("setbalance"))
async def cmd_set_balance(message: types.Message):
    """Установить баланс игрока: /setbalance <user_id> <amount>"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔️ У вас нет доступа к этой команде!")
        return
    
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer(
            "❌ Неверный формат!\n\n"
            "<b>Использование:</b>\n"
            "<code>/setbalance USER_ID AMOUNT</code>\n\n"
            "Примеры:\n"
            "<code>/setbalance 123456789 100</code>\n"
            "<code>/setbalance 123456789 50.5</code>"
        )
        return
    
    try:
        target_user_id = int(parts[1])
        new_balance = float(parts[2])
    except ValueError:
        await message.answer("❌ Неверный формат! USER_ID и AMOUNT должны быть числами!")
        return
    
    if new_balance < 0:
        await message.answer("❌ Баланс не может быть отрицательным!")
        return
    
    if new_balance > 1000000:
        await message.answer("❌ Максимальный баланс - 1,000,000 USDT!")
        return
    
    user = get_user(target_user_id)
    
    if not user:
        await message.answer(f"❌ Пользователь с ID {target_user_id} не найден!")
        return
    
    old_balance = user[3]
    username = user[1]
    first_name = user[2]
    
    # Устанавливаем новый баланс
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, target_user_id))
    conn.commit()
    conn.close()
    
    logger.info(f"⚠️ Админ {message.from_user.id} изменил баланс пользователя {target_user_id} ({old_balance} → {new_balance} USDT)")
    
    await message.answer(
        f"✅ <b>Баланс изменен!</b>\n\n"
        f"👤 Пользователь: {first_name} (@{username if username else 'нет'})\n"
        f"🆔 ID: <code>{target_user_id}</code>\n\n"
        f"💰 Старый баланс: {old_balance:.2f} USDT\n"
        f"💰 Новый баланс: {new_balance:.2f} USDT\n\n"
        f"Изменение: {new_balance - old_balance:+.2f} USDT"
    )


@dp.message(Command("adminhelp"))
async def cmd_admin_help(message: types.Message):
    """Список админских команд"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔️ У вас нет доступа к этой команде!")
        return
    
    await message.answer(
        "<b>⚙️ Админские команды</b>\n\n"
        "<b>Управление балансами:</b>\n"
        "<code>/balance USER_ID</code> - проверить баланс игрока\n"
        "<code>/reset USER_ID</code> - обнулить баланс\n"
        "<code>/setbalance USER_ID AMOUNT</code> - установить баланс\n\n"
        "<b>Примеры:</b>\n"
        "<code>/balance 123456789</code>\n"
        "<code>/reset 123456789</code>\n"
        "<code>/setbalance 123456789 100</code>\n\n"
        "<b>Другие команды:</b>\n"
        "/admin - админ панель\n"
        "/adminhelp - эта справка"
    )
```

---

## Как использовать:

### 1. **Проверить баланс игрока:**
```
/balance 123456789
```
Покажет полную информацию о пользователе.

---

### 2. **Обнулить баланс:**
```
/reset 123456789
```
Установит баланс в 0.

---

### 3. **Установить баланс:**
```
/setbalance 123456789 100
```
Установит баланс 100 USDT.

---

### 4. **Справка по командам:**
```
/adminhelp


async def main():
    init_db()
    logger.info("База данных инициализирована")

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook удален")

    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())

   
