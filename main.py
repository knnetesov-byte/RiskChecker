"""
Telegram-бот для проверки юридических лиц по ИНН.
С минимальным веб-сервером для работы на Render.com.
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
from src.modules.fedresurs import FedresursChecker
from src.modules.court_checker import CourtChecker
from src.modules.oborot_net import OborotNetChecker
from src.modules.rusprofile import RusProfileChecker
from src.modules.risk_assessor import RiskAssessor
from src.reports.formatter import format_full_report, format_short_status

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
DATAPI_API_KEY = os.getenv("DATAPI_API_KEY", "")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# Создаём экземпляры модулей
fedresurs_checker = FedresursChecker(
    timeout=REQUEST_TIMEOUT,
    max_retries=MAX_RETRIES,
)
court_checker = CourtChecker(
    timeout=REQUEST_TIMEOUT,
    max_retries=MAX_RETRIES,
)
oborot_checker = OborotNetChecker(
    timeout=REQUEST_TIMEOUT,
    max_retries=MAX_RETRIES,
)
rusprofile_checker = RusProfileChecker(
    timeout=REQUEST_TIMEOUT,
    max_retries=MAX_RETRIES,
)
risk_assessor = RiskAssessor()

# Хранилище данных для отслеживания процесса проверки
check_states: dict[int, dict] = {}

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

async def cmd_start_deep_link(message: Message):
    """Обработка запуска с параметром."""
    await message.answer(
        "👋 Привет! Я бот для проверки юридических лиц по ИНН.\n\n"
        "Введите ИНН компании для проверки:\n"
        "Пример: 7707083893 (ООО 'Яндекс')\n\n"
        "Я проверю компанию по нескольким открытым источникам:\n"
        "• Fedresurs — реестр банкротов\n"
        "• kad.arbitr.ru — судебные дела\n"
        "• oborot.net — Росфинмониторинг\n"
        "• RusProfile — данные о компании\n\n"
        "📌 После проверки вы получите:\n"
        "• Срок действия компании\n"
        "• Проверку по всем базам\n"
        "• Уставный капитал\n"
        "• Судебные дела и историю\n"
        "• Оценку рисков\n\n"
        "Введите ИНН для начала проверки!"
    )

async def cmd_start(message: Message):
    """Команда /start — приветствие."""
    await message.answer(
        "👋 Привет! Я — *КонтрагентПро*, бот для проверки юридических лиц.\n\n"
        "Напишите ИНН компании, и я проведу полную проверку:\n\n"
        "📊 **Что проверяю:**\n"
        "1️⃣ Fedresurs — реестр банкротов\n"
        "2️⃣ kad.arbitr.ru — судебные дела\n"
        "3️⃣ oborot.net — Росфинмониторинг\n"
        "4️⃣ RusProfile — данные о компании\n\n"
        "📋 **Результат включает:**\n"
        "• Срок действия компании\n"
        "• Проверку учредителей и директора\n"
        "• Уставный капитал\n"
        "• Судебные дела (активные + проигранные)\n"
        "• Комплексную оценку рисков\n\n"
        "Введите ИНН для проверки (10 цифр):",
        parse_mode="Markdown",
    )

async def cmd_help(message: Message):
    """Команда /help — справка."""
    await message.answer(
        "📖 *СПРАВКА ПО ИСПОЛЬЗОВАНИЮ*\n\n"
        "*Команды:*\n"
        "• /start — Запустить бота\n"
        "• /help — Показать справку\n"
        "• /stop — Остановить проверку\n\n"
        "*Как проверить компанию:*\n"
        "1. Напишите ИНН компании (10 цифр)\n"
        "2. Дождитесь результатов (1-3 минуты)\n"
        "3. Получите полный отчёт с оценкой рисков\n\n"
        "*Примеры ИНН:*\n"
        "• 7707083893 — ООО «Яндекс»\n"
        "• 7710000001 — ООО «Газпром»\n"
        "• 7707388800 — ПАО «Сбербанк»\n\n"
        "*Примечание:*\n"
        "Проверка использует открытые источники. "
        "Для полной информации рекомендуется "
        "платные сервисы (Контур.Фокус, СПАРК).",
        parse_mode="Markdown",
    )

async def cmd_stop(message: Message):
    """Остановка текущей проверки."""
    if message.from_user.id in check_states:
        del check_states[message.from_user.id]
        await message.answer("✅ Проверка остановлена.")
    else:
        await message.answer("❌ Нет активной проверки для остановки.")

# ==================== ОСНОВНАЯ ЛОГИКА ПРОВЕРКИ ====================

def validate_inn(inn: str) -> tuple[bool, str]:
    """Валидация ИНН (10 цифр)."""
    # Очистка от пробелов, дефисов и других символов
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
    """
    Проверка контрольной суммы 10-значного ИНН.
    """
    if len(inn) != 10:
        return False
    digits = [int(d) for d in inn]
    # Коэффициенты для 10-значного ИНН: 2, 4, 10, 3, 5, 9, 4, 6, 8
    coeffs = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    total = sum(d * c for d, c in zip(digits[:-1], coeffs))
    check_digit = (total % 11) % 10
    return check_digit == digits[-1]

async def run_full_check(user_id: int, inn: str):
    """Запуск полной проверки компании."""
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="Markdown"),
    )

    status_msg = await bot.send_message(
        user_id,
        f"🔍 *Начинаю проверку ИНН: {inn}*\n\n"
        f"⏳ Это займёт 1-3 минуты.\n"
        f"Проверяю по всем доступным источникам...",
        parse_mode="Markdown",
    )

    try:
        bankruptcy_task = asyncio.create_task(fedresurs_checker.check(inn))
        court_task = asyncio.create_task(court_checker.check(inn))
        oborot_task = asyncio.create_task(oborot_checker.check(inn))
        rusprofile_task = asyncio.create_task(rusprofile_checker.check(inn))

        await bot.edit_message_text(
            f"🔍 *Проверка ИНН: {inn}*\n\n"
            f"⏳ Проверяю:\n"
            f"• Fedresurs — реестр банкротов\n"
            f"• kad.arbitr.ru — судебные дела\n"
            f"• oborot.net — Росфинмониторинг\n"
            f"• RusProfile — данные о компании",
            chat_id=user_id,
            message_id=status_msg.message_id,
            parse_mode="Markdown",
        )

        bankruptcy, courts, oborot, rusprofile = await asyncio.gather(
            bankruptcy_task,
            court_task,
            oborot_task,
            rusprofile_task,
        )

        await bot.edit_message_text(
            f"🔍 *Проверка ИНН: {inn}*\n\n"
            f"✅ Данные получены!\n"
            f"📊 Формирую отчёт...",
            chat_id=user_id,
            message_id=status_msg.message_id,
            parse_mode="Markdown",
        )

        risk_assessment = risk_assessor.assess(
            inn=inn,
            bankruptcy=bankruptcy,
            courts=courts,
            oborot=oborot,
            rusprofile=rusprofile,
        )

        report = format_full_report(
            inn=inn,
            risk_assessment=risk_assessment,
            bankruptcy=bankruptcy,
            courts=courts,
            oborot=oborot,
            rusprofile=rusprofile,
        )

        if len(report) > 4000:
            report = report[:3997] + "\n\n_...отчёт обрезан_"

        await bot.edit_message_text(
            report,
            chat_id=user_id,
            message_id=status_msg.message_id,
            parse_mode="Markdown",
        )

        logger.info(
            f"Проверка ИНН {inn} завершена. "
            f"Риск: {risk_assessment.overall_risk}, "
            f"Балл: {risk_assessment.risk_score}"
        )

    except Exception as e:
        logger.error(f"Ошибка при проверке ИНН {inn}: {e}", exc_info=True)
        await bot.edit_message_text(
            f"❌ *Ошибка при проверке*\n\n"
            f"Произошла непредвиденная ошибка:\n"
            f"`{str(e)}`\n\n"
            f"Попробуйте позже или используйте команду /help.",
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
            "⏳ Уже идёт проверка. Подождите завершения или используйте /stop."
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
    # Держим сервер запущенным бесконечно
    await asyncio.Event().wait()

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

async def main_async():
    """Запуск бота и веб-сервера."""
    # Запускаем веб-сервер в фоне
    web_task = asyncio.create_task(start_web_server())
    
    # Создаём бота и диспетчер
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="Markdown"),
    )
    dp = Dispatcher()

    # Регистрируем хендлеры
    dp.message.register(cmd_start_deep_link, CommandStart(deep_link="check"))
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_stop, Command("stop"))
    dp.message.register(handle_inn_message, F.text.regexp(r"\d{10}"))
    dp.message.register(handle_inn_message, F.text)

    print("🚀 Бот запускается...")
    try:
        await dp.start_polling(bot, timeout=60)
    except TelegramForbiddenError:
        logger.error(
            "Бот не имеет прав для отправки сообщений. "
            "Проверьте токен и настройки бота."
        )
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}", exc_info=True)

def main():
    """Точка входа."""
    if not BOT_TOKEN:
        logger.error(
            "BOT_TOKEN не установлен! "
            "Скопируйте .env.example в .env и укажите токен бота."
        )
        print(
            "\n⚠️  Для запуска бота:\n"
            "1. Создайте бота через @BotFather\n"
            "2. Скопируйте .env.example в .env\n"
            "3. Вставьте токен в .env\n"
            "4. Установите зависимости: pip install -r requirements.txt\n"
            "5. Запустите: python main.py\n"
        )
        sys.exit(1)
    
    asyncio.run(main_async())

if __name__ == "__main__":
    main()