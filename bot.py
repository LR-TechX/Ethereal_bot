import logging
import sqlite3
import re
import time
import secrets
import datetime
import os
import psycopg2
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# SQl Alchemy updated for deployment
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os

load_dotenv()  # loads .env

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
db = SQLAlchemy(app)

# Load environment variables for sensitive credentials
from dotenv import load_dotenv
load_dotenv()

# Bot credentials
BOT_TOKEN = os.getenv("BOT_TOKEN", "7603606508:AAHACwLH7BtDb5UUz-ifwTxeSWBZGlCwGOw")
ADMIN_ID = int(os.getenv("ADMIN_ID", 5646269450))  # Super admin ID
GROUP_LINK = os.getenv("GROUP_LINK", "@etherealplus")
SITE_LINK = os.getenv("SITE_LINK", "https://etherealweb.site/signup?ref=Bigscott")
AI_BOOST_LINK = os.getenv("AI_BOOST_LINK", "https://etherealweb.site/account/social-boost")
VERIFICATION_GROUP = os.getenv("VERIFICATION_GROUP", "@taskchecked")
DAILY_TASK_LINK = os.getenv("DAILY_TASK_LINK", "https://etherealweb.site/account/social/snapchat-streak")

# The database source
DATABASE_URL = os.environ.get('DATABASE_URL')
# Predefined FAQs
FAQS = {
    "what_is_ethereal": {
        "question": "What is Ethereal?",
        "answer": "Ethereal is a platform where you earn money by completing tasks like reading posts, playing games, sending Snapchat streaks, and inviting friends."
    },
    "payment_methods": {
        "question": "What payment methods are available?",
        "answer": "Payments can be made via bank transfer, mobile money, or Zelle, depending on your country. Check the 'How to Pay' guide in the Help menu."
    },
    "task_rewards": {
        "question": "How are task rewards calculated?",
        "answer": "Rewards vary by task type. For example, reading posts earns $2.5 per 10 words, Candy Crush tasks earn $5 daily, and Snapchat streaks can earn up to $20."
    }
}

HELP_TOPICS = {
    "how_to_pay": {"label": "How to Pay", "type": "video", "url": "https://youtu.be/YourPaymentGuide"},
    "register": {"label": "Registration Process", "type": "text", "text": (
        "1. Once you have clicked start → choose package\n"
        "2. Select your coach\n"
        "3. Pay via your selected country account → upload screenshot\n"
        "4. Wait for approval, then send details\n"
        "5. Join the group and start earning! 🎉"
    )},
    "daily_tasks": {"label": "Daily Tasks", "type": "video", "url": "https://youtu.be/YourTasksGuide"},
    "reminder": {"label": "Toggle Reminder", "type": "toggle"},
    "faq": {"label": "FAQs", "type": "faq"},
    "password_recovery": {"label": "Password Recovery", "type": "input", "text": "Please provide your registered email to request password recovery:"},
    "apply_coach": {"label": "Apply to be a Coach", "type": "text", "text": "To apply to be a coach, use the /coach command. An admin will contact you."},
}

