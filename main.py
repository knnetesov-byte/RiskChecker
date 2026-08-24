"""
Telegram-бот для проверки юридических лиц по ИНН.
Парсинг данных с Checko.ru.
"""

import os
import sys
import logging
import asyncio
import aiohttp
from bs4 import BeautifulSoup

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties

from dotenv import load_dotenv

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

# Хранилище данных для отслеживания процесса проверки
check_states: dict[int, dict] = {}

# ==================== ПАРСЕР CHECKO.RU ====================

async def get_company_data(inn: str) -> dict:
    """Получение данных о компании с Checko.ru."""
    try:
        url = f"https://checko.ru/inn/{inn}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as session:
            # Имитация задержки, как будто человек открывает страницу
            await asyncio.sleep(2)
            
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    logger.error(f"Checko.ru вернул статус {response.status} для ИНН {inn}")
                    return {}

                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                data = {}

                # Название компании
                name_tag = soup.find('h1')
                if name_tag:
                    data['full_name'] = name_tag.text.strip()
                else:
                    name_tag = soup.find('div', class_='company-name')
                    if name_tag:
                        data['full_name'] = name_tag.text.strip()

                # Ищем данные в таблице
                rows = soup.find_all('div', class_='row')
                for row in rows:
                    label = row.find('div', class_='col-sm-4')
                    value = row.find('div', class_='col-sm-8')
                    if label and value:
                        label_text = label.text.strip()
                        value_text = value.text.strip()

                        if 'ИНН' in label_text:
                            data['inn'] = value_text
                        elif 'ОГРН' in label_text:
                            data['ogrn'] = value_text
                        elif 'Статус' in label_text:
                            data['state'] = value_text
                        elif 'Юридический адрес' in label_text:
                            data['address'] = value_text
                        elif 'Руководитель' in label_text:
                            data['director_name'] = value_text
                        elif 'Уставный капитал' in label_text:
                            data['authorized_capital'] = value_text
                        elif 'Дата регистрации' in label_text:
                            data['registration_date'] = value_text

                if data:
                    logger.info(f"Успешно получены данные с Checko.ru для ИНН {inn}")
                    return data
                else:
                    logger.warning(f"Данные для ИНН {inn} не найдены на Checko.ru")
                    return {}

    except Exception as e:
        logger.error(f"Ошибка при парсинге Checko.ru для ИНН {inn}: {e}")
        return {}

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

async def cmd_start(message: Message):
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
    await message.answer(
        "📖 *СПРАВКА ПО ИСПОЛЬЗОВАНИЮ*\n\n"
        "*Команды:*\n"
        "• /start — Запустить бота\n"
        "• /help — Показать справку\n\n"
        "*Как проверить компанию:*\n"
        "1. Напишите ИНН компании (10 цифр)\n"
        "2. Дождитесь результата (10-20 секунд)\n\n"
        "*Примеры ИНН:*\n"
        "• 7707083893 — ООО «Яндекс»\n"
        "• 7710000001 — ООО «Газпром»\n\n",
        parse_mode="Markdown",
    )

# ==================== ОСНОВНАЯ ЛОГИКА ПРОВЕРКИ ====================

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
        data = await get_company_data(inn)

        if data:
            report = f"""
📋 *Результат проверки ИНН {inn}*

🏢 *Компания:* {data.get('full_name', 'Не указано')}
📌 *ИНН:* {data.get('inn', 'Не указан')}
📌 *ОГРН:* {data.get('ogrn', 'Не указан')}
📍 *Адрес:* {data.get('address', 'Не указан')}
👤 *Директор:* {data.get('director_name', 'Не указан')}
📊 *Статус:* {data.get('state', 'Не указан')}
💰 *Уставный капитал:* {data.get('authorized_capital', 'Не указан')}
📅 *Дата регистрации:* {data.get('registration_date', 'Не указана')}
"""
        else:
            report = f"""
❌ *Компания с ИНН {inn} не найдена на Checko.ru*

Проверьте правильность ИНН или попробуйте позже.
"""

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
