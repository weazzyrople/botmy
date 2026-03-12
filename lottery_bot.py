import os
import sqlite3
import asyncio
import logging
import requests
import time
import sys
import subprocess
import base64
from datetime import datetime, timedelta
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

def ensure_watchfiles():
    try:
        import watchfiles
        print("✅ watchfiles уже установлен!")
        return True
    except ImportError:
        print("📦 watchfiles не найден. Устанавливаю автоматически...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "watchfiles"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print("✅ watchfiles успешно установлен!")
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            print(f"❌ Ошибка установки: {e}")
            return False


if '--reload' in sys.argv and __name__ == '__main__':
    if ensure_watchfiles():
        print("🔥 Запуск в режиме Hot Reload...")
        def run_bot():
            args = [arg for arg in sys.argv if arg != '--reload']
            return subprocess.Popen([sys.executable] + args)
        last_mtime = os.path.getmtime(__file__)
        process = run_bot()
        try:
            while True:
                time.sleep(1)
                current_mtime = os.path.getmtime(__file__)
                if current_mtime != last_mtime:
                    print("🔄 Файл изменён! Перезапускаю...")
                    process.terminate()
                    process.wait()
                    last_mtime = current_mtime
                    process = run_bot()
        except KeyboardInterrupt:
            print("\n🛑 Остановка бота...")
            process.terminate()
            process.wait()
        sys.exit(0)


load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
STATS_CHANNEL_ID = -1003692039981
WIN_TEMPLATE_MESSAGE_ID = 19
LOSE_TEMPLATE_MESSAGE_ID = 20

BOT_TOKEN = os.getenv('BOT_TOKEN', '8285134993:AAG2KWUw-UEj7RqAv79PJgopKu1xueR5njU')
CRYPTO_BOT_TOKEN = os.getenv('CRYPTO_BOT_TOKEN', '512423:AAjvv90onLsaYycj668hryY9Mrkd9wjJoNT')
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x]

logger.info(f"BOT_TOKEN загружен: {BOT_TOKEN[:20]}...")
logger.info(f"CRYPTO_BOT_TOKEN загружен: {CRYPTO_BOT_TOKEN[:20]}...")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

STARS_TO_USDT_RATE = 1 / 50
TON_TO_USDT_RATE = 5.5
TON_WALLET_ADDRESS = "UQDzTiMyO6C15cz1_n2dRLitZr7Q2FMCa4kDEG-cD7QHwcgZ"

VIP_LEVELS = {
    'bronze':   {'name': '🥉 Бронза',  'min_deposit': 0,   'cashback': 0.00},
    'silver':   {'name': '🥈 Серебро', 'min_deposit': 50,  'cashback': 0.01},
    'gold':     {'name': '🥇 Золото',  'min_deposit': 200, 'cashback': 0.02},
    'platinum': {'name': '💎 Платина', 'min_deposit': 500, 'cashback': 0.03},
}

def get_vip_level(total_deposited: float) -> str:
    if total_deposited >= 500:
        return 'platinum'
    elif total_deposited >= 200:
        return 'gold'
    elif total_deposited >= 50:
        return 'silver'
    return 'bronze'

def get_streak_bonus_multiplier(win_streak: int) -> float:
    if win_streak >= 10:
        return 0.01
    elif win_streak >= 5:
        return 0.005
    elif win_streak >= 3:
        return 0.003
    return 0.0

def get_streak_emoji(win_streak: int) -> str:
    if win_streak >= 10:
        return "🔥🔥🔥"
    elif win_streak >= 5:
        return "🔥🔥"
    elif win_streak >= 3:
        return "🔥"
    return ""

def get_ton_price() -> float:
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            price = data.get("the-open-network", {}).get("usd", TON_TO_USDT_RATE)
            logger.info(f"💱 Курс TON: ${price}")
            return float(price)
        return TON_TO_USDT_RATE
    except Exception as e:
        logger.error(f"❌ Ошибка курса TON: {e}")
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
    admin_deposit_search = State()
    duel_choosing_game = State()
    duel_entering_amount = State()
    duel_waiting_opponent = State()
    coin_entering_amount = State()
    tournament_entering_amount = State()
    entering_deposit_amount = State()

GAMES = {
    'dice':       {'emoji': '🎲', 'name': 'Кубик',     'dice_emoji': DiceEmoji.DICE},
    'basketball': {'emoji': '🏀', 'name': 'Баскетбол', 'dice_emoji': DiceEmoji.BASKETBALL},
    'football':   {'emoji': '⚽', 'name': 'Футбол',    'dice_emoji': DiceEmoji.FOOTBALL},
    'darts':      {'emoji': '🎯', 'name': 'Дартс',     'dice_emoji': DiceEmoji.DART},
    'bowling':    {'emoji': '🎳', 'name': 'Боулинг',   'dice_emoji': DiceEmoji.BOWLING},
}

BET_TYPES = {
    'dice': {
        'Четное':   {'odds': 2.0, 'check': lambda x: x in [2, 4, 6]},
        'Нечетное': {'odds': 2.0, 'check': lambda x: x in [1, 3, 5]},
        'Больше 3': {'odds': 2.0, 'check': lambda x: x > 3},
        'Меньше 4': {'odds': 2.0, 'check': lambda x: x < 4},
    },
    'basketball': {
        'Гол':     {'odds': 2.0, 'check': lambda x: x in [4, 5]},
        'Застрял': {'odds': 2.0, 'check': lambda x: x == 3},
        'Мимо':    {'odds': 2.0, 'check': lambda x: x in [1, 2]},
    },
    'football': {
        'Гол':  {'odds': 2.0, 'check': lambda x: x in [3, 4, 5]},
        'Мимо': {'odds': 2.0, 'check': lambda x: x in [1, 2]},
    },
    'darts': {
        'Центр':   {'odds': 2.0, 'check': lambda x: x == 6},
        'Красное': {'odds': 2.0, 'check': lambda x: x == 5},
        'Белое':   {'odds': 2.0, 'check': lambda x: x in [3, 4]},
        'Мимо':    {'odds': 2.0, 'check': lambda x: x in [1, 2]},
    },
    'bowling': {
        'Страйк': {'odds': 2.0, 'check': lambda x: x == 6},
        'Мимо':   {'odds': 2.0, 'check': lambda x: x in [1, 2, 3]},
    },
}


# ==================== DATABASE ====================

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
            win_streak INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Добавляем win_streak если нет (миграция)
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN win_streak INTEGER DEFAULT 0')
    except:
        pass

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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS duels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            opponent_id INTEGER,
            game_type TEXT,
            bet_amount REAL,
            status TEXT DEFAULT 'waiting',
            creator_result INTEGER,
            opponent_result INTEGER,
            winner_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES users (user_id),
            FOREIGN KEY (opponent_id) REFERENCES users (user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tournaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            entry_fee REAL,
            prize_pool REAL,
            status TEXT DEFAULT 'active',
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tournament_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER,
            user_id INTEGER,
            profit REAL DEFAULT 0,
            games_played INTEGER DEFAULT 0,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tournament_id) REFERENCES tournaments (id),
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
    return float(user[3]) if user else 0.0

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

    cursor.execute('SELECT win_streak FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    current_streak = int(row[0]) if row and row[0] else 0

    cursor.execute('''
        INSERT INTO games (user_id, game_type, bet_type, bet_amount, result_value, win, payout)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, game_type, bet_type, bet_amount, result_value, win, payout))

    if win:
        new_streak = current_streak + 1
        bonus_multiplier = get_streak_bonus_multiplier(new_streak)
        net_profit = payout - bet_amount
        bonus_amount = net_profit * bonus_multiplier
        total_profit = net_profit + bonus_amount

        cursor.execute('''
            UPDATE users SET
                balance = balance + ?,
                total_wagered = total_wagered + ?,
                total_won = total_won + ?,
                games_played = games_played + 1,
                wins = wins + 1,
                win_streak = ?
            WHERE user_id = ?
        ''', (total_profit, bet_amount, payout + bonus_amount, new_streak, user_id))

        conn.commit()
        conn.close()
        return {
            'net_profit': net_profit,
            'bonus_amount': bonus_amount,
            'total_profit': total_profit,
            'streak': new_streak,
            'bonus_multiplier': bonus_multiplier
        }
    else:
        old_streak = current_streak
        cursor.execute('''
            UPDATE users SET
                balance = balance - ?,
                total_wagered = total_wagered + ?,
                total_lost = total_lost + ?,
                games_played = games_played + 1,
                losses = losses + 1,
                win_streak = 0
            WHERE user_id = ?
        ''', (bet_amount, bet_amount, bet_amount, user_id))

        conn.commit()
        conn.close()
        return {
            'net_profit': 0,
            'bonus_amount': 0,
            'total_profit': 0,
            'streak': 0,
            'bonus_multiplier': 0,
            'old_streak': old_streak
        }

def get_all_users():
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users ORDER BY balance DESC')
    users = cursor.fetchall()
    conn.close()
    return users

def get_leaderboard(limit: int = 10):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, first_name, username, total_won, wins, games_played
        FROM users WHERE games_played > 0
        ORDER BY total_won DESC LIMIT ?
    ''', (limit,))
    leaders = cursor.fetchall()
    conn.close()
    return leaders

def create_promocode(code: str, amount: float, max_uses: int):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO promocodes (code, amount, max_uses) VALUES (?, ?, ?)',
                       (code, amount, max_uses))
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
    cursor.execute('INSERT INTO promocode_uses (user_id, code, amount) VALUES (?, ?, ?)', (user_id, code, amount))
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    cursor.execute('''INSERT INTO transactions (user_id, type, amount, status, invoice_id)
                      VALUES (?, 'promocode', ?, 'completed', ?)''', (user_id, amount, f"promo_{code}"))
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

def get_referral_link(user_id: int) -> str:
    return f"https://t.me/ffortunna_bot?start=ref_{user_id}"

def add_referral(user_id: int, referrer_id: int) -> bool:
    if user_id == referrer_id:
        return False
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM referrals WHERE user_id = ?', (user_id,))
    if cursor.fetchone():
        conn.close()
        return False
    cursor.execute('INSERT INTO referrals (user_id, referrer_id, bonus_paid) VALUES (?, ?, 0)',
                   (user_id, referrer_id))
    conn.commit()
    conn.close()
    return True

def pay_referral_bonus(user_id: int, deposit_amount: float):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT referrer_id FROM referrals WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result:
        referrer_id = result[0]
        bonus = deposit_amount * 0.05
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (bonus, referrer_id))
        cursor.execute('''INSERT INTO transactions (user_id, type, amount, status, invoice_id)
                          VALUES (?, 'referral_bonus', ?, 'completed', ?)''',
                       (referrer_id, bonus, f"ref_{user_id}_{deposit_amount}"))
        conn.commit()
        conn.close()
        return referrer_id, bonus
    conn.close()
    return None, 0

def get_referral_stats(user_id: int):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0, 0

def get_referrals_list(user_id: int):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.user_id, u.first_name, u.username, r.created_at, r.bonus_paid
        FROM referrals r JOIN users u ON r.user_id = u.user_id
        WHERE r.referrer_id = ? ORDER BY r.created_at DESC LIMIT 20
    ''', (user_id,))
    refs = cursor.fetchall()
    conn.close()
    return refs

# ==================== DUELS DB ====================

def create_duel(creator_id: int, game_type: str, bet_amount: float):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO duels (creator_id, game_type, bet_amount, status) VALUES (?, ?, ?, "waiting")',
                   (creator_id, game_type, bet_amount))
    duel_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return duel_id

def get_open_duels():
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT d.id, d.creator_id, u.first_name, u.username, d.game_type, d.bet_amount, d.created_at
        FROM duels d JOIN users u ON d.creator_id = u.user_id
        WHERE d.status = 'waiting' ORDER BY d.created_at DESC LIMIT 10
    ''')
    duels = cursor.fetchall()
    conn.close()
    return duels

def get_duel(duel_id: int):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM duels WHERE id = ?', (duel_id,))
    duel = cursor.fetchone()
    conn.close()
    return duel

def accept_duel(duel_id: int, opponent_id: int):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''UPDATE duels SET opponent_id = ?, status = 'in_progress'
                      WHERE id = ? AND status = 'waiting' ''', (opponent_id, duel_id))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

def cancel_duel(duel_id: int):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE duels SET status = 'cancelled' WHERE id = ? AND status = 'waiting'", (duel_id,))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

def finish_duel(duel_id: int, creator_result: int, opponent_result: int, winner_id):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''UPDATE duels SET creator_result = ?, opponent_result = ?, winner_id = ?,
                      status = 'finished', finished_at = CURRENT_TIMESTAMP WHERE id = ?''',
                   (creator_result, opponent_result, winner_id, duel_id))
    conn.commit()
    conn.close()