# Database setup with error handling
try:
    conn = psycopg2.connect('DATABASE_URL', check_same_thread=False)
    cursor = conn.cursor()

    # Users table with added 'selected_coach' column
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY,
        package TEXT,
        payment_status TEXT DEFAULT 'new',
        name TEXT,
        username TEXT,
        email TEXT,
        phone TEXT,
        password TEXT,
        join_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        alarm_setting INTEGER DEFAULT 0,
        streaks INTEGER DEFAULT 0,
        invites INTEGER DEFAULT 0,
        balance REAL DEFAULT 0,
        screenshot_uploaded_at DATETIME,
        approved_at DATETIME,
        registration_date DATETIME,
        referral_code TEXT,
        referred_by INTEGER,
        selected_coach INTEGER
    )
    """)

    # Payments table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        type TEXT,
        package TEXT,
        quantity INTEGER,
        total_amount INTEGER,
        payment_account TEXT,
        status TEXT DEFAULT 'pending_payment',
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        approved_at DATETIME
    )
    """)

    # Coupons table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS coupons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id INTEGER,
        code TEXT,
        FOREIGN KEY (payment_id) REFERENCES payments(id)
    )
    """)

    # Interactions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS interactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        action TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Tasks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT,
        link TEXT,
        reward REAL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        expires_at DATETIME
    )
    """)

    # User_tasks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_tasks (
        user_id INTEGER,
        task_id INTEGER,
        completed_at DATETIME,
        PRIMARY KEY (user_id, task_id),
        FOREIGN KEY (user_id) REFERENCES users(chat_id),
        FOREIGN KEY (task_id) REFERENCES tasks(id)
    )
    """)

    # Coaches table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS coaches (
        coach_id INTEGER PRIMARY KEY,
        name TEXT,
        added_by INTEGER,
        added_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Payment accounts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payment_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        country TEXT,
        flag TEXT,
        details TEXT,
        is_active INTEGER DEFAULT 1
    )
    """)

    # Ensure 'selected_coach' column exists in users table
    cursor.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'selected_coach' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN selected_coach INTEGER")

    # Ensure "Big Scott Media" is in the coaches table as the default coach
    cursor.execute("SELECT * FROM coaches WHERE coach_id=?", (ADMIN_ID,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO coaches (coach_id, name, added_by) VALUES (?, ?, ?)", (ADMIN_ID, "Big Scott Media", ADMIN_ID))
    conn.commit()
except sqlite3.Error as e:
    logging.error(f"Database error: {e}")
    raise

# In-memory storage
user_state = {}
start_time = time.time()

# Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Helper functions
def get_status(chat_id):
    try:
        cursor.execute("SELECT payment_status FROM users WHERE chat_id=?", (chat_id,))
        row = cursor.fetchone()
        return row[0] if row else None
    except sqlite3.Error as e:
        logger.error(f"Database error in get_status: {e}")
        return None

def log_interaction(chat_id, action):
    try:
        cursor.execute("INSERT INTO interactions (chat_id, action) VALUES (?, ?)", (chat_id, action))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error in log_interaction: {e}")

def generate_referral_code():
    return secrets.token_urlsafe(6)

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    referral_code = generate_referral_code()
    args = context.args
    referred_by = None
    if args and args[0].startswith("ref_"):
        referred_by = int(args[0].split("_")[1])
    log_interaction(chat_id, "start")
    try:
        cursor.execute("SELECT payment_status FROM users WHERE chat_id=?", (chat_id,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO users (chat_id, username, referral_code, referred_by) VALUES (?, ?, ?, ?)",
                (chat_id, update.effective_user.username or "Unknown", referral_code, referred_by)
            )
            conn.commit()
            if referred_by:
                cursor.execute("UPDATE users SET invites = invites + 1, balance = balance + 0.1 WHERE chat_id=?", (referred_by,))
                conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error in start: {e}")
        await update.message.reply_text("An error occurred. Please try again.")
        return
    keyboard = [[InlineKeyboardButton("🚀 Proceed", callback_data="menu")]]
    referral_link = f"https://t.me/{context.bot.username}?start=ref_{chat_id}"
    await update.message.reply_text(
        f"Welcome to Ethereal!\n\nGet paid for working with AI and doing what you love most.\n"
        "• Read posts ➜ earn $2.5/10 words\n• Play Candy Crush daily ➜ earn $5\n"
        "• Send Snapchat streaks ➜ earn up to $20\n• Invite friends and more!\n\n"
        f"Your referral link: {referral_link}\n"
        "Choose your package and start earning today.\nClick below to get started.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    reply_keyboard = [["/menu(🔙)"]]
    await update.message.reply_text(
        "Use the button below 'ONLY' if you get stuck on a process:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_state[chat_id] = {'expecting': 'support_message'}
    await update.message.reply_text("Please describe your issue or question:")
    log_interaction(chat_id, "support_initiated")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    log_interaction(chat_id, "stats")
    try:
        cursor.execute("SELECT payment_status, streaks, invites, package, balance FROM users WHERE chat_id=?", (chat_id,))
        user = cursor.fetchone()
        if not user:
            if update.callback_query:
                await update.callback_query.answer("No user data found. Please start with /start.")
            else:
                await update.message.reply_text("No user data found. Please start with /start.")
            return
        payment_status, streaks, invites, package, balance = user
        text = (
            "📊 Your Platform Stats:\n\n"
            f"• Package: {package or 'Not selected'}\n"
            f"• Payment Status: {payment_status.capitalize()}\n"
            f"• Streaks: {streaks}\n"
            f"• Invites: {invites}\n"
            f"• Balance: ${balance:.2f}"
        )
        if balance >= 30:
            keyboard = [[InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]]
        else:
            keyboard = []
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    except sqlite3.Error as e:
        logger.error(f"Database error in stats: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def reset_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in user_state:
        del user_state[chat_id]
    await update.message.reply_text("State reset. Try the flow again.")
    log_interaction(chat_id, "reset_state")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("This command is restricted to the super admin.")
        return
    user_state[chat_id] = {'expecting': 'broadcast_message'}
    await update.message.reply_text("Please enter the broadcast message to send to all registered users:")
    log_interaction(chat_id, "broadcast_initiated")

async def botstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("This command is restricted to the super admin.")
        return
    runtime = time.time() - start_time
    try:
        cursor.execute("SELECT COUNT(DISTINCT chat_id) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT chat_id) FROM users WHERE payment_status='registered'")
        registered_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM interactions WHERE action='start'")
        link_clicks = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM interactions WHERE timestamp >= datetime('now', '-1 hour')")
        hourly_usage = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM interactions WHERE timestamp >= datetime('now', '-24 hours')")
        daily_usage = cursor.fetchone()[0]
        text = (
            "🤖 Bot Stats:\n\n"
            f"• Runtime: {int(runtime // 3600)}h {int((runtime % 3600) // 60)}m\n"
            f"• Total Users: {total_users}\n"
            f"• Registered Users: {registered_users}\n"
            f"• Bot Link Clicks: {link_clicks}\n"
            f"• Hourly Interactions: {hourly_usage}\n"
            f"• Daily Interactions: {daily_usage}"
        )
        await update.message.reply_text(text)
        log_interaction(chat_id, "botstats")
    except sqlite3.Error as e:
        logger.error(f"Database error in botstats: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def registered_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("This command is restricted to the super admin.")
        return
    try:
        cursor.execute("SELECT chat_id, username, package, registration_date FROM users WHERE payment_status='registered'")
        users = cursor.fetchall()
        if not users:
            await update.message.reply_text("No registered users found.")
            return
        text = "Registered Users:\n\n"
        for user in users:
            text += f"Chat ID: {user[0]}, Username: @{user[1] or 'Unknown'}, Package: {user[2]}, Registered: {user[3]}\n"
        await update.message.reply_text(text)
        log_interaction(chat_id, "registered_users")
    except sqlite3.Error as e:
        logger.error(f"Database error in registered_users: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("This command is restricted to the super admin.")
        return
    args = context.args
    if len(args) != 3:
        await update.message.reply_text("Usage: /add_task <type> <link> <reward>")
        return
    task_type, link, reward = args
    try:
        reward = float(reward)
    except ValueError:
        await update.message.reply_text("Reward must be a number.")
        return
    created_at = datetime.datetime.now()
    expires_at = created_at + datetime.timedelta(days=1)
    try:
        cursor.execute(
            "INSERT INTO tasks (type, link, reward, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (task_type, link, reward, created_at, expires_at)
        )
        conn.commit()
        await update.message.reply_text("Task added successfully.")
        log_interaction(chat_id, "add_task")
    except sqlite3.Error as e:
        logger.error(f"Database error in add_task: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def apply_coach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        cursor.execute("SELECT payment_status FROM users WHERE chat_id=?", (chat_id,))
        status = cursor.fetchone()[0]
        if status != 'registered':
            await update.message.reply_text("Only registered users can apply to be a coach.")
            return
        await context.bot.send_message(
            ADMIN_ID,
            f"User @{update.effective_user.username or 'Unknown'} (chat_id: {chat_id}) wants to apply to be a coach."
        )
        await update.message.reply_text("Your application has been sent. An admin will contact you soon.")
        log_interaction(chat_id, "apply_coach")
    except sqlite3.Error as e:
        logger.error(f"Database error in apply_coach: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def add_coach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("This command is restricted to the super admin.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /addcoach <chat_id>")
        return
    try:
        coach_id = int(context.args[0])
        cursor.execute("SELECT * FROM coaches WHERE coach_id=?", (coach_id,))
        if cursor.fetchone():
            await update.message.reply_text("This user is already a coach.")
            return
        coach_name = f"Coach {coach_id}" if coach_id != ADMIN_ID else "Big Scott Media"
        cursor.execute("INSERT INTO coaches (coach_id, name, added_by) VALUES (?, ?, ?)", (coach_id, coach_name, ADMIN_ID))
        conn.commit()
        await update.message.reply_text(f"Coach {coach_id} added successfully as {coach_name}.")
        log_interaction(chat_id, "add_coach")
    except ValueError:
        await update.message.reply_text("Invalid chat_id.")
    except sqlite3.Error as e:
        logger.error(f"Database error in add_coach: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def list_coaches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("This command is restricted to the super admin.")
        return
    try:
        cursor.execute("SELECT coach_id, name FROM coaches")
        coaches = cursor.fetchall()
        if not coaches:
            await update.message.reply_text("No coaches found.")
            return
        text = "List of Coaches:\n\n"
        for coach in coaches:
            text += f"Coach ID: {coach[0]}, Name: {coach[1]}\n"
        await update.message.reply_text(text)
        log_interaction(chat_id, "list_coaches")
    except sqlite3.Error as e:
        logger.error(f"Database error in list_coaches: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def remove_coach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("This command is restricted to the super admin.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /remove_coach <coach_id>")
        return
    try:
        coach_id = int(context.args[0])
        cursor.execute("DELETE FROM coaches WHERE coach_id=?", (coach_id,))
        if cursor.rowcount == 0:
            await update.message.reply_text("Coach not found.")
        else:
            conn.commit()
            await update.message.reply_text(f"Coach {coach_id} removed successfully.")
        log_interaction(chat_id, "remove_coach")
    except ValueError:
        await update.message.reply_text("Invalid coach_id.")
    except sqlite3.Error as e:
        logger.error(f"Database error in remove_coach: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def registration_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("This command is restricted to the super admin.")
        return
    try:
        cursor.execute("SELECT COUNT(*) FROM users WHERE payment_status='registered'")
        total_registered = cursor.fetchone()[0]
        cursor.execute("SELECT package, COUNT(*) FROM users WHERE payment_status='registered' GROUP BY package")
        package_counts = cursor.fetchall()
        cursor.execute("SELECT selected_coach, COUNT(*) FROM users WHERE payment_status='registered' GROUP BY selected_coach")
        coach_counts = cursor.fetchall()
        text = f"📊 Registration Statistics:\n\nTotal Registered Users: {total_registered}\n\n"
        text += "Registrations per Package:\n"
        for package, count in package_counts:
            text += f"- {package}: {count}\n"
        text += "\nRegistrations per Coach:\n"
        for coach_id, count in coach_counts:
            if coach_id:
                cursor.execute("SELECT name FROM coaches WHERE coach_id=?", (coach_id,))
                coach_name = cursor.fetchone()[0]
                text += f"- {coach_name}: {count}\n"
            else:
                text += f"- No coach: {count}\n"
        await update.message.reply_text(text)
        log_interaction(chat_id, "registration_stats")
    except sqlite3.Error as e:
        logger.error(f"Database error in registration_stats: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def my_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cursor.execute("SELECT * FROM coaches WHERE coach_id=?", (chat_id,))
    if not cursor.fetchone():
        await update.message.reply_text("You are not a coach.")
        return
    try:
        cursor.execute("SELECT chat_id, username, package, registration_date FROM users WHERE selected_coach=? AND payment_status='registered'", (chat_id,))
        users = cursor.fetchall()
        if not users:
            await update.message.reply_text("You have no registered users.")
            return
        text = "Your Registered Users:\n\n"
        for user in users:
            text += f"Chat ID: {user[0]}, Username: @{user[1] or 'Unknown'}, Package: {user[2]}, Registered: {user[3]}\n"
        await update.message.reply_text(text)
        log_interaction(chat_id, "my_users")
    except sqlite3.Error as e:
        logger.error(f"Database error in my_users: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def add_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("This command is restricted to the super admin.")
        return
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /add_account <country> <flag> <details>")
        return
    country = context.args[0]
    flag = context.args[1]
    details = " ".join(context.args[2:])
    try:
        cursor.execute("INSERT INTO payment_accounts (country, flag, details) VALUES (?, ?, ?)", (country, flag, details))
        conn.commit()
        await update.message.reply_text(f"Payment account for {country} added successfully.")
        log_interaction(chat_id, "add_account")
    except sqlite3.Error as e:
        logger.error(f"Database error in add_account: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("This command is restricted to the super admin.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /delete_account <country>")
        return
    country = context.args[0]
    try:
        cursor.execute("DELETE FROM payment_accounts WHERE country=?", (country,))
        if cursor.rowcount == 0:
            await update.message.reply_text("Account not found.")
        else:
            conn.commit()
            await update.message.reply_text(f"Payment account for {country} deleted successfully.")
        log_interaction(chat_id, "delete_account")
    except sqlite3.Error as e:
        logger.error(f"Database error in delete_account: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def list_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("This command is restricted to the super admin.")
        return
    try:
        cursor.execute("SELECT country, flag, details, is_active FROM payment_accounts")
        accounts = cursor.fetchall()
        if not accounts:
            await update.message.reply_text("No payment accounts found.")
            return
        text = "Payment Accounts:\n\n"
        for account in accounts:
            status = "Active" if account[3] else "Inactive"
            text += f"Country: {account[0]} {account[1]}, Details: {account[2]}, Status: {status}\n"
        await update.message.reply_text(text)
        log_interaction(chat_id, "list_accounts")
    except sqlite3.Error as e:
        logger.error(f"Database error in list_accounts: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

# Callback handlers
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.from_user.id
    logger.info(f"Received callback data: {data} from chat_id: {chat_id}")
    await query.answer()
    log_interaction(chat_id, f"button_{data}")

    try:
        if data == "menu":
            if chat_id in user_state:
                del user_state[chat_id]
            await show_main_menu(update, context)
        elif data == "stats":
            await stats(update, context)
        elif data == "refer_friend":
            cursor.execute("SELECT referral_code FROM users WHERE chat_id=?", (chat_id,))
            referral_code = cursor.fetchone()[0]
            referral_link = f"https://t.me/{context.bot.username}?start=ref_{chat_id}"
            text = (
                "👥 Refer a Friend and Earn Rewards!\n\n"
                "Share your referral link with friends. For each friend who joins using your link, you earn $0.1. "
                "If they register, you earn an additional $0.4 for Standard or $0.9 for X package.\n\n"
                f"Your referral link: {referral_link}"
            )
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Help Menu", callback_data="help")]]))
        elif data == "withdraw":
            cursor.execute("SELECT balance FROM users WHERE chat_id=?", (chat_id,))
            balance = cursor.fetchone()[0]
            if balance < 30:
                await query.answer("Your balance is less than $30.")
                return
            await context.bot.send_message(
                ADMIN_ID,
                f"Withdrawal request from @{update.effective_user.username or 'Unknown'} (chat_id: {chat_id})\n"
                f"Amount: ${balance}"
            )
            await query.edit_message_text(
                "Your withdrawal request has been sent to the admin. Please wait for processing.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]])
            )
        elif data == "how_it_works":
            keyboard = [
                [InlineKeyboardButton("💎Get Started", callback_data="package_selector")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]
            ]
            await query.edit_message_text(
                "🔖 How Ethereal💚 Works\n"
                "Ethereal rewards you for everyday activities — like reading posts, playing games (e.g., Candy Crush), "
                "sending Snapchat streaks, and clicking links.\n"
                "— — —\n"
                "📍 ETHEREAL STANDARD — ₦9,000\n"
                "• Instant ₦8,000 cashback\n"
                "• Free up to 3GB data on signup\n"
                "• Earn up to $1 per link\n"
                "• Earn up to ₦2,500 for every 10 words read\n"
                "• Up to ₦5,000 daily from Candy Crush\n"
                "• Daily passive income from your team + your earnings (₦5,000 daily)\n"
                "• Earn up to $20 sending Snapchat streaks\n"
                "• ₦8,100–₦8,400 per person you invite\n"
                "• Valid for 5 months (renewal fee required)\n"
                "• No personal AI-assisted earnings\n\n"
                "— — —\n\n"
                "📍 ETHEREAL-X — ₦14,000\n"
                "• Instant ₦12,000 cashback\n"
                "• Free up to 5GB data on signup\n"
                "• Earn up to $2 per link\n"
                "• Earn up to ₦3,500 per 10 words (no cap)\n"
                "• Up to ₦5,000 daily from Candy Crush\n"
                "• Earn up to $50 sending Snapchat streaks\n"
                "• Daily passive income from your team + your earnings (₦10,000 daily)\n"
                "• ₦12,500–₦13,000 per person you invite\n"
                "• Valid for 1 year (no renewal fee)\n"
                "• Includes personal AI-assisted earnings",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif data == "coupon":
            user_state[chat_id] = {'expecting': 'coupon_quantity'}
            keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]]
            await query.edit_message_text("How many coupons do you want to purchase?", reply_markup=InlineKeyboardMarkup(keyboard))
        elif data in ["coupon_standard", "coupon_x"]:
            package = "Standard" if data == "coupon_standard" else "X"
            price = 9000 if package == "Standard" else 14000
            quantity = user_state[chat_id]['coupon_quantity']
            total = quantity * price
            user_state[chat_id].update({'coupon_package': package, 'coupon_total': total})
            await context.bot.send_message(
                ADMIN_ID,
                f"User @{update.effective_user.username or 'Unknown'} (chat_id: {chat_id}) wants to purchase {quantity} {package} coupons for ₦{total}."
            )
            keyboard = [[InlineKeyboardButton(a, callback_data=f"coupon_account_{a}")] for a in coupon_accounts.keys()]
            keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="menu")])
            await query.edit_message_text(
                f"You are purchasing {quantity} {package} coupons.\nTotal amount: ₦{total}\n\nSelect the account to pay to:\n\nFor coupon payment accounts in other countries not listed, contact @bigscottmedia",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif data.startswith("coupon_account_"):
            account = data[len("coupon_account_"):]
            try:
                payment_details = coupon_accounts[account]
                user_state[chat_id]['selected_account'] = account
                cursor.execute(
                    "INSERT INTO payments (chat_id, type, package, quantity, total_amount, payment_account) "
                    "VALUES (?, 'coupon', ?, ?, ?, ?)",
                    (chat_id, user_state[chat_id]['coupon_package'], user_state[chat_id]['coupon_quantity'], user_state[chat_id]['coupon_total'], account)
                )
                conn.commit()
                payment_id = cursor.lastrowid
                user_state[chat_id]['waiting_approval'] = {'type': 'coupon', 'payment_id': payment_id}
                keyboard = [
                    [InlineKeyboardButton("Change Account", callback_data="change_coupon_account")],
                    [InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]
                ]
                await context.bot.send_message(
                    chat_id,
                    f"Payment details:\n\n{payment_details}\n\nPlease make the payment and send the screenshot.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                user_state[chat_id]['expecting'] = 'coupon_screenshot'
            except KeyError:
                await context.bot.send_message(chat_id, "Error: Invalid account. Contact @bigscottmedia.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]]))
        elif data == "change_coupon_account":
            keyboard = [[InlineKeyboardButton(a, callback_data=f"coupon_account_{a}")] for a in coupon_accounts.keys()]
            keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="menu")])
            await query.edit_message_text(
                f"You are purchasing {user_state[chat_id]['coupon_quantity']} {user_state[chat_id]['coupon_package']} coupons.\nTotal amount: ₦{user_state[chat_id]['coupon_total']}\n\nSelect the account to pay to:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif data == "package_selector":
            status = get_status(chat_id)
            if status == 'registered':
                await context.bot.send_message(chat_id, "You are already registered.")
                return
            keyboard = [
                [InlineKeyboardButton("🚀X (₦14,000)", callback_data="reg_x")],
                [InlineKeyboardButton("✈️Standard (₦9,000)", callback_data="reg_standard")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="menu")],
            ]
            await query.edit_message_text("Choose your package:", reply_markup=InlineKeyboardMarkup(keyboard))
        elif data in ["reg_standard", "reg_x"]:
            package = "Standard" if data == "reg_standard" else "X"
            user_state[chat_id] = {'package': package}
            try:
                cursor.execute("UPDATE users SET package=?, payment_status='pending_payment' WHERE chat_id=?", (package, chat_id))
                if cursor.rowcount == 0:
                    cursor.execute("INSERT INTO users (chat_id, package, payment_status, username) VALUES (?, ?, 'pending_payment', ?)", (chat_id, package, update.effective_user.username or "Unknown"))
                conn.commit()
                cursor.execute("SELECT coach_id, name FROM coaches")
                coaches = cursor.fetchall()
                if not coaches:
                    await query.edit_message_text("No coaches available. Please contact @bigscottmedia.")
                    return
                keyboard = [[InlineKeyboardButton(f"{coach[1]}", callback_data=f"select_coach_{coach[0]}")] for coach in coaches]
                keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="menu")])
                await query.edit_message_text("Select your coach:", reply_markup=InlineKeyboardMarkup(keyboard))
            except sqlite3.Error as e:
                logger.error(f"Database error in package_selector: {e}")
                await query.edit_message_text("An error occurred. Please try again.")
                return
        elif data.startswith("select_coach_"):
            coach_id = int(data[len("select_coach_"):])
            user_state[chat_id]['selected_coach'] = coach_id
            cursor.execute("UPDATE users SET selected_coach=? WHERE chat_id=?", (coach_id, chat_id))
            conn.commit()
            cursor.execute("SELECT country, flag FROM payment_accounts WHERE is_active=1")
            accounts = cursor.fetchall()
            if not accounts:
                await query.edit_message_text("No active payment accounts available. Contact @bigscottmedia.")
                return
            keyboard = [[InlineKeyboardButton(f"{flag} {country}", callback_data=f"reg_country_{country}")] for country, flag in accounts]
            keyboard.append([InlineKeyboardButton("Others", callback_data="reg_country_others")])
            keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="menu")])
            await query.edit_message_text("Select your country for payment:", reply_markup=InlineKeyboardMarkup(keyboard))
        elif data.startswith("reg_country_"):
            country = data[len("reg_country_"):]
            cursor.execute("SELECT details FROM payment_accounts WHERE country=? AND is_active=1", (country,))
            result = cursor.fetchone()
            if not result:
                await context.bot.send_message(chat_id, "Error: Invalid country. Contact @bigscottmedia.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]]))
                return
            payment_details = result[0]
            user_state[chat_id]['selected_country'] = country
            user_state[chat_id]['expecting'] = 'reg_screenshot'
            keyboard = [
                [InlineKeyboardButton("Change Country", callback_data="show_country_selection")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]
            ]
            await context.bot.send_message(
                chat_id,
                f"Payment details for {country}:\n\n{payment_details}\n\nPlease make the payment and send the screenshot.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif data == "show_country_selection":
            package = user_state[chat_id].get('package', '')
            if not package:
                await query.edit_message_text("Please select a package first.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]]))
                return
            cursor.execute("SELECT country, flag FROM payment_accounts WHERE is_active=1")
            accounts = cursor.fetchall()
            keyboard = [[InlineKeyboardButton(f"{flag} {country}", callback_data=f"reg_country_{country}")] for country, flag in accounts]
            keyboard.append([InlineKeyboardButton("Others", callback_data="reg_country_others")])
            keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="menu")])
            await query.edit_message_text("Select your country for payment:", reply_markup=InlineKeyboardMarkup(keyboard))
        elif data == "reg_country_others":
            user_state[chat_id]['expecting'] = 'other_country'
            keyboard = [[InlineKeyboardButton("🔙 Country Selection", callback_data="show_country_selection")]]
            await query.edit_message_text("Please enter your country:", reply_markup=InlineKeyboardMarkup(keyboard))
        elif data.startswith("approve_"):
            parts = data.split("_")
            if parts[1] == "reg":
                user_chat_id = int(parts[2])
                try:
                    cursor.execute("UPDATE users SET payment_status='pending_details', approved_at=? WHERE chat_id=?", (datetime.datetime.now(), user_chat_id))
                    conn.commit()
                    await context.bot.send_message(
                        user_chat_id,
                        "✅ Your payment is approved!\n\n*KINDLY 🎯 SEND YOUR DETAILS FOR YOUR REGISTRATION*\n"
                        "➡️ Email address\n➡️ Full name\n➡️ Username (e.g. @you)\n➡️ Phone number (with your country code)\n\n"
                        "All in one message, each on its own line as seen.",
                        parse_mode="Markdown"
                    )
                    await query.edit_message_text("Payment approved. Waiting for user details.")
                except sqlite3.Error as e:
                    logger.error(f"Database error in approve_reg: {e}")
                    await query.edit_message_text("An error occurred. Please try again.")
            elif parts[1] == "coupon":
                payment_id = int(parts[2])
                try:
                    cursor.execute("UPDATE payments SET status='approved', approved_at=? WHERE id=?", (datetime.datetime.now(), payment_id))
                    conn.commit()
                    user_state[ADMIN_ID] = {'expecting': {'type': 'coupon_codes', 'payment_id': payment_id}}
                    await context.bot.send_message(ADMIN_ID, f"Payment {payment_id} approved. Please send the coupon codes (one per line).")
                    await query.edit_message_text("Payment approved. Waiting for coupon codes.")
                except sqlite3.Error as e:
                    logger.error(f"Database error in approve_coupon: {e}")
                    await query.edit_message_text("An error occurred. Please try again.")
            elif parts[1] == "task":
                task_id = int(parts[2])
                user_chat_id = int(parts[3])
                try:
                    cursor.execute("INSERT INTO user_tasks (user_id, task_id, completed_at) VALUES (?, ?, ?)", (user_chat_id, task_id, datetime.datetime.now()))
                    cursor.execute("SELECT reward FROM tasks WHERE id=?", (task_id,))
                    reward = cursor.fetchone()[0]
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE chat_id=?", (reward, user_chat_id))
                    conn.commit()
                    await context.bot.send_message(user_chat_id, f"Task approved! You earned ${reward}.")
                    await query.edit_message_text("Task approved and reward awarded.")
                except sqlite3.Error as e:
                    logger.error(f"Database error in approve_task: {e}")
                    await query.edit_message_text("An error occurred. Please try again.")
        elif data.startswith("finalize_reg_"):
            user_chat_id = int(data.split("_")[2])
            user_state[ADMIN_ID] = {'expecting': 'user_credentials', 'for_user': user_chat_id}
            await context.bot.send_message(
                ADMIN_ID,
                f"Please send the username and password for user {user_chat_id} in the format:\nusername\npassword"
            )
            await query.edit_message_text("Waiting for user credentials.")
        elif data.startswith("reject_task_"):
            parts = data.split("_")
            task_id = int(parts[2])
            user_chat_id = int(parts[3])
            try:
                cursor.execute("SELECT balance FROM users WHERE chat_id=?", (user_chat_id,))
                balance = cursor.fetchone()[0]
                cursor.execute("SELECT reward FROM tasks WHERE id=?", (task_id,))
                reward = cursor.fetchone()[0]
                if balance >= reward:
                    cursor.execute("UPDATE users SET balance = balance - ? WHERE chat_id=?", (reward, user_chat_id))
                    cursor.execute("DELETE FROM user_tasks WHERE user_id=? AND task_id=?", (user_chat_id, task_id))
                    conn.commit()
                    await context.bot.send_message(user_chat_id, "Task verification rejected. Reward revoked.")
                    await query.edit_message_text("Task rejected and reward removed.")
                else:
                    await query.edit_message_text("Task rejected, but balance insufficient to revoke reward.")
            except sqlite3.Error as e:
                logger.error(f"Database error in reject_task: {e}")
                await query.edit_message_text("An error occurred. Please try again.")
        elif data.startswith("pending_"):
            parts = data.split("_")
            if parts[1] == "reg":
                await context.bot.send_message(int(parts[2]), "Your payment is still being reviewed. Please check back later.")
            elif parts[1] == "coupon":
                payment_id = int(parts[2])
                try:
                    cursor.execute("SELECT chat_id FROM payments WHERE id=?", (payment_id,))
                    user_chat_id = cursor.fetchone()[0]
                    await context.bot.send_message(user_chat_id, "Your coupon payment is still being reviewed.")
                except sqlite3.Error as e:
                    logger.error(f"Database error in pending_coupon: {e}")
                    await query.edit_message_text("An error occurred. Please try again.")
        elif data == "check_approval":
            if 'waiting_approval' not in user_state.get(chat_id, {}):
                await context.bot.send_message(chat_id, "You have no pending payments.")
                return
            approval = user_state[chat_id]['waiting_approval']
            if approval['type'] == 'registration':
                status = get_status(chat_id)
                if status == 'pending_details':
                    await context.bot.send_message(chat_id, "Payment approved. Please send your details.")
                elif status == 'registered':
                    await context.bot.send_message(chat_id, "Your registration is complete.")
                else:
                    await context.bot.send_message(chat_id, "Your payment is being reviewed.")
            elif approval['type'] == 'coupon':
                payment_id = approval['payment_id']
                try:
                    cursor.execute("SELECT status FROM payments WHERE id=?", (payment_id,))
                    status = cursor.fetchone()[0]
                    if status == 'approved':
                        await context.bot.send_message(chat_id, "Coupon payment approved. Check your coupons above.")
                    else:
                        await context.bot.send_message(chat_id, "Your coupon payment is being reviewed.")
                except sqlite3.Error as e:
                    logger.error(f"Database error in check_approval: {e}")
                    await context.bot.send_message(chat_id, "An error occurred. Please try again.")
        elif data == "toggle_reminder":
            try:
                cursor.execute("SELECT alarm_setting FROM users WHERE chat_id=?", (chat_id,))
                current_setting = cursor.fetchone()[0]
                new_setting = 1 if current_setting == 0 else 0
                cursor.execute("UPDATE users SET alarm_setting=? WHERE chat_id=?", (new_setting, chat_id))
                conn.commit()
                status = "enabled" if new_setting == 1 else "disabled"
                await query.edit_message_text(f"Daily reminder {status}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Help Menu", callback_data="help")]]))
            except sqlite3.Error as e:
                logger.error(f"Database error in toggle_reminder: {e}")
                await query.edit_message_text("An error occurred. Please try again.")
        elif data == "boost_ai":
            await query.edit_message_text(
                f"🚀 Boost with AI\n\nAccess AI-powered features to maximize your earnings: {AI_BOOST_LINK}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]])
            )
        elif data == "user_registered":
            try:
                cursor.execute("SELECT username, email, password, package FROM users WHERE chat_id=?", (chat_id,))
                user = cursor.fetchone()
                if user:
                    username, email, password, package = user
                    await query.edit_message_text(
                        f"🎉 Registration Complete!\n\n"
                        f"• Site: {SITE_LINK}\n"
                        f"• Username: {username}\n"
                        f"• Email: {email}\n"
                        f"• Password: {password}\n\n"
                        "Keep your credentials safe. Use 'Password Recovery' in the Help menu if needed.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]])
                    )
                else:
                    await query.edit_message_text("No registration data found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]]))
            except sqlite3.Error as e:
                logger.error(f"Database error in user_registered: {e}")
                await query.edit_message_text("An error occurred. Please try again.")
        elif data == "daily_tasks":
            try:
                cursor.execute("SELECT package FROM users WHERE chat_id=?", (chat_id,))
                package = cursor.fetchone()[0]
                msg = f"Follow this link to perform your daily tasks and earn: {DAILY_TASK_LINK}"
                if package == "X":
                    msg = f"🌟 X Users: Maximize your earnings with this special daily task link: {DAILY_TASK_LINK}"
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]]))
            except sqlite3.Error as e:
                logger.error(f"Database error in daily_tasks: {e}")
                await query.edit_message_text("An error occurred. Please try again.")
        elif data == "earn_extra":
            now = datetime.datetime.now()
            try:
                cursor.execute("""
                SELECT t.id, t.type, t.link, t.reward
                FROM tasks t
                WHERE t.expires_at > ?
                AND t.id NOT IN (SELECT ut.task_id FROM user_tasks ut WHERE ut.user_id = ?)
                """, (now, chat_id))
                tasks = cursor.fetchall()
                if not tasks:
                    await query.edit_message_text(
                        "No extra tasks available right now. Please check back later.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]])
                    )
                    return
                keyboard = []
                for task in tasks:
                    task_id, task_type, link, reward = task
                    join_button = InlineKeyboardButton(f"Join {task_type} (${reward})", url=link)
                    verify_button = InlineKeyboardButton("Verify", callback_data=f"verify_task_{task_id}")
                    keyboard.append([join_button, verify_button])
                keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="menu")])
                await query.edit_message_text("Available extra tasks for today:", reply_markup=InlineKeyboardMarkup(keyboard))
            except sqlite3.Error as e:
                logger.error(f"Database error in earn_extra: {e}")
                await query.edit_message_text("An error occurred. Please try again.")
        elif data.startswith("verify_task_"):
            task_id = int(data[len("verify_task_"):])
            try:
                cursor.execute("SELECT type, link FROM tasks WHERE id=?", (task_id,))
                task = cursor.fetchone()
                if not task:
                    await query.answer("Task not found.")
                    return
                task_type, link = task
                if task_type in ["join_group", "join_channel"]:
                    chat_username = link.split("/")[-1]
                    try:
                        member = await context.bot.get_chat_member(chat_username, chat_id)
                        if member.status in ["member", "administrator", "creator"]:
                            cursor.execute("INSERT INTO user_tasks (user_id, task_id, completed_at) VALUES (?, ?, ?)", (chat_id, task_id, datetime.datetime.now()))
                            cursor.execute("SELECT reward FROM tasks WHERE id=?", (task_id,))
                            reward = cursor.fetchone()[0]
                            cursor.execute("UPDATE users SET balance = balance + ? WHERE chat_id=?", (reward, chat_id))
                            conn.commit()
                            await query.answer(f"Task completed! You earned ${reward}.")
                        else:
                            await query.answer("You are not in the group/channel yet.")
                    except Exception as e:
                        logger.error(f"Error verifying task: {e}")
                        await query.answer("Error verifying task. Try again later.")
                elif task_type == "external_task":
                    user_state[chat_id] = {'expecting': 'task_screenshot', 'task_id': task_id}
                    await context.bot.send_message(chat_id, f"Please send the screenshot for task #{task_id} verification.")
            except sqlite3.Error as e:
                logger.error(f"Database error in verify_task: {e}")
                await query.answer("An error occurred. Please try again.")
        elif data == "faq":
            keyboard = [[InlineKeyboardButton(faq["question"], callback_data=f"faq_{key}")] for key, faq in FAQS.items()]
            keyboard.append([InlineKeyboardButton("Ask Another Question", callback_data="faq_custom")])
            keyboard.append([InlineKeyboardButton("🔙 Help Menu", callback_data="help")])
            await query.edit_message_text("Select a question or ask your own:", reply_markup=InlineKeyboardMarkup(keyboard))
        elif data.startswith("faq_"):
            faq_key = data[len("faq_"):]
            if faq_key == "custom":
                user_state[chat_id]['expecting'] = 'faq'
                await query.edit_message_text("Please type your question:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Help Menu", callback_data="help")]]))
            else:
                faq = FAQS.get(faq_key)
                if faq:
                    await query.edit_message_text(
                        f"❓ {faq['question']}\n\n{faq['answer']}",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 FAQ Menu", callback_data="faq"), InlineKeyboardButton("🔙 Help Menu", callback_data="help")]])
                    )
                else:
                    await query.edit_message_text("FAQ not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Help Menu", callback_data="help")]]))
        elif data in HELP_TOPICS:
            topic = HELP_TOPICS[data]
            keyboard = [[InlineKeyboardButton("🔙 Help Menu", callback_data="help")]]
            if topic["type"] == "input":
                user_state[chat_id]['expecting'] = data
                await query.edit_message_text(topic["text"], reply_markup=InlineKeyboardMarkup(keyboard))
            elif topic["type"] == "toggle":
                keyboard = [
                    [InlineKeyboardButton("Toggle Reminder On/Off", callback_data="toggle_reminder")],
                    [InlineKeyboardButton("🔙 Help Menu", callback_data="help")]
                ]
                await query.edit_message_text("Toggle your daily reminder:", reply_markup=InlineKeyboardMarkup(keyboard))
            elif topic["type"] == "faq":
                await button_handler(update, context)  # Redirect to FAQ handler
            else:
                content = topic["text"] if topic["type"] == "text" else f"Watch here: {topic['url']}"
                await query.edit_message_text(content, reply_markup=InlineKeyboardMarkup(keyboard))
        elif data == "help":
            await help_menu(update, context)
        elif data == "enable_reminders":
            try:
                cursor.execute("UPDATE users SET alarm_setting=1 WHERE chat_id=?", (chat_id,))
                conn.commit()
                await query.edit_message_text(
                    "✅ Daily reminders enabled!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]])
                )
            except sqlite3.Error as e:
                logger.error(f"Database error in enable_reminders: {e}")
                await query.edit_message_text("An error occurred. Please try again.")
        elif data == "disable_reminders":
            try:
                cursor.execute("UPDATE users SET alarm_setting=0 WHERE chat_id=?", (chat_id,))
                conn.commit()
                await query.edit_message_text(
                    "❌ Okay, daily reminders not set.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]])
                )
            except sqlite3.Error as e:
                logger.error(f"Database error in disable_reminders: {e}")
                await query.edit_message_text("An error occurred. Please try again.")
    except Exception as e:
        logger.error(f"Error in button_handler: {e}")
        await query.edit_message_text("An error occurred. Please try again or contact @bigscottmedia.")

