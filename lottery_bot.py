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

# Токены из .env
BOT_TOKEN = os.getenv('8285134993:AAG2KWUw-UEj7RqAv79PJgopKu1xueR5njU')
CRYPTO_BOT_TOKEN = os.getenv('512423:AAjvv90onLsaYycj668hryY9Mrkd9wjJoNT')
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x]

# Инициализация бота
BOT_TOKEN = "8285134993:AAG2KWUw-UEj7RqAv79PJgopKu1xueR5njU"
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# Состояния FSM
class BetStates(StatesGroup):
    choosing_game = State()
    choosing_bet_type = State()
    choosing_amount = State()
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
        'Гол': {'odds': 2.5, 'check': lambda x: x in [4, 5]},
        'Застрял': {'odds': 5.0, 'check': lambda x: x == 3},
        'Мимо': {'odds': 1.5, 'check': lambda x: x in [1, 2]},
    },
    'football': {
        'Гол': {'odds': 2.8, 'check': lambda x: x in [3, 4, 5]},
        'Мимо': {'odds': 1.4, 'check': lambda x: x in [1, 2]},
    },
    'darts': {
        'Центр': {'odds': 5.0, 'check': lambda x: x == 6},
        'Красное': {'odds': 3.0, 'check': lambda x: x in [4, 5]},
        'Белое': {'odds': 2.0, 'check': lambda x: x in [2, 3]},
        'Мимо': {'odds': 1.3, 'check': lambda x: x == 1},
    },
    'bowling': {
        'Страйк': {'odds': 4.5, 'check': lambda x: x == 6},
        'Мимо': {'odds': 1.2, 'check': lambda x: x in [1, 2, 3, 4, 5]},
    }
}

# Суммы ставок
BET_AMOUNTS = [1, 5, 10, 25, 50, 100]


