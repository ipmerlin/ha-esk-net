"""Maintain complete standalone custom-integration translations."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components/esk_net"


def translation(ru):
    names = (
        [
            "Баланс",
            "Дней до блокировки",
            "Тариф",
            "Стоимость тарифа в месяц",
            "Лицевой счёт",
            "Полная стоимость в месяц",
            "Активированные услуги",
        ]
        if ru
        else [
            "Balance",
            "Days until blocking",
            "Tariff",
            "Monthly tariff price",
            "Account number",
            "Total monthly price",
            "Active services",
        ]
    )
    credentials = {
        "username": "Логин" if ru else "Username",
        "password": "Пароль" if ru else "Password",
    }
    return {
        "title": "ЕСК — личный кабинет" if ru else "ESK Net",
        "config": {
            "step": {
                "user": {
                    "title": "Личный кабинет ЕСК" if ru else "ESK personal cabinet",
                    "description": "Введите данные для входа на lk.esknet.net."
                    if ru
                    else "Enter your lk.esknet.net credentials.",
                    "data": credentials,
                },
                "reauth_confirm": {
                    "title": "Повторная авторизация ЕСК" if ru else "Reauthenticate ESK",
                    "description": "Введите актуальные данные того же лицевого счёта."
                    if ru
                    else "Enter current credentials for the same account.",
                    "data": credentials,
                },
            },
            "error": {
                "invalid_auth": "Не удалось войти. Проверьте логин и пароль."
                if ru
                else "Authentication failed. Check your username and password.",
                "cannot_connect": "Личный кабинет недоступен. Повторите позже."
                if ru
                else "Cannot connect to the cabinet. Try again later.",
                "cannot_parse": "Не удалось распознать страницу ЛК. Возможно, сайт изменился или проверка сайта не завершилась."
                if ru
                else "Cannot parse the cabinet. The layout may have changed or the site challenge was not resolved.",
            },
            "abort": {
                "already_configured": "Этот лицевой счёт уже добавлен."
                if ru
                else "This account is already configured.",
                "reauth_successful": "Учётные данные обновлены."
                if ru
                else "Credentials updated successfully.",
                "unique_id_mismatch": "Эти данные относятся к другому лицевому счёту."
                if ru
                else "These credentials belong to a different account.",
            },
        },
        "options": {
            "step": {
                "init": {
                    "title": "Параметры обновления" if ru else "Update settings",
                    "description": "Интервал от 30 до 1440 минут. По умолчанию — 240 минут."
                    if ru
                    else "Interval from 30 to 1440 minutes. Default: 240 minutes.",
                    "data": {
                        "update_interval": "Интервал обновления (минуты)"
                        if ru
                        else "Update interval (minutes)"
                    },
                }
            }
        },
        "entity": {
            "sensor": {
                key: {"name": name}
                for key, name in zip(
                    (
                        "balance",
                        "days_left",
                        "tariff",
                        "tariff_price",
                        "account",
                        "total_monthly_price",
                        "active_services",
                    ),
                    names,
                    strict=True,
                )
            }
        },
    }


if __name__ == "__main__":
    (ROOT / "translations").mkdir(exist_ok=True)
    for filename, ru in (
        ("strings.json", False),
        ("translations/en.json", False),
        ("translations/ru.json", True),
    ):
        (ROOT / filename).write_text(
            json.dumps(translation(ru), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