# Message handlers
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if 'expecting' not in user_state.get(chat_id, {}):
        return
    expecting = user_state[chat_id]['expecting']
    photo_file = update.message.photo[-1].file_id
    try:
        if expecting == 'reg_screenshot':
            cursor.execute("UPDATE users SET screenshot_uploaded_at=? WHERE chat_id=?", (datetime.datetime.now(), chat_id))
            conn.commit()
            cursor.execute("SELECT selected_coach FROM users WHERE chat_id=?", (chat_id,))
            selected_coach = cursor.fetchone()[0]
            coach_name = "None"
            if selected_coach:
                cursor.execute("SELECT name FROM coaches WHERE coach_id=?", (selected_coach,))
                coach_name = cursor.fetchone()[0]
            keyboard = [
                [InlineKeyboardButton("Approve", callback_data=f"approve_reg_{chat_id}")],
                [InlineKeyboardButton("Pending", callback_data=f"pending_reg_{chat_id}")],
            ]
            await context.bot.send_photo(
                ADMIN_ID,
                photo_file,
                caption=f"📸 Registration Payment from @{update.effective_user.username or 'Unknown'} (chat_id: {chat_id})\nSelected Coach: {coach_name}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            await update.message.reply_text("✅ Screenshot received! Awaiting admin approval.")
            user_state[chat_id]['waiting_approval'] = {'type': 'registration'}
            context.job_queue.run_once(check_registration_payment, 3600, data={'chat_id': chat_id})
        elif expecting == 'coupon_screenshot':
            payment_id = user_state[chat_id]['waiting_approval']['payment_id']
            keyboard = [
                [InlineKeyboardButton("Approve", callback_data=f"approve_coupon_{payment_id}")],
                [InlineKeyboardButton("Pending", callback_data=f"pending_coupon_{payment_id}")],
            ]
            await context.bot.send_photo(
                ADMIN_ID,
                photo_file,
                caption=f"📸 Coupon Payment from @{update.effective_user.username or 'Unknown'} (chat_id: {chat_id})",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            await update.message.reply_text("✅ Screenshot received! Awaiting admin approval.")
            context.job_queue.run_once(check_coupon_payment, 3600, data={'payment_id': payment_id})
        elif expecting == 'task_screenshot':
            task_id = user_state[chat_id]['task_id']
            await context.bot.send_photo(
                ADMIN_ID,
                photo_file,
                caption=f"Task #{task_id} verification from @{update.effective_user.username or 'Unknown'} (chat_id: {chat_id})",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Approve", callback_data=f"approve_task_{task_id}_{chat_id}")],
                    [InlineKeyboardButton("Reject", callback_data=f"reject_task_{task_id}_{chat_id}")]
                ])
            )
            await update.message.reply_text("Screenshot received. Awaiting admin approval.")
        del user_state[chat_id]['expecting']
        log_interaction(chat_id, "photo_upload")
    except Exception as e:
        logger.error(f"Error in handle_photo: {e}")
        await update.message.reply_text("An error occurred. Please try again or contact @bigscottmedia.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text
    log_interaction(chat_id, "text_message")
    logger.info(f"user_state[{chat_id}] = {user_state.get(chat_id, 'None')}")
    if 'expecting' in user_state.get(chat_id, {}):
        expecting = user_state[chat_id]['expecting']
        try:
            if expecting == 'coupon_quantity':
                try:
                    quantity = int(text)
                    if quantity <= 0:
                        raise ValueError
                    user_state[chat_id]['coupon_quantity'] = quantity
                    keyboard = [
                        [InlineKeyboardButton("Standard (₦9,000)", callback_data="coupon_standard")],
                        [InlineKeyboardButton("X (₦14,000)", callback_data="coupon_x")],
                        [InlineKeyboardButton("🔙 Main Menu", callback_data="menu")],
                    ]
                    await update.message.reply_text("Select the package for your coupons:", reply_markup=InlineKeyboardMarkup(keyboard))
                    del user_state[chat_id]['expecting']
                except ValueError:
                    await update.message.reply_text("Please enter a valid positive integer.")
            elif expecting == 'other_country':
                country = text.strip()
                await context.bot.send_message(
                    ADMIN_ID,
                    f"User @{update.effective_user.username or 'Unknown'} (chat_id: {chat_id}) requested registration for country: {country}"
                )
                keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]]
                await update.message.reply_text(
                    "Your request has been sent to the admin. Please contact @bigscottmedia to complete your registration.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                del user_state[chat_id]['expecting']
            elif expecting == 'faq':
                await context.bot.send_message(ADMIN_ID, f"FAQ from @{update.effective_user.username or 'Unknown'} (chat_id: {chat_id}): {text}")
                await update.message.reply_text("Thank you! We’ll get back to you soon.")
                del user_state[chat_id]['expecting']
            elif expecting == 'password_recovery':
                cursor.execute("SELECT username, email, password FROM users WHERE email=? AND chat_id=? AND payment_status='registered'", (text, chat_id))
                user = cursor.fetchone()
                if user:
                    username, email, _ = user
                    new_password = secrets.token_urlsafe(8)
                    cursor.execute("UPDATE users SET password=? WHERE chat_id=?", (new_password, chat_id))
                    conn.commit()
                    await context.bot.send_message(
                        chat_id,
                        f"Your password has been reset.\nNew Password: {new_password}\nKeep it safe and use 'Password Recovery' if needed again."
                    )
                    await context.bot.send_message(
                        ADMIN_ID,
                        f"Password reset for @{username or 'Unknown'} (chat_id: {chat_id}, email: {email})"
                    )
                else:
                    await update.message.reply_text("No account found with that email or you are not fully registered. Please try again or contact @bigscottmedia.")
                del user_state[chat_id]['expecting']
            elif expecting == 'support_message':
                await context.bot.send_message(
                    ADMIN_ID,
                    f"Support request from @{update.effective_user.username or 'Unknown'} (chat_id: {chat_id}): {text}"
                )
                await update.message.reply_text("Thank you! Our support team will get back to you soon.")
                del user_state[chat_id]['expecting']
            elif isinstance(expecting, dict) and expecting.get('type') == 'coupon_codes' and chat_id == ADMIN_ID:
                payment_id = expecting['payment_id']
                codes = text.splitlines()
                for code in codes:
                    code = code.strip()
                    if code:
                        cursor.execute("INSERT INTO coupons (payment_id, code) VALUES (?, ?)", (payment_id, code))
                conn.commit()
                cursor.execute("SELECT chat_id FROM payments WHERE id=?", (payment_id,))
                user_chat_id = cursor.fetchone()[0]
                await context.bot.send_message(
                    user_chat_id,
                    "🎉 Your coupon purchase is approved!\n\nHere are your coupons:\n" + "\n".join(codes)
                )
                await update.message.reply_text("Coupons sent to the user successfully.")
                del user_state[chat_id]['expecting']
            elif expecting == 'broadcast_message' and chat_id == ADMIN_ID:
                logger.info(f"Sending broadcast: {text}")
                cursor.execute("SELECT chat_id FROM users WHERE payment_status='registered'")
                user_ids = [row[0] for row in cursor.fetchall()]
                for user_id in user_ids:
                    try:
                        await context.bot.send_message(user_id, f"📢 Broadcast: {text}")
                    except Exception as e:
                        logger.error(f"Failed to send broadcast to {user_id}: {e}")
                await update.message.reply_text(f"Broadcast sent to {len(user_ids)} users.")
                del user_state[chat_id]['expecting']
            elif expecting == 'user_credentials' and chat_id == ADMIN_ID:
                lines = text.splitlines()
                if len(lines) != 2:
                    await update.message.reply_text("Please send username and password in two lines.")
                    return
                username, password = lines
                for_user = user_state[chat_id]['for_user']
                cursor.execute(
                    "UPDATE users SET username=?, password=?, payment_status='registered', registration_date=? WHERE chat_id=?",
                    (username, password, datetime.datetime.now(), for_user)
                )
                conn.commit()
                cursor.execute("SELECT package, referred_by, selected_coach FROM users WHERE chat_id=?", (for_user,))
                row = cursor.fetchone()
                if row:
                    package, referred_by, selected_coach = row
                    if referred_by:
                        additional_reward = 0.4 if package == "Standard" else 0.9
                        cursor.execute("UPDATE users SET balance = balance + ? WHERE chat_id=?", (additional_reward, referred_by))
                        conn.commit()
                await context.bot.send_message(
                    for_user,
                    f"🎉 Registration successful! Your username is\n {username}\n and password is\n {password}\n\n Join the group using the link below to keep up with info:\n {GROUP_LINK}"
                )
                cursor.execute("SELECT package, email, name, phone FROM users WHERE chat_id=?", (for_user,))
                user_details = cursor.fetchone()
                if user_details:
                    pkg, email, full_name, phone = user_details
                    coach_name = "None"
                    if selected_coach:
                        cursor.execute("SELECT name FROM coaches WHERE coach_id=?", (selected_coach,))
                        coach_name = cursor.fetchone()[0]
                        await context.bot.send_message(
                            selected_coach,
                            f"New registration under your coaching:\nUser ID: {for_user}\nUsername: {username}\nPackage: {pkg}\nEmail: {email}\nName: {full_name}\nPhone: {phone}"
                        )
                    await context.bot.send_message(
                        ADMIN_ID,
                        f"New registration:\nUser ID: {for_user}\nUsername: {username}\nPackage: {pkg}\nEmail: {email}\nName: {full_name}\nPhone: {phone}\nCoach: {coach_name}"
                    )
                await update.message.reply_text("Credentials set and sent to the user.")
                keyboard = [
                    [InlineKeyboardButton("Yes, enable reminders", callback_data="enable_reminders")],
                    [InlineKeyboardButton("No, disable reminders", callback_data="disable_reminders")],
                ]
                await context.bot.send_message(for_user, "Would you like to receive daily reminders to complete your tasks?", reply_markup=InlineKeyboardMarkup(keyboard))
                del user_state[chat_id]
        except Exception as e:
            logger.error(f"Error in handle_text: {e}")
            await update.message.reply_text("An error occurred. Please try again or contact @bigscottmedia.")
    else:
        status = get_status(chat_id)
        if status == 'pending_details':
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if len(lines) < 4:
                await update.message.reply_text("❗️ Please send all four lines.", parse_mode="Markdown")
                return
            email, full_name, username, phone = lines[:4]
            if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                await update.message.reply_text("❗️ Invalid email.")
                return
            if not username.startswith('@'):
                await update.message.reply_text("❗️ Username must start with @.")
                return
            password = secrets.token_urlsafe(8)
            try:
                cursor.execute(
                    "UPDATE users SET email=?, name=?, username=?, phone=?, password=? WHERE chat_id=?",
                    (email, full_name, username, phone, password, chat_id)
                )
                conn.commit()
                pkg = cursor.execute("SELECT package FROM users WHERE chat_id=?", (chat_id,)).fetchone()[0]
                keyboard = [[InlineKeyboardButton("Finalize Registration", callback_data=f"finalize_reg_{chat_id}")]]
                await context.bot.send_message(
                    ADMIN_ID,
                    f"🆕 User Details Received:\nUser ID: {chat_id}\nUsername: {username}\nPackage: {pkg}\nEmail: {email}\nName: {full_name}\nPhone: {phone}\n\nPlease finalize registration by providing credentials.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                await update.message.reply_text(
                    "✅ Details received! Awaiting admin finalization.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]])
                )
            except sqlite3.Error as e:
                logger.error(f"Database error in pending_details: {e}")
                await update.message.reply_text("An error occurred. Please try again.")

# Job functions
async def check_registration_payment(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data['chat_id']
    status = get_status(chat_id)
    if status == 'pending_payment':
        cursor.execute("SELECT selected_coach FROM users WHERE chat_id=?", (chat_id,))
        selected_coach = cursor.fetchone()[0]
        if selected_coach:
            await context.bot.send_message(
                selected_coach,
                f"Reminder: User (chat_id: {chat_id}) has not completed registration within the time limit."
            )
        keyboard = [[InlineKeyboardButton("Payment Approval Stats", callback_data="check_approval")]]
        await context.bot.send_message(chat_id, "Your payment is still being reviewed. Click below to check status:", reply_markup=InlineKeyboardMarkup(keyboard))

async def check_coupon_payment(context: ContextTypes.DEFAULT_TYPE):
    payment_id = context.job.data['payment_id']
    try:
        cursor.execute("SELECT status, chat_id FROM payments WHERE id=?", (payment_id,))
        row = cursor.fetchone()
        if row and row[0] == 'pending_payment':
            chat_id = row[1]
            keyboard = [[InlineKeyboardButton("Payment Approval Stats", callback_data="check_approval")]]
            await context.bot.send_message(chat_id, "Your coupon payment is still being reviewed. Click below to check status:", reply_markup=InlineKeyboardMarkup(keyboard))
    except sqlite3.Error as e:
        logger.error(f"Database error in check_coupon_payment: {e}")

async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    try:
        cursor.execute("SELECT chat_id FROM users WHERE alarm_setting=1")
        user_ids = [row[0] for row in cursor.fetchall()]
        for user_id in user_ids:
            try:
                await context.bot.send_message(user_id, "🌟 Daily Reminder: Complete your Ethereal tasks to maximize your earnings!")
                log_interaction(user_id, "daily_reminder")
            except Exception as e:
                logger.error(f"Failed to send reminder to {user_id}: {e}")
    except sqlite3.Error as e:
        logger.error(f"Database error in daily_reminder: {e}")

async def daily_summary(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now()
    start_time = now - datetime.timedelta(days=1)
    try:
        cursor.execute("SELECT COUNT(*) FROM users WHERE registration_date >= ?", (start_time,))
        new_users = cursor.fetchone()[0]
        cursor.execute("""
        SELECT SUM(CASE package WHEN 'Standard' THEN 9000 WHEN 'X' THEN 14000 ELSE 0 END)
        FROM users
        WHERE approved_at >= ? AND payment_status = 'registered'
        """, (start_time,))
        reg_payments = cursor.fetchone()[0] or 0
        cursor.execute("SELECT SUM(total_amount) FROM payments WHERE approved_at >= ? AND status = 'approved'", (start_time,))
        coupon_payments = cursor.fetchone()[0] or 0
        total_payments = reg_payments + coupon_payments
        cursor.execute("SELECT COUNT(*) FROM user_tasks WHERE completed_at >= ?", (start_time,))
        tasks_completed = cursor.fetchone()[0]
        cursor.execute("""
        SELECT SUM(t.reward)
        FROM user_tasks ut
        JOIN tasks t ON ut.task_id = t.id
        WHERE ut.completed_at >= ?
        """, (start_time,))
        total_distributed = cursor.fetchone()[0] or 0
        text = (
            f"📊 Daily Summary ({now.strftime('%Y-%m-%d')}):\n\n"
            f"• New Users: {new_users}\n"
            f"• Total Payments Approved: ₦{total_payments}\n"
            f"• Tasks Completed: {tasks_completed}\n"
            f"• Total Balance Distributed: ${total_distributed}"
        )
        await context.bot.send_message(ADMIN_ID, text)
    except sqlite3.Error as e:
        logger.error(f"Database error in daily_summary: {e}")
        await context.bot.send_message(ADMIN_ID, "Error generating daily summary.")

# Channel handler
async def channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "/help":
        await update.message.reply_text("Help message for channel members.")
    elif update.message.text == "/stats":
        await update.message.reply_text("Channel stats coming soon!")
    elif update.message.text == "/my_users":
        await my_users(update, context)

# Menus
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        cursor.execute("SELECT payment_status, package FROM users WHERE chat_id=?", (chat_id,))
        user = cursor.fetchone()
        keyboard = [
            [InlineKeyboardButton("How It Works", callback_data="how_it_works")],
            [InlineKeyboardButton("Purchase Coupon", callback_data="coupon")],
            [InlineKeyboardButton("💸 Register & Make Payment", callback_data="package_selector")],
            [InlineKeyboardButton("❓ Help", callback_data="help")],
        ]
        if user and user[0] == 'registered':
            keyboard = [
                [InlineKeyboardButton("📊 My Stats", callback_data="stats")],
                [InlineKeyboardButton("Do Daily Tasks", callback_data="daily_tasks")],
                [InlineKeyboardButton("💰 Earn Extra for the Day", callback_data="earn_extra")],
                [InlineKeyboardButton("Purchase Coupon", callback_data="coupon")],
                [InlineKeyboardButton("❓ Help", callback_data="help")],
            ]
            if user[1] == "X":
                keyboard.insert(1, [InlineKeyboardButton("🚀 Boost with AI", callback_data="boost_ai")])
        text = "Select an option below:"
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        log_interaction(chat_id, "show_main_menu")
    except sqlite3.Error as e:
        logger.error(f"Database error in show_main_menu: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.callback_query.from_user.id
    status = get_status(chat_id)
    keyboard = [[InlineKeyboardButton(topic["label"], callback_data=key)] for key, topic in HELP_TOPICS.items()]
    if status == 'registered':
        keyboard.append([InlineKeyboardButton("👥 Refer a Friend", callback_data="refer_friend")])
    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="menu")])
    query = update.callback_query
    await query.edit_message_text("What would you like help with?", reply_markup=InlineKeyboardMarkup(keyboard))
    log_interaction(chat_id, "help_menu")

# Main
def main():
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("menu", show_main_menu))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("reset", reset_state))
        application.add_handler(CommandHandler("broadcast", broadcast))
        application.add_handler(CommandHandler("botstats", botstats))
        application.add_handler(CommandHandler("registered_users", registered_users))
        application.add_handler(CommandHandler("add_task", add_task))
        application.add_handler(CommandHandler("support", support))
        application.add_handler(CommandHandler("coach", apply_coach))
        application.add_handler(CommandHandler("addcoach", add_coach))
        application.add_handler(CommandHandler("list_coaches", list_coaches))
        application.add_handler(CommandHandler("remove_coach", remove_coach))
        application.add_handler(CommandHandler("registration_stats", registration_stats))
        application.add_handler(CommandHandler("my_users", my_users))
        application.add_handler(CommandHandler("add_account", add_account))
        application.add_handler(CommandHandler("delete_account", delete_account))
        application.add_handler(CommandHandler("list_accounts", list_accounts))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        # Replace with your actual channel ID
        channel_id = int(os.getenv("CHANNEL_ID", -1002028515715))  # Updated channl ID
        application.add_handler(MessageHandler(filters.Chat(channel_id) & filters.TEXT, channel_message))
        application.job_queue.run_daily(daily_reminder, time=datetime.time(hour=8, minute=0))
        application.job_queue.run_daily(daily_summary, time=datetime.time(hour=20, minute=0))
        application.run_polling()
    except Exception as e:
        logger.error(f"Error in main: {e}")
        print("Failed to start bot. Check logs for details.")

if __name__ == '__main__':
    main()

# Define coupon_accounts dictionary if used elsewhere in the original code
coupon_accounts = {
    "Kuda Account": "2036035854\n Kuda Microfinance Bank\n Eluem, Chike Olanrewaju",
    "Opay Account": "8051454564\n Opay\n Chike Eluem Olanrewaju",
    "Zenith Account": "2267515466\n Zenith Bank\n Chike Eluem Olanrewaju",
    # Add more accounts as needed
}