# Инициализация БД
def init_db():
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()

    # Таблица пользователей
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

    # Таблица игр
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

    # Таблица транзакций
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
        INSERT OR IGNORE INTO users (user_id, username, first_name)
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

    # Записываем игру
    cursor.execute('''
        INSERT INTO games (user_id, game_type, bet_type, bet_amount, result_value, win, payout)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, game_type, bet_type, bet_amount, result_value, win, payout))

    # Обновляем статистику пользователя
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


def admin_panel_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Функции для работы с CryptoBot
async def create_invoice(amount: float, description: str):
    """Создание инвойса через CryptoBot API"""
    import aiohttp
    import ssl
    import certifi

    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {
        "Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN
    }
    data = {
        "asset": "USDT",
        "amount": str(amount),
        "description": description,
        "paid_btn_name": "callback",
        "paid_btn_url": f"https://t.me/{(await bot.get_me()).username}"
    }

    # Создаем SSL контекст с правильными сертификатами
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.post(url, headers=headers, json=data) as resp:
            if resp.status == 200:
                result = await resp.json()
                if result.get('ok'):
                    return result['result']
    return None


async def check_invoice(invoice_id: str):
    """Проверка статуса инвойса"""
    import aiohttp
    import ssl
    import certifi

    url = f"https://pay.crypt.bot/api/getInvoices"
    headers = {
        "Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN
    }
    params = {
        "invoice_ids": invoice_id
    }

    # Создаем SSL контекст с правильными сертификатами
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status == 200:
                result = await resp.json()
                if result.get('ok') and result['result']['items']:
                    return result['result']['items'][0]
    return None


async def auto_check_payment(message: types.Message, user_id: int, invoice_id: str, state: FSMContext):
    """Автоматическая проверка оплаты каждые 3 секунды в течение 5 минут"""
    max_attempts = 100  # 100 * 3 сек = 5 минут
    attempt = 0

    while attempt < max_attempts:
        await asyncio.sleep(3)
        attempt += 1

        invoice = await check_invoice(invoice_id)

        if invoice and invoice['status'] == 'paid':
            amount = float(invoice['amount'])

            # Начисляем баланс
            update_balance(user_id, amount)

            # Записываем транзакцию
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

            # Проверяем что это - игра или просто пополнение
            data = await state.get_data()
            is_deposit_only = data.get('is_deposit_only', False)

            if is_deposit_only:
                # Просто пополнение
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
                # Игра - запускаем СРАЗУ без сообщения
                game_id = data.get('game_id')
                bet_type = data.get('bet_type')
                bet_amount = data.get('bet_amount')

                if game_id and bet_type and bet_amount:
                    await process_game(message, user_id, game_id, bet_type, bet_amount, state)

            return

    # Время вышло
    try:
        await message.edit_text(
            "⏰ Время ожидания оплаты истекло.\n"
            "Если вы оплатили счет, средства будут зачислены автоматически."
        )
    except:
        pass
    await state.clear()


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


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔️ У вас нет доступа к админ-панели!")
        return

    await message.answer(
        "<b>⚙️ Админ панель</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_panel_keyboard()
    )


# Обработчики кнопок меню
@dp.message(F.text == "🎮 Играть")
async def menu_play(message: types.Message, state: FSMContext):
    await state.set_state(BetStates.choosing_game)
    await message.answer(
        "<b>🎮 Выбери игру:</b>",
        reply_markup=games_keyboard()
    )


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
async def menu_deposit(message: types.Message):
    await message.answer(
        "<b>➕ Пополнение баланса</b>\n\n"
        "Выберите сумму пополнения:",
        reply_markup=bet_amounts_keyboard()
    )


@dp.message(F.text == "📊 Статистика")
async def menu_stats(message: types.Message):
    user_id = message.from_user.id

    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()

    # Последние 10 игр
    cursor.execute('''
        SELECT game_type, bet_type, bet_amount, win, payout, created_at
        FROM games
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 10
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
        await message.answer("⛔️ У вас нет доступа к админ-панели!")
        return

    await message.answer(
        "<b>⚙️ Админ панель</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_panel_keyboard()
    )


# Обработчики callback-запросов
@dp.callback_query(F.data.startswith("game_"))
async def callback_choose_game(callback: types.CallbackQuery, state: FSMContext):
    game_id = callback.data.split("_")[1]

    await state.update_data(game_id=game_id)
    await state.set_state(BetStates.choosing_bet_type)

    game_emoji = GAMES[game_id]['emoji']
    game_name = GAMES[game_id]['name']

    await callback.message.edit_text(
        f"<b>{game_emoji} {game_name}</b>\n\n"
        f"Выбери тип ставки:",
        reply_markup=bet_types_keyboard(game_id)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("bettype_"))
async def callback_choose_bet_type(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 2)
    game_id = parts[1]
    bet_type = parts[2]

    await state.update_data(bet_type=bet_type)
    await state.set_state(BetStates.choosing_amount)

    game_emoji = GAMES[game_id]['emoji']
    game_name = GAMES[game_id]['name']
    odds = BET_TYPES[game_id][bet_type]['odds']

    await callback.message.edit_text(
        f"<b>{game_emoji} {game_name}</b>\n"
        f"<b>Ставка:</b> {bet_type} (x{odds})\n\n"
        f"Выбери сумму ставки:",
        reply_markup=bet_amounts_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("amount_"))
async def callback_choose_amount(callback: types.CallbackQuery, state: FSMContext):
    amount = float(callback.data.split("_")[1])
    user_id = callback.from_user.id
    balance = get_balance(user_id)

    data = await state.get_data()
    game_id = data.get('game_id')
    bet_type = data.get('bet_type')

    # Проверяем, что это ставка из игры, а не просто пополнение
    if not game_id or not bet_type:
        # Это обычное пополнение баланса
        await state.set_state(BetStates.waiting_payment)

        invoice = await create_invoice(
            amount,
            f"Пополнение баланса {amount} USDT"
        )

        if invoice:
            await state.update_data(
                invoice_id=invoice['invoice_id'],
                deposit_amount=amount,
                is_deposit_only=True
            )
            await callback.message.edit_text(
                f"<b>💳 Пополнение баланса</b>\n\n"
                f"Сумма: <b>{amount} USDT</b>\n\n"
                f"Нажмите кнопку ниже для оплаты.\n"
                f"После оплаты баланс будет автоматически зачислен.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Оплатить", url=invoice['pay_url'])],
                    [InlineKeyboardButton(text="✖️ Отменить", callback_data="cancel_payment")]
                ])
            )
            # Запускаем фоновую проверку оплаты
            asyncio.create_task(auto_check_payment(callback.message, user_id, invoice['invoice_id'], state))
        else:
            await callback.message.edit_text("❌ Ошибка создания платежа. Попробуйте позже.")
            await state.clear()

        await callback.answer()
        return

    # Это ставка в игре
    if balance >= amount:
        # Сразу играем, если баланс достаточен
        await process_game(callback.message, user_id, game_id, bet_type, amount, state)
        await callback.answer()
    else:
        # Нужно пополнить
        await state.update_data(bet_amount=amount)
        await state.set_state(BetStates.waiting_payment)

        game_emoji = GAMES[game_id]['emoji']
        game_name = GAMES[game_id]['name']

        # Создаем инвойс
        invoice = await create_invoice(
            amount,
            f"Ставка {amount} USDT на {game_emoji} {bet_type}"
        )

        if invoice:
            await state.update_data(invoice_id=invoice['invoice_id'])
            await callback.message.edit_text(
                f"<b>💳 Оплата ставки</b>\n\n"
                f"Сумма: <b>{amount} USDT</b>\n"
                f"Игра: {game_emoji} {game_name}\n"
                f"Ставка: {bet_type}\n\n"
                f"Нажмите кнопку ниже для оплаты.\n"
                f"После оплаты игра запустится автоматически! 🎮",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Оплатить", url=invoice['pay_url'])],
                    [InlineKeyboardButton(text="✖️ Отменить", callback_data="cancel_payment")]
                ])
            )
            # Запускаем фоновую проверку оплаты
            asyncio.create_task(auto_check_payment(callback.message, user_id, invoice['invoice_id'], state))
        else:
            await callback.message.edit_text("❌ Ошибка создания платежа. Попробуйте позже.")
            await state.clear()

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
    await callback.message.answer(
        "🏠 Главное меню",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data == "back_games")
