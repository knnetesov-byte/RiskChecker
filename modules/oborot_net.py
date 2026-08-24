"""
Модуль oborot.net — проверка по данным Росфинмониторинга.
Проверка на внесение в перечень террористов и экстремистов.
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
class RosfinmonitoringData:
    """Данные проверки по Росфинмониторингу."""
    inn: str
    found: bool = False
    in_list: bool = False
    list_type: str = ""
    list_date: str = ""
    decision_number: str = ""
    decision_date: str = ""
    risks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@dataclass
class OborotData:
    """Данные проверки оборота."""
    inn: str
    found: bool = False
    is_suspicious: bool = False
    suspicious_reasons: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@dataclass
class OborotNetResult:
    """Результат проверки oborot.net."""
    inn: str
    found: bool = False
    in_rfm_list: bool = False
    rfm_list_type: str = ""
    rfm_decision_number: str = ""
    rfm_decision_date: str = ""
    suspicious_activities: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class OborotNetChecker:
    """Проверка через oborot.net — данные Росфинмониторинга."""

    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = "https://oborot.net"

    async def check(self, inn: str) -> OborotNetResult:
        """
        Проверяет компанию по ИНН в базах Росфинмониторинга.

        Args:
            inn: ИНН юридического лица

        Returns:
            OborotNetResult с результатами проверки
        """
        result = OborotNetResult(inn=inn)

        try:
            # Проверка 1: Росфинмониторинг
            rfm_data = await self._check_rfm(inn)
            if rfm_data:
                result.found = True
                result.in_rfm_list = rfm_data.in_list
                result.rfm_list_type = rfm_data.list_type
                result.rfm_decision_number = rfm_data.decision_number
                result.rfm_decision_date = rfm_data.decision_date

                if rfm_data.in_list:
                    result.risks.append({
                        "severity": "critical",
                        "title": "Компания в списке Росфинмониторинга",
                        "description": (
                            f"Обнаружено внесение в перечень. "
                            f"Тип: {rfm_data.list_type}. "
                            f"Решение №: {rfm_data.decision_number}"
                        ),
                    })

                result.warnings.extend(rfm_data.warnings)

            # Проверка 2: Подозрительные операции
            oborot_data = await self._check_oborot(inn)
            if oborot_data:
                result.found = True
                if oborot_data.is_suspicious:
                    result.suspicious_activities.extend(
                        oborot_data.suspicious_reasons
                    )
                    result.risks.append({
                        "severity": "high",
                        "title": "Подозрительная активность",
                        "description": (
                            f"Обнаружены подозрительные паттерны: "
                            f"{', '.join(oborot_data.suspicious_reasons[:3])}"
                        ),
                    })
                result.warnings.extend(oborot_data.warnings)

            if not result.found:
                result.warnings.append(
                    "Подозрительная информация не обнаружена. "
                    "Это положительный фактор."
                )

        except asyncio.TimeoutError:
            result.warnings.append(
                "Превышено время ожидания ответа от oborot.net."
            )
        except Exception as e:
            logger.error(
                f"Ошибка при проверке oborot.net для ИНН {inn}: {e}",
                exc_info=True,
            )
            result.warnings.append(
                f"Ошибка при запросе к oborot.net: {str(e)}"
            )

        return result

    async def _check_rfm(self, inn: str) -> Optional[RosfinmonitoringData]:
        """
        Проверка по базам Росфинмониторинга.
        """
        result = RosfinmonitoringData(inn=inn)

        # Источники данных Росфинмониторинга:
        # 1. Перечень террористов
        # 2. Перечень экстремистов
        # 3. Перечень организаций (финансирование терроризма)
        # 4. Перечень граждан РФ (терроризм/экстремизм)
        # 5. Перечень иностранных лиц

        sources = [
            ("terrorists", "Перечень террористов"),
            ("extremists", "Перечень экстремистов"),
            ("organizations", "Перечень организаций"),
            ("citizens", "Перечень граждан РФ"),
        ]

        async with aiohttp.ClientSession() as session:
            for source_key, source_name in sources:
                url = (
                    f"https://oborot.net/search?q={inn}"
                    f"&type={source_key}"
                )

                headers = self._get_headers()

                for attempt in range(self.max_retries):
                    try:
                        async with session.get(
                            url,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=self.timeout),
                        ) as response:
                            if response.status == 200:
                                html = await response.text()
                                found = self._parse_rfm_results(
                                    html, inn, source_name, result
                                )
                                if found:
                                    return result
                            elif response.status == 429:
                                await asyncio.sleep((attempt + 1) * 2)

                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        logger.warning(
                            f"Попытка {attempt + 1}/{self.max_retries} не удалась: {e}"
                        )
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep(2)

        return None

    async def _check_oborot(self, inn: str) -> Optional[OborotData]:
        """
        Проверка подозрительных операций.
        """
        result = OborotData(inn=inn)

        # Анализируем подозрительные паттерны:
        # 1. Частая смена руководства
        # 2. Типовые адреса
        # 3. Масовые директоры
        # 4. Нестандартные операции

        url = f"https://oborot.net/search?q={inn}"
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
                            result.found = True
                            result.suspicious_reasons = (
                                self._analyze_suspicious_patterns(html, inn)
                            )
                            if result.suspicious_reasons:
                                result.is_suspicious = True
                            break
                        elif response.status == 429:
                            await asyncio.sleep((attempt + 1) * 2)

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(
                        f"Попытка {attempt + 1}/{self.max_retries} не удалась: {e}"
                    )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2)

        return result if result.found else None

    def _parse_rfm_results(
        self, html: str, inn: str, source_name: str,
        result: RosfinmonitoringData,
    ) -> bool:
        """Парсинг результатов Росфинмониторинга."""
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        # Ищем ИНН в результатах
        if inn not in text:
            return False

        result.found = True
        result.in_list = True
        result.list_type = source_name

        # Ищем номер решения
        decision_match = re.search(
            r"решение\s*[:\s]*(№?\s*[А-ЯA-Z0-9\-]+)",
            text,
            re.I,
        )
        if decision_match:
            result.decision_number = decision_match.group(1).strip()

        # Ищем дату
        date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
        if date_match:
            result.decision_date = date_match.group(1)

        return True

    def _analyze_suspicious_patterns(
        self, html: str, inn: str
    ) -> list[str]:
        """Анализ подозрительных паттернов."""
        suspicious = []
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text().lower()

        # Паттерн 1: Масовый директор
        if "массовый директор" in text or "массовый учредитель" in text:
            suspicious.append(
                "Обнаружен признак массового директора/учредителя"
            )

        # Паттерн 2: Типовой адрес
        if "типовой адрес" in text or "адрес массового пребывания" in text:
            suspicious.append("Использован типовой адрес регистрации")

        # Паттерн 3: Частая смена руководства
        if (
            "смена директора" in text
            or "смена руководителя" in text
            or "частая смена" in text
        ):
            suspicious.append("Обнаружена частая смена руководства")

        # Паттерн 4: Неактивная компания
        if "ликвидирован" in text or "в процессе ликвидации" in text:
            suspicious.append("Компания в процессе ликвидации")

        # Паттерн 5: Недобросовестный налогоплательщик
        if "ндфл" in text or "недобросовестный налогоплательщик" in text:
            suspicious.append("Признаки недобросовестного налогоплательщика")

        return suspicious

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
