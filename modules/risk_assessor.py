"""
Модуль оценки рисков.
Агрегирует данные из всех источников и формирует итоговую оценку.
"""

import logging
from typing import Optional
from dataclasses import dataclass, field

from src.modules.fedresurs import BankruptcyData
from src.modules.court_checker import CourtData
from src.modules.oborot_net import OborotNetResult
from src.modules.rusprofile import RusProfileData

logger = logging.getLogger(__name__)


@dataclass
class RiskAssessment:
    """Итоговая оценка рисков."""
    inn: str
    overall_risk: str = ""  # критический, высокий, средний, низкий, минимальный
    risk_score: int = 0  # 0-100
    company_status: str = ""
    company_age_years: str = ""
    authorized_capital: str = ""
    risks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    summary: str = ""


class RiskAssessor:
    """
    Модуль комплексной оценки рисков.
    Анализирует данные из всех источников и формирует итоговую оценку.
    """

    # Вес каждого источника
    WEIGHTS = {
        "bankruptcy": 30,  # банкротство — самый критичный фактор
        "courts": 25,  # судебные дела
        "oborot": 20,  # росфинмониторинг
        "rusprofile": 15,  # общие риски
        "general": 10,  # общая оценка
    }

    # Баллы заSeverity
    SEVERITY_SCORES = {
        "critical": 25,
        "high": 15,
        "medium": 8,
        "low": 3,
    }

    def assess(
        self,
        inn: str,
        bankruptcy: Optional[BankruptcyData] = None,
        courts: Optional[CourtData] = None,
        oborot: Optional[OborotNetResult] = None,
        rusprofile: Optional[RusProfileData] = None,
    ) -> RiskAssessment:
        """
        Комплексная оценка рисков по всем источникам.

        Args:
            inn: ИНН компании
            bankruptcy: Данные из Fedresurs
            courts: Данные из kad.arbitr.ru
            oborot: Данные из oborot.net
            rusprofile: Данные из RusProfile

        Returns:
            RiskAssessment с итоговой оценкой
        """
        assessment = RiskAssessment(inn=inn)

        all_risks = []
        all_warnings = []

        # 1. Оценка банкротства
        if bankruptcy:
            self._assess_bankruptcy_risks(bankruptcy, all_risks, all_warnings)
            assessment.company_status = bankruptcy.bankruptcy_status

        # 2. Оценка судебных дел
        if courts:
            self._assess_court_risks(courts, all_risks, all_warnings)
            if not assessment.company_status:
                assessment.company_status = "Информация недостаточна"

        # 3. Оценка оборота
        if oborot:
            self._assess_oborot_risks(oborot, all_risks, all_warnings)

        # 4. Оценка RusProfile
        if rusprofile:
            self._assess_rusprofile_risks(rusprofile, all_risks, all_warnings)
            if rusprofile.company:
                assessment.authorized_capital = rusprofile.company.authorized_capital
                if not assessment.company_status:
                    assessment.company_status = rusprofile.company.status

        # 5. Общая оценка
        self._calculate_overall_risk(assessment, all_risks)

        # 6. Добавляем все риски и предупреждения
        assessment.risks = all_risks
        assessment.warnings = all_warnings

        # 7. Формируем рекомендации
        self._generate_recommendations(assessment)

        # 8. Формируем итоговое описание
        self._generate_summary(assessment)

        return assessment

    def _assess_bankruptcy_risks(
        self,
        data: BankruptcyData,
        risks: list,
        warnings: list,
    ):
        """Оценка рисков банкротства."""
        if data.is_bankrupt:
            risks.append({
                "severity": "critical",
                "source": "Fedresurs",
                "title": "Компания в процессе банкротства",
                "description": (
                    f"Обнаружено дело о банкротстве "
                    f"(№ {data.case_number}). "
                    f"Статус: {data.case_status}. "
                    f"Арбитражный управляющий: {data.arbitration_manager}"
                ),
            })

        # Риск: длительное банкротство
        for risk in data.risks:
            risk["source"] = "Fedresurs"
            risks.append(risk)

        # Предупреждения
        warnings.extend(data.warnings)

    def _assess_court_risks(
        self,
        data: CourtData,
        risks: list,
        warnings: list,
    ):
        """Оценка судебных рисков."""
        if data.lost_cases > 5:
            risks.append({
                "severity": "critical",
                "source": "kad.arbitr.ru",
                "title": "Критическое количество проигранных дел",
                "description": (
                    f"Компания проиграла {data.lost_cases} из "
                    f"{data.total_cases} дел. "
                    f"Общая сумма исков: {data.total_amount}"
                ),
            })
        elif data.lost_cases > 2:
            risks.append({
                "severity": "high",
                "source": "kad.arbitr.ru",
                "title": "Несколько проигранных дел",
                "description": (
                    f"Компания проиграла {data.lost_cases} из "
                    f"{data.total_cases} дел. "
                    f"Общая сумма исков: {data.total_amount}"
                ),
            })
        elif data.lost_cases > 0:
            risks.append({
                "severity": "medium",
                "source": "kad.arbitr.ru",
                "title": "Есть проигранные дела",
                "description": (
                    f"Компания проиграла {data.lost_cases} из "
                    f"{data.total_cases} дел."
                ),
            })

        # Активные дела
        if data.active_cases > 5:
            risks.append({
                "severity": "high",
                "source": "kad.arbitr.ru",
                "title": "Много активных судебных дел",
                "description": (
                    f"В настоящее время рассматривается "
                    f"{data.active_cases} дел."
                ),
            })

        # Предупреждения
        warnings.extend(data.warnings)

    def _assess_oborot_risks(
        self,
        data: OborotNetResult,
        risks: list,
        warnings: list,
    ):
        """Оценка рисков по данным oborot.net."""
        if data.in_rfm_list:
            risks.append({
                "severity": "critical",
                "source": "oborot.net",
                "title": "Компания в списке Росфинмониторинга",
                "description": (
                    f"Обнаружено внесение в перечень: "
                    f"{data.rfm_list_type}. "
                    f"Решение №: {data.rfm_decision_number}"
                ),
            })

        if data.suspicious_activities:
            risks.append({
                "severity": "high",
                "source": "oborot.net",
                "title": "Подозрительная активность",
                "description": (
                    f"Обнаружены подозрительные паттерны: "
                    f"{'; '.join(data.suspicious_activities[:3])}"
                ),
            })

        warnings.extend(data.warnings)

    def _assess_rusprofile_risks(
        self,
        data: RusProfileData,
        risks: list,
        warnings: list,
    ):
        """Оценка рисков по данным RusProfile."""
        if data.company:
            # Статус компании
            if data.company.status in [
                "Ликвидирована",
                "В процессе ликвидации",
            ]:
                risks.append({
                    "severity": "critical",
                    "source": "RusProfile",
                    "title": "Компания недействующая",
                    "description": (
                        f"Статус компании: {data.company.status}. "
                        "Работа с такой компанией не рекомендуется."
                    ),
                })

            # Возраст компании
            if data.company.registration_date:
                try:
                    from datetime import datetime
                    reg_date = datetime.strptime(
                        data.company.registration_date, "%d.%m.%Y"
                    )
                    age_days = (datetime.now() - reg_date).days
                    age_years = age_days / 365.25

                    if age_years < 1:
                        risks.append({
                            "severity": "medium",
                            "source": "RusProfile",
                            "title": "Новая компания",
                            "description": (
                                f"Компания зарегистрирована менее года назад "
                                f"({age_days} дней). "
                                "Высокий риск недобросовестности."
                            ),
                        })
                        assessment.company_age_years = f"< 1 года ({age_days} дней)"
                    elif age_years < 3:
                        risks.append({
                            "severity": "low",
                            "source": "RusProfile",
                            "title": "Небольшой возраст компании",
                            "description": (
                                f"Компания работает менее 3 лет "
                                f"({age_days} дней)."
                            ),
                        })
                        assessment.company_age_years = f"{age_years:.1f} года"
                    else:
                        assessment.company_age_years = f"{age_years:.1f} года"

                except (ValueError, TypeError):
                    pass

            # Количество сотрудников
            if data.company.employees_count:
                try:
                    emp_count = int(data.company.employees_count)
                    if emp_count == 0:
                        risks.append({
                            "severity": "medium",
                            "source": "RusProfile",
                            "title": "Нет сотрудников",
                            "description": (
                                "Компания не имеет сотрудников. "
                                "Возможна компания-однодневка."
                            ),
                        })
                except ValueError:
                    pass

            # Количество рисков на RusProfile
            if data.company.risks_count > 10:
                risks.append({
                    "severity": "high",
                    "source": "RusProfile",
                    "title": "Много рисков на RusProfile",
                    "description": (
                        f"На сайте RusProfile обнаружено "
                        f"{data.company.risks_count} рисков."
                    ),
                })

        # Предупреждения
        warnings.extend(data.warnings)

    def _calculate_overall_risk(
        self,
        assessment: RiskAssessment,
        risks: list,
    ):
        """Расчёт общей оценки риска."""
        if not risks:
            assessment.overall_risk = "минимальный"
            assessment.risk_score = 5
            return

        # Считаем баллы
        total_score = 0
        max_possible = 100

        for risk in risks:
            severity = risk.get("severity", "low")
            total_score += self.SEVERITY_SCORES.get(severity, 3)

        # Нормализуем до 100
        risk_score = min(total_score, max_possible)
        assessment.risk_score = risk_score

        # Определяем уровень риска
        if risk_score >= 75:
            assessment.overall_risk = "критический"
        elif risk_score >= 50:
            assessment.overall_risk = "высокий"
        elif risk_score >= 25:
            assessment.overall_risk = "средний"
        elif risk_score > 0:
            assessment.overall_risk = "низкий"
        else:
            assessment.overall_risk = "минимальный"

    def _generate_recommendations(self, assessment: RiskAssessment):
        """Формирование рекомендаций."""
        recommendations = []

        if assessment.overall_risk == "критический":
            recommendations.append(
                "⛔ НЕ РЕКОМЕНДУЕТСЯ работать с данной компанией. "
                "Обнаружены критические риски."
            )
            recommendations.append(
                "Рекомендуется провести дополнительноеdue diligence "
                "через платные сервисы (Контур.Фокус, СПАРК)."
            )
            recommendations.append(
                "Рассмотрите альтернативных контрагентов."
            )

        elif assessment.overall_risk == "высокий":
            recommendations.append(
                "⚠️ С осторожностью. Рекомендуется дополнительная проверка."
            )
            recommendations.append(
                "Проведите проверку через платные сервисы "
                "(Контур.Фокус, СПАРК, СБисконт)."
            )
            recommendations.append(
                "Требуйте дополнительные гарантии при работе."
            )

        elif assessment.overall_risk == "средний":
            recommendations.append(
                "⚡ Стандартный уровень риска. "
                "Рекомендуется стандартная процедура проверки контрагента."
            )
            recommendations.append(
                "Проверьте актуальность документов перед сделкой."
            )

        else:
            recommendations.append(
                "✅ Компания имеет низкий уровень риска. "
                "Можно работать в стандартном режиме."
            )
            recommendations.append(
                "Всё равно рекомендуется стандартная проверка документов."
            )

        # Дополнительные рекомендации
        if assessment.authorized_capital:
            try:
                cap = float(
                    assessment.authorized_capital.replace(
                        ",", "."
                    ).replace(" ", "")
                )
                if cap < 100_000:
                    recommendations.append(
                        "⚠️ Низкий уставный капитал. "
                        "Компания может быть финансово нестабильна."
                    )
            except ValueError:
                pass

        assessment.recommendations = recommendations

    def _generate_summary(self, assessment: RiskAssessment):
        """Формирование итогового описания."""
        parts = []

        parts.append(
            f"📊 Оценка риска: **{assessment.overall_risk.upper()}** "
            f"(балл: {assessment.risk_score}/100)"
        )

        if assessment.company_status:
            parts.append(f"📋 Статус: {assessment.company_status}")

        if assessment.company_age_years:
            parts.append(f"📅 Возраст: {assessment.company_age_years}")

        if assessment.authorized_capital:
            parts.append(
                f"💰 Уставный капитал: {assessment.authorized_capital}"
            )

        risk_count = len(assessment.risks)
        critical_count = sum(
            1 for r in assessment.risks if r.get("severity") == "critical"
        )

        if critical_count > 0:
            parts.append(
                f"🔴 Критических рисков: {critical_count}"
            )
        if risk_count > 0:
            parts.append(f"⚡ Всего рисков: {risk_count}")

        assessment.summary = " | ".join(parts)