async def callback_back_games(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BetStates.choosing_game)
    await callback.message.edit_text(
        "<b>🎮 Выбери игру:</b>",
        reply_markup=games_keyboard()
    )
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
        f"<b>{game_emoji} {game_name}</b>\n\n"
        f"Выбери тип ставки:",
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

    # Общая статистика
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
        await callback.message.edit_text(
            "👥 Пользователи не найдены.",
            reply_markup=admin_panel_keyboard()
        )
        await callback.answer()
        return

    text = "<b>👥 Топ-10 пользователей по балансу:</b>\n\n"
    for i, user in enumerate(users[:10], 1):
        user_id, username, first_name, balance = user[0], user[1], user[2], user[3]
        username_display = f"@{username}" if username else first_name
        text += f"{i}. {username_display}\n   💰 {balance:.2f} USDT\n\n"

    await callback.message.edit_text(
        text,
        reply_markup=admin_panel_keyboard()
    )
    await callback.answer()


# Основная функция игры
async def process_game(message: types.Message, user_id: int, game_id: str,
                       bet_type: str, bet_amount: float, state: FSMContext):
    """Обработка игры"""

    if game_id not in GAMES:
        await message.answer("❌ Ошибка: неизвестная игра!")
        await state.clear()
        return

    game_emoji = GAMES[game_id]['emoji']
    game_name = GAMES[game_id]['name']
    dice_emoji_type = GAMES[game_id]['dice_emoji']

    # Отправляем анимированное эмодзи
    dice_message = await message.answer_dice(emoji=dice_emoji_type)
    result_value = dice_message.dice.value

    # Ждем окончания анимации
    await asyncio.sleep(4)

    # Проверяем результат
    check_func = BET_TYPES[game_id][bet_type]['check']
    win = check_func(result_value)
    odds = BET_TYPES[game_id][bet_type]['odds']
    payout = bet_amount * odds if win else 0

    # Записываем результат
    record_game(user_id, game_emoji, bet_type, bet_amount, result_value, win, payout)

    # Формируем сообщение о результате
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

    # Кнопки для продолжения
    buttons = [
        [InlineKeyboardButton(text="🔄 Играть еще", callback_data="back_games")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_main")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(result_text, reply_markup=keyboard)
    await state.clear()


# Запуск бота
async def main():
    init_db()
    logger.info("База данных инициализирована")

    # Удаляем webhook перед запуском polling
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook удален")

    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
