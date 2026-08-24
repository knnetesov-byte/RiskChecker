"""
Модуль RusProfile — парсинг данных о компании.
Получение информации об учредителях, директоре, уставном капитале.
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
class CompanyInfo:
    """Основная информация о компании."""
    inn: str
    full_name: str = ""
    short_name: str = ""
    ogrn: str = ""
    kpp: str = ""
    registration_date: str = ""
    liquidation_date: str = ""
    status: str = ""  # действующая/ликвидирована/в процессе ликвидации
    authorized_capital: str = ""  # уставный капитал
    address: str = ""
    okved: str = ""
    okved_name: str = ""
    employees_count: str = ""
    risks_count: int = 0
    website: str = ""


@dataclass
class PersonInfo:
    """Информация о физическом лице (учредитель/директор)."""
    name: str = ""
    role: str = ""  # учредитель, директор, директор
    share_percent: str = ""
    inn: str = ""
    ogrn: str = ""
    birth_year: str = ""
    position: str = ""


@dataclass
class RusProfileData:
    """Результат проверки RusProfile."""
    inn: str
    found: bool = False
    company: Optional[CompanyInfo] = None
    founders: list[PersonInfo] = field(default_factory=list)
    director: Optional[PersonInfo] = None
    risks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class RusProfileChecker:
    """Парсинг данных о компании с RusProfile."""

    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = "https://www.rusprofile.ru"

    async def check(self, inn: str) -> RusProfileData:
        """
        Проверяет компанию по ИНН на RusProfile.

        Args:
            inn: ИНН юридического лица

        Returns:
            RusProfileData с результатами проверки
        """
        result = RusProfileData(inn=inn)

        try:
            # Шаг 1: Получение карточки компании
            company_data = await self._get_company_card(inn)
            if company_data:
                result.found = True
                result.company = company_data

                # Оценка рисков по уставному капиталу
                if company_data.authorized_capital:
                    capital_risk = self._check_capital_risk(
                        company_data.authorized_capital
                    )
                    if capital_risk:
                        result.risks.append(capital_risk)

                # Оценка рисков по статусу
                if company_data.status in [
                    "Ликвидирована",
                    "В процессе ликвидации",
                ]:
                    result.risks.append({
                        "severity": "critical",
                        "title": "Компания недействующая",
                        "description": (
                            f"Статус компании: {company_data.status}. "
                            "Работа с такой компанией крайне не рекомендуется."
                        ),
                    })

                # Оценка рисков по количеству рисков
                if company_data.risks_count > 10:
                    result.risks.append({
                        "severity": "high",
                        "title": "Большое количество рисков",
                        "description": (
                            f"На сайте RusProfile обнаружено "
                            f"{company_data.risks_count} рисков."
                        ),
                    })

                # Шаг 2: Получение учредителей
                founders = await self._get_founders(inn)
                if founders:
                    result.founders = founders

                    # Проверка учредителей на массовость
                    founder_names = [f.name for f in founders]
                    if len(founder_names) != len(set(founder_names)):
                        result.risks.append({
                            "severity": "medium",
                            "title": "Повторяющиеся учредители",
                            "description": "Обнаружены повторяющиеся имена учредителей.",
                        })

                # Шаг 3: Получение директора
                director = await self._get_director(inn)
                if director:
                    result.director = director

            else:
                result.warnings.append(
                    "Компания не найдена на RusProfile. "
                    "Это может означать, что компания новая или данные отсутствуют."
                )

        except asyncio.TimeoutError:
            result.warnings.append(
                "Превышено время ожидания ответа от RusProfile."
            )
        except Exception as e:
            logger.error(
                f"Ошибка при проверке RusProfile для ИНН {inn}: {e}",
                exc_info=True,
            )
            result.warnings.append(
                f"Ошибка при запросе к RusProfile: {str(e)}"
            )

        return result

    async def _get_company_card(self, inn: str) -> Optional[CompanyInfo]:
        """
        Получение карточки компании с RusProfile.
        """
        url = f"https://www.rusprofile.ru/id/{inn}"

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
                            return self._parse_company_card(html)
                        elif response.status == 429:
                            await asyncio.sleep((attempt + 1) * 2)

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(
                        f"Попытка {attempt + 1}/{self.max_retries} не удалась: {e}"
                    )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2)

        return None

    async def _get_founders(self, inn: str) -> list[PersonInfo]:
        """
        Получение списка учредителей.
        """
        founders = []

        url = f"https://www.rusprofile.ru/id/{inn}"

        headers = self._get_headers()
        headers.update({"Referer": f"https://www.rusprofile.ru/id/{inn}"})

        async with aiohttp.ClientSession() as session:
            for attempt in range(self.max_retries):
                try:
                    async with session.get(
                        f"{url}/founders",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as response:
                        if response.status == 200:
                            html = await response.text()
                            founders = self._parse_founders(html)
                            break
                        elif response.status == 429:
                            await asyncio.sleep((attempt + 1) * 2)

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(
                        f"Попытка {attempt + 1} получения учредителей не удалась: {e}"
                    )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2)

        return founders

    async def _get_director(self, inn: str) -> Optional[PersonInfo]:
        """
        Получение информации о директоре.
        """
        url = f"https://www.rusprofile.ru/id/{inn}"

        headers = self._get_headers()

        async with aiohttp.ClientSession() as session:
            for attempt in range(self.max_retries):
                try:
                    async with session.get(
                        f"{url}/management",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as response:
                        if response.status == 200:
                            html = await response.text()
                            return self._parse_director(html)
                        elif response.status == 429:
                            await asyncio.sleep((attempt + 1) * 2)

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(
                        f"Попытка {attempt + 1} получения директора не удалась: {e}"
                    )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2)

        return None

    def _parse_company_card(self, html: str) -> Optional[CompanyInfo]:
        """Парсинг карточки компании."""
        soup = BeautifulSoup(html, "html.parser")
        info = CompanyInfo(inn="")

        # ИНН
        inn_match = re.search(r"ИНН\s*([\d]+)", html)
        if inn_match:
            info.inn = inn_match.group(1)

        # Полное наименование
        name_match = soup.find("h1")
        if name_match:
            info.full_name = name_match.get_text(strip=True)

        # Краткое наименование
        short_name_match = re.search(
            r"Краткое наименование[:\s]+(.+)",
            html,
        )
        if short_name_match:
            info.short_name = short_name_match.group(1).strip()

        # ОГРН
        ogrn_match = re.search(r"ОГРН\s*([\d]+)", html)
        if ogrn_match:
            info.ogrn = ogrn_match.group(1)

        # КПП
        kpp_match = re.search(r"КПП\s*([\d]+)", html)
        if kpp_match:
            info.kpp = kpp_match.group(1)

        # Статус
        status_keywords = [
            "Действующая",
            "Ликвидирована",
            "В процессе ликвидации",
            "В процессе реорганизации",
            "Банкротство",
        ]
        for kw in status_keywords:
            if kw.lower() in html.lower():
                info.status = kw
                break
        else:
            info.status = "Не определено"

        # Дата регистрации
        reg_match = re.search(
            r"Дата\sрегистра(?:ии|ция)[:\s]+(\d{2}\.\d{2}\.\d{4})",
            html,
        )
        if reg_match:
            info.registration_date = reg_match.group(1)

        # Дата ликвидации
        liq_match = re.search(
            r"Дата\sликвидаци(?:и|я)[:\s]+(\d{2}\.\d{2}\.\d{4})",
            html,
        )
        if liq_match:
            info.liquidation_date = liq_match.group(1)

        # Уставный капитал
        capital_match = re.search(
            r"Уставный\sкапитал[:\s]+([\d\s.,]+)\s*(руб|₽)?",
            html,
            re.I,
        )
        if capital_match:
            info.authorized_capital = capital_match.group(1).strip()

        # Адрес
        address_match = re.search(
            r"Адрес[:\s]+(.+?)(?=\n\n|\nИНН|\nОГРН)",
            html,
            re.S,
        )
        if address_match:
            info.address = address_match.group(1).strip()

        # ОКВЭД
        okved_match = re.search(
            r"Основной\sвид\sдеятельности[:\s]+(.+?)(?=\n\n)",
            html,
        )
        if okved_match:
            okved_text = okved_match.group(1).strip()
            # Извлекаем код и название
            code_match = re.search(r"([\d]+)", okved_text)
            if code_match:
                info.okved = code_match.group(1)
            info.okved_name = re.sub(r"[\d\-]+", "", okved_text).strip()

        # Количество сотрудников
        emp_match = re.search(
            r"Численность\sсотрудников[:\s]+([\d]+)",
            html,
        )
        if emp_match:
            info.employees_count = emp_match.group(1)

        # Количество рисков
        risk_match = re.search(r"(\d+)\s*(риск|проверка)", html, re.I)
        if risk_match:
            info.risks_count = int(risk_match.group(1))

        # Сайт
        site_match = re.search(r"Сайт[:\s]+(https?://[^\s]+)", html)
        if site_match:
            info.website = site_match.group(1)

        return info if info.inn else None

    def _parse_founders(self, html: str) -> list[PersonInfo]:
        """Парсинг списка учредителей."""
        founders = []

        # Ищем блоки с информацией об учредителях
        # Формат может различаться, поэтому ищем по паттернам
        patterns = [
            # Паттерн 1: ФИО + доля
            (
                r"([А-ЯA-Z][а-яёa-z]+\s+[А-ЯA-Z][а-яёa-z]+\s+[А-ЯA-Z][а-яёa-z]+).*?"
                r"(доля[:\s]+([\d.]+)%|участие[:\s]+([\d.]+)%)",
                ["name", None, "share", None],
            ),
            # Паттерн 2: ФИО + должность
            (
                r"([А-ЯA-Z][а-яёa-z]+\s+[А-ЯA-Z][а-яёa-z]+\s+[А-ЯA-Z][а-яёa-z]+)",
                ["name"],
            ),
        ]

        soup = BeautifulSoup(html, "html.parser")
        founder_blocks = soup.find_all(
            ["div", "li", "tr"],
            class_=re.compile(r"founder|partner|учредитель", re.I),
        )

        if founder_blocks:
            for block in founder_blocks:
                text = block.get_text()
                name_match = re.search(
                    r"([А-ЯA-Z][а-яёa-z]+\s+[А-ЯA-Z][а-яёa-z]+\s+[А-ЯA-Z][а-яёa-z]+)",
                    text,
                )
                if name_match:
                    founder = PersonInfo(
                        name=name_match.group(1).strip(),
                        role="учредитель",
                    )
                    # Ищем долю
                    share_match = re.search(
                        r"([\d.]+)\s*%",
                        text,
                    )
                    if share_match:
                        founder.share_percent = share_match.group(1)
                    founders.append(founder)

        # Если не нашли по CSS-классам, парсим по тексту
        if not founders:
            names = re.findall(
                r"([А-ЯA-Z][а-яёa-z]+\s+[А-ЯA-Z][а-яёa-z]+\s+[А-ЯA-Z][а-яёa-z]+)",
                html,
            )
            for name in names[:10]:  # Максимум 10 учредителей
                if name not in ["Россия", "Российской", "Российская"]:
                    founders.append(PersonInfo(name=name, role="учредитель"))

        return founders

    def _parse_director(self, html: str) -> Optional[PersonInfo]:
        """Парсинг информации о директоре."""
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        # Ищем ФИО директора
        name_match = re.search(
            r"([А-ЯA-Z][а-яёa-z]+\s+[А-ЯA-Z][а-яёa-z]+\s+[А-ЯA-Z][а-яёa-z]+)",
            text,
        )

        if name_match:
            director = PersonInfo(
                name=name_match.group(1).strip(),
                role="директор",
                position="Генеральный директор",
            )

            # Ищем ИНН директора
            inn_match = re.search(r"ИНН\s+(\d{10,12})", text)
            if inn_match:
                director.inn = inn_match.group(1)

            return director

        return None

    def _check_capital_risk(self, capital: str) -> Optional[dict]:
        """
        Проверка риска по уставному капиталу.
        Минимальный уставный капитал для ООО — 10 000 руб.
        """
        # Извлекаем число
        amount_match = re.search(r"([\d.,]+)", capital)
        if not amount_match:
            return None

        try:
            amount = float(amount_match.group(1).replace(",", "."))
        except ValueError:
            return None

        # Минимальный уставный капитал для ООО — 10 000 руб.
        if amount < 10_000:
            return {
                "severity": "medium",
                "title": "Нестандартный уставный капитал",
                "description": (
                    f"Уставный капитал {capital} — "
                    "ниже минимального значения для ООО (10 000 руб.). "
                    "Это может указывать на проблемную компанию."
                ),
            }

        # Очень большой уставный капитал тоже подозрителен
        if amount > 1_000_000_000:
            return {
                "severity": "low",
                "title": "Аномально большой уставный капитал",
                "description": (
                    f"Уставный капитал {capital} — "
                    "аномально высокое значение. "
                    "Рекомендуется дополнительная проверка."
                ),
            }

        return None

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
            "Accept-Encoding": "gzip, deflate",
        }