def get_user_duels(user_id: int, limit: int = 10):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''SELECT * FROM duels WHERE creator_id = ? OR opponent_id = ?
                      ORDER BY created_at DESC LIMIT ?''', (user_id, user_id, limit))
    duels = cursor.fetchall()
    conn.close()
    return duels


# ==================== TOURNAMENTS DB ====================

def get_active_tournament():
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM tournaments
        WHERE status = 'active' AND datetime(end_time) > datetime('now')
        ORDER BY created_at DESC LIMIT 1
    ''')
    tournament = cursor.fetchone()
    conn.close()
    return tournament

def join_tournament(tournament_id: int, user_id: int, entry_fee: float):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tournament_participants WHERE tournament_id = ? AND user_id = ?',
                   (tournament_id, user_id))
    if cursor.fetchone():
        conn.close()
        return False
    cursor.execute('INSERT INTO tournament_participants (tournament_id, user_id) VALUES (?, ?)',
                   (tournament_id, user_id))
    cursor.execute('UPDATE tournaments SET prize_pool = prize_pool + ? WHERE id = ?',
                   (entry_fee * 0.95, tournament_id))
    conn.commit()
    conn.close()
    return True

def update_tournament_stats(user_id: int, profit: float):
    tournament = get_active_tournament()
    if not tournament:
        return
    tournament_id = tournament[0]
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE tournament_participants
        SET profit = profit + ?, games_played = games_played + 1
        WHERE tournament_id = ? AND user_id = ?
    ''', (profit, tournament_id, user_id))
    conn.commit()
    conn.close()

def get_tournament_leaderboard(tournament_id: int, limit: int = 10):
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT tp.user_id, u.first_name, u.username, tp.profit, tp.games_played
        FROM tournament_participants tp
        JOIN users u ON tp.user_id = u.user_id
        WHERE tp.tournament_id = ?
        ORDER BY tp.profit DESC
        LIMIT ?
    ''', (tournament_id, limit))
    leaders = cursor.fetchall()
    conn.close()
    return leaders

def create_weekend_tournament():
    now = datetime.now()
    if now.weekday() not in [5, 6]:
        return None
    if get_active_tournament():
        return None
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    if now.weekday() == 5:
        end_time = now.replace(hour=23, minute=59, second=59) + timedelta(days=1)
        name = "🏆 Турнир выходного дня"
    else:
        end_time = now.replace(hour=23, minute=59, second=59)
        name = "🏆 Воскресный турнир"
    cursor.execute('''
        INSERT INTO tournaments (name, entry_fee, prize_pool, status, start_time, end_time)
        VALUES (?, 10, 0, 'active', ?, ?)
    ''', (name, now.isoformat(), end_time.isoformat()))
    tournament_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return tournament_id


# ==================== KEYBOARDS ====================

def admin_keyboard():
    keyboard = [
        [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="⚔️ Дуэли")],
        [KeyboardButton(text="🏆 Турниры")],
        [KeyboardButton(text="➕ Пополнить"), KeyboardButton(text="💸 Вывод")],
        [KeyboardButton(text="🎁 Промокод"), KeyboardButton(text="👥 Рефералы")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🏆 Топ игроков")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="⚙️ Админ панель")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def main_keyboard():
    keyboard = [
        [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="⚔️ Дуэли")],
        [KeyboardButton(text="🏆 Турниры")],
        [KeyboardButton(text="➕ Пополнить"), KeyboardButton(text="💸 Вывод")],
        [KeyboardButton(text="🎁 Промокод"), KeyboardButton(text="👥 Рефералы")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🏆 Топ игроков")],
        [KeyboardButton(text="👤 Профиль")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def admin_panel_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="💰 Управление балансами", callback_data="admin_balances")],
        [InlineKeyboardButton(text="🎁 Управление промокодами", callback_data="admin_promocodes")],
        [InlineKeyboardButton(text="💳 История пополнений", callback_data="admin_deposits")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
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

def games_keyboard():
    buttons = []
    for game_id, game_data in GAMES.items():
        buttons.append([InlineKeyboardButton(
            text=f"{game_data['emoji']} {game_data['name']}",
            callback_data=f"game_{game_id}"
        )])
    buttons.append([InlineKeyboardButton(text="🪙 Монетка", callback_data="game_coin")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def bet_types_keyboard(game_id: str):
    buttons = []
    for bet_type, data in BET_TYPES[game_id].items():
        buttons.append([InlineKeyboardButton(
            text=f"{bet_type} (x{data['odds']})",
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

def duels_menu_keyboard():
    buttons = [
        [InlineKeyboardButton(text="⚔️ Создать дуэль", callback_data="duel_create")],
        [InlineKeyboardButton(text="🎯 Найти дуэль", callback_data="duel_find")],
        [InlineKeyboardButton(text="📜 Мои дуэли", callback_data="duel_my")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def duel_games_keyboard():
    buttons = []
    for game_id, game_data in GAMES.items():
        buttons.append([InlineKeyboardButton(
            text=f"{game_data['emoji']} {game_data['name']}",
            callback_data=f"duel_game_{game_id}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="duel_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def open_duels_keyboard(duels):
    buttons = []
    for duel in duels:
        duel_id, creator_id, first_name, username, game_type, bet_amount, created_at = duel
        game_emoji = GAMES[game_type]['emoji']
        game_name = GAMES[game_type]['name']
        buttons.append([InlineKeyboardButton(
            text=f"{game_emoji} {game_name} | {bet_amount} USDT | vs {first_name}",
            callback_data=f"duel_accept_{duel_id}"
        )])
    if not buttons:
        buttons.append([InlineKeyboardButton(text="😔 Нет доступных дуэлей", callback_data="duel_menu")])
    buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="duel_find")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="duel_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def duel_action_keyboard(duel_id: int):
    buttons = [
        [InlineKeyboardButton(text="❌ Отменить дуэль", callback_data=f"duel_cancel_{duel_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="duel_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def tournament_menu_keyboard(tournament_id: int = None):
    buttons = []
    if tournament_id:
        buttons.append([InlineKeyboardButton(text="🎮 Вступить в турнир", callback_data=f"tournament_join_{tournament_id}")])
        buttons.append([InlineKeyboardButton(text="📊 Таблица лидеров", callback_data=f"tournament_leaderboard_{tournament_id}")])
    buttons.append([InlineKeyboardButton(text="ℹ️ О турнирах", callback_data="tournament_info")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def repeat_bet_keyboard(game_id: str, bet_type: str, bet_amount: float):
    buttons = [
        [InlineKeyboardButton(text="🔄 Повторить ставку", callback_data=f"repeat_{game_id}_{bet_type}_{bet_amount}")],
        [InlineKeyboardButton(text="2️⃣ Удвоить ставку", callback_data=f"repeat_{game_id}_{bet_type}_{bet_amount * 2}")],
        [InlineKeyboardButton(text="🎮 Другая игра", callback_data="back_games")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def coin_amount_keyboard():
    """Клавиатура быстрого выбора суммы для монетки"""
    buttons = [
        [
            InlineKeyboardButton(text="1 USDT", callback_data="coin_amount_1"),
            InlineKeyboardButton(text="5 USDT", callback_data="coin_amount_5"),
        ],
        [
            InlineKeyboardButton(text="10 USDT", callback_data="coin_amount_10"),
            InlineKeyboardButton(text="25 USDT", callback_data="coin_amount_25"),
        ],
        [
            InlineKeyboardButton(text="50 USDT", callback_data="coin_amount_50"),
            InlineKeyboardButton(text="100 USDT", callback_data="coin_amount_100"),
        ],
        [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="coin_amount_custom")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_games")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def coin_choice_keyboard(amount: float):
    """Клавиатура выбора орёл/решка с суммой"""
    buttons = [
        [
            InlineKeyboardButton(text="🦅 Орёл", callback_data=f"coin_heads_{amount}"),
            InlineKeyboardButton(text="🎭 Решка", callback_data=f"coin_tails_{amount}"),
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="game_coin")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def coin_repeat_keyboard(amount: float):
    """Клавиатура после игры в монетку"""
    double = amount * 2
    buttons = [
        [
            InlineKeyboardButton(text=f"🔄 Повторить ({amount} USDT)", callback_data=f"coin_repeat_{amount}"),
        ],
        [
            InlineKeyboardButton(text=f"2️⃣ Удвоить ({double} USDT)", callback_data=f"coin_repeat_{double}"),
        ],
        [InlineKeyboardButton(text="🪙 Изменить ставку", callback_data="game_coin")],
        [InlineKeyboardButton(text="🎮 Другие игры", callback_data="back_games")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== PAYMENTS ====================

async def create_invoice(amount: float, description: str):
    import aiohttp, ssl, certifi
    if not CRYPTO_BOT_TOKEN:
        return None
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN, "Content-Type": "application/json"}
    data = {"asset": "USDT", "amount": str(amount), "description": description}
    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(url, headers=headers, json=data) as resp:
                result = await resp.json()
                if resp.status == 200 and result.get('ok'):
                    return result['result']
    except Exception as e:
        logger.error(f"❌ Ошибка инвойса: {e}")
    return None

async def check_invoice(invoice_id: str):
    import aiohttp, ssl, certifi
    url = "https://pay.crypt.bot/api/getInvoices"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, headers=headers, params={"invoice_ids": invoice_id}) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get('ok') and result.get('result', {}).get('items'):
                        return result['result']['items'][0]
    except Exception as e:
        logger.error(f"❌ Ошибка проверки инвойса: {e}")
    return None

async def auto_check_payment(message: types.Message, user_id: int, invoice_id: str, state: FSMContext):
    for attempt in range(100):
        await asyncio.sleep(3)
        invoice = await check_invoice(invoice_id)
        if invoice and invoice.get('status') == 'paid':
            amount = float(invoice['amount'])
            update_balance(user_id, amount)
            conn = sqlite3.connect('lottery_bot.db')
            cursor = conn.cursor()
            cursor.execute('''INSERT INTO transactions (user_id, type, amount, status, invoice_id)
                              VALUES (?, 'deposit', ?, 'completed', ?)''', (user_id, amount, invoice_id))
            cursor.execute('UPDATE users SET total_deposited = total_deposited + ? WHERE user_id = ?',
                           (amount, user_id))
            conn.commit()
            conn.close()
            referrer_id, bonus = pay_referral_bonus(user_id, amount)
            if referrer_id:
                try:
                    await bot.send_message(referrer_id,
                        f"💰 <b>Реферальный бонус!</b>\n\nРеферал пополнил {amount} USDT\n"
                        f"🎁 Вам: <b>{bonus:.2f} USDT</b>")
                except:
                    pass
            data = await state.get_data()
            if data.get('is_deposit_only'):
                try:
                    await message.edit_text(
                        f"✔️ <b>Оплата получена!</b>\n\nЗачислено: <b>{amount} USDT</b>\n"
                        f"Баланс: <b>{get_balance(user_id):.2f} USDT</b>")
                except:
                    await bot.send_message(user_id, f"✔️ Зачислено: <b>{amount} USDT</b>")
                await state.clear()
            else:
                game_id = data.get('game_id')
                bet_type = data.get('bet_type')
                bet_amount = data.get('bet_amount')
                if game_id and bet_type and bet_amount:
                    await process_game(message, user_id, game_id, bet_type, bet_amount, state)
            return
    try:
        await message.edit_text("⏰ Время ожидания оплаты истекло.")
    except:
        pass
    await state.clear()

async def create_stars_invoice(user_id: int, stars_amount: int, title: str, description: str, payload: str):
    try:
        await bot.send_invoice(
            chat_id=user_id, title=title, description=description,
            payload=payload, currency="XTR",
            prices=[LabeledPrice(label="Пополнение", amount=stars_amount)],
            provider_token=""
        )
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка Stars: {e}")
        return False

async def check_ton_transaction(wallet_address: str, amount_ton: float, comment: str, timeout: int = 600):
    start_time = time.time()
    api_url = f"https://tonapi.io/v2/blockchain/accounts/{wallet_address}/transactions"
    while time.time() - start_time < timeout:
        try:
            response = requests.get(api_url, params={"limit": 10}, timeout=10)
            if response.status_code == 200:
                for tx in response.json().get("transactions", []):
                    if tx.get("in_msg"):
                        in_msg = tx["in_msg"]
                        value = int(in_msg.get("value", 0)) / 1_000_000_000
                        msg_data = in_msg.get("message", "")
                        tx_comment = ""
                        if isinstance(msg_data, str) and msg_data:
                            try:
                                tx_comment = base64.b64decode(msg_data).decode('utf-8', errors='ignore')
                            except:
                                tx_comment = msg_data
                        if abs(value - amount_ton) < 0.01 and comment.lower() in tx_comment.lower():
                            return True, tx
        except Exception as e:
            logger.error(f"❌ Ошибка TON: {e}")
        await asyncio.sleep(5)
    return False, None

async def auto_check_ton_payment(message, user_id, payment_id, amount_ton, amount_usdt, state):
    found, transaction = await check_ton_transaction(TON_WALLET_ADDRESS, amount_ton, payment_id)
    if found:
        update_balance(user_id, amount_usdt)
        conn = sqlite3.connect('lottery_bot.db')
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO transactions (user_id, type, amount, status, invoice_id)
                          VALUES (?, 'deposit', ?, 'completed', ?)''',
                       (user_id, amount_usdt, f"ton_{payment_id}"))
        cursor.execute('UPDATE users SET total_deposited = total_deposited + ? WHERE user_id = ?',
                       (amount_usdt, user_id))
        conn.commit()
        conn.close()
        referrer_id, bonus = pay_referral_bonus(user_id, amount_usdt)
        if referrer_id:
            try:
                await bot.send_message(referrer_id,
                    f"💰 <b>Реферальный бонус!</b>\n\nРеферал пополнил {amount_usdt} USDT\n"
                    f"🎁 Вам: <b>{bonus:.2f} USDT</b>")
            except:
                pass
        data = await state.get_data()
        if data.get('is_deposit_only'):
            try:
                await message.edit_text(
                    f"✅ <b>TON получен!</b>\n\n💠 {amount_ton} TON\n"
                    f"💰 Зачислено: <b>{amount_usdt} USDT</b>\n"
                    f"💵 Баланс: <b>{get_balance(user_id):.2f} USDT</b>")
            except:
                await bot.send_message(user_id, f"✅ TON получен! Зачислено: {amount_usdt} USDT")
            await state.clear()
        else:
            game_id = data.get('game_id')
            bet_type = data.get('bet_type')
            bet_amount = data.get('bet_amount')
            if game_id and bet_type and bet_amount:
                await process_game(message, user_id, game_id, bet_type, bet_amount, state)
        return True
    try:
        await message.edit_text(
            f"⏰ <b>Время истекло</b>\n\nПлатеж не найден.\n"
            f"Если отправили {amount_ton} TON с комментарием <code>{payment_id}</code> — "
            f"свяжитесь с поддержкой.")
    except:
        pass
    await state.clear()
    return False


# ==================== GAME LOGIC ====================

async def process_game(message: types.Message, user_id: int, game_id: str, bet_type: str, bet_amount: float, state: FSMContext):
    import random as _rnd
    game_data  = GAMES[game_id]
    dice_emoji = game_data['dice_emoji']
    game_name  = game_data['name']
    game_emoji = game_data['emoji']
    user       = get_user(user_id)
    first_name = user[2] if user else 'Игрок'

    # 1. Анонс в канал
    channel_link = 'https://t.me/ffortunna_bot'
    try:
        ann = await bot.send_message(
            STATS_CHANNEL_ID,
            f'🎰 <b>НОВАЯ СТАВКА!</b>\n'
            f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
            f'{game_emoji} <b>{game_name}</b>  ·  {bet_type}\n'
            f'👤 {first_name}\n'
            f'💰 {bet_amount:.2f} USDT\n'
            f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
            f'🎲 Бросаем кубик...'
        )
        channel_link = f'https://t.me/c/{str(STATS_CHANNEL_ID)[4:]}/{ann.message_id}'
    except Exception as e:
        logger.error(f'Анонс в канал: {e}')

    # 2. Сообщение игроку
    await bot.send_message(
        user_id,
        f'✅ <b>Ставка принята!</b>\n\n'
        f'{game_emoji} <b>{game_name}</b>\n'
        f'🎯 Ставка: <b>{bet_type}</b>\n'
        f'💰 Сумма: <b>{bet_amount:.2f} USDT</b>\n\n'
        f'📺 Трансляция в канале 👇\n{channel_link}',
        disable_web_page_preview=True
    )

    await asyncio.sleep(1)

    # 3. Бросок игроку — только его dice.value реальный
    result_value = _rnd.randint(1, 6)
    try:
        player_dice  = await bot.send_dice(user_id, emoji=dice_emoji)
        result_value = player_dice.dice.value
        logger.info(f'[{game_id}] dice={result_value}')
    except Exception as e:
        logger.error(f'Дайс игроку: {e}')

    # 4. Декоративный кубик + имя в канал
    try:
        await bot.send_message(STATS_CHANNEL_ID, f'🎲 <b>{first_name}</b> бросает:')
        await bot.send_dice(STATS_CHANNEL_ID, emoji=dice_emoji)
    except Exception as e:
        logger.error(f'Дайс в канал: {e}')

    await asyncio.sleep(4)

    bet_config = BET_TYPES[game_id][bet_type]
    is_win     = bet_config['check'](result_value)

    kb_ch = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🎰 Играть', url='https://t.me/ffortunna_bot')]
    ])

    if is_win:
        base_payout  = bet_amount * bet_config['odds']
        res          = record_game(user_id, game_id, bet_type, bet_amount, result_value, True, base_payout)
        net_profit   = res['net_profit']
        bonus_amount = res['bonus_amount']
        total_profit = res['total_profit']
        streak       = res['streak']
        bonus_mult   = res['bonus_multiplier']
        s_emoji      = get_streak_emoji(streak)
        streak_line  = ''
        if streak >= 3:
            streak_line = (
                f'\n🔥 <b>СТРИК x{streak}!</b>  +{bonus_mult*100:.1f}%'
                f'\n💰 Базовая: +{net_profit:.2f}  🎁 Бонус: +{bonus_amount:.2f}'
            )
        try:
            await bot.send_message(STATS_CHANNEL_ID,
                f'🏆 <b>ПОБЕДА!</b> {s_emoji}\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'{game_emoji} {game_name}  ·  {bet_type}\n'
                f'🎲 Выпало: <b>{result_value}</b> ✅\n'
                f'👤 {first_name}{streak_line}\n'
                f'💎 <b>+{total_profit:.2f} USDT</b>\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'👇 Хочешь так же?',
                reply_markup=kb_ch)
        except:
            pass
        profit_text = (
            f'💵 Прибыль: <b>+{net_profit:.2f} USDT</b>' if streak < 3
            else f'💰 Базовая: +{net_profit:.2f}\n🎁 Бонус стрика: +{bonus_amount:.2f}'
        )
        await bot.send_message(user_id,
            f'🎉 <b>ПОБЕДА!</b> {s_emoji}\n\n'
            f'{game_emoji} {game_name}  ·  {bet_type}\n'
            f'🎲 Выпало: <b>{result_value}</b> ✅\n\n'
            f'{profit_text}\n'
            f'💎 <b>ИТОГО: +{total_profit:.2f} USDT</b>\n\n'
            f'🔥 Серия: <b>{streak}</b>\n'
            f'💵 Баланс: <b>{get_balance(user_id):.2f} USDT</b>',
            reply_markup=repeat_bet_keyboard(game_id, bet_type, bet_amount))
    else:
        res        = record_game(user_id, game_id, bet_type, bet_amount, result_value, False, 0)
        old_streak = res.get('old_streak', 0)
        streak_lost = ''
        if old_streak >= 3:
            streak_lost = f'\n💔 Стрик x{old_streak} прерван {get_streak_emoji(old_streak)}'
        try:
            await bot.send_message(STATS_CHANNEL_ID,
                f'😔 <b>Проигрыш</b>\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'{game_emoji} {game_name}  ·  {bet_type}\n'
                f'🎲 Выпало: <b>{result_value}</b> ❌\n'
                f'👤 {first_name}  -{bet_amount:.2f} USDT{streak_lost}\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'🍀 Удача ждёт!',
                reply_markup=kb_ch)
        except:
            pass
        await bot.send_message(user_id,
            f'😔 <b>Проигрыш</b>\n\n'
            f'{game_emoji} {game_name}  ·  {bet_type}\n'
            f'🎲 Выпало: <b>{result_value}</b> ❌\n\n'
            f'💸 Ставка: {bet_amount:.2f} USDT\n'
            f'❌ Потеря: <b>-{bet_amount:.2f} USDT</b>{streak_lost}\n\n'
            f'💵 Баланс: <b>{get_balance(user_id):.2f} USDT</b>',
            reply_markup=repeat_bet_keyboard(game_id, bet_type, bet_amount))

    await state.clear()


async def process_coin_flip(target: types.Message | types.CallbackQuery, user_id: int, amount: float, user_choice: str):
    """
    Универсальная функция броска монетки.
    target — это либо Message, либо CallbackQuery (для send_message используем bot напрямую)
    """
    user = get_user(user_id)
    first_name = user[2] if user else "Игрок"

    # Проверяем баланс
    balance = get_balance(user_id)
    if balance < amount:
        text = (f"❌ <b>Недостаточно средств!</b>\n\n"
                f"Баланс: {balance:.2f} USDT\nНужно: {amount:.2f} USDT")
        await bot.send_message(user_id, text,
                               reply_markup=payment_method_keyboard(amount - balance, "deposit"))
        return

    # Списываем СРАЗУ перед игрой (чтобы не было дублей)
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

    choice_name = "🦅 Орёл" if user_choice == "heads" else "🎭 Решка"

    try:
        announcement = await bot.send_message(
            STATS_CHANNEL_ID,
            f"🪙 <b>МОНЕТКА!</b>\n\n"
            f"👤 Игрок: {first_name}\n"
            f"💰 Ставка: {amount:.2f} USDT\n"
            f"🎯 Выбор: {choice_name}\n\n"
            f"🎰 Крутим..."
        )
        channel_link = f"https://t.me/c/{str(STATS_CHANNEL_ID)[4:]}/{announcement.message_id}"
    except:
        channel_link = "https://t.me/ffortunna_bot"

    await bot.send_message(user_id,
        f"🪙 <b>Монетка летит!</b>\n\n"
        f"╔══════════════╗\n"
        f"║  🦅  vs  🎭  ║\n"
        f"╚══════════════╝\n\n"
        f"💰 Ставка: <b>{amount:.2f} USDT</b>\n"
        f"🎯 Твой выбор: <b>{choice_name}</b>\n"
        f"🎰 Возможный выигрыш: <b>{amount * 1.9:.2f} USDT</b>\n\n"
        f"📺 Следи: {channel_link}",
        disable_web_page_preview=True)

    await asyncio.sleep(2)

    # Монетка: честный рандом 50/50
    import random as _rnd
    coin_result = _rnd.choice(['heads', 'tails'])
    result_name = '🦅 Орёл' if coin_result == 'heads' else '🎭 Решка'
    is_win = coin_result == user_choice

    # Показываем кубик как анимацию ожидания
    try:
        await bot.send_dice(user_id, emoji='🎲')
    except:
        pass
    try:
        await bot.send_message(STATS_CHANNEL_ID, f'🪙 <b>{first_name}</b> бросает монетку...')
        await bot.send_dice(STATS_CHANNEL_ID, emoji='🎲')
    except:
        pass

    await asyncio.sleep(4)

    kb_channel = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪙 Играть в монетку", url="https://t.me/ffortunna_bot")]
    ])

    if is_win:
        # Коэффициент x1.9
        base_payout = amount * 1.9
        net_profit = base_payout - amount

        # Стрик
        conn = sqlite3.connect('lottery_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT win_streak FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        current_streak = int(row[0]) if row and row[0] else 0
        new_streak = current_streak + 1

        bonus_multiplier = get_streak_bonus_multiplier(new_streak)
        bonus_amount = net_profit * bonus_multiplier
        total_profit = net_profit + bonus_amount

        cursor.execute('''
            INSERT INTO games (user_id, game_type, bet_type, bet_amount, result_value, win, payout)
            VALUES (?, 'coin', ?, ?, 0, 1, ?)
        ''', (user_id, user_choice, amount, base_payout + bonus_amount))

        cursor.execute('''
            UPDATE users SET
                balance = balance + ?,
                total_wagered = total_wagered + ?,
                total_won = total_won + ?,
                games_played = games_played + 1,
                wins = wins + 1,
                win_streak = ?
            WHERE user_id = ?
        ''', (base_payout + bonus_amount, amount, base_payout + bonus_amount, new_streak, user_id))
        conn.commit()
        conn.close()

        streak_emoji = get_streak_emoji(new_streak)
        streak_text = ""
        if new_streak >= 3:
            streak_text = (f"\n🔥 <b>БОНУС x{new_streak}!</b>\n"
                           f"💰 Базовая: {net_profit:.2f} USDT\n"
                           f"🎁 Бонус (+{bonus_multiplier*100:.1f}%): +{bonus_amount:.2f} USDT")

        try:
            await bot.send_message(STATS_CHANNEL_ID,
                f"🎉 <b>ПОБЕДА!</b> {streak_emoji}\n\n"
                f"🪙 Монетка: {result_name}\n"
                f"💰 Ставка: {amount:.2f} USDT{streak_text}\n"
                f"💎 <b>ИТОГО: +{total_profit:.2f} USDT</b>\n"
                f"👤 {first_name}", reply_markup=kb_channel)
        except:
            pass

        profit_line = f"💵 Прибыль: <b>+{net_profit:.2f} USDT</b>" if new_streak < 3 else \
                      f"💰 Базовая: +{net_profit:.2f} USDT\n🎁 Бонус: +{bonus_amount:.2f} USDT"

        # Визуализация монетки
        coin_visual = "🦅" if coin_result == "heads" else "🎭"
        await bot.send_message(user_id,
            f"🎉 <b>ПОБЕДА!</b> {streak_emoji}\n\n"
            f"╔══════════════╗\n"
            f"║   {coin_visual}  ВЫПАЛО  {coin_visual}   ║\n"
            f"╚══════════════╝\n\n"
            f"🪙 Выпало: <b>{result_name}</b> ✅\n"
            f"🎯 Твой выбор: <b>{choice_name}</b> ✅\n\n"
            f"{profit_line}\n"
            f"💎 <b>ИТОГО: +{total_profit:.2f} USDT</b>\n\n"
            f"🔥 Серия побед: {new_streak}\n"
            f"💵 Баланс: <b>{get_balance(user_id):.2f} USDT</b>",
            reply_markup=coin_repeat_keyboard(amount))
    else:
        # Проигрыш — деньги уже списали выше
        conn = sqlite3.connect('lottery_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT win_streak FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        old_streak = int(row[0]) if row and row[0] else 0

        cursor.execute('''
            INSERT INTO games (user_id, game_type, bet_type, bet_amount, result_value, win, payout)
            VALUES (?, 'coin', ?, ?, 0, 0, 0)
        ''', (user_id, user_choice, amount))

        cursor.execute('''
            UPDATE users SET
                total_wagered = total_wagered + ?,
                total_lost = total_lost + ?,
                games_played = games_played + 1,
                losses = losses + 1,
                win_streak = 0
            WHERE user_id = ?
        ''', (amount, amount, user_id))
        conn.commit()
        conn.close()

        streak_lost = ""
        if old_streak >= 3:
            s_emoji = get_streak_emoji(old_streak)
            streak_lost = f"\n💔 Стрик прерван! {s_emoji} (было {old_streak})"

        try:
            await bot.send_message(STATS_CHANNEL_ID,
                f"😔 <b>Проигрыш</b>\n\n"
                f"🪙 Монетка: {result_name}\n"
                f"💰 Потеря: {amount:.2f} USDT{streak_lost}\n"
                f"👤 {first_name}", reply_markup=kb_channel)
        except:
            pass

        coin_visual_lose = "🦅" if coin_result == "heads" else "🎭"
        your_visual = "🦅" if user_choice == "heads" else "🎭"
        await bot.send_message(user_id,
            f"😔 <b>Проигрыш</b>\n\n"
            f"╔══════════════╗\n"
            f"║   {coin_visual_lose}  ВЫПАЛО  {coin_visual_lose}   ║\n"
            f"╚══════════════╝\n\n"
            f"🪙 Выпало: <b>{result_name}</b>\n"
            f"🎯 Твой выбор: <b>{'🦅 Орёл' if user_choice == 'heads' else '🎭 Решка'}</b> ❌\n\n"
            f"💔 Потеря: <b>-{amount:.2f} USDT</b>{streak_lost}\n"
            f"💵 Баланс: <b>{get_balance(user_id):.2f} USDT</b>",
            reply_markup=coin_repeat_keyboard(amount))


async def start_duel_game(chat_id: int, duel_id: int):
    """
    Трансляция дуэли:
    - dice.value реальный ТОЛЬКО в ЛС с игроком
    - В канал: анонс -> кубик-за-кубиком -> итог
    - Каждый игрок видит оба броска у себя
    """
    import random as rnd
    try:
        duel = get_duel(duel_id)
        if not duel:
            logger.error(f'Дуэль {duel_id} не найдена')
            return

        creator_id    = duel[1]
        opponent_id   = duel[2]
        game_type     = duel[3]
        bet_amount    = float(duel[4])
        game_data     = GAMES[game_type]
        g_emoji       = game_data['emoji']
        g_name        = game_data['name']
        dice_emoji    = game_data['dice_emoji']
        creator       = get_user(creator_id)
        opponent      = get_user(opponent_id)
        creator_name  = creator[2]  if creator  else 'Игрок 1'
        opponent_name = opponent[2] if opponent else 'Игрок 2'
        bank          = bet_amount * 2

        kb_play = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='⚔️ Сыграть дуэль', url='https://t.me/ffortunna_bot')]
        ])

        # 1. Анонс в канал
        try:
            await bot.send_message(STATS_CHANNEL_ID,
                f'⚔️ <b>ДУЭЛЬ #{duel_id}</b>\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'{g_emoji} <b>{g_name}</b>\n'
                f'🏦 Банк: <b>{bank:.2f} USDT</b>\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'🔴 <b>{creator_name}</b>\n'
                f'         ⚔️ VS ⚔️\n'
                f'🔵 <b>{opponent_name}</b>\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'⏳ Ждём броски...')
        except Exception as e:
            logger.error(f'Анонс дуэли: {e}')

        # 2. Уведомление обоим игрокам
        for pid, opp in [(creator_id, opponent_name), (opponent_id, creator_name)]:
            try:
                await bot.send_message(pid,
                    f'⚔️ <b>Дуэль #{duel_id} началась!</b>\n\n'
                    f'{g_emoji} <b>{g_name}</b>\n'
                    f'🆚 Соперник: <b>{opp}</b>\n'
                    f'🏦 Банк: <b>{bank:.2f} USDT</b>\n\n'
                    f'🎲 Смотри броски ниже 👇')
            except:
                pass

        await asyncio.sleep(1)

        # 3. Бросок создателя — его dice.value реальный
        creator_result = rnd.randint(1, 6)
        try:
            d1 = await bot.send_dice(creator_id, emoji=dice_emoji)
            creator_result = d1.dice.value
            logger.info(f'Дуэль #{duel_id}: {creator_name}={creator_result}')
        except Exception as e:
            logger.error(f'Дайс creator: {e}')

        # Трансляция в канал
        try:
            await bot.send_message(STATS_CHANNEL_ID,
                f'🔴 <b>{creator_name}</b> бросает {g_emoji}:')
            await bot.send_dice(STATS_CHANNEL_ID, emoji=dice_emoji)
        except:
            pass

        await asyncio.sleep(2)

        # 4. Бросок соперника
        opponent_result = rnd.randint(1, 6)
        try:
            d2 = await bot.send_dice(opponent_id, emoji=dice_emoji)
            opponent_result = d2.dice.value
            logger.info(f'Дуэль #{duel_id}: {opponent_name}={opponent_result}')
        except Exception as e:
            logger.error(f'Дайс opponent: {e}')

        # Трансляция в канал
        try:
            await bot.send_message(STATS_CHANNEL_ID,
                f'🔵 <b>{opponent_name}</b> бросает {g_emoji}:')
            await bot.send_dice(STATS_CHANNEL_ID, emoji=dice_emoji)
        except:
            pass

        # Показываем каждому бросок соперника
        try:
            await bot.send_message(creator_id, f'🔵 Бросок <b>{opponent_name}</b>:')
            await bot.send_dice(creator_id, emoji=dice_emoji)
        except:
            pass
        try:
            await bot.send_message(opponent_id, f'🔴 Бросок <b>{creator_name}</b>:')
            await bot.send_dice(opponent_id, emoji=dice_emoji)
        except:
            pass

        await asyncio.sleep(4)

        # 5. Итог
        if creator_result == opponent_result:
            update_balance(creator_id, bet_amount)
            update_balance(opponent_id, bet_amount)
            finish_duel(duel_id, creator_result, opponent_result, None)
            try:
                await bot.send_message(STATS_CHANNEL_ID,
                    f'🤝 <b>НИЧЬЯ!</b>\n'
                    f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                    f'🔴 {creator_name}: <b>{creator_result}</b>\n'
                    f'🔵 {opponent_name}: <b>{opponent_result}</b>\n'
                    f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                    f'💰 Ставки возвращены',
                    reply_markup=kb_play)
            except:
                pass
            for pid in [creator_id, opponent_id]:
                try:
                    await bot.send_message(pid,
                        f'🤝 <b>Ничья в дуэли #{duel_id}!</b>\n\n'
                        f'🔴 {creator_name}: <b>{creator_result}</b>\n'
                        f'🔵 {opponent_name}: <b>{opponent_result}</b>\n\n'
                        f'💰 Возвращено: <b>{bet_amount:.2f} USDT</b>\n'
                        f'💵 Баланс: <b>{get_balance(pid):.2f} USDT</b>',
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text='⚔️ Реванш!', callback_data='duel_create')]
                        ]))
                except:
                    pass
            return

        # Победитель
        if creator_result > opponent_result:
            winner_id,   loser_id   = creator_id,    opponent_id
            winner_name, loser_name = creator_name,  opponent_name
            winner_val,  loser_val  = creator_result, opponent_result
            w_color,     l_color    = '🔴', '🔵'
        else:
            winner_id,   loser_id   = opponent_id,   creator_id
            winner_name, loser_name = opponent_name, creator_name
            winner_val,  loser_val  = opponent_result, creator_result
            w_color,     l_color    = '🔵', '🔴'

        payout     = round(bank * 0.90, 2)
        commission = round(bank - payout, 2)
        update_balance(winner_id, payout)
        finish_duel(duel_id, creator_result, opponent_result, winner_id)

        try:
            await bot.send_message(STATS_CHANNEL_ID,
                f'🏆 <b>ДУЭЛЬ #{duel_id} — ИТОГ!</b>\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'🔴 {creator_name}\n'
                f'   {g_emoji} Бросок: <b>{creator_result}</b>\n'
                f'🔵 {opponent_name}\n'
                f'   {g_emoji} Бросок: <b>{opponent_result}</b>\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'{w_color} 👑 Победитель: <b>{winner_name}</b>\n'
                f'💎 Выигрыш: <b>+{payout:.2f} USDT</b>\n'
                f'🏦 Комиссия: {commission:.2f} USDT',
                reply_markup=kb_play)
        except:
            pass

        try:
            await bot.send_message(winner_id,
                f'🏆 <b>ТЫ ПОБЕДИЛ!</b>\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'{g_emoji} <b>{g_name}</b>  ·  ⚔️ Дуэль #{duel_id}\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'🟢 Ты: {g_emoji} <b>{winner_val}</b> ✅\n'
                f'🔘 {loser_name}: {g_emoji} <b>{loser_val}</b>\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'💎 Выигрыш: <b>+{payout:.2f} USDT</b>\n'
                f'💵 Баланс: <b>{get_balance(winner_id):.2f} USDT</b>',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text='⚔️ Новая дуэль', callback_data='duel_create')]
                ]))
        except:
            pass

        try:
            await bot.send_message(loser_id,
                f'😔 <b>Поражение</b>\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'{g_emoji} <b>{g_name}</b>  ·  ⚔️ Дуэль #{duel_id}\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'🔘 Ты: {g_emoji} <b>{loser_val}</b> ❌\n'
                f'🟢 {winner_name}: {g_emoji} <b>{winner_val}</b> ✅\n'
                f'┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n'
                f'💸 Потеря: <b>-{bet_amount:.2f} USDT</b>\n'
                f'💵 Баланс: <b>{get_balance(loser_id):.2f} USDT</b>',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text='⚔️ Реванш!', callback_data='duel_create')]
                ]))
        except:
            pass

    except Exception as e:
        logger.error(f'❌ Критическая ошибка дуэль #{duel_id}: {e}', exc_info=True)


# ==================== HANDLERS ====================

@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.content_type == types.ContentType.SUCCESSFUL_PAYMENT)
async def process_successful_payment(message: types.Message, state: FSMContext):
    successful_payment = message.successful_payment
    payload = successful_payment.invoice_payload
    user_id = message.from_user.id
    try:
        parts = payload.split("_")
        if len(parts) >= 3:
            stars_amount = int(parts[1])
            purpose = parts[2]
            if successful_payment.currency == "XTR" and successful_payment.total_amount == stars_amount:
                amount_usdt = round(stars_amount * STARS_TO_USDT_RATE, 2)
                update_balance(user_id, amount_usdt)
                conn = sqlite3.connect('lottery_bot.db')
                cursor = conn.cursor()
                invoice_id = f"stars_{user_id}_{datetime.now().timestamp()}"
                cursor.execute('''INSERT INTO transactions (user_id, type, amount, status, invoice_id)
                                  VALUES (?, 'deposit', ?, 'completed', ?)''', (user_id, amount_usdt, invoice_id))
                cursor.execute('UPDATE users SET total_deposited = total_deposited + ? WHERE user_id = ?',
                               (amount_usdt, user_id))
                conn.commit()
                conn.close()
                referrer_id, bonus = pay_referral_bonus(user_id, amount_usdt)
                if referrer_id:
                    try:
                        await bot.send_message(referrer_id,
                            f"💰 <b>Реферальный бонус!</b>\n\nРеферал пополнил {amount_usdt} USDT\n"
                            f"🎁 Вам: <b>{bonus:.2f} USDT</b>")
                    except:
                        pass
                data = await state.get_data()
                if purpose == "deposit":
                    await message.answer(
                        f"✅ <b>Оплата успешна!</b>\n\n⭐ {stars_amount} Stars\n"
                        f"💰 Зачислено: <b>{amount_usdt} USDT</b>\n"
                        f"💵 Баланс: <b>{get_balance(user_id):.2f} USDT</b>")
                    await state.clear()
                else:
                    game_id = data.get('game_id')
                    bet_type = data.get('bet_type')
                    bet_amount = data.get('bet_amount')
                    if game_id and bet_type and bet_amount:
                        await process_game(message, user_id, game_id, bet_type, bet_amount, state)
    except Exception as e:
        logger.error(f"❌ Ошибка платежа: {e}")
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
                referrer_id = int(args.replace('ref_', ''))
                if add_referral(user_id, referrer_id):
                    try:
                        await bot.send_message(referrer_id,
                            f"🎉 <b>Новый реферал!</b>\n\n👤 {first_name} присоединился!\n"
                            f"💰 Вы получаете <b>5%</b> от его пополнений")
                    except Exception as e:
                        logger.error(f"❌ Ошибка уведомления: {e}")
            except:
                pass

    keyboard = admin_keyboard() if user_id in ADMIN_IDS else main_keyboard()
    ref_link = get_referral_link(user_id)
    inline_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Моя реферальная ссылка", callback_data="show_ref_link")],
        [InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся к лотерейному боту! 🎰")]
    ])

    await message.answer(
        f"<b>🎰 Добро пожаловать в FORTUNA!</b>\n\n"
        f"Привет, {first_name}! 👋\n\n"
        f"<b>🎮 Доступные игры:</b>\n"
        f"🎲 Кубик | 🏀 Баскетбол | ⚽ Футбол\n"
        f"🎯 Дартс | 🎳 Боулинг | 🪙 Монетка\n\n"
        f"<b>🔥 СТРИКИ - СИСТЕМА БОНУСОВ!</b>\n"
        f"• 3 победы → +0.3% к выигрышу 🔥\n"
        f"• 5 побед → +0.5% к выигрышу 🔥🔥\n"
        f"• 10 побед → +1.0% к выигрышу 🔥🔥🔥\n\n"
        f"<b>⚔️ PVP ДУЭЛИ</b>\n"
        f"• Сражайся с другими игроками\n"
        f"• Победитель забирает 90% банка\n\n"
        f"<b>🏆 ТУРНИРЫ ВЫХОДНОГО ДНЯ</b>\n"
        f"• Каждую субботу и воскресенье\n"
        f"• Взнос: 10 USDT\n\n"
        f"<b>💰 Способы пополнения:</b>\n"
        f"⭐ Stars | 💎 USDT | 💠 TON\n\n"
        f"<b>👥 Реферальная программа:</b>\n"
        f"🎁 <b>5% от каждого пополнения</b> друга!\n\n"
        f"Выбери действие из меню ниже ⬇️",
        reply_markup=keyboard
    )


@dp.message(Command("myid"))
async def cmd_my_id(message: types.Message):
    await message.answer(f"<b>🆔 Ваш Telegram ID:</b>\n\n<code>{message.from_user.id}</code>")


@dp.message(F.sticker)
async def get_sticker_id(message: types.Message):
    """Временный хендлер — присылаешь стикер боту, он отвечает file_id"""
    s = message.sticker
    await message.answer(
        f"🎯 <b>Sticker file_id:</b>\n\n"
        f"<code>{s.file_id}</code>\n\n"
        f"📦 Set: <code>{s.set_name or 'нет'}</code>\n"
        f"🎬 Animated: {s.is_animated}\n"
        f"📹 Video: {s.is_video}\n"
        f"😊 Emoji: {s.emoji}"
    )


# ==================== MENU HANDLERS ====================

@dp.message(F.text == "🎮 Играть")
async def menu_play(message: types.Message, state: FSMContext):
    await state.set_state(BetStates.choosing_game)
    await message.answer("<b>🎮 Выбери игру:</b>", reply_markup=games_keyboard())


@dp.message(F.text == "👤 Профиль")
async def menu_profile(message: types.Message):
    user_id = message.from_user.id

    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, first_name, balance, total_deposited, total_withdrawn,
               total_wagered, total_won, total_lost, games_played, wins, losses, win_streak
        FROM users WHERE user_id = ?
    ''', (user_id,))
    stats = cursor.fetchone()
    conn.close()

    if not stats:
        await message.answer("❌ Ошибка получения профиля!")
        return

    balance = float(stats[3])
    total_deposited = float(stats[4])
    total_wagered = float(stats[6])
    total_won = float(stats[7])
    total_lost = float(stats[8])
    games_played = int(stats[9])
    wins = int(stats[10])
    losses = int(stats[11])
    win_streak = int(stats[12]) if stats[12] is not None else 0

    win_rate = (wins / games_played * 100) if games_played > 0 else 0
    profit = total_won - total_lost

    streak_emoji = get_streak_emoji(win_streak)
    bonus_mult = get_streak_bonus_multiplier(win_streak)
    bonus_text = f" → +{bonus_mult*100:.1f}% к прибыли" if win_streak >= 3 else ""

    vip_level = get_vip_level(total_deposited)
    vip_name = VIP_LEVELS[vip_level]['name']
    next_map = {'bronze': ('silver', 50), 'silver': ('gold', 200), 'gold': ('platinum', 500), 'platinum': (None, None)}
    next_lvl, next_dep = next_map[vip_level]
    vip_progress = f"\n📈 До {VIP_LEVELS[next_lvl]['name']}: <b>{next_dep - total_deposited:.0f} USDT</b>" if next_lvl else ""

    await message.answer(
        f"<b>👤 Твой профиль</b>\n\n"
        f"{vip_name}{vip_progress}\n\n"
        f"💰 <b>Баланс:</b> {balance:.2f} USDT\n"
        f"📥 <b>Пополнено:</b> {total_deposited:.2f} USDT\n"
        f"📊 <b>Всего ставок:</b> {total_wagered:.2f} USDT\n"
        f"✔️ <b>Выиграно:</b> {total_won:.2f} USDT\n"
        f"✖️ <b>Проиграно:</b> {total_lost:.2f} USDT\n"
        f"💵 <b>Профит:</b> {profit:+.2f} USDT\n\n"
        f"🎮 <b>Игр сыграно:</b> {games_played}\n"
        f"✔️ <b>Побед:</b> {wins}\n"
        f"✖️ <b>Поражений:</b> {losses}\n"
        f"📈 <b>Винрейт:</b> {win_rate:.1f}%\n\n"
        f"🔥 <b>Серия побед:</b> {win_streak} {streak_emoji}{bonus_text}"
    )


@dp.message(F.text == "💸 Вывод")
async def menu_withdraw(message: types.Message):
    await message.answer(
        "<b>💸 Вывод средств</b>\n\n"
        "Для вывода обратитесь:\n👤 @fortuna_viplati\n\n"
        "Укажите ID и сумму.\n⏱ Обработка: 1-48 часа"
    )


@dp.message(F.text == "➕ Пополнить")
async def menu_deposit(message: types.Message, state: FSMContext):
    await state.set_state(BetStates.entering_deposit_amount)
    await message.answer(
        "<b>💰 Пополнение баланса</b>\n\n"
        "Введите сумму пополнения (от 1 USDT):\n\n"
        "<i>Примеры: 10, 50, 100</i>"
    )


@dp.message(BetStates.entering_deposit_amount)
async def process_deposit_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount < 1:
            await message.answer("❌ Минимальная сумма - 1 USDT")
            return
        await message.answer(
            f"💰 <b>Пополнение на {amount} USDT</b>\n\nВыберите способ оплаты:",
            reply_markup=payment_method_keyboard(amount, "deposit")
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число! Например: 10 или 50")


@dp.message(F.text == "🎁 Промокод")
async def menu_promocode(message: types.Message, state: FSMContext):
    await state.set_state(BetStates.entering_promocode)
    await message.answer("<b>🎁 Активация промокода</b>\n\nВведите промокод:")


@dp.message(F.text == "📊 Статистика")
async def menu_stats(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''SELECT game_type, bet_type, bet_amount, win, payout, created_at
                      FROM games WHERE user_id = ? ORDER BY created_at DESC LIMIT 10''', (user_id,))
    recent_games = cursor.fetchall()
    conn.close()
    if not recent_games:
        await message.answer("📊 <b>Статистика</b>\n\nУ вас еще нет сыгранных игр.")
        return
    text = "<b>📊 Последние 10 игр:</b>\n\n"
    for game in recent_games:
        game_type, bet_type, bet_amount, win, payout, created_at = game
        emoji = "✔️" if win else "✖️"
        profit = payout - bet_amount if win else -bet_amount
        type_name = "🪙 Монетка" if game_type == "coin" else game_type
        text += f"{emoji} <b>{type_name} - {bet_type}</b>\n   Ставка: {bet_amount:.2f} USDT | {profit:+.2f} USDT\n\n"
    await message.answer(text)


@dp.message(F.text == "🏆 Топ игроков")
async def menu_leaderboard(message: types.Message):
    leaders = get_leaderboard(10)
    if not leaders:
        await message.answer("🏆 <b>Топ игроков</b>\n\nПока никто не играл!")
        return
    text = "<b>🏆 ТОП-10 ИГРОКОВ</b>\n\n"
    medals = ["🥇", "🥈", "🥉"] + ["4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    for i, leader in enumerate(leaders):
        user_id, first_name, username, total_won, wins, games_played = leader
        medal = medals[i] if i < len(medals) else f"{i+1}."
        text += f"{medal} <b>{first_name}</b>\n   💰 {total_won:.2f} USDT | 🎮 {wins} побед\n\n"
    await message.answer(text)


@dp.message(F.text == "⚙️ Админ панель")
async def menu_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔️ У вас нет доступа к админ панели!")
        return
    await message.answer("<b>⚙️ Админ панель</b>\n\nВыберите действие:", reply_markup=admin_panel_keyboard())


# ==================== COIN GAME ====================

@dp.callback_query(F.data == "game_coin")
async def select_coin_game(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    balance = get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"<b>🪙 МОНЕТКА</b>\n\n"
        f"Орёл или решка?\n"
        f"🎲 Бросаем кубик — нечётное = 🦅 Орёл, чётное = 🎭 Решка\n"
        f"💰 Коэффициент: <b>x1.9</b>\n\n"
        f"💵 Ваш баланс: <b>{balance:.2f} USDT</b>\n\n"
        f"Выберите сумму ставки:",
        reply_markup=coin_amount_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("coin_amount_"))
async def coin_amount_selected(callback: types.CallbackQuery, state: FSMContext):
    value = callback.data.replace("coin_amount_", "")

    if value == "custom":
        await state.set_state(BetStates.coin_entering_amount)
        await callback.message.edit_text(
            "<b>🪙 МОНЕТКА</b>\n\nВведи сумму ставки (от 1 USDT):"
        )
        await callback.answer()
        return

    amount = float(value)
    user_id = callback.from_user.id
    balance = get_balance(user_id)

    if balance < amount:
        await callback.answer(
            f"❌ Недостаточно средств! Баланс: {balance:.2f} USDT",
            show_alert=True
        )
        return

    await callback.message.edit_text(
        f"<b>🪙 МОНЕТКА</b>\n\n"
        f"💰 Ставка: <b>{amount} USDT</b>\n"
        f"💎 Выигрыш: <b>{amount * 1.9:.2f} USDT</b>\n\n"
        f"Выбери сторону монеты:",
        reply_markup=coin_choice_keyboard(amount)
    )
    await callback.answer()


@dp.message(BetStates.coin_entering_amount)
async def coin_custom_amount_entered(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount < 1:
            await message.answer("❌ Минимум 1 USDT")
            return
        balance = get_balance(message.from_user.id)
        if balance < amount:
            await message.answer(
                f"❌ <b>Недостаточно средств!</b>\n\n"
                f"Баланс: {balance:.2f} USDT\n"
                f"Нужно: {amount:.2f} USDT",
                reply_markup=payment_method_keyboard(amount - balance, "deposit"))
            await state.clear()
            return
        await state.clear()
        await message.answer(
            f"<b>🪙 МОНЕТКА</b>\n\n"
            f"💰 Ставка: <b>{amount} USDT</b>\n"
            f"💎 Выигрыш: <b>{amount * 1.9:.2f} USDT</b>\n\n"
            f"Выбери сторону монеты:",
            reply_markup=coin_choice_keyboard(amount)
        )
    except ValueError:
        await message.answer("❌ Введи число!")


@dp.callback_query(F.data.startswith("coin_heads_") | F.data.startswith("coin_tails_"))
async def coin_flip_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    parts = callback.data.split("_")
    # coin_heads_10.0 → parts = ['coin', 'heads', '10.0']
    side = parts[1]  # heads или tails
    amount = float(parts[2])
    user_id = callback.from_user.id

    await process_coin_flip(callback, user_id, amount, side)


@dp.callback_query(F.data.startswith("coin_repeat_"))
async def coin_repeat_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    amount = float(callback.data.replace("coin_repeat_", ""))
    user_id = callback.from_user.id
    balance = get_balance(user_id)

    if balance < amount:
        await callback.message.answer(
            f"❌ <b>Недостаточно средств!</b>\n\nБаланс: {balance:.2f} USDT\nНужно: {amount:.2f} USDT",
            reply_markup=payment_method_keyboard(amount - balance, "deposit"))
        return

    await callback.message.edit_text(
        f"<b>🪙 МОНЕТКА</b>\n\n"
        f"💰 Ставка: <b>{amount} USDT</b>\n"
        f"💎 Выигрыш: <b>{amount * 1.9:.2f} USDT</b>\n\n"
        f"Выбери сторону монеты:",
        reply_markup=coin_choice_keyboard(amount)
    )


# ==================== GAME CALLBACKS ====================

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
    await callback.message.edit_text("<b>⚙️ Админ панель</b>\n\nВыберите действие:", reply_markup=admin_panel_keyboard())
    await callback.answer()


@dp.callback_query(F.data.startswith("game_"))
async def select_game(callback: types.CallbackQuery, state: FSMContext):
    game_id = callback.data.split("_", 1)[1]
    if game_id == "coin":
        return  # Обрабатывается отдельным хендлером выше

    await state.update_data(game_id=game_id)
    await state.set_state(BetStates.choosing_bet_type)
    game_name = GAMES[game_id]['name']
    await callback.message.edit_text(
        f"<b>🎮 {game_name}</b>\n\nВыбери тип ставки:",
        reply_markup=bet_types_keyboard(game_id)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("bettype_"))
async def select_bet_type(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 2)
    game_id, bet_type = parts[1], parts[2]
    await state.update_data(game_id=game_id, bet_type=bet_type, is_deposit_only=False)
    await state.set_state(BetStates.entering_custom_amount)
    game_name = GAMES[game_id]['name']
    odds = BET_TYPES[game_id][bet_type]['odds']
    await callback.message.edit_text(
        f"<b>🎮 {game_name}</b>\n<b>🎯 Ставка:</b> {bet_type} (x{odds})\n\n"
        f"💰 <b>Введите сумму ставки (от 1 USDT):</b>\n\n<i>Примеры: 1, 5, 10, 25</i>"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("repeat_"))
async def repeat_bet(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 3)
    game_id, bet_type, bet_amount = parts[1], parts[2], float(parts[3])
    user_id = callback.from_user.id
    balance = get_balance(user_id)
    if balance >= bet_amount:
        await state.update_data(game_id=game_id, bet_type=bet_type, bet_amount=bet_amount, is_deposit_only=False)
        await callback.answer("🎲 Повторяем ставку...")
        await process_game(callback.message, user_id, game_id, bet_type, bet_amount, state)
    else:
        await callback.message.answer(
            f"❌ Недостаточно средств!\n\nБаланс: {balance:.2f} USDT\nНужно: {bet_amount:.2f} USDT",
            reply_markup=payment_method_keyboard(bet_amount - balance, "bet"))
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
                f"💰 <b>Пополнение на {amount} USDT</b>\n\nВыберите способ оплаты:",
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
                    f"💰 <b>Недостаточно средств!</b>\n\nВаш баланс: <b>{balance:.2f} USDT</b>\n"
                    f"Нужно: <b>{amount:.2f} USDT</b>\nНе хватает: <b>{need_amount:.2f} USDT</b>\n\n"
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
            f"✅ <b>Промокод активирован!</b>\n\n🎁 Код: <code>{code}</code>\n"
            f"💰 Начислено: <b>{result} USDT</b>\n"
            f"💵 Ваш баланс: <b>{get_balance(user_id):.2f} USDT</b>")
    else:
        await message.answer(f"❌ <b>Ошибка!</b>\n\n{result}")
    await state.clear()


# ==================== PAYMENT CALLBACKS ====================

@dp.callback_query(F.data.startswith("pay_stars_"))
async def process_stars_payment(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    amount = float(parts[2])
    purpose = parts[3]
    user_id = callback.from_user.id
    stars_amount = int(amount / STARS_TO_USDT_RATE)
    await callback.message.delete()
    success = await create_stars_invoice(user_id, stars_amount, "Пополнение баланса",
                                         f"Пополнение на {amount} USDT", f"stars_{stars_amount}_{purpose}")
    if not success:
        await bot.send_message(user_id, "❌ Ошибка создания счета")
    await callback.answer()


@dp.callback_query(F.data.startswith("pay_crypto_"))
async def process_crypto_payment(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    amount = float(parts[2])
    user_id = callback.from_user.id
    invoice = await create_invoice(amount, f"Пополнение баланса {amount} USDT")
    if invoice:
        pay_url = invoice['pay_url']
        invoice_id = invoice['invoice_id']
        await callback.message.edit_text(
            f"💎 <b>Криптовалютный платеж</b>\n\n💰 Сумма: <b>{amount} USDT</b>\n\n⏳ Ожидаем оплату...",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
                [InlineKeyboardButton(text="✖️ Отменить", callback_data="cancel_payment")]
            ])
        )
        asyncio.create_task(auto_check_payment(callback.message, user_id, invoice_id, state))
    else:
        await callback.message.edit_text("❌ Ошибка создания инвойса")
    await callback.answer()


@dp.callback_query(F.data.startswith("pay_ton_"))
async def process_ton_payment(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    amount_usdt = float(parts[2])
    purpose = parts[3]
    user_id = callback.from_user.id
    ton_rate = get_ton_price()
    amount_ton = round(amount_usdt / ton_rate, 3)
    payment_id = f"pay{user_id}{int(datetime.now().timestamp())}"
    await state.update_data(ton_payment_id=payment_id, ton_amount_usdt=amount_usdt,
                            ton_amount_ton=amount_ton, is_deposit_only=(purpose == "deposit"))
    await state.set_state(BetStates.waiting_ton_payment)
    ton_link = f"ton://transfer/{TON_WALLET_ADDRESS}?amount={int(amount_ton * 1_000_000_000)}&text={payment_id}"
    await callback.message.edit_text(
        f"💠 <b>Оплата через TON Wallet</b>\n\n"
        f"💰 Сумма: <b>{amount_ton} TON</b> (= {amount_usdt} USDT)\n"
        f"💱 Курс: 1 TON = ${ton_rate}\n\n"
        f"📝 Адрес кошелька:\n<code>{TON_WALLET_ADDRESS}</code>\n\n"
        f"❗️ <b>Комментарий:</b>\n<code>{payment_id}</code>\n\n"
        f"✅ Средства зачислятся автоматически",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💠 Открыть TON Wallet", url=ton_link)],
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"ton_paid_{payment_id}")],
            [InlineKeyboardButton(text="✖️ Отменить", callback_data="cancel_payment")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("ton_paid_"))
async def confirm_ton_payment(callback: types.CallbackQuery, state: FSMContext):
    payment_id = callback.data.replace("ton_paid_", "")
    user_id = callback.from_user.id
    data = await state.get_data()
    if data.get('ton_payment_id') != payment_id:
        await callback.answer("❌ Ошибка идентификации", show_alert=True)
        return
    amount_usdt = data.get('ton_amount_usdt')
    amount_ton = data.get('ton_amount_ton')
    status_message = await callback.message.edit_text(
        f"⏳ <b>Проверяем платеж...</b>\n\nОжидаем {amount_ton} TON\nКомментарий: <code>{payment_id}</code>")
    await callback.answer("⏳ Проверяем...")
    asyncio.create_task(auto_check_ton_payment(status_message, user_id, payment_id, amount_ton, amount_usdt, state))


@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await bot.send_message(callback.from_user.id, "❌ Оплата отменена")
    await state.clear()
    await callback.answer()


# ==================== DUELS ====================

@dp.message(F.text == "⚔️ Дуэли")
async def menu_duels(message: types.Message):
    await message.answer(
        "<b>⚔️ ДУЭЛИ</b>\n\n"
        "Сразись с другим игроком!\n\n"
        "🎯 <b>Как играть:</b>\n"
        "1. Создай дуэль или прими чужую\n"
        "2. Оба игрока бросают кубик\n"
        "3. У кого выше результат — тот забирает банк!\n\n"
        "💰 <b>Комиссия:</b> 10% от банка\n"
        "📊 <b>Пример:</b> Ставка 10 USDT → банк 20 USDT → победитель получает 18 USDT",
        reply_markup=duels_menu_keyboard()
    )


@dp.callback_query(F.data == "duel_create")
async def duel_create_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BetStates.duel_choosing_game)
    await callback.message.edit_text("<b>⚔️ Создание дуэли</b>\n\nВыбери игру:", reply_markup=duel_games_keyboard())
    await callback.answer()


@dp.callback_query(F.data.startswith("duel_game_"))
async def duel_game_selected(callback: types.CallbackQuery, state: FSMContext):
    game_id = callback.data.replace("duel_game_", "")
    await state.update_data(duel_game_id=game_id)
    await state.set_state(BetStates.duel_entering_amount)
    game = GAMES[game_id]
    balance = get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"<b>⚔️ Создание дуэли</b>\n\n"
        f"{game['emoji']} <b>{game['name']}</b>\n\n"
        f"💵 Ваш баланс: <b>{balance:.2f} USDT</b>\n\n"
        f"💰 Введи сумму ставки (от 1 USDT):\n\n<i>Пример: 5, 10, 25</i>")
    await callback.answer()


@dp.message(BetStates.duel_entering_amount)
async def duel_amount_entered(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount < 1:
            await message.answer("❌ Минимальная ставка - 1 USDT")
            return
        user_id = message.from_user.id
        balance = get_balance(user_id)
        if balance < amount:
            await message.answer(
                f"❌ <b>Недостаточно средств!</b>\n\n"
                f"Баланс: {balance:.2f} USDT\nНужно: {amount:.2f} USDT\n\n"
                f"Пополни баланс:",
                reply_markup=payment_method_keyboard(amount - balance, "deposit"))
            await state.clear()
            return
        data = await state.get_data()
        game_id = data['duel_game_id']

        # Списываем ставку сразу при создании
        update_balance(user_id, -amount)
        duel_id = create_duel(user_id, game_id, amount)
        game = GAMES[game_id]

        try:
            await bot.send_message(STATS_CHANNEL_ID,
                f"⚔️ <b>НОВАЯ ДУЭЛЬ!</b>\n\n"
                f"{game['emoji']} <b>{game['name']}</b>\n"
                f"💰 Ставка: {amount} USDT | 🏆 Банк: {amount * 2:.2f} USDT\n"
                f"👤 Создал: {message.from_user.first_name}\n\n⏳ Ищем соперника...",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⚔️ Принять вызов", url="https://t.me/ffortunna_bot?start=duel")]
                ]))
        except:
            pass

        await message.answer(
            f"✅ <b>Дуэль #{duel_id} создана!</b>\n\n"
            f"{game['emoji']} Игра: {game['name']}\n"
            f"💰 Ставка: {amount} USDT | 🏆 Банк: {amount * 2:.2f} USDT\n"
            f"💵 Баланс: {get_balance(user_id):.2f} USDT\n\n"
            f"⏳ Ожидаем соперника...",
            reply_markup=duel_action_keyboard(duel_id))
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число! Например: 5 или 10")


@dp.callback_query(F.data == "duel_find")
async def duel_find(callback: types.CallbackQuery):
    duels = get_open_duels()
    if not duels:
        await callback.message.edit_text(
            "<b>🎯 Найти дуэль</b>\n\n😔 Нет доступных дуэлей\n\nСоздай свою дуэль первым!",
            reply_markup=duels_menu_keyboard())
    else:
        await callback.message.edit_text(
            f"<b>🎯 Открытые дуэли ({len(duels)})</b>\n\nВыбери дуэль:",
            reply_markup=open_duels_keyboard(duels))
    await callback.answer()


@dp.callback_query(F.data.startswith("duel_accept_"))
async def duel_accept_handler(callback: types.CallbackQuery, state: FSMContext):
    duel_id = int(callback.data.replace("duel_accept_", ""))
    user_id = callback.from_user.id

    duel = get_duel(duel_id)
    if not duel:
        await callback.answer("❌ Дуэль не найдена!", show_alert=True)
        return
    if duel[5] != 'waiting':
        await callback.answer("❌ Дуэль уже занята или завершена!", show_alert=True)
        return
    if duel[1] == user_id:
        await callback.answer("❌ Нельзя принять свою дуэль!", show_alert=True)
        return

    balance = get_balance(user_id)
    bet_amount = float(duel[4])

    if balance < bet_amount:
        await callback.answer(f"❌ Нужно {bet_amount} USDT! У вас {balance:.2f}", show_alert=True)
        return

    # Принимаем дуэль и списываем ставку
    if not accept_duel(duel_id, user_id):
        await callback.answer("❌ Дуэль уже занята!", show_alert=True)
        return

    update_balance(user_id, -bet_amount)

    await callback.answer("⚔️ Дуэль принята! Начинаем...")

    try:
        await callback.message.edit_text(
            f"⚔️ <b>Дуэль #{duel_id} принята!</b>\n\n⏳ Идёт игра...")
    except:
        pass

    # Запускаем игру в фоне
    asyncio.create_task(start_duel_game(user_id, duel_id))


@dp.callback_query(F.data.startswith("duel_cancel_"))
async def duel_cancel_handler(callback: types.CallbackQuery):
    duel_id = int(callback.data.replace("duel_cancel_", ""))
    user_id = callback.from_user.id
    duel = get_duel(duel_id)
    if not duel or duel[1] != user_id:
        await callback.answer("❌ Нельзя отменить эту дуэль!", show_alert=True)
        return
    if duel[5] != 'waiting':
        await callback.answer("❌ Дуэль уже началась!", show_alert=True)
        return
    cancel_duel(duel_id)
    # Возвращаем ставку
    update_balance(user_id, float(duel[4]))
    await callback.message.edit_text(
        f"✅ <b>Дуэль #{duel_id} отменена</b>\n\n"
        f"💰 Ставка возвращена: <b>{duel[4]} USDT</b>\n"
        f"💵 Баланс: <b>{get_balance(user_id):.2f} USDT</b>")
    await callback.answer()


@dp.callback_query(F.data == "duel_my")
async def duel_my(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    duels = get_user_duels(user_id, 10)
    if not duels:
        await callback.message.edit_text(
            "<b>📜 Мои дуэли</b>\n\nУ тебя ещё не было дуэлей!",
            reply_markup=duels_menu_keyboard())
        await callback.answer()
        return
    text = "<b>📜 Последние 10 дуэлей:</b>\n\n"
    for duel in duels:
        duel_id, creator_id, opponent_id, game_type, bet_amount, status = duel[0], duel[1], duel[2], duel[3], duel[4], duel[5]
        winner_id = duel[8]
        game_emoji = GAMES.get(game_type, {}).get('emoji', '🎮')
        if status == 'waiting':       s = "⏳ Ожидание"
        elif status == 'cancelled':   s = "❌ Отменена"
        elif status == 'in_progress': s = "⚔️ В игре"
        elif status == 'finished':
            if winner_id is None:     s = "🤝 Ничья"
            elif winner_id == user_id: s = "🏆 Победа"
            else:                      s = "😔 Поражение"
        else: s = status
        text += f"#{duel_id} {game_emoji} | {bet_amount} USDT | {s}\n"
    await callback.message.edit_text(text, reply_markup=duels_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "duel_menu")
async def duel_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "<b>⚔️ ДУЭЛИ</b>\n\nСразись с другим игроком!\n\n💰 <b>Комиссия:</b> 10% от банка",
        reply_markup=duels_menu_keyboard())
    await callback.answer()


# ==================== TOURNAMENTS ====================

@dp.message(F.text == "🏆 Турниры")
async def menu_tournaments(message: types.Message):
    create_weekend_tournament()
    tournament = get_active_tournament()

    if tournament:
        t_id, name, entry_fee, prize_pool, status, start_time, end_time, created_at = tournament
        conn = sqlite3.connect('lottery_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM tournament_participants WHERE tournament_id = ?', (t_id,))
        participants = cursor.fetchone()[0]
        conn.close()
        end_dt = datetime.fromisoformat(end_time)
        time_left = end_dt - datetime.now()
        hours_left = int(time_left.total_seconds() / 3600)
        await message.answer(
            f"<b>{name}</b>\n\n"
            f"💰 <b>Взнос:</b> {entry_fee} USDT\n"
            f"🏆 <b>Призовой фонд:</b> {prize_pool:.2f} USDT\n"
            f"👥 <b>Участников:</b> {participants}\n"
            f"⏰ <b>Осталось:</b> {hours_left}ч\n\n"
            f"🥇 50% | 🥈 30% | 🥉 20%\n\nУдачи! 🍀",
            reply_markup=tournament_menu_keyboard(t_id))
    else:
        await message.answer(
            "<b>🏆 ТУРНИРЫ</b>\n\n⏰ Сейчас нет активных турниров\n\n"
            "🗓 Каждую субботу и воскресенье\n💰 Взнос: 10 USDT",
            reply_markup=tournament_menu_keyboard())


@dp.callback_query(F.data.startswith("tournament_join_"))
async def tournament_join_handler(callback: types.CallbackQuery):
    tournament_id = int(callback.data.replace("tournament_join_", ""))
    user_id = callback.from_user.id
    tournament = get_active_tournament()
    if not tournament or tournament[0] != tournament_id:
        await callback.answer("❌ Турнир не найден!", show_alert=True)
        return
    entry_fee = tournament[2]
    balance = get_balance(user_id)
    if balance < entry_fee:
        await callback.answer(f"❌ Недостаточно средств! Нужно {entry_fee} USDT", show_alert=True)
        return
    if join_tournament(tournament_id, user_id, entry_fee):
        update_balance(user_id, -entry_fee)
        await callback.answer(f"✅ Вы вступили в турнир! (-{entry_fee} USDT)", show_alert=True)
        await callback.message.edit_text(
            f"✅ <b>Вы участвуете в турнире!</b>\n\n"
            f"💰 Списано: {entry_fee} USDT\n"
            f"💵 Баланс: {get_balance(user_id):.2f} USDT\n\nИграйте и зарабатывайте очки! 🎮")
    else:
        await callback.answer("❌ Вы уже участвуете в этом турнире!", show_alert=True)


@dp.callback_query(F.data.startswith("tournament_leaderboard_"))
async def tournament_leaderboard_handler(callback: types.CallbackQuery):
    tournament_id = int(callback.data.replace("tournament_leaderboard_", ""))
    leaders = get_tournament_leaderboard(tournament_id, 10)
    if not leaders:
        await callback.answer("Пока нет участников!", show_alert=True)
        return
    text = "<b>🏆 ТАБЛИЦА ЛИДЕРОВ</b>\n\n"
    medals = ["🥇", "🥈", "🥉"] + ["4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    for i, leader in enumerate(leaders):
        user_id, first_name, username, profit, games = leader
        medal = medals[i] if i < len(medals) else f"{i+1}."
        text += f"{medal} <b>{first_name}</b>\n   💰 {profit:+.2f} USDT | 🎮 {games} игр\n\n"
    await callback.message.edit_text(text, reply_markup=tournament_menu_keyboard(tournament_id))
    await callback.answer()


@dp.callback_query(F.data == "tournament_info")
async def tournament_info_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "<b>ℹ️ О ТУРНИРАХ</b>\n\n"
        "<b>Когда:</b> Каждую субботу и воскресенье\n\n"
        "<b>Как участвовать:</b>\n"
        "1. Оплати взнос (10 USDT)\n"
        "2. Играй в любые игры\n"
        "3. Набирай очки с выигрышей\n\n"
        "<b>Призы:</b>\n"
        "🥇 1 место: 50% фонда\n"
        "🥈 2 место: 30% фонда\n"
        "🥉 3 место: 20% фонда\n\n"
        "Удачи! 🍀",
        reply_markup=tournament_menu_keyboard())
    await callback.answer()


# ==================== REFERRALS ====================

@dp.message(F.text == "👥 Рефералы")
async def menu_referrals(message: types.Message):
    user_id = message.from_user.id
    total_refs, _ = get_referral_stats(user_id)
    ref_link = get_referral_link(user_id)
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = ? AND type = 'referral_bonus'", (user_id,))
    total_earned = cursor.fetchone()[0]
    conn.close()
    text = (f"<b>👥 Реферальная программа</b>\n\n"
            f"🎁 <b>Ваша реферальная ссылка:</b>\n<code>{ref_link}</code>\n\n"
            f"📊 <b>Статистика:</b>\n👤 Приглашено: {total_refs} чел.\n💰 Заработано: {total_earned:.2f} USDT\n\n"
            f"<b>Условия:</b>\n• За каждое пополнение друга: <b>5%</b>\n• Начисляется автоматически\n\nПоделитесь ссылкой! 🚀")
    if total_refs > 0:
        refs = get_referrals_list(user_id)
        text += "\n\n<b>🎯 Ваши рефералы:</b>\n"
        for ref in refs[:5]:
            text += f"👤 {ref[1]} (@{ref[2] or 'нет'})\n"
        if total_refs > 5:
            text += f"\n<i>... и ещё {total_refs - 5}</i>"
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся! 🎰")]
    ]))


@dp.callback_query(F.data == "show_ref_link")
async def show_ref_link_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    ref_link = get_referral_link(user_id)
    total_refs, _ = get_referral_stats(user_id)
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = ? AND type = 'referral_bonus'", (user_id,))
    total_earned = cursor.fetchone()[0]
    conn.close()
    await callback.message.answer(
        f"<b>👥 Твоя реферальная ссылка:</b>\n\n<code>{ref_link}</code>\n\n"
        f"📊 Рефералов: {total_refs} | 💰 Заработано: {total_earned:.2f} USDT\n\n"
        f"🎁 <b>5% от каждого пополнения</b> друга!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся! 🎰")]
        ]))
    await callback.answer()


# ==================== ADMIN ====================

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
        f"✖️ Проиграно: {total_lost:.2f} USDT\n"
        f"💹 Профит казино: {total_lost - total_won:.2f} USDT",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_admin_panel")]
        ]))
    await callback.answer()


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    users = get_all_users()
    text = "<b>👥 Список пользователей:</b>\n\n"
    for user in users[:20]:
        user_id, username, first_name, balance, total_deposited = user[0], user[1], user[2], user[3], user[4]
        vip = VIP_LEVELS[get_vip_level(total_deposited)]['name']
        text += f"ID: <code>{user_id}</code>\n👤 {first_name} (@{username or 'нет'}) {vip}\n💰 {balance:.2f} USDT\n\n"
    if len(users) > 20:
        text += f"<i>... и ещё {len(users) - 20}</i>"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_admin_panel")]
    ]))
    await callback.answer()


@dp.callback_query(F.data == "admin_balances")
async def admin_balances(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    await callback.message.edit_text("<b>💰 Управление балансами</b>", reply_markup=admin_balance_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin_promocodes")
async def admin_promocodes(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    await callback.message.edit_text("<b>🎁 Управление промокодами</b>", reply_markup=admin_promocode_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin_create_promo")
async def admin_create_promo(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    await state.set_state(BetStates.admin_creating_promo_code)
    await callback.message.edit_text("<b>➕ Создание промокода</b>\n\nВведите код (например: BONUS100):")
    await callback.answer()


@dp.callback_query(F.data == "admin_list_promos")
async def admin_list_promos(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    promos = get_all_promocodes()
    if not promos:
        await callback.message.edit_text("<b>📋 Промокодов нет.</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promocodes")]]))
        await callback.answer()
        return
    text = "<b>📋 Активные промокоды:</b>\n\n"
    for promo in promos:
        promo_id, code, amount, max_uses, current_uses, created_at = promo
        text += f"🎁 <code>{code}</code> — {amount} USDT | {current_uses}/{max_uses}\n"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promocodes")]
    ]))
    await callback.answer()


@dp.callback_query(F.data == "admin_delete_promo")
async def admin_delete_promo(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    promos = get_all_promocodes()
    if not promos:
        await callback.answer("Промокодов нет!", show_alert=True)
        return
    buttons = [[InlineKeyboardButton(text=f"🗑 {p[1]}", callback_data=f"delete_promo_{p[1]}")] for p in promos]
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promocodes")])
    await callback.message.edit_text("<b>🗑 Удаление промокода:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("delete_promo_"))
async def confirm_delete_promo(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    code = callback.data.replace("delete_promo_", "")
    delete_promocode(code)
    await callback.message.edit_text(f"✅ Промокод <code>{code}</code> удалён.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promocodes")]]))
    await callback.answer()


@dp.callback_query(F.data == "admin_check_balance")
async def admin_check_balance(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    await state.set_state(BetStates.admin_entering_user_id)
    await state.update_data(action="check")
    await callback.message.edit_text("<b>🔍 Проверка баланса</b>\n\nВведите Telegram ID:")
    await callback.answer()


@dp.callback_query(F.data == "admin_add_balance")
async def admin_add_balance(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    await state.set_state(BetStates.admin_entering_user_id)
    await state.update_data(action="add")
    await callback.message.edit_text("<b>➕ Добавление баланса</b>\n\nВведите Telegram ID:")
    await callback.answer()


@dp.callback_query(F.data == "admin_subtract_balance")
async def admin_subtract_balance(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    await state.set_state(BetStates.admin_entering_user_id)
    await state.update_data(action="subtract")
    await callback.message.edit_text("<b>➖ Вычитание баланса</b>\n\nВведите Telegram ID:")
    await callback.answer()


@dp.callback_query(F.data == "admin_set_balance")
async def admin_set_balance_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    await state.set_state(BetStates.admin_entering_user_id)
    await state.update_data(action="set")
    await callback.message.edit_text("<b>💰 Установка баланса</b>\n\nВведите Telegram ID:")
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
            await message.answer(f"<b>🔍 Баланс</b>\n\nID: <code>{target_user_id}</code>\n💰 {get_balance(target_user_id):.2f} USDT")
            await state.clear()
        else:
            await state.set_state(BetStates.admin_entering_balance)
            labels = {"add": "➕ Добавление", "subtract": "➖ Вычитание", "set": "💰 Установка"}
            await message.answer(
                f"<b>{labels.get(action, action)}</b>\n\nID: <code>{target_user_id}</code>\n"
                f"💰 Баланс: {get_balance(target_user_id):.2f} USDT\n\nВведите сумму:")
    except ValueError:
        await message.answer("❌ Неверный формат ID!")


@dp.message(BetStates.admin_entering_balance)
async def process_admin_balance(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        amount = float(message.text.replace(',', '.'))
        data = await state.get_data()
        target_user_id = data.get('target_user_id')
        action = data.get('action')
        current = get_balance(target_user_id)
        if action == "set":
            set_balance(target_user_id, amount)
            await message.answer(f"✅ Установлено {amount:.2f} USDT (ID: <code>{target_user_id}</code>)")
        elif action == "add":
            set_balance(target_user_id, current + amount)
            await message.answer(f"✅ Добавлено {amount:.2f} USDT\nНовый: {current + amount:.2f} USDT")
        elif action == "subtract":
            set_balance(target_user_id, current - amount)
            await message.answer(f"✅ Вычтено {amount:.2f} USDT\nНовый: {current - amount:.2f} USDT")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число!")
        await state.clear()


@dp.message(BetStates.admin_creating_promo_code)
async def process_promo_code(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    code = message.text.strip().upper()
    if len(code) < 3:
        await message.answer("❌ Минимум 3 символа!")
        return
    await state.update_data(promo_code=code)
    await state.set_state(BetStates.admin_creating_promo_amount)
    await message.answer(f"🎁 Код: <code>{code}</code>\n\nВведите сумму начисления (USDT):")


@dp.message(BetStates.admin_creating_promo_amount)
async def process_promo_amount(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            await message.answer("❌ Сумма > 0!")
            return
        await state.update_data(promo_amount=amount)
        await state.set_state(BetStates.admin_creating_promo_uses)
        data = await state.get_data()
        await message.answer(f"🎁 Код: <code>{data['promo_code']}</code>\n💰 {amount} USDT\n\nВведите макс. кол-во активаций:")
    except ValueError:
        await message.answer("❌ Введите число!")


@dp.message(BetStates.admin_creating_promo_uses)
async def process_promo_uses(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        max_uses = int(message.text)
        if max_uses <= 0:
            await message.answer("❌ Количество > 0!")
            return
        data = await state.get_data()
        code, amount = data['promo_code'], data['promo_amount']
        if create_promocode(code, amount, max_uses):
            await message.answer(f"✅ <b>Промокод создан!</b>\n\n🎁 <code>{code}</code>\n💰 {amount} USDT\n📊 0/{max_uses}")
        else:
            await message.answer(f"❌ Промокод <code>{code}</code> уже существует!")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите целое число!")


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    await state.set_state(BetStates.admin_broadcast)
    await callback.message.edit_text("<b>📢 Рассылка</b>\n\nОтправьте сообщение.\n\n/cancel для отмены")
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
    status_msg = await message.answer(f"📢 <b>Начинаю рассылку...</b>\n\nВсего: {total}")
    for user in users:
        user_id = user[0]
        try:
            if message.photo:
                await bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption or "")
            elif message.video:
                await bot.send_video(user_id, message.video.file_id, caption=message.caption or "")
            elif message.text:
                await bot.send_message(user_id, message.text)
            success += 1
        except:
            failed += 1
        if (success + failed) % 10 == 0:
            try:
                await status_msg.edit_text(f"📢 Рассылка...\n✅ {success} | ❌ {failed}")
            except:
                pass
        await asyncio.sleep(0.05)
    await status_msg.edit_text(f"✅ <b>Рассылка завершена!</b>\n\nВсего: {total}\n✅ {success} | ❌ {failed}")
    await state.clear()


@dp.callback_query(F.data == "admin_deposits")
async def admin_deposits(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    conn = sqlite3.connect('lottery_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.id, t.user_id, t.type, t.amount, t.status, t.invoice_id, t.created_at, u.first_name, u.username
        FROM transactions t JOIN users u ON t.user_id = u.user_id
        WHERE t.type IN ('deposit', 'promocode', 'referral_bonus')
        ORDER BY t.created_at DESC LIMIT 20
    ''')
    deposits = cursor.fetchall()
    conn.close()
    if not deposits:
        await callback.message.edit_text("<b>💳 Пополнений нет.</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_admin_panel")]]))
        await callback.answer()
        return
    text = "<b>💳 Последние 20 пополнений:</b>\n\n"
    for d in deposits:
        trans_id, user_id, trans_type, amount, status, invoice_id, created_at, first_name, username = d
        if invoice_id.startswith('stars_'):   method = "⭐"
        elif invoice_id.startswith('ton_'):   method = "💠"
        elif invoice_id.startswith('promo_'): method = "🎁"
        elif invoice_id.startswith('ref_'):   method = "👥"
        else:                                 method = "💎"
        s = "✅" if status == "completed" else "⏳"
        try: date = datetime.fromisoformat(created_at).strftime("%d.%m %H:%M")
        except: date = created_at[:16]
        text += f"{s} {method} <b>#{trans_id}</b> | {first_name} | <b>{amount:.2f} USDT</b> | {date}\n"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Поиск по ID", callback_data="admin_deposit_search")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_admin_panel")]
    ]))
    await callback.answer()


@dp.callback_query(F.data == "admin_deposit_search")
async def admin_deposit_search_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Нет доступа!", show_alert=True)
        return
    await state.set_state(BetStates.admin_deposit_search)
    await callback.message.edit_text("<b>🔍 Поиск пополнений</b>\n\nВведите Telegram ID:")
    await callback.answer()


@dp.message(BetStates.admin_deposit_search)
async def admin_deposit_search_process(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        user_id = int(message.text)
        conn = sqlite3.connect('lottery_bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT t.id, t.type, t.amount, t.status, t.invoice_id, t.created_at, u.first_name
            FROM transactions t JOIN users u ON t.user_id = u.user_id
            WHERE t.user_id = ? AND t.type IN ('deposit', 'promocode', 'referral_bonus')
            ORDER BY t.created_at DESC
        ''', (user_id,))
        deposits = cursor.fetchall()
        cursor.execute('SELECT balance, total_deposited FROM users WHERE user_id = ?', (user_id,))
        user_data = cursor.fetchone()
        conn.close()
        if not user_data:
            await message.answer("❌ Пользователь не найден!")
            await state.clear()
            return
        balance, total_deposited = user_data
        text = (f"<b>🔍 ID {user_id}</b>\n\n"
                f"💰 Баланс: <b>{balance:.2f} USDT</b>\n📥 Всего: <b>{total_deposited:.2f} USDT</b>\n\n")
        if not deposits:
            text += "❌ Пополнений нет"
        else:
            text += "<b>История:</b>\n\n"
            for d in deposits:
                trans_id, trans_type, amount, status, invoice_id, created_at, first_name = d
                if invoice_id.startswith('stars_'):   method = "⭐ Stars"
                elif invoice_id.startswith('ton_'):   method = "💠 TON"
                elif invoice_id.startswith('promo_'): method = "🎁 Промокод"
                elif invoice_id.startswith('ref_'):   method = "👥 Реферал"
                else:                                 method = "💎 Crypto"
                s = "✅" if status == "completed" else "⏳"
                try: date = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
                except: date = created_at[:19]
                text += f"{s} {method} | <b>{amount:.2f} USDT</b> | {date}\n"
        await message.answer(text)
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный формат ID!")


# ==================== ADMIN COMMANDS ====================

@dp.message(Command("approve_ton"))
async def approve_ton_payment(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        parts = message.text.split()
        target_user_id = int(parts[1])
        amount_usdt = float(parts[2])
        update_balance(target_user_id, amount_usdt)
        conn = sqlite3.connect('lottery_bot.db')
        cursor = conn.cursor()
        invoice_id = f"ton_{target_user_id}_{datetime.now().timestamp()}"
        cursor.execute('''INSERT INTO transactions (user_id, type, amount, status, invoice_id)
                          VALUES (?, 'deposit', ?, 'completed', ?)''', (target_user_id, amount_usdt, invoice_id))
        cursor.execute('UPDATE users SET total_deposited = total_deposited + ? WHERE user_id = ?',
                       (amount_usdt, target_user_id))
        conn.commit()
        conn.close()
        pay_referral_bonus(target_user_id, amount_usdt)
        try:
            await bot.send_message(target_user_id,
                f"✅ <b>Оплата подтверждена!</b>\n\n💰 {amount_usdt} USDT\n💵 Баланс: {get_balance(target_user_id):.2f} USDT")
        except:
            pass
        await message.answer(f"✅ Подтверждено! User: {target_user_id} | Сумма: {amount_usdt} USDT")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}\n\nФормат: /approve_ton USER_ID AMOUNT")


@dp.message(Command("tonprice"))
async def cmd_ton_price(message: types.Message):
    price = get_ton_price()
    await message.answer(
        f"💱 <b>Курс TON</b>\n\n1 TON = <b>${price}</b>\n\n"
        f"10 USDT = {10/price:.3f} TON\n50 USDT = {50/price:.3f} TON\n100 USDT = {100/price:.3f} TON")


# ==================== MAIN ====================

async def main():
    init_db()
    create_weekend_tournament()
    logger.info("🚀 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        try:
            import watchfiles
            print("🔥 Hot Reload активирован!")
            def run_bot():
                return subprocess.Popen([sys.executable, __file__, '--running'])
            process = run_bot()
            last_mtime = os.path.getmtime(__file__)
            try:
                while True:
                    time.sleep(1)
                    current_mtime = os.path.getmtime(__file__)
                    if current_mtime != last_mtime:
                        print("🔄 Изменения обнаружены! Перезапуск...")
                        process.terminate()
                        process.wait()
                        last_mtime = current_mtime
                        process = run_bot()
            except KeyboardInterrupt:
                print("\n🛑 Остановка...")
                process.terminate()
                process.wait()
        except ImportError:
            print("📦 Устанавливаю watchfiles...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "watchfiles", "-q"])
            print("✅ Установлено! Перезапускаю...")
            os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        asyncio.run(main())
