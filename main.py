"""
Telegram-бот для проверки юридических лиц по ИНН.
Работает через вызов atomno-mcp-fns-check в подпроцессе.
"""

import os
import sys
import logging
import asyncio
import json
import subprocess

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("AI_TOKEN", "")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))

check_states: dict[int, dict] = {}

# ==================== ВЫЗОВ ATOMNO-MCP-FNS-CHECK ====================

def run_mcp_check(inn: str) -> dict:
    """Вызов atomno-mcp-fns-check через командную строку."""
    try:
        result = subprocess.run(
            ["atomno-mcp-fns-check", "check_contractor", inn],
            capture_output=True,
            text=True,
            timeout=REQUEST_TIMEOUT
        )
        if result.returncode != 0:
            logger.error(f"Ошибка MCP: {result.stderr}")
            return {}
        data = json.loads(result.stdout)
        return data
    except Exception as e:
        logger.error(f"Ошибка при вызове MCP: {e}")
        return {}

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я — *КонтрагентПро*, бот для проверки юридических лиц.\n\n"
        "Напишите ИНН компании, и я проверю её по открытым источникам.\n\n"
        "Введите ИНН для проверки (10 цифр):",
        parse_mode="Markdown",
    )

async def cmd_help(message: Message):
    await message.answer(
        "📖 *СПРАВКА ПО ИСПОЛЬЗОВАНИЮ*\n\n"
        "Напишите ИНН компании (10 цифр), и я проверю её по открытым источникам.",
        parse_mode="Markdown",
    )

# ==================== ОСНОВНАЯ ЛОГИКА ====================

def validate_inn(inn: str) -> tuple[bool, str]:
    inn = inn.strip().replace(" ", "").replace("-", "")
    if len(inn) != 10:
        return False, f"❌ ИНН должен содержать ровно 10 цифр. Ваш ввод: `{inn}`"
    if not inn.isdigit():
        return False, f"❌ ИНН должен содержать только цифры. Ваш ввод: `{inn}`"
    if not _validate_inn_checksum(inn):
        return False, f"❌ ИНН не прошёл проверку контрольной суммы."
    return True, inn

def _validate_inn_checksum(inn: str) -> bool:
    if len(inn) != 10:
        return False
    digits = [int(d) for d in inn]
    coeffs = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    total = sum(d * c for d, c in zip(digits[:-1], coeffs))
    check_digit = (total % 11) % 10
    return check_digit == digits[-1]

async def run_full_check(user_id: int, inn: str):
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
        result = run_mcp_check(inn)

        if result and result.get('inn'):
            card = result.get('card', {})
            legal_status = result.get('legal_status', {})
            risks = result.get('risks', {})

            report = f"""
📋 *Результат проверки ИНН {inn}*

🏢 *Компания:* {card.get('name', {}).get('full', 'Не указано')}
📌 *ИНН:* {result.get('inn', 'Не указан')}
📌 *ОГРН:* {result.get('ogrn', 'Не указан')}
📍 *Адрес:* {card.get('address', {}).get('full', 'Не указан')}
👤 *Директор:* {card.get('director', {}).get('full_name', 'Не указан')}
📊 *Статус:* {legal_status.get('status_label_ru', 'Не указан')}
⚠️ *Уровень риска:* {risks.get('overall_risk_level', 'не определён')}
💡 *Вердикт:* {result.get('verdict_action', 'Не определён')}
📝 *Рекомендации:* {result.get('verdict_reason_ru', 'Нет данных')}
"""
        else:
            report = f"❌ *Не удалось получить данные по ИНН {inn}*"

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
            f"❌ *Ошибка при проверке*\n\n`{str(e)}`",
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
    user_id = message.from_user.id

    if user_id in check_states:
        await message.answer("⏳ Уже идёт проверка. Подождите завершения.")
        return

    is_valid, result = validate_inn(message.text)
    if not is_valid:
        await message.answer(result)
        return

    inn = result
    check_states[user_id] = {"inn": inn}
    asyncio.create_task(run_full_check(user_id, inn))

# ==================== ВЕБ-СЕРВЕР ДЛЯ RENDER ====================

async def health_check(request):
    return web.Response(text="I'm alive!", status=200)

async def start_web_server():
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
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен!")
        sys.exit(1)
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
