import os
import sqlite3
import asyncio
import logging
import requests
import time
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
from pytonconnect import TonConnect
import base64

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
TON_TO_USDT_RATE = 5.5  # Запасной курс если API не работает

def get_ton_price() -> float:
    """Получить актуальный курс TON/USDT с CoinGecko"""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            price = data.get("the-open-network", {}).get("usd", TON_TO_USDT_RATE)
            logger.info(f"💱 Актуальный курс TON: ${price}")
            return float(price)
        else:
            logger.warning(f"⚠️ API не работает, используется запасной курс {TON_TO_USDT_RATE}")
            return TON_TO_USDT_RATE
    except Exception as e:
        logger.error(f"❌ Ошибка получения курса TON: {e}")
        return TON_TO_USDT_RATE

class BetStates(StatesGroup):
    choosing_game = State()
    choosing_bet_type = State()
    entering_custom_amount = State()
    entering_custom_stars = State()
    waiting_payment = State()
    waiting_ton_payment = State()
    admin_entering_user_id = State()
    admin_entering_balance = State()
    entering_promocode = State()
    admin_creating_promo_code = State()
    admin_creating_promo_amount = State()
    admin_creating_promo_uses = State()
    admin_broadcast = State()


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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            referrer_id INTEGER,
            bonus_paid BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (referrer_id) REFERENCES users (user_id)
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
        # При выигрыше: добавляем чистую прибыль (payout - bet_amount)
        profit = payout - bet_amount
        cursor.execute('''
            UPDATE users SET 
                balance = balance + ?,
                total_wagered = total_wagered + ?,
                total_won = total_won + ?,
                games_played = games_played + 1,
                wins = wins + 1
            WHERE user_id = ?
        ''', (profit, bet_amount, payout, user_id))
    else:
        # При проигрыше: вычитаем ставку
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
    
  
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    

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

def get_referral_link(user_id: int) -> str:
    bot_username = "ffortunna_bot"  
    return f"https://t.me/{bot_username}?start=ref_{user_id}"


def add_referral(user_id: int, referrer_id: int) -> bool:
    """Добавить реферала (БЕЗ начисления бонуса)"""
    if user_id == referrer_id:
        return False
    
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    
   
    cursor.execute('SELECT * FROM referrals WHERE user_id = ?', (user_id,))
    if cursor.fetchone():
        conn.close()
        return False
    
   
    cursor.execute('''
        INSERT INTO referrals (user_id, referrer_id, bonus_paid)
        VALUES (?, ?, 0)
    ''', (user_id, referrer_id))
    
    conn.commit()
    conn.close()
    return True


def pay_referral_bonus(user_id: int, deposit_amount: float):
    """Начислить 5% рефереру от пополнения"""
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    
    # Находим реферера
    cursor.execute('SELECT referrer_id FROM referrals WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if result:
        referrer_id = result[0]
        bonus = deposit_amount * 0.05  # 5% от суммы
        
        # Начисляем бонус рефереру
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', 
                       (bonus, referrer_id))
        
        # Записываем транзакцию
        cursor.execute('''
            INSERT INTO transactions (user_id, type, amount, status, invoice_id)
            VALUES (?, 'referral_bonus', ?, 'completed', ?)
        ''', (referrer_id, bonus, f"ref_{user_id}_{deposit_amount}"))
        
        conn.commit()
        conn.close()
        
        return referrer_id, bonus
    
    conn.close()
    return None, 0


