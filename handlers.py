from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID
from storage import load_data, set_setting, get_session, update_session, reset_session
from scheduler import start_work_session, reschedule_daily
from database import get_stats_today, get_stats_week, get_stats_month, get_stats_custom, get_all_time_stats

router = Router()

def admin_only(func):
    from functools import wraps
    @wraps(func)
    async def wrapper(message: Message, *args, **kwargs):
        if message.from_user.id != ADMIN_ID:
            return
        return await func(message, *args, **kwargs)
    return wrapper

class AdminStates(StatesGroup):
    waiting_start_time = State()
    waiting_work_duration = State()
    waiting_session_duration = State()
    waiting_break_duration = State()

def admin_panel_kb():
    data = load_data()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⏰ Время старта: {data['work_start_time']}",
            callback_data="set_start_time"
        )],
        [InlineKeyboardButton(
            text=f"⏱ Общее время работы: {data['work_duration_minutes']} мин",
            callback_data="set_work_duration"
        )],
        [InlineKeyboardButton(
            text=f"💼 Длина сессии: {data['session_minutes']} мин",
            callback_data="set_session_duration"
        )],
        [InlineKeyboardButton(
            text=f"☕ Длина перерыва: {data['break_minutes']} мин",
            callback_data="set_break_duration"
        )],
        [InlineKeyboardButton(text="🚀 Запустить сессию сейчас", callback_data="force_start")],
        [InlineKeyboardButton(text="❌ Сбросить сессию", callback_data="reset_session")],
    ])

def stats_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Сегодня", callback_data="stats_today"),
            InlineKeyboardButton(text="📆 Неделя", callback_data="stats_week"),
        ],
        [
            InlineKeyboardButton(text="🗓 Месяц", callback_data="stats_month"),
            InlineKeyboardButton(text="📊 30 дней", callback_data="stats_30"),
        ],
        [InlineKeyboardButton(text="🌍 Всё время", callback_data="stats_alltime")],
    ])

def fmt_minutes(minutes: int) -> str:
    if not minutes:
        return "0 мин"
    if minutes < 60:
        return f"{minutes} мин"
    h = minutes // 60
    m = minutes % 60
    return f"{h}ч {m}мин" if m > 0 else f"{h}ч"

def progress_bar(current: int, total: int, length: int = 10) -> str:
    if not total:
        return "░" * length
    filled = round((current / total) * length)
    filled = max(0, min(length, filled))
    return "█" * filled + "░" * (length - filled)

def format_today_stats(s: dict) -> str:
    if not s.get("exists"):
        return "📅 Сегодня ещё не начинал работу."
    bar = progress_bar(s["worked_minutes"], s["planned_minutes"])
    pct = round((s["worked_minutes"] / s["planned_minutes"]) * 100) if s["planned_minutes"] else 0
    status = "✅ День завершён!" if s["completed"] else "🔄 В процессе"
    lines = [
        "📅 <b>Сегодня</b>",
        "",
        f"Прогресс: {bar} {pct}%",
        f"Отработано: {fmt_minutes(s['worked_minutes'])} / {fmt_minutes(s['planned_minutes'])}",
        f"Сессий: {s['sessions_completed']}",
        f"Статус: {status}",
    ]
    if s.get("started_at"):
        from datetime import datetime
        started = datetime.fromisoformat(s["started_at"]).strftime("%H:%M")
        lines.append(f"Начало: {started}")
    if s.get("finished_at") and s["completed"]:
        from datetime import datetime
        finished = datetime.fromisoformat(s["finished_at"]).strftime("%H:%M")
        lines.append(f"Конец: {finished}")
    return "\n".join(lines)

