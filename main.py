"""
Telegram-бот для проверки юридических лиц по ИНН.
Версия с минимальной проверкой через Checko.ru.
"""

import os
import sys
import logging
import asyncio
from typing import Optional

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.exceptions import TelegramForbiddenError
from aiogram.client.default import DefaultBotProperties

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from src.modules.rusprofile import RusProfileChecker

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("AI_TOKEN", "")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# Создаём экземпляры модулей
rusprofile_checker = RusProfileChecker(
    timeout=REQUEST_TIMEOUT,
    max_retries=MAX_RETRIES,
)

# Хранилище данных для отслеживания процесса проверки
check_states: dict[int, dict] = {}

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

async def cmd_start(message: Message):
    """Команда /start — приветствие."""
    await message.answer(
        "👋 Привет! Я — *КонтрагентПро*, бот для проверки юридических лиц.\n\n"
        "Напишите ИНН компании, и я проверю её по открытым источникам.\n\n"
        "📋 *Что я покажу:*\n"
        "• Название компании\n"
        "• ОГРН\n"
        "• Адрес\n"
        "• Руководителя\n"
        "• Статус (действует/ликвидирована)\n"
        "• Уставный капитал\n"
        "• Дату регистрации\n\n"
        "Введите ИНН для проверки (10 цифр):",
        parse_mode="Markdown",
    )

async def cmd_help(message: Message):
    """Команда /help — справка."""
    await message.answer(
        "📖 *СПРАВКА ПО ИСПОЛЬЗОВАНИЮ*\n\n"
        "*Команды:*\n"
        "• /start — Запустить бота\n"
        "• /help — Показать справку\n\n"
        "*Как проверить компанию:*\n"
        "1. Напишите ИНН компании (10 цифр)\n"
        "2. Дождитесь результата (5-15 секунд)\n\n"
        "*Примеры ИНН:*\n"
        "• 7707083893 — ООО «Яндекс»\n"
        "• 7710000001 — ООО «Газпром»\n\n"
        "*Примечание:*\n"
        "Данные собираются из открытых источников.",
        parse_mode="Markdown",
    )

# ==================== ОСНОВНАЯ ЛОГИКА ПРОВЕРКИ ====================

def validate_inn(inn: str) -> tuple[bool, str]:
    """Валидация ИНН (10 цифр)."""
    inn = inn.strip().replace(" ", "").replace("-", "")
    if len(inn) != 10:
        return False, (
            f"❌ Неверный формат ИНН.\n\n"
            f"ИНН должен содержать ровно 10 цифр.\n"
            f"Ваш ввод: `{inn}`\n\n"
            f"Попробуйте ещё раз."
        )
    if not inn.isdigit():
        return False, (
            f"❌ ИНН должен содержать только цифры.\n\n"
            f"Ваш ввод: `{inn}`\n\n"
            f"Попробуйте ещё раз."
        )
    if not _validate_inn_checksum(inn):
        return False, (
            f"❌ ИНН не прошёл проверку контрольной суммы.\n\n"
            f"Проверьте правильность ввода и попробуйте ещё раз."
        )
    return True, inn

def _validate_inn_checksum(inn: str) -> bool:
    """Проверка контрольной суммы 10-значного ИНН."""
    if len(inn) != 10:
        return False
    digits = [int(d) for d in inn]
    coeffs = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    total = sum(d * c for d, c in zip(digits[:-1], coeffs))
    check_digit = (total % 11) % 10
    return check_digit == digits[-1]

async def run_full_check(user_id: int, inn: str):
    """Запуск проверки компании через Checko.ru."""
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="Markdown"),
    )

    status_msg = await bot.send_message(
        user_id,
        f"🔍 *Проверяю ИНН: {inn}*",
        parse_mode="Markdown",
    )

    try:
        # Проверка через RusProfile (Checko.ru)
        result = await rusprofile_checker.check(inn)
        
        if result.get("success"):
            data = result.get("data", {})
            report = f"""
📋 *Результат проверки ИНН {inn}*

🏢 *Компания:* {data.get('name', {}).get('full', 'Не найдено')}
📌 *ИНН:* {data.get('inn', 'Не указан')}
📌 *ОГРН:* {data.get('ogrn', 'Не указан')}
📍 *Адрес:* {data.get('address', 'Не указан')}
👤 *Директор:* {data.get('director', 'Не указан')}
📊 *Статус:* {data.get('status', 'Не указан')}
💰 *Уставный капитал:* {data.get('capital', 'Не указан')}
📅 *Дата регистрации:* {data.get('registration_date', 'Не указана')}
"""
        else:
            report = f"❌ Не удалось получить данные по ИНН {inn}"

        await bot.edit_message_text(
            report,
            chat_id=user_id,
            message_id=status_msg.message_id,
            parse_mode="Markdown",
        )

        logger.info(f"Проверка ИНН {inn} завершена")

    except Exception as e:
        logger.error(f"Ошибка при проверке ИНН {inn}: {e}", exc_info=True)
        await bot.edit_message_text(
            f"❌ *Ошибка при проверке*\n\n"
            f"`{str(e)}`",
            chat_id=user_id,
            message_id=status_msg.message_id,
            parse_mode="Markdown",
        )
    finally:
        if user_id in check_states:
            del check_states[user_id]
        await bot.session.close()

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================

async def handle_inn_message(message: Message):
    """Обработка сообщения с ИНН."""
    user_id = message.from_user.id

    if user_id in check_states:
        await message.answer(
            "⏳ Уже идёт проверка. Подождите завершения."
        )
        return

    is_valid, result = validate_inn(message.text)
    if not is_valid:
        await message.answer(result)
        return

    inn = result
    check_states[user_id] = {"inn": inn, "started_at": asyncio.get_event_loop().time()}
    asyncio.create_task(run_full_check(user_id, inn))

# ==================== ВЕБ-СЕРВЕР ДЛЯ RENDER ====================

async def health_check(request):
    """Проверка здоровья для Render."""
    return web.Response(text="I'm alive!", status=200)

async def start_web_server():
    """Запуск минимального веб-сервера на порту 10000."""
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10000)
    await site.start()
    print("✅ Веб-сервер для Render запущен на порту 10000")
    await asyncio.Event().wait()

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

async def main_async():
    """Запуск бота и веб-сервера."""
    web_task = asyncio.create_task(start_web_server())
    
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="Markdown"),
    )
    dp = Dispatcher()

    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(handle_inn_message, F.text.regexp(r"\d{10}"))
    dp.message.register(handle_inn_message, F.text)

    print("🚀 Бот запускается...")
    try:
        await dp.start_polling(bot, timeout=60)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}", exc_info=True)

def main():
    """Точка входа."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен!")
        sys.exit(1)
    
    asyncio.run(main_async())

if __name__ == "__main__":
    main()