def get_referral_stats(user_id: int):

    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT COUNT(*), COALESCE(SUM(CASE WHEN bonus_paid = 1 THEN 1 ELSE 0 END), 0)
        FROM referrals WHERE referrer_id = ?
    ''', (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    total_refs = result[0] if result else 0
    paid_refs = result[1] if result else 0
    
    return total_refs, paid_refs


def get_referrals_list(user_id: int):

    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT u.user_id, u.first_name, u.username, r.created_at, r.bonus_paid
        FROM referrals r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.referrer_id = ?
        ORDER BY r.created_at DESC
        LIMIT 20
    ''', (user_id,))
    
    refs = cursor.fetchall()
    conn.close()
    return refs

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
        [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="📊 Статистика")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def admin_keyboard():
    keyboard = [
        [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="➕ Пополнить"), KeyboardButton(text="🎁 Промокод")],
        [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="📊 Статистика")],
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
        [InlineKeyboardButton(text="💠 TON Wallet", callback_data=f"pay_ton_{amount}_{purpose}")],
        [InlineKeyboardButton(text="✖️ Отменить", callback_data="cancel_payment")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_panel_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="💰 Управление балансами", callback_data="admin_balances")],
        [InlineKeyboardButton(text="🎁 Управление промокодами", callback_data="admin_promocodes")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],  # ← ДОБАВЬ ЭТО
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

           
            referrer_id, bonus = pay_referral_bonus(user_id, amount)
            if referrer_id:
                try:
                    await bot.send_message(
                        referrer_id,
                        f"💰 <b>Реферальный бонус!</b>\n\n"
                        f"Ваш реферал пополнил баланс на {amount} USDT\n"
                        f"🎁 Вам начислено: <b>{bonus:.2f} USDT</b> (5%)"
                    )
                except:
                    pass

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


