import os
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TOKEN_HERE")
TIMEZONE = ZoneInfo("Europe/Tallinn")
DATA_FILE = "calls.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

MEMBERS = ["Никита", "Рагнар", "Алекс"]

SELECT_DATE, SELECT_TIME, ENTER_CUSTOM_DATE, ENTER_CUSTOM_TIME, SELECT_REMINDER, ENTER_TASKS = range(6)

# ─── STORAGE ───────────────────────────────────────────────────────────────────
def load_calls():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE) as f:
        return json.load(f)

def save_calls(calls):
    with open(DATA_FILE, "w") as f:
        json.dump(calls, f, ensure_ascii=False, indent=2)

# ─── HELPERS ───────────────────────────────────────────────────────────────────
def format_call(call):
    dt = datetime.fromisoformat(call["datetime"]).astimezone(TIMEZONE)
    date_str = dt.strftime("%d %b %Y, %H:%M")
    lines = [f"📞 *Звонок #{call['id']}* — {date_str}"]
    if call.get("tasks"):
        lines.append("")
        for person, task in call["tasks"].items():
            lines.append(f"  • *{person}:* {task}")
    return "\n".join(lines)

MINI_APP_URL = os.environ.get("MINI_APP_URL", "")

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 Назначить звонок", callback_data="new_call")],
        [InlineKeyboardButton("📋 Предстоящие звонки", callback_data="list_calls")],
    ])

# ─── START ─────────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Здарова, черти! На сколько запланировать некст звонок? 📞",
        reply_markup=main_menu_keyboard(),
    )

async def btn_list_calls(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    calls = load_calls()
    now = datetime.now(TIMEZONE)
    upcoming = sorted(
        [c for c in calls if datetime.fromisoformat(c["datetime"]) > now
         and c.get("chat_id") == query.message.chat_id],
        key=lambda c: c["datetime"]
    )
    if not upcoming:
        await query.edit_message_text(
            "📭 Нет запланированных звонков.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Назад", callback_data="back_main")]])
        )
        return
    text = "\n\n".join(format_call(c) for c in upcoming)
    buttons = [[InlineKeyboardButton(f"❌ Отменить #{c['id']}", callback_data=f"cancel_{c['id']}")] for c in upcoming]
    buttons.append([InlineKeyboardButton("« Назад", callback_data="back_main")])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def btn_back_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "👋 Здарова, черти! На сколько запланировать некст звонок? 📞",
        reply_markup=main_menu_keyboard(),
    )

async def btn_cancel_call(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    call_id = int(query.data.split("_")[1])
    calls = load_calls()
    save_calls([c for c in calls if c["id"] != call_id])
    await query.edit_message_text(
        f"🗑 Звонок #{call_id} отменён.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Назад", callback_data="back_main")]])
    )

