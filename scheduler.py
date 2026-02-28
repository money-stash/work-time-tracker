import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from config import ADMIN_ID, TIMEZONE
from storage import load_data, get_session, update_session, reset_session
from database import record_session_start, record_session_end, record_day_complete

scheduler = AsyncIOScheduler(timezone=TIMEZONE)
_bot: Bot = None
_session_task: asyncio.Task = None
_current_session_db_id: int = None
_session_counter: int = 0

async def send_work_start_prompt():
    session = get_session()
    if session["active"]:
        return
    reset_session()
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚀 Начать работу", callback_data="start_work")
    ]])
    data = load_data()
    await _bot.send_message(
        ADMIN_ID,
        f"⏰ Время работать!\n\nСегодня план: {data['work_duration_minutes']} мин "
        f"по {data['session_minutes']} мин сессиям.\n\nНажми кнопку чтобы начать!",
        reply_markup=kb
    )

async def run_work_session():
    global _session_task, _current_session_db_id, _session_counter
    data = load_data()
    session_min = data["session_minutes"]
    break_min = data["break_minutes"]
    warning_min = data["warning_before_end_minutes"]
    total_work = data["work_duration_minutes"]

    session = get_session()
    completed = session.get("completed_minutes", 0)

    _session_counter += 1
    _current_session_db_id = record_session_start(_session_counter, session_min)

    update_session(active=True, state="working", completed_minutes=completed)
    await asyncio.sleep(session_min * 60)

    record_session_end(_current_session_db_id, session_min)
    completed += session_min
    update_session(completed_minutes=completed)

    if completed >= total_work:
        record_day_complete(completed)
        reset_session()
        _session_counter = 0
        await _bot.send_message(
            ADMIN_ID,
            f"🎉 Рабочий день завершён!\n\n"
            f"✅ Отработано: {completed} мин\n"
            f"💼 Сессий: {completed // session_min}\n\n"
            f"Ты молодец! Отдыхай 😊\n\nСтатистика: /stats"
        )
        reschedule_daily()
        return

    update_session(state="break")
    await _bot.send_message(
        ADMIN_ID,
        f"✅ Сессия завершена! Отработано сегодня: {completed} / {total_work} мин\n\n"
        f"😌 Отдохни {break_min} минут. Заслужил!"
    )

    warning_after = (break_min - warning_min) * 60
    if warning_after > 0:
        await asyncio.sleep(warning_after)
        await _bot.send_message(ADMIN_ID, f"⏳ Через {warning_min} мин снова за работу!")
        await asyncio.sleep(warning_min * 60)
    else:
        await asyncio.sleep(break_min * 60)

    update_session(state="ready_check")
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💪 Да, готов!", callback_data="continue_work")
    ]])
    await _bot.send_message(ADMIN_ID, "🔔 Отдых закончился!\n\nГотов продолжать?", reply_markup=kb)

def reschedule_daily():
    if scheduler.get_job("work_start"):
        scheduler.remove_job("work_start")
    data = load_data()
    hour, minute = data["work_start_time"].split(":")
    scheduler.add_job(
        send_work_start_prompt,
        CronTrigger(hour=int(hour), minute=int(minute), timezone=TIMEZONE),
        id="work_start",
        replace_existing=True
    )

async def start_work_session():
    global _session_task
    if _session_task and not _session_task.done():
        _session_task.cancel()
    _session_task = asyncio.create_task(run_work_session())

async def start_scheduler(bot: Bot):
    global _bot
    _bot = bot
    from database import init_db
    init_db()
    scheduler.start()
    reschedule_daily()