async def check_ton_transaction(wallet_address: str, amount_ton: float, comment: str, timeout: int = 600):
    """
    Автоматическая проверка TON транзакции
    wallet_address - адрес получателя
    amount_ton - сумма в TON
    comment - комментарий для поиска
    timeout - время ожидания в секундах (10 минут)
    """
    logger.info(f"🔍 Запуск проверки TON транзакции: {amount_ton} TON, комментарий: {comment}")
    
    start_time = time.time()
    check_interval = 5  # Проверяем каждые 5 секунд
    
    # API endpoint для проверки транзакций (используем TON API)
    api_url = f"https://tonapi.io/v2/blockchain/accounts/{wallet_address}/transactions"
    
    last_checked_lt = None
    
    while time.time() - start_time < timeout:
        try:
            # Получаем последние транзакции
            params = {"limit": 10}
            if last_checked_lt:
                params["before_lt"] = last_checked_lt
            
            response = requests.get(api_url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                transactions = data.get("transactions", [])
                
                for tx in transactions:
                    # Проверяем входящую транзакцию
                    if tx.get("in_msg"):
                        in_msg = tx["in_msg"]
                        
                        # Получаем сумму
                        value = int(in_msg.get("value", 0)) / 1_000_000_000  # Конвертируем из nanoTON
                        
                        # Получаем комментарий
                        msg_data = in_msg.get("message", "")
                        tx_comment = ""
                        
                        if isinstance(msg_data, str) and msg_data:
                            try:
                                # Декодируем Base64 комментарий
                                decoded = base64.b64decode(msg_data).decode('utf-8', errors='ignore')
                                tx_comment = decoded
                            except:
                                tx_comment = msg_data
                        
                        # Проверяем совпадение суммы и комментария
                        if abs(value - amount_ton) < 0.01 and comment.lower() in tx_comment.lower():
                            logger.info(f"✅ TON транзакция найдена! Сумма: {value}, комментарий: {tx_comment}")
                            return True, tx
                
                # Обновляем последний проверенный lt
                if transactions:
                    last_checked_lt = transactions[0].get("lt")
            else:
                logger.warning(f"⚠️ Ошибка API TON: {response.status_code}")
        
        except Exception as e:
            logger.error(f"❌ Ошибка проверки TON транзакции: {e}")
        
        await asyncio.sleep(check_interval)
    
    logger.warning(f"⏰ Время ожидания TON транзакции истекло")
    return False, None


async def auto_check_ton_payment(message: types.Message, user_id: int, payment_id: str, 
                                 amount_ton: float, amount_usdt: float, state: FSMContext):
    """Автоматическая проверка и зачисление TON платежа"""
    logger.info(f"⏳ Запуск автопроверки TON платежа для {payment_id}")
    
    # Проверяем транзакцию
    found, transaction = await check_ton_transaction(
        wallet_address=TON_WALLET_ADDRESS,
        amount_ton=amount_ton,
        comment=payment_id,
        timeout=600  # 10 минут
    )
    
    if found:
        logger.info(f"✅ TON платеж получен!")
        
        # Начисляем баланс
        update_balance(user_id, amount_usdt)
        
        # Записываем транзакцию
        conn = sqlite3.connect('lottery_bot.db')
        cursor = conn.cursor()
        invoice_id = f"ton_{payment_id}"
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
        
        # Начисляем реферальный бонус
        referrer_id, bonus = pay_referral_bonus(user_id, amount_usdt)
        if referrer_id:
            try:
                await bot.send_message(
                    referrer_id,
                    f"💰 <b>Реферальный бонус!</b>\n\n"
                    f"Ваш реферал пополнил баланс на {amount_usdt} USDT\n"
                    f"🎁 Вам начислено: <b>{bonus:.2f} USDT</b> (5%)"
                )
            except:
                pass
        
        # Проверяем цель платежа
        data = await state.get_data()
        is_deposit_only = data.get('is_deposit_only', False)
        
        if is_deposit_only:
            # Обычное пополнение
            try:
                await message.edit_text(
                    f"✅ <b>TON платеж получен!</b>\n\n"
                    f"💠 Оплачено: {amount_ton} TON\n"
                    f"💰 Зачислено: <b>{amount_usdt} USDT</b>\n"
                    f"💵 Ваш баланс: <b>{get_balance(user_id):.2f} USDT</b>"
                )
            except:
                await bot.send_message(
                    user_id,
                    f"✅ <b>TON платеж получен!</b>\n\n"
                    f"💠 Оплачено: {amount_ton} TON\n"
                    f"💰 Зачислено: <b>{amount_usdt} USDT</b>\n"
                    f"💵 Ваш баланс: <b>{get_balance(user_id):.2f} USDT</b>"
                )
            await state.clear()
        else:
            # Пополнение для ставки
            game_id = data.get('game_id')
            bet_type = data.get('bet_type')
            bet_amount = data.get('bet_amount')
            
            if game_id and bet_type and bet_amount:
                await process_game(message, user_id, game_id, bet_type, bet_amount, state)
        
        return True
    else:
        # Транзакция не найдена
        logger.warning(f"⏰ TON платеж не получен в течение 10 минут")
        try:
            await message.edit_text(
                f"⏰ <b>Время ожидания истекло</b>\n\n"
                f"Платеж не был найден в течение 10 минут.\n\n"
                f"Если вы отправили {amount_ton} TON с комментарием:\n"
                f"<code>{payment_id}</code>\n\n"
                f"Средства будут зачислены автоматически при поступлении.\n"
                f"Или свяжитесь с поддержкой."
            )
        except:
            pass
        
        await state.clear()
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

                # ← ДОБАВЬ ЭТО: Начисляем 5% рефереру
                referrer_id, bonus = pay_referral_bonus(user_id, amount_usdt)
                if referrer_id:
                    try:
                        await bot.send_message(
                            referrer_id,
                            f"💰 <b>Реферальный бонус!</b>\n\n"
                            f"Ваш реферал пополнил баланс на {amount_usdt} USDT\n"
                            f"🎁 Вам начислено: <b>{bonus:.2f} USDT</b> (5%)"
                        )
                    except:
                        pass

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
    
    
    if message.text and len(message.text.split()) > 1:
        args = message.text.split()[1]
        if args.startswith('ref_'):
            try:
                referrer_id = int(args.split('_')[1])
                if add_referral(user_id, referrer_id):
                    # Уведомляем реферера
                    try:
                        await bot.send_message(
                            referrer_id,
                            f"🎉 <b>Новый реферал!</b>\n\n"
                            f"👤 {first_name} присоединился по вашей ссылке!\n"
                            f"💰 Вы будете получать <b>5% от всех его пополнений</b>"
                        )
                    except:
                        pass
                    
                   
                    await message.answer(
                        f"🎁 <b>Добро пожаловать!</b>\n\n"
                        f"Вы присоединились по реферальной ссылке!\n"
                        f"Приглашайте друзей и получайте бонусы! 💰"
                    )
            except:
                pass

    keyboard = admin_keyboard() if user_id in ADMIN_IDS else main_keyboard()
    
   
    ref_link = get_referral_link(user_id)
    inline_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Моя реферальная ссылка", callback_data="show_ref_link")],
        [InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся к лотерейному боту! 🎰")]
    ])

    await message.answer(
        f"<b>🎰 Добро пожаловать в Лотерейного Бота!</b>\n\n"
        f"Привет, {first_name}! 👋\n\n"
        f"<b>Доступные игры:</b>\n"
        f"🎲 Кубик\n🏀 Баскетбол\n⚽ Футбол\n🎯 Дартс\n🎳 Боулинг\n\n"
        f"<b>Способы оплаты:</b>\n"
        f"⭐️ Telegram Stars (50 Stars = 1 USDT)\n"
        f"💎 Криптовалюта (USDT)\n"
        f"💠 TON Wallet\n\n"
        f"🎁 <b>Приглашай друзей и получай 5% от их пополнений!</b>\n\n"
        f"Выбери действие из меню ниже ⬇️",
        reply_markup=keyboard
    )
    
   
    await message.answer(
        "💰 <b>Начни зарабатывать прямо сейчас!</b>",
        reply_markup=inline_keyboard
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
    
    await state.update_data(game_id=game_id, bet_type=bet_type, is_deposit_only=False)
    await state.set_state(BetStates.entering_custom_amount)
    
    game_name = GAMES[game_id]['name']
    odds = BET_TYPES[game_id][bet_type]['odds']
    
    await callback.message.edit_text(
        f"<b>🎮 {game_name}</b>\n"
        f"<b>🎯 Ставка:</b> {bet_type} (x{odds})\n\n"
        f"💰 <b>Введите сумму ставки (от 1 USDT):</b>\n\n"
        f"<i>Примеры: 1 или 5 или 10 или 25</i>"
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
            # Это пополнение баланса
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
                # Достаточно средств - играем (баланс спишется в record_game)
                await state.update_data(bet_amount=amount)
                await process_game(message, user_id, game_id, bet_type, amount, state)
            else:
                # Недостаточно средств - предлагаем пополнить
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

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    
    await state.set_state(BetStates.admin_broadcast)
    await callback.message.edit_text(
        "<b>📢 Рассылка сообщения</b>\n\n"
        "Отправьте сообщение которое хотите разослать всем пользователям.\n\n"
        "Можно отправить:\n"
        "• Текст\n"
        "• Фото с текстом\n"
        "• Видео с текстом\n\n"
        "Отправьте /cancel для отмены"
    )
    await callback.answer()


@dp.message(BetStates.admin_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    if message.text == "/cancel":
        await message.answer("❌ Рассылка отменена")
        await state.clear()
        return
    
    users = get_all_users()
    total = len(users)
    success = 0
    failed = 0
    
    status_msg = await message.answer(
        f"📢 <b>Начинаю рассылку...</b>\n\n"
        f"Всего пользователей: {total}"
    )
    
    for user in users:
        user_id = user[0]
        try:
            if message.photo:
                await bot.send_photo(
                    user_id, 
                    message.photo[-1].file_id,
                    caption=message.caption or ""
                )
            elif message.video:
                await bot.send_video(
                    user_id,
                    message.video.file_id,
                    caption=message.caption or ""
                )
            elif message.text:
                await bot.send_message(user_id, message.text)
            
            success += 1
        except Exception as e:
            failed += 1
            logger.error(f"Ошибка рассылки для {user_id}: {e}")
        
        # Обновляем статус каждые 10 пользователей
        if (success + failed) % 10 == 0:
            try:
                await status_msg.edit_text(
                    f"📢 <b>Рассылка...</b>\n\n"
                    f"Всего: {total}\n"
                    f"✅ Отправлено: {success}\n"
                    f"❌ Ошибок: {failed}"
                )
            except:
                pass
        
        await asyncio.sleep(0.05)  # Задержка чтобы не получить бан
    
    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"Всего пользователей: {total}\n"
        f"✅ Успешно: {success}\n"
        f"❌ Ошибок: {failed}"
    )
    await state.clear()

@dp.message(F.text == "👥 Рефералы")
async def menu_referrals(message: types.Message):
    user_id = message.from_user.id
    
  
    total_refs, _ = get_referral_stats(user_id)
    ref_link = get_referral_link(user_id)
    
  
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COALESCE(SUM(amount), 0) FROM transactions 
        WHERE user_id = ? AND type = 'referral_bonus'
    ''', (user_id,))
    total_earned = cursor.fetchone()[0]
    conn.close()
    
    text = (
        f"<b>👥 Реферальная программа</b>\n\n"
        f"🎁 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"👤 Приглашено: {total_refs} чел.\n"
        f"💰 Заработано: {total_earned:.2f} USDT\n\n"
        f"<b>Условия:</b>\n"
        f"• За каждое пополнение друга: <b>5%</b>\n"
        f"• Бонус начисляется автоматически\n"
        f"• Бессрочно и без ограничений\n\n"
        f"Поделитесь ссылкой с друзьями! 🚀"
    )
    
 
    if total_refs > 0:
        refs = get_referrals_list(user_id)
        text += "\n\n<b>🎯 Ваши рефералы:</b>\n"
        for ref in refs[:5]:
            ref_id, name, username, created_at, _ = ref
            text += f"👤 {name} (@{username or 'нет'})\n"
        
        if total_refs > 5:
            text += f"\n<i>... и еще {total_refs - 5}</i>"
    
   
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📤 Поделиться ссылкой",
            url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся к лотерейному боту! 🎰"
        )]
    ])
    
    await message.answer(text, reply_markup=keyboard)

@dp.callback_query(F.data == "show_ref_link")
async def show_ref_link_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    ref_link = get_referral_link(user_id)
    
   
    total_refs, _ = get_referral_stats(user_id)
    
    
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COALESCE(SUM(amount), 0) FROM transactions 
        WHERE user_id = ? AND type = 'referral_bonus'
    ''', (user_id,))
    total_earned = cursor.fetchone()[0]
    conn.close()
    
    await callback.message.answer(
        f"<b>👥 Твоя реферальная ссылка:</b>\n\n"
        f"<code>{ref_link}</code>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"👤 Рефералов: {total_refs}\n"
        f"💰 Заработано: {total_earned:.2f} USDT\n\n"
        f"🎁 Получай <b>5% от каждого пополнения</b> друга!\n\n"
        f"Скопируй ссылку и отправь друзьям 👆",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся к лотерейному боту! 🎰")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_ton_"))