# ─── NEW CALL FLOW ─────────────────────────────────────────────────────────────
async def btn_new_call(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    now = datetime.now(TIMEZONE)
    dates = [(now + timedelta(days=i)) for i in range(7)]
    buttons = []
    row = []
    for i, d in enumerate(dates):
        label = d.strftime("%d %b")
        if i == 0: label = f"Сегодня {label}"
        elif i == 1: label = f"Завтра {label}"
        row.append(InlineKeyboardButton(label, callback_data=f"date_{d.strftime('%Y-%m-%d')}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("📅 Другая дата...", callback_data="date_custom")])
    buttons.append([InlineKeyboardButton("« Отмена", callback_data="back_main")])
    await query.edit_message_text(
        "📅 *Выбери дату звонка:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return SELECT_DATE

async def handle_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "date_custom":
        await query.edit_message_text(
            "📅 Введи дату в формате *ДД.ММ.ГГГГ*\nНапример: `15.06.2026`",
            parse_mode="Markdown",
        )
        return ENTER_CUSTOM_DATE
    ctx.user_data["call_date"] = query.data.replace("date_", "")
    return await show_time_picker(query, ctx)

async def handle_custom_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        d = datetime.strptime(text, "%d.%m.%Y")
        ctx.user_data["call_date"] = d.strftime("%Y-%m-%d")
        buttons = build_time_buttons()
        await update.message.reply_text(
            "⏰ *Выбери время звонка:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return SELECT_TIME
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Например: `15.06.2026`", parse_mode="Markdown")
        return ENTER_CUSTOM_DATE

def build_time_buttons():
    times = ["13:00", "14:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00", "22:00", "23:00"]
    buttons = []
    row = []
    for i, t in enumerate(times):
        row.append(InlineKeyboardButton(t, callback_data=f"time_{t}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🕐 Другое время...", callback_data="time_custom")])
    return buttons

async def show_time_picker(query, ctx):
    await query.edit_message_text(
        "⏰ *Выбери время звонка:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(build_time_buttons()),
    )
    return SELECT_TIME

def reminder_keyboard():
    options = [
        ("За 10 минут", "10m"),
        ("За 30 минут", "30m"),
        ("За 1 час", "1h"),
        ("За 3 часа", "3h"),
        ("За 24 часа", "24h"),
    ]
    buttons = [[InlineKeyboardButton(label, callback_data=f"rem_{val}")] for label, val in options]
    buttons.append([InlineKeyboardButton("✅ Готово", callback_data="rem_done")])
    return InlineKeyboardMarkup(buttons)

async def show_reminder_picker(msg, ctx, edit=True):
    ctx.user_data["reminders"] = []
    text = "🔔 *Когда напомнить о звонке?*\n\nВыбери один или несколько вариантов, потом нажми ✅ Готово"
    if edit:
        await msg.edit_text(text, parse_mode="Markdown", reply_markup=reminder_keyboard())
    else:
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=reminder_keyboard())
    return SELECT_REMINDER

async def handle_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "time_custom":
        await query.edit_message_text(
            "⏰ Введи время в формате *ЧЧ:ММ*\nНапример: `17:30`",
            parse_mode="Markdown",
        )
        return ENTER_CUSTOM_TIME
    ctx.user_data["call_time"] = query.data.replace("time_", "")
    return await show_reminder_picker(query.message, ctx, edit=True)

async def handle_custom_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        datetime.strptime(text, "%H:%M")
        ctx.user_data["call_time"] = text
        return await show_reminder_picker(update.message, ctx, edit=False)
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Например: `17:30`", parse_mode="Markdown")
        return ENTER_CUSTOM_TIME

async def handle_reminder_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data.replace("rem_", "")

    if val == "done":
        if not ctx.user_data.get("reminders"):
            ctx.user_data["reminders"] = ["1h", "10m"]  # default
        ctx.user_data["tasks"] = {}
        ctx.user_data["task_idx"] = 0
        person = MEMBERS[0]
        await query.edit_message_text(
            f"✏️ Задачи для *{person}*:\n\nЧто нужно сделать к звонку?\nЕсли задач нет — напиши `-`",
            parse_mode="Markdown",
        )
        return ENTER_TASKS

    reminders = ctx.user_data.get("reminders", [])
    if val in reminders:
        reminders.remove(val)
    else:
        reminders.append(val)
    ctx.user_data["reminders"] = reminders

    labels = {"10m": "10 мин", "30m": "30 мин", "1h": "1 час", "3h": "3 часа", "24h": "24 часа"}
    selected = ", ".join(labels[r] for r in reminders) if reminders else "ничего не выбрано"
    
    options = [
        ("За 10 минут", "10m"),
        ("За 30 минут", "30m"),
        ("За 1 час", "1h"),
        ("За 3 часа", "3h"),
        ("За 24 часа", "24h"),
    ]
    buttons = []
    for label, v in options:
        prefix = "✅ " if v in reminders else ""
        buttons.append([InlineKeyboardButton(f"{prefix}{label}", callback_data=f"rem_{v}")])
    buttons.append([InlineKeyboardButton("✅ Готово", callback_data="rem_done")])

    await query.edit_message_text(
        f"🔔 *Когда напомнить о звонке?*\n\nВыбрано: {selected}\n\nНажми ✅ Готово когда закончишь",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return SELECT_REMINDER

async def handle_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    idx = ctx.user_data["task_idx"]
    person = MEMBERS[idx]
    if text != "-":
        ctx.user_data["tasks"][person] = text
    ctx.user_data["task_idx"] += 1

    if ctx.user_data["task_idx"] < len(MEMBERS):
        next_person = MEMBERS[ctx.user_data["task_idx"]]
        await update.message.reply_text(
            f"✏️ Задачи для *{next_person}*:\n\nЧто нужно сделать к звонку?\nЕсли задач нет — напиши `-`",
            parse_mode="Markdown",
        )
        return ENTER_TASKS

    date_str = ctx.user_data["call_date"]
    time_str = ctx.user_data["call_time"]
    naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    local_dt = naive_dt.replace(tzinfo=TIMEZONE)

    calls = load_calls()
    call_id = max((c["id"] for c in calls), default=0) + 1
    call = {
        "id": call_id,
        "datetime": local_dt.isoformat(),
        "tasks": ctx.user_data["tasks"],
        "reminders": ctx.user_data.get("reminders", ["1h", "10m"]),
        "chat_id": update.effective_chat.id,
    }
    calls.append(call)
    save_calls(calls)
    schedule_reminders(ctx.application.job_queue, call)

    await update.message.reply_text(
        f"✅ Готово! Звонок запланирован.\n\n{format_call(call)}\n\nЯ напомню за 24ч, за 1ч и за 10 минут.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END

async def cancel_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Отменено.", reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text("❌ Отменено.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# ─── REMINDERS ─────────────────────────────────────────────────────────────────
def schedule_reminders(job_queue, call):
    dt = datetime.fromisoformat(call["datetime"])
    now = datetime.now(TIMEZONE)
    
    reminder_map = {
        "10m": (timedelta(minutes=10), "🚨 *Через 10 минут звонок!*"),
        "30m": (timedelta(minutes=30), "⏰ *Через 30 минут звонок!*"),
        "1h":  (timedelta(hours=1),    "⏰ *Напоминание:* через час звонок!"),
        "3h":  (timedelta(hours=3),    "🔔 *Напоминание:* через 3 часа звонок!"),
        "24h": (timedelta(hours=24),   "🔔 *Напоминание:* завтра звонок!"),
    }
    
    selected = call.get("reminders", ["1h", "10m"])
    reminders = [(dt - delta, text) for key, (delta, text) in reminder_map.items() if key in selected]
    reminders.append((dt, "📞 *Время звонка!* Все на связи?"))

    for remind_dt, prefix in reminders:
        if remind_dt > now:
            job_queue.run_once(
                send_reminder,
                when=remind_dt,
                data={"call_id": call["id"], "chat_id": call["chat_id"], "prefix": prefix},
                name=f"reminder_{call['id']}_{remind_dt.timestamp()}",
            )

async def send_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    data = ctx.job.data
    calls = load_calls()
    call = next((c for c in calls if c["id"] == data["call_id"]), None)
    if not call:
        return
    await ctx.bot.send_message(
        chat_id=data["chat_id"],
        text=data["prefix"] + "\n\n" + format_call(call),
        parse_mode="Markdown"
    )

def restore_jobs(app):
    calls = load_calls()
    now = datetime.now(TIMEZONE)
    for call in calls:
        if datetime.fromisoformat(call["datetime"]) > now:
            schedule_reminders(app.job_queue, call)
    log.info(f"Восстановлено {len(calls)} звонков.")

async def handle_webapp_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = json.loads(update.effective_message.web_app_data.data)
    date_str = data["date"]
    time_str = data["time"]
    naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    local_dt = naive_dt.replace(tzinfo=TIMEZONE)

    calls = load_calls()
    call_id = max((c["id"] for c in calls), default=0) + 1
    call = {
        "id": call_id,
        "datetime": local_dt.isoformat(),
        "tasks": data.get("tasks", {}),
        "reminders": data.get("reminders", ["1h", "10m"]),
        "chat_id": update.effective_chat.id,
    }
    calls.append(call)
    save_calls(calls)
    schedule_reminders(ctx.application.job_queue, call)

    await update.message.reply_text(
        f"✅ Звонок назначен!\n\n{format_call(call)}\n\nНапомню заранее.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

# ─── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(btn_new_call, pattern="^new_call$")],
        states={
            SELECT_DATE: [CallbackQueryHandler(handle_date, pattern="^date_")],
            ENTER_CUSTOM_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_date)],
            SELECT_TIME: [CallbackQueryHandler(handle_time, pattern="^time_")],
            ENTER_CUSTOM_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_time)],
            SELECT_REMINDER: [CallbackQueryHandler(handle_reminder_select, pattern="^rem_")],
            ENTER_TASKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task)],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_conv, pattern="^back_main$"),
            CommandHandler("cancel", cancel_conv),
        ],
        per_chat=False,
        per_user=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(btn_list_calls, pattern="^list_calls$"))
    app.add_handler(CallbackQueryHandler(btn_back_main, pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(btn_cancel_call, pattern="^cancel_\d+$"))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))

    restore_jobs(app)
    log.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)

import asyncio
if __name__ == "__main__":
    asyncio.run(main())