def format_period_stats(s: dict) -> str:
    if s["days_worked"] == 0:
        return f"📊 За {s['period']} — нет данных."
    pct = round((s["total_worked_minutes"] / s["total_planned_minutes"]) * 100) if s["total_planned_minutes"] else 0
    lines = [
        f"📊 <b>Статистика за {s['period']}</b>",
        "",
        f"Отработано: {fmt_minutes(s['total_worked_minutes'])}",
        f"План: {fmt_minutes(s['total_planned_minutes'])} ({pct}% выполнено)",
        f"Дней с работой: {s['days_worked']} / {s['total_days']}",
        f"Дней по плану ✅: {s['days_completed']}",
        f"Всего сессий: {s['total_sessions']}",
        f"Среднее в день: {fmt_minutes(s['avg_per_day_minutes'])}",
        "",
        "<b>По дням:</b>",
    ]
    from datetime import datetime
    for day in s["days"]:
        if day["worked_minutes"] == 0:
            continue
        d = datetime.fromisoformat(day["date"]).strftime("%d.%m")
        check = "✅" if day["completed"] else "🔄"
        bar = progress_bar(day["worked_minutes"], day["planned_minutes"], 6)
        lines.append(f"{check} {d}: {bar} {fmt_minutes(day['worked_minutes'])}")
    return "\n".join(lines)

def format_alltime_stats(s: dict) -> str:
    if not s or not s.get("total_days"):
        return "🌍 Ещё нет данных."
    from datetime import datetime
    first = datetime.fromisoformat(s["first_day"]).strftime("%d.%m.%Y") if s["first_day"] else "—"
    lines = [
        "🌍 <b>Всё время</b>",
        "",
        f"Первый день: {first}",
        f"Всего дней с работой: {s['total_days']}",
        f"Завершённых дней: {s['completed_days']}",
        f"Всего отработано: {fmt_minutes(s['total_minutes'] or 0)}",
        f"Всего сессий: {s['total_sessions']}",
    ]
    if s["total_days"] and s["total_minutes"]:
        avg = round(s["total_minutes"] / s["total_days"])
        lines.append(f"Среднее в день: {fmt_minutes(avg)}")
    return "\n".join(lines)


@router.message(Command("start"))
@admin_only
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я твой рабочий бот-трекер.\n\n"
        "/admin — настройки\n"
        "/status — текущий статус\n"
        "/stats — статистика"
    )

@router.message(Command("admin"))
@admin_only
async def cmd_admin(message: Message):
    await message.answer("⚙️ Панель управления:", reply_markup=admin_panel_kb())

@router.message(Command("status"))
@admin_only
async def cmd_status(message: Message):
    session = get_session()
    data = load_data()
    state_map = {
        "idle": "😴 Ожидание",
        "working": "💼 Работаем",
        "break": "☕ Перерыв",
        "ready_check": "🔔 Ожидание подтверждения"
    }
    state_label = state_map.get(session.get("state", "idle"), "Неизвестно")
    await message.answer(
        f"📊 Статус:\n"
        f"• Состояние: {state_label}\n"
        f"• Отработано: {fmt_minutes(session.get('completed_minutes', 0))} / {fmt_minutes(data['work_duration_minutes'])}\n"
        f"• Время старта: {data['work_start_time']}"
    )

@router.message(Command("stats"))
@admin_only
async def cmd_stats(message: Message):
    await message.answer("📊 Выбери период:", reply_markup=stats_kb())