async def process_ton_payment(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    amount_usdt = float(parts[2])
    purpose = parts[3]
    
    user_id = callback.from_user.id
    
    # Получаем актуальный курс TON
    ton_rate = get_ton_price()
    
    # Конвертируем USDT в TON по актуальному курсу
    amount_ton = amount_usdt / ton_rate
    amount_ton = round(amount_ton, 3)
    
    # Генерируем уникальный комментарий для идентификации платежа
    payment_id = f"pay{user_id}{int(datetime.now().timestamp())}"
    
    # Сохраняем данные платежа
    await state.update_data(
        ton_payment_id=payment_id,
        ton_amount_usdt=amount_usdt,
        ton_amount_ton=amount_ton,
        is_deposit_only=(purpose == "deposit")
    )
    await state.set_state(BetStates.waiting_ton_payment)
    
    # Формируем ссылку на TON кошелёк
    ton_link = f"ton://transfer/{TON_WALLET_ADDRESS}?amount={int(amount_ton * 1_000_000_000)}&text={payment_id}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💠 Открыть TON Wallet", url=ton_link)],
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"ton_paid_{payment_id}")],
        [InlineKeyboardButton(text="✖️ Отменить", callback_data="cancel_payment")]
    ])
    
    await callback.message.edit_text(
        f"💠 <b>Оплата через TON Wallet</b>\n\n"
        f"💰 Сумма: <b>{amount_ton} TON</b> (= {amount_usdt} USDT)\n"
        f"💱 Курс: 1 TON = ${ton_rate}\n\n"
        f"📝 Адрес кошелька:\n<code>{TON_WALLET_ADDRESS}</code>\n\n"
        f"❗️ <b>ВАЖНО:</b> В комментарии к переводу укажите:\n"
        f"<code>{payment_id}</code>\n\n"
        f"<b>Инструкция:</b>\n"
        f"1. Нажмите «Открыть TON Wallet»\n"
        f"2. Переведите <b>{amount_ton} TON</b>\n"
        f"3. Убедитесь что комментарий указан\n"
        f"4. Нажмите «Я оплатил»\n\n"
        f"✅ Средства зачислятся <b>автоматически</b> в течение 1-2 минут",
        reply_markup=keyboard
    )
    
    await callback.answer()
  

