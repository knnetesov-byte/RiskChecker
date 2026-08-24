"""
Модуль kad.arbitr.ru — проверка судебных дел.
Проверка компании как ответчика в арбитражных судах.
"""

import asyncio
import re
import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class CourtCase:
    """Одно судебное дело."""
    case_number: str = ""
    case_status: str = ""
    court_name: str = ""
    article: str = ""
    initiator: str = ""
    amount: str = ""
    description: str = ""
    result: str = ""  # выиграно/проиграно
    date: str = ""


@dataclass
class CourtData:
    """Данные о судебных делах."""
    inn: str
    full_name: str = ""
    found: bool = False
    total_cases: int = 0
    active_cases: int = 0
    lost_cases: int = 0
    total_amount: str = ""
    cases: list[CourtCase] = field(default_factory=list)
    risks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class CourtChecker:
    """Проверка судебных дел через kad.arbitr.ru."""

    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = "https://kad.arbitr.ru"

    async def check(self, inn: str, full_name: str = "") -> CourtData:
        """
        Проверяет компанию по ИНН в базе судебных дел.

        Args:
            inn: ИНН юридического лица
            full_name: Полное наименование компании (для уточнения)

        Returns:
            CourtData с результатами проверки
        """
        result = CourtData(inn=inn, full_name=full_name)

        try:
            # Шаг 1: Поиск через карточку компании
            company_data = await self._get_company_card(inn)
            if company_data:
                result.found = True
                result.full_name = company_data.get("full_name", full_name)
                result.total_cases = company_data.get("total_cases", 0)

            # Шаг 2: Поиск судебных дел
            cases = await self._search_cases(inn, full_name)
            if cases:
                result.cases = cases
                result.total_cases = len(cases)

                # Считаем активные и проигранные дела
                result.active_cases = sum(
                    1 for c in cases if c.case_status in [
                        "Рассматривается",
                        "На рассмотрении",
                        "Определение",
                        "Решение",
                    ]
                )
                result.lost_cases = sum(
                    1 for c in cases if c.result in [
                        "Не в пользу компании",
                        "Ответчик проиграл",
                        "В удовлетворении отказано",
                        "Удовлетворено частично",
                    ]
                )

                # Подсчёт общей суммы
                result.total_amount = self._calculate_total_amount(cases)

                # Оценка рисков
                result.risks = self._assess_court_risks(result)
            else:
                result.warnings.append(
                    "Судебные дела не найдены. Это положительный фактор."
                )

        except asyncio.TimeoutError:
            result.warnings.append(
                "Превышено время ожидания ответа от kad.arbitr.ru."
            )
        except Exception as e:
            logger.error(
                f"Ошибка при проверке судов для ИНН {inn}: {e}",
                exc_info=True,
            )
            result.warnings.append(f"Ошибка при запросе к kad.arbitr.ru: {str(e)}")

        return result

    async def _get_company_card(self, inn: str) -> Optional[dict]:
        """
        Получение карточки компании через сударь (sudact.ru).
        """
        # Используем sudact.ru для поиска компании
        url = f"https://sudact.ru/arbCourt/search/?text={inn}&type=inn"

        headers = self._get_headers()

        async with aiohttp.ClientSession() as session:
            for attempt in range(self.max_retries):
                try:
                    async with session.get(
                        url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as response:
                        if response.status == 200:
                            html = await response.text()
                            return self._parse_company_card(html, inn)
                        elif response.status == 429:
                            await asyncio.sleep((attempt + 1) * 2)

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(
                        f"Попытка {attempt + 1}/{self.max_retries} не удалась: {e}"
                    )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2)

        return None

    async def _search_cases(self, inn: str, full_name: str) -> list[CourtCase]:
        """
        Поиск судебных дел по ИНН/наименованию.
        """
        cases = []
        search_terms = []

        if full_name:
            search_terms.append(full_name)
        search_terms.append(inn)

        for term in search_terms:
            if not term:
                continue

            # Поиск через kad.arbitr.ru
            url = f"https://kad.arbitr.ru/SearchListL2"

            data = {
                "query": f"ИНН {inn}",
                "page": 0,
                "pageSize": 50,
            }

            headers = self._get_headers()
            headers.update({
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://kad.arbitr.ru/",
            })

            async with aiohttp.ClientSession() as session:
                for attempt in range(self.max_retries):
                    try:
                        async with session.post(
                            url,
                            headers=headers,
                            data=data,
                            timeout=aiohttp.ClientTimeout(total=self.timeout),
                        ) as response:
                            if response.status == 200:
                                html = await response.text()
                                parsed = self._parse_cases_list(html)
                                cases.extend(parsed)
                                break
                            elif response.status == 429:
                                await asyncio.sleep((attempt + 1) * 2)

                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        logger.warning(
                            f"Попытка {attempt + 1} поиска дел не удалась: {e}"
                        )
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep(2)

            # Дубликаты
            case_numbers = {c.case_number for c in cases if c.case_number}
            cases = [c for c in cases if c.case_number not in case_numbers or cases.count(c) == 1]
            case_numbers = set()

        return cases[:50]  # Максимум 50 дел для отображения

    async def _get_case_details(self, case_number: str) -> Optional[CourtCase]:
        """
        Получение деталей конкретного дела.
        """
        url = f"https://kad.arbitr.ru/Content/Online.jsp?case_kad={case_number}"

        headers = self._get_headers()

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    if response.status == 200:
                        html = await response.text()
                        return self._parse_case_details(html)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"Не удалось получить детали дела {case_number}: {e}")

        return None

    def _parse_company_card(self, html: str, inn: str) -> Optional[dict]:
        """Парсинг карточки компании с sudact.ru."""
        soup = BeautifulSoup(html, "html.parser")
        results = {}

        # Ищем информацию о компании
        text_content = soup.get_text()

        # Определяем количество дел
        cases_match = re.search(r"(\d+)\s+дел", text_content)
        if cases_match:
            results["total_cases"] = int(cases_match.group(1))

        return results if results.get("total_cases", 0) > 0 else None

    def _parse_cases_list(self, html: str) -> list[CourtCase]:
        """Парсинг списка судебных дел."""
        soup = BeautifulSoup(html, "html.parser")
        cases = []

        # Ищем элементы с делами
        case_blocks = soup.find_all(
            ["div", "tr"],
            class_=re.compile(r"case|list|row", re.I),
        )

        for block in case_blocks[:50]:
            text = block.get_text()

            # Ищем номер дела
            case_match = re.search(
                r"([А-ЯA-Z]{1,3})\s*(\d{4})\s*/\s*\d{2,3}\s*-\s*\d{4,6}[/a]",
                text,
            )
            if not case_match:
                case_match = re.search(
                    r"дело\s*№?\s*([А-ЯA-Z]{0,3}\s*\d{4}/\d{2,3}\s*-\s*\d{4,6})",
                    text,
                )

            if case_match:
                case = CourtCase()
                case.case_number = case_match.group(0).strip()
                cases.append(case)

        # Альтернативный парсинг — просто по тексту
        if not cases:
            case_numbers = re.findall(
                r"([А-ЯA-Z]{0,3}\s*\d{4}/\d{2,3}\s*-\s*\d{4,6})",
                html,
            )
            for cn in case_numbers[:50]:
                cases.append(CourtCase(case_number=cn.strip()))

        return cases

    def _parse_case_details(self, html: str) -> CourtCase:
        """Парсинг деталей конкретного дела."""
        case = CourtCase()
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        # Номер дела
        case_match = re.search(
            r"([А-ЯA-Z]{0,3}\s*\d{4}/\d{2,3}\s*-\s*\d{4,6})",
            text,
        )
        if case_match:
            case.case_number = case_match.group(1).strip()

        # Статус дела
        status_keywords = [
            "Рассматривается",
            "Определено",
            "Решение",
            "Завершено",
            "Оставлено без рассмотрения",
        ]
        for kw in status_keywords:
            if kw.lower() in text.lower():
                case.case_status = kw
                break

        # Сумма иска
        amount_match = re.search(
            r"(сумма\s*иска|иск|взыскать)[:\s]*(\d[\d\s.,]*)",
            text,
            re.I,
        )
        if amount_match:
            case.amount = amount_match.group(2).strip()

        # Статья
        article_match = re.search(
            r"ст\.\s*\d+[\s,\-]*[а-яёA-Z]*",
            text,
            re.I,
        )
        if article_match:
            case.article = article_match.group(0).strip()

        return case

    def _calculate_total_amount(self, cases: list[CourtCase]) -> str:
        """Подсчёт общей суммы исков."""
        total = 0
        for case in cases:
            # Извлекаем число из строки суммы
            amount_match = re.search(r"([\d.,]+)", case.amount)
            if amount_match:
                try:
                    amount = float(amount_match.group(1).replace(",", "."))
                    total += amount
                except ValueError:
                    pass

        if total > 0:
            if total >= 1_000_000:
                return f"{total:,.0f} руб. (~{total / 1_000_000:.1f} млн руб.)"
            elif total >= 1_000:
                return f"{total:,.0f} руб. (~{total / 1_000:.1f} тыс. руб.)"
            return f"{total:,.0f} руб."
        return "Не определена"

    def _assess_court_risks(self, data: CourtData) -> list:
        """Оценка рисков на основе судебных дел."""
        risks = []

        # Общий риск: количество дел
        if data.total_cases > 20:
            risks.append({
                "severity": "critical",
                "title": "Критическое количество судебных дел",
                "description": (
                    f"Компания является стороной в {data.total_cases} судебных делах. "
                    "Это указывает на систематические проблемы."
                ),
            })
        elif data.total_cases > 10:
            risks.append({
                "severity": "high",
                "title": "Большое количество судебных дел",
                "description": (
                    f"Компания является стороной в {data.total_cases} судебных делах."
                ),
            })
        elif data.total_cases > 5:
            risks.append({
                "severity": "medium",
                "title": "Умеренное количество судебных дел",
                "description": (
                    f"Компания является стороной в {data.total_cases} судебных делах."
                ),
            })

        # Риск: проигранные дела
        if data.lost_cases > 5:
            risks.append({
                "severity": "critical",
                "title": "Множество проигранных дел",
                "description": (
                    f"Компания проиграла {data.lost_cases} дел. "
                    "Это указывает на систематические нарушения обязательств."
                ),
            })
        elif data.lost_cases > 2:
            risks.append({
                "severity": "high",
                "title": "Несколько проигранных дел",
                "description": (
                    f"Компания проиграла {data.lost_cases} дел."
                ),
            })
        elif data.lost_cases > 0:
            risks.append({
                "severity": "low",
                "title": "Есть проигранные дела",
                "description": (
                    f"Компания проиграла {data.lost_cases} дел."
                ),
            })

        # Риск: активные дела
        if data.active_cases > 5:
            risks.append({
                "severity": "high",
                "title": "Много активных судебных дел",
                "description": (
                    f"В настоящее время рассматривается {data.active_cases} дел."
                ),
            })

        # Риск: большая сумма исков
        total_str = data.total_amount
        if "млн" in total_str:
            risks.append({
                "severity": "high",
                "title": "Крупные суммы исков",
                "description": f"Общая сумма исков: {total_str}",
            })
        elif "тыс" in total_str and "млн" not in total_str:
            try:
                amount = float(total_str.replace("тыс", "").replace(" ", "").replace(",", "."))
                if amount > 1000:
                    risks.append({
                        "severity": "medium",
                        "title": "Значительные суммы исков",
                        "description": f"Общая сумма исков: {total_str}",
                    })
            except ValueError:
                pass

        return risks

    def _get_headers(self) -> dict:
        """Базовые заголовки для запросов."""
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }
