"""
Модуль для формирования отчётов.
Генерирует текстовые отчёты для отображения в Telegram.
"""

from typing import Optional
from datetime import datetime

from src.modules.fedresurs import BankruptcyData
from src.modules.court_checker import CourtData
from src.modules.oborot_net import OborotNetResult
from src.modules.rusprofile import RusProfileData
from src.modules.risk_assessor import RiskAssessment


def format_full_report(
    inn: str,
    risk_assessment: RiskAssessment,
    bankruptcy: Optional[BankruptcyData] = None,
    courts: Optional[CourtData] = None,
    oborot: Optional[OborotNetResult] = None,
    rusprofile: Optional[RusProfileData] = None,
) -> str:
    """
    Формирует полный текстовый отчёт для отображения в Telegram.

    Args:
        inn: ИНН компании
        risk_assessment: Итоговая оценка рисков
        bankruptcy: Данные из Fedresurs
        courts: Данные из kad.arbitr.ru
        oborot: Данные из oborot.net
        rusprofile: Данные из RusProfile

    Returns:
        Отформатированный текст отчёта
    """
    report_lines = []

    # Заголовок
    report_lines.append("🔍 **ПРОВЕРКА ПО ИНН: {}**".format(inn))
    report_lines.append(f"📅 Дата проверки: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    report_lines.append("")

    # Итоговая оценка
    report_lines.append("📊 **ОЦЕНКА РИСКОВ**")
    report_lines.append(f"   {risk_assessment.summary}")
    report_lines.append("")

    # 1. Основная информация о компании
    if rusprofile and rusprofile.company:
        company = rusprofile.company
        report_lines.append("🏢 **ИНФОРМАЦИЯ О КОМПАНИИ**")
        if company.full_name:
            report_lines.append(f"   📌 Полное наименование: {company.full_name}")
        if company.short_name:
            report_lines.append(f"   📌 Краткое наименование: {company.short_name}")
        if company.ogrn:
            report_lines.append(f"   🔢 ОГРН: {company.ogrn}")
        if company.kpp:
            report_lines.append(f"   🔢 КПП: {company.kpp}")
        if company.registration_date:
            report_lines.append(
                f"   📅 Дата регистрации: {company.registration_date}"
            )
        if company.liquidation_date:
            report_lines.append(
                f"   ⚠️ Дата ликвидации: {company.liquidation_date}"
            )
        report_lines.append(f"   📋 Статус: {company.status}")
        if company.address:
            report_lines.append(f"   📍 Адрес: {company.address}")
        if company.okved:
            report_lines.append(
                f"   🏭 ОКВЭД: {company.okved} - {company.okved_name}"
            )
        if company.employees_count:
            report_lines.append(
                f"   👥 Сотрудники: {company.employees_count} чел."
            )
        if company.website:
            report_lines.append(f"   🌐 Сайт: {company.website}")
        report_lines.append("")

        # Уставный капитал
        if company.authorized_capital:
            report_lines.append(
                f"💰 **УСТАВНЫЙ КАПИТАЛ:** {company.authorized_capital}"
            )
            report_lines.append("")

    # 2. Учредители и руководство
    if rusprofile and rusprofile.founders:
        report_lines.append("👥 **УЧРЕДИТЕЛИ**")
        for i, founder in enumerate(rusprofile.founders, 1):
            line = f"   {i}. {founder.name}"
            if founder.share_percent:
                line += f" (доля: {founder.share_percent}%)"
            if founder.inn:
                line += f" (ИНН: {founder.inn})"
            report_lines.append(line)
        report_lines.append("")

    if rusprofile and rusprofile.director:
        director = rusprofile.director
        report_lines.append("👔 **РУКОВОДСТВО**")
        report_lines.append(
            f"   📌 {director.name}"
        )
        if director.position:
            report_lines.append(
                f"   📋 Должность: {director.position}"
            )
        if director.inn:
            report_lines.append(
                f"   🔢 ИНН: {director.inn}"
            )
        report_lines.append("")

    # 3. Банкротство
    if bankruptcy:
        report_lines.append("⚖️ **ПРОВЕРКА ПО БАНКРОВСТВУ (Fedresurs)**")
        if bankruptcy.is_bankrupt:
            report_lines.append(
                "   🔴 **ВНИМАНИЕ: Компания в процессе банкротства!**"
            )
            if bankruptcy.case_number:
                report_lines.append(
                    f"   📋 Номер дела: {bankruptcy.case_number}"
                )
            if bankruptcy.case_status:
                report_lines.append(
                    f"   📊 Статус: {bankruptcy.case_status}"
                )
            if bankruptcy.arbitration_manager:
                report_lines.append(
                    f"   👤 Арбитражный управляющий: {bankruptcy.arbitration_manager}"
                )
            if bankruptcy.registration_date:
                report_lines.append(
                    f"   📅 Дата регистрации: {bankruptcy.registration_date}"
                )
            if bankruptcy.court:
                report_lines.append(
                    f"   🏛 Суд: {bankruptcy.court}"
                )
        else:
            report_lines.append(
                "   🟢 Банкротство не обнаружено"
            )
        report_lines.append("")

    # 4. Судебные дела
    if courts:
        report_lines.append("⚖️ **СУДЕБНЫЕ ДЕЛА (kad.arbitr.ru)**")
        report_lines.append(
            f"   📊 Всего дел: {courts.total_cases}"
        )
        report_lines.append(
            f"   🟡 Активных дел: {courts.active_cases}"
        )
        if courts.lost_cases > 0:
            report_lines.append(
                f"   🔴 Проигранных дел: {courts.lost_cases}"
            )
        if courts.total_amount:
            report_lines.append(
                f"   💰 Общая сумма исков: {courts.total_amount}"
            )
        report_lines.append("")

        # Последние дела
        if courts.cases:
            report_lines.append("   **Последние дела:**")
            for i, case in enumerate(courts.cases[:10], 1):
                line = f"   {i}. №{case.case_number}"
                if case.case_status:
                    line += f" — {case.case_status}"
                if case.amount:
                    line += f" (сумма: {case.amount})"
                report_lines.append(line)
            report_lines.append("")

    # 5. Росфинмониторинг
    if oborot:
        report_lines.append("🔐 **ПРОВЕРКА ПО РОСФИНАТОРИНГУ (oborot.net)**")
        if oborot.in_rfm_list:
            report_lines.append(
                "   🔴 **ВНИМАНИЕ: Компания в списке Росфинмониторинга!**"
            )
            if oborot.rfm_list_type:
                report_lines.append(
                    f"   📋 Тип: {oborot.rfm_list_type}"
                )
            if oborot.rfm_decision_number:
                report_lines.append(
                    f"   📄 Решение №: {oborot.rfm_decision_number}"
                )
        elif oborot.suspicious_activities:
            report_lines.append(
                "   🟡 Обнаружены подозрительные активности:"
            )
            for activity in oborot.suspicious_activities:
                report_lines.append(f"   - {activity}")
        else:
            report_lines.append(
                "   🟢 Подозрительная информация не обнаружена"
            )
        report_lines.append("")

    # 6. Риски
    if risk_assessment.risks:
        report_lines.append("⚠️ **ОБНАРУЖЕННЫЕ РИСКИ**")
        for i, risk in enumerate(risk_assessment.risks, 1):
            severity_icon = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🟢",
            }.get(risk.get("severity", "low"), "⚪")

            source = risk.get("source", "")
            source_str = f" ({source})" if source else ""

            report_lines.append(
                f"   {severity_icon} **{risk['title']}**{source_str}"
            )
            if risk.get("description"):
                report_lines.append(
                    f"      {risk['description']}"
                )
        report_lines.append("")

    # 7. Рекомендации
    if risk_assessment.recommendations:
        report_lines.append("💡 **РЕКОМЕНДАЦИИ**")
        for rec in risk_assessment.recommendations:
            report_lines.append(f"   • {rec}")
        report_lines.append("")

    # 8. Предупреждения
    if risk_assessment.warnings:
        report_lines.append("📝 **ПРЕДУПРЕЖДЕНИЯ**")
        for warning in risk_assessment.warnings:
            report_lines.append(f"   • {warning}")
        report_lines.append("")

    # Подвал
    report_lines.append("_Отчёт сгенерирован ботом проверки контрагентов_")

    return "\n".join(report_lines)


def format_short_status(
    inn: str,
    risk_assessment: RiskAssessment,
) -> str:
    """
    Формирует краткий статус для отображения в процессе проверки.
    """
    status_icon = {
        "критический": "🔴",
        "высокий": "🟠",
        "средний": "🟡",
        "низкий": "🟢",
        "минимальный": "✅",
    }.get(risk_assessment.overall_risk, "⚪")

    return (
        f"{status_icon} ИНН: {inn} | "
        f"Риск: {risk_assessment.overall_risk.upper()} | "
        f"Балл: {risk_assessment.risk_score}/100"
    )