@router.callback_query(F.data == "stats_today")
async def cb_stats_today(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    s = get_stats_today()
    await callback.message.edit_text(format_today_stats(s), parse_mode="HTML", reply_markup=stats_kb())
    await callback.answer()

@router.callback_query(F.data == "stats_week")
async def cb_stats_week(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    s = get_stats_week()
    await callback.message.edit_text(format_period_stats(s), parse_mode="HTML", reply_markup=stats_kb())
    await callback.answer()

@router.callback_query(F.data == "stats_month")
async def cb_stats_month(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    s = get_stats_month()
    await callback.message.edit_text(format_period_stats(s), parse_mode="HTML", reply_markup=stats_kb())
    await callback.answer()

@router.callback_query(F.data == "stats_30")
async def cb_stats_30(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    s = get_stats_custom(30)
    await callback.message.edit_text(format_period_stats(s), parse_mode="HTML", reply_markup=stats_kb())
    await callback.answer()

@router.callback_query(F.data == "stats_alltime")
async def cb_stats_alltime(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    s = get_all_time_stats()
    await callback.message.edit_text(format_alltime_stats(s), parse_mode="HTML", reply_markup=stats_kb())
    await callback.answer()

@router.callback_query(F.data == "start_work")
async def cb_start_work(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    session = get_session()
    if session.get("active"):
        await callback.answer("Сессия уже активна!")
        return
    update_session(active=True, state="working", completed_minutes=0)
    data = load_data()
    await callback.message.edit_text(f"🚀 Поехали! Работаем {data['session_minutes']} минут. Удачи! 💪")
    await callback.answer()
    await start_work_session()

@router.callback_query(F.data == "continue_work")
async def cb_continue_work(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    update_session(state="working")
    data = load_data()
    await callback.message.edit_text(f"💪 Отлично! Работаем ещё {data['session_minutes']} минут!")
    await callback.answer()
    await start_work_session()

@router.callback_query(F.data == "force_start")
async def cb_force_start(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    reset_session()
    await callback.message.edit_text("🚀 Запускаю рабочую сессию прямо сейчас!")
    await callback.answer()
    from scheduler import send_work_start_prompt
    await send_work_start_prompt()

@router.callback_query(F.data == "reset_session")
async def cb_reset_session(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    reset_session()
    await callback.answer("✅ Сессия сброшена")
    await callback.message.edit_text("❌ Сессия сброшена.", reply_markup=admin_panel_kb())

@router.callback_query(F.data == "set_start_time")
async def cb_set_start_time(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.waiting_start_time)
    await callback.message.answer("Введи время старта в формате ЧЧ:ММ (например 14:00):")
    await callback.answer()

@router.callback_query(F.data == "set_work_duration")
async def cb_set_work_duration(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.waiting_work_duration)
    await callback.message.answer("Введи общее время работы в минутах (например 120):")
    await callback.answer()

@router.callback_query(F.data == "set_session_duration")
async def cb_set_session_duration(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.waiting_session_duration)
    await callback.message.answer("Введи длину одной рабочей сессии в минутах (например 30):")
    await callback.answer()

@router.callback_query(F.data == "set_break_duration")
async def cb_set_break_duration(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.waiting_break_duration)
    await callback.message.answer("Введи длину перерыва в минутах (например 10):")
    await callback.answer()

@router.message(AdminStates.waiting_start_time)
async def process_start_time(message: Message, state: FSMContext):
    text = message.text.strip()
    try:
        hour, minute = text.split(":")
        assert 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
    except:
        await message.answer("Неверный формат. Введи время в формате ЧЧ:ММ:")
        return
    set_setting("work_start_time", text)
    reschedule_daily()
    await state.clear()
    await message.answer(f"✅ Время старта обновлено: {text}", reply_markup=admin_panel_kb())

@router.message(AdminStates.waiting_work_duration)
async def process_work_duration(message: Message, state: FSMContext):
    try:
        value = int(message.text.strip())
        assert value > 0
    except:
        await message.answer("Введи положительное число:")
        return
    set_setting("work_duration_minutes", value)
    await state.clear()
    await message.answer(f"✅ Общее время работы: {value} мин", reply_markup=admin_panel_kb())

@router.message(AdminStates.waiting_session_duration)
async def process_session_duration(message: Message, state: FSMContext):
    try:
        value = int(message.text.strip())
        assert value > 0
    except:
        await message.answer("Введи положительное число:")
        return
    set_setting("session_minutes", value)
    await state.clear()
    await message.answer(f"✅ Длина сессии: {value} мин", reply_markup=admin_panel_kb())

@router.message(AdminStates.waiting_break_duration)
async def process_break_duration(message: Message, state: FSMContext):
    try:
        value = int(message.text.strip())
        assert value > 0
    except:
        await message.answer("Введи положительное число:")
        return
    set_setting("break_minutes", value)
    await state.clear()
    await message.answer(f"✅ Длина перерыва: {value} мин", reply_markup=admin_panel_kb())
