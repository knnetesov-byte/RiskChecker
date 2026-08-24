"""
Модуль Fedresurs — проверка по Федеральному реестру сведений о банкротстве.
https://fedresurs.ru
"""

import asyncio
import re
import logging
from typing import Optional
from dataclasses import dataclass, field

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class BankruptcyData:
    """Данные о банкротстве."""
    inn: str
    found: bool = False
    is_bankrupt: bool = False
    bankruptcy_status: str = ""
    case_number: str = ""
    case_status: str = ""
    arbitration_manager: str = ""
    registration_date: str = ""
    court: str = ""
    risks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class FedresursChecker:
    """Проверка компании в реестре банкротов Fedresurs."""

    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = "https://fedresurs.ru"

    async def check(self, inn: str) -> BankruptcyData:
        """
        Проверяет компанию по ИНН в реестре банкротов.

        Args:
            inn: ИНН юридического лица

        Returns:
            BankruptcyData с результатами проверки
        """
        result = BankruptcyData(inn=inn)

        try:
            # Шаг 1: Поиск компании по ИНН
            search_data = await self._search_by_inn(inn)
            if not search_data:
                result.warnings.append(
                    "Не удалось получить данные из Fedresurs. "
                    "Возможно, компания не найдена в реестре банкротства."
                )
                return result

            result.found = True

            # Шаг 2: Анализ данных
            if search_data.get("is_bankrupt"):
                result.is_bankrupt = True
                result.bankruptcy_status = search_data.get("status", "Не определено")
                result.case_number = search_data.get("case_number", "")
                result.case_status = search_data.get("case_status", "")
                result.arbitration_manager = search_data.get("arbitration_manager", "")
                result.registration_date = search_data.get("registration_date", "")
                result.court = search_data.get("court", "")

                # Оценка рисков
                if result.is_bankrupt:
                    result.risks.append({
                        "severity": "critical",
                        "title": "Компания в процессе банкротства",
                        "description": (
                            f"Обнаружено дело о банкротстве "
                            f"(№ {result.case_number}). "
                            f"Статус: {result.case_status}"
                        ),
                    })

                # Риск: длительный процесс банкротства
                if result.registration_date:
                    try:
                        from datetime import datetime
                        reg_date = datetime.strptime(
                            result.registration_date, "%d.%m.%Y"
                        )
                        days = (datetime.now() - reg_date).days
                        if days > 365:
                            result.risks.append({
                                "severity": "high",
                                "title": "Длительный процесс банкротства",
                                "description": (
                                    f"Процесс банкротства длится уже "
                                    f"{days} дней (более {days // 365} лет)"
                                ),
                            })
                    except (ValueError, TypeError):
                        pass

                # Риск: отсутствие арбитражного управляющего
                if not result.arbitration_manager:
                    result.risks.append({
                        "severity": "medium",
                        "title": "Не указан арбитражный управляющий",
                        "description": "Не удалось определить арбитражного управляющего по делу",
                    })
            else:
                result.bankruptcy_status = "Банкротство не обнаружено"
                result.warnings.append(
                    "В реестре банкротств сведения не обнаружены. "
                    "Это положительный фактор."
                )

        except asyncio.TimeoutError:
            result.warnings.append(
                "Превышено время ожидания ответа от Fedresurs. "
                "Попробуйте повторить проверку позже."
            )
        except Exception as e:
            logger.error(f"Ошибка при проверке Fedresurs для ИНН {inn}: {e}", exc_info=True)
            result.warnings.append(
                f"Ошибка при запросе к Fedresurs: {str(e)}"
            )

        return result

    async def _search_by_inn(self, inn: str) -> Optional[dict]:
        """
        Поиск компании по ИНН в реестре банкротов.

        Пытаемся найти данные через API или парсинг сайта.
        """
        # Пробуем через поиск на сайте Fedresurs
        search_url = f"{self.base_url}/p/spe/?q={inn}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }

        async with aiohttp.ClientSession() as session:
            for attempt in range(self.max_retries):
                try:
                    async with session.get(
                        search_url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as response:
                        if response.status == 200:
                            html = await response.text()
                            return self._parse_search_results(html, inn)

                        elif response.status == 429:
                            wait_time = (attempt + 1) * 2
                            logger.warning(
                                f"Rate limit на Fedresurs. Ждём {wait_time} сек..."
                            )
                            await asyncio.sleep(wait_time)

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(
                        f"Попытка {attempt + 1}/{self.max_retries} не удалась: {e}"
                    )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2)

        return None

    def _parse_search_results(self, html: str, inn: str) -> Optional[dict]:
        """
        Парсинг результатов поиска на Fedresurs.
        """
        soup = BeautifulSoup(html, "html.parser")
        results = {"is_bankrupt": False}

        # Ищем упоминания ИНН в результатах
        text_content = soup.get_text()

        # Проверяем наличие информации о банкротстве
        bankrupt_keywords = [
            "банкротство",
            "банкр",
            "арбитраж",
            "дело о банкротстве",
            "постановление",
        ]

        text_lower = text_content.lower()
        has_bankruptcy = any(kw in text_lower for kw in bankrupt_keywords)

        if has_bankruptcy and inn in text_content:
            results["is_bankrupt"] = True
            # Пытаемся извлечь номер дела
            case_match = re.search(
                r"№?\s*[А-ЯA-Z0-9\-]+\s*/\s*\d{4}", text_content
            )
            if case_match:
                results["case_number"] = case_match.group(0).strip()

            # Пытаемся извлечь дату
            date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})", text_content)
            if date_match:
                results["registration_date"] = date_match.group(1)

            # Ищем имя арбитражного управляющего
            manager_match = re.search(
                r"(арбитражный управля[аоий]|управляющий)[:\s]+([А-ЯA-Zа-яA-Z\s,]+)",
                text_content,
            )
            if manager_match:
                results["arbitration_manager"] = manager_match.group(2).strip()

        return results if results["is_bankrupt"] else None

    async def check_batch(self, inns: list[str]) -> list[BankruptcyData]:
        """
        Пакетная проверка нескольких ИНН.

        Args:
            inns: Список ИНН для проверки

        Returns:
            Список BankruptcyData для каждого ИНН
        """
        tasks = [self.check(inn) for inn in inns]
        return await asyncio.gather(*tasks, return_exceptions=True)
