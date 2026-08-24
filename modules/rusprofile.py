"""
import os
import logging
import aiohttp
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class RusProfileData:
    """Класс для хранения данных о компании."""
    def __init__(self, data: dict):
        self.full_name = data.get('full_name')
        self.short_name = data.get('short_name')
        self.inn = data.get('inn')
        self.ogrn = data.get('ogrn')
        self.address = data.get('address')
        self.director_name = data.get('director_name')
        self.state = data.get('state')
        self.authorized_capital = data.get('authorized_capital')
        self.registration_date = data.get('registration_date')
        self.liquidation_date = data.get('liquidation_date')
        self.okved = data.get('okved')

class RusProfileChecker:
    """Проверка данных о компании через Checko.ru."""

    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = "https://checko.ru"

    async def check(self, inn: str) -> RusProfileData:
        """
        Получение данных о компании по ИНН из Checko.ru.
        Возвращает объект RusProfileData.
        """
        try:
            url = f"{self.base_url}/inn/{inn}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
            }

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"Checko.ru вернул статус {response.status} для ИНН {inn}")
                        return RusProfileData({})

                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    # Извлекаем данные
                    data = {}

                    # Название компании
                    name_block = soup.find('h1', itemprop='name')
                    if name_block:
                        data['full_name'] = name_block.text.strip()
                        data['short_name'] = name_block.text.strip()

                    # ИНН
                    inn_block = soup.find('td', string='ИНН')
                    if inn_block:
                        next_td = inn_block.find_next('td')
                        if next_td:
                            data['inn'] = next_td.text.strip()

                    # ОГРН
                    ogrn_block = soup.find('td', string='ОГРН')
                    if ogrn_block:
                        next_td = ogrn_block.find_next('td')
                        if next_td:
                            data['ogrn'] = next_td.text.strip()

                    # Статус
                    status_block = soup.find('td', string='Статус')
                    if status_block:
                        next_td = status_block.find_next('td')
                        if next_td:
                            data['state'] = next_td.text.strip()

                    # Адрес
                    address_block = soup.find('td', string='Юридический адрес')
                    if address_block:
                        next_td = address_block.find_next('td')
                        if next_td:
                            data['address'] = next_td.text.strip()

                    # Директор
                    director_block = soup.find('td', string='Руководитель')
                    if director_block:
                        next_td = director_block.find_next('td')
                        if next_td:
                            data['director_name'] = next_td.text.strip()

                    # Уставный капитал
                    capital_block = soup.find('td', string='Уставный капитал')
                    if capital_block:
                        next_td = capital_block.find_next('td')
                        if next_td:
                            data['authorized_capital'] = next_td.text.strip()

                    # Дата регистрации
                    reg_date_block = soup.find('td', string='Дата регистрации')
                    if reg_date_block:
                        next_td = reg_date_block.find_next('td')
                        if next_td:
                            data['registration_date'] = next_td.text.strip()

                    logger.info(f"Успешно получены данные с Checko.ru для ИНН {inn}")
                    return RusProfileData(data)

        except Exception as e:
            logger.error(f"Ошибка при парсинге Checko.ru для ИНН {inn}: {e}")
            return RusProfileData({})
        }