@dp.callback_query(F.data.startswith("ton_paid_"))
async def confirm_ton_payment(callback: types.CallbackQuery, state: FSMContext):
    payment_id = callback.data.replace("ton_paid_", "")
    user_id = callback.from_user.id
    
    data = await state.get_data()
    
    if data.get('ton_payment_id') != payment_id:
        await callback.answer("❌ Ошибка идентификации платежа", show_alert=True)
        return
    
    amount_usdt = data.get('ton_amount_usdt')
    amount_ton = data.get('ton_amount_ton')
    
    status_message = await callback.message.edit_text(
        f"⏳ <b>Проверяем платеж...</b>\n\n"
        f"Ожидаем поступление {amount_ton} TON\n"
        f"Комментарий: <code>{payment_id}</code>\n\n"
        f"Это займет 1-2 минуты..."
    )
    
    await callback.answer("⏳ Проверяем транзакцию...")
    
    # Запускаем автопроверку в фоне
    asyncio.create_task(
        auto_check_ton_payment(
            status_message, 
            user_id, 
            payment_id, 
            amount_ton, 
            amount_usdt, 
            state
        )
    )


# Команда для админа - подтверждение TON платежа
@dp.message(Command("approve_ton"))
async def approve_ton_payment(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        parts = message.text.split()
        target_user_id = int(parts[1])
        amount_usdt = float(parts[2])
        
        # Начисляем баланс
        update_balance(target_user_id, amount_usdt)
        
        # Записываем транзакцию
        conn = sqlite3.connect('lottery_bot.db')
        cursor = conn.cursor()
        invoice_id = f"ton_{target_user_id}_{datetime.now().timestamp()}"
        cursor.execute('''
            INSERT INTO transactions (user_id, type, amount, status, invoice_id)
            VALUES (?, 'deposit', ?, 'completed', ?)
        ''', (target_user_id, amount_usdt, invoice_id))
        cursor.execute(
            'UPDATE users SET total_deposited = total_deposited + ? WHERE user_id = ?',
            (amount_usdt, target_user_id)
        )
        conn.commit()
        conn.close()
        
        # Начисляем реферальный бонус
        referrer_id, bonus = pay_referral_bonus(target_user_id, amount_usdt)
        if referrer_id:
            try:
                await bot.send_message(
                    referrer_id,
                    f"💰 <b>Реферальный бонус!</b>\n\n"
                    f"Ваш реферал пополнил баланс на {amount_usdt} USDT\n"
                    f"🎁 Вам начислено: <b>{bonus:.2f} USDT</b> (5%)"
                )
            except:
                pass
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                target_user_id,
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"💰 Зачислено: <b>{amount_usdt} USDT</b>\n"
                f"💵 Ваш баланс: <b>{get_balance(target_user_id):.2f} USDT</b>"
            )
        except:
            pass
        
        await message.answer(
            f"✅ <b>Платеж подтвержден!</b>\n\n"
            f"User: <code>{target_user_id}</code>\n"
            f"Сумма: {amount_usdt} USDT"
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}\n\nФормат: /approve_ton USER_ID AMOUNT")

@dp.message(Command("tonprice"))
async def cmd_ton_price(message: types.Message):
    """Показать текущий курс TON"""
    current_price = get_ton_price()
    
    await message.answer(
        f"💱 <b>Актуальный курс TON</b>\n\n"
        f"1 TON = <b>${current_price}</b> USDT\n\n"
        f"<b>Примеры конвертации:</b>\n"
        f"• 10 USDT = <b>{10/current_price:.3f} TON</b>\n"
        f"• 50 USDT = <b>{50/current_price:.3f} TON</b>\n"
        f"• 100 USDT = <b>{100/current_price:.3f} TON</b>\n\n"
        f"<i>Курс обновляется при каждой оплате</i>"
    )

async def main():
    init_db()
    logger.info("🚀 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
   
