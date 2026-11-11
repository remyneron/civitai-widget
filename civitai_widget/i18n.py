"""Minimal two-language UI strings (English / Russian)."""

from __future__ import annotations

import os

_STRINGS: dict[str, tuple[str, str]] = {
    # key: (en, ru)
    "app_name": ("Civitai Widget", "Civitai Widget"),
    "pause": ("Pause", "Пауза"),
    "resume": ("Resume", "Продолжить"),
    "next_page": ("Next page", "Следующая страница"),
    "prev_page": ("Previous page", "Предыдущая страница"),
    "interval": ("Page interval", "Интервал смены"),
    "seconds": ("{n} s", "{n} с"),
    "period": ("Period", "Период"),
    "period_Day": ("Day", "День"),
    "period_Week": ("Week", "Неделя"),
    "period_Month": ("Month", "Месяц"),
    "period_Year": ("Year", "Год"),
    "period_AllTime": ("All time", "Всё время"),
    "title_Day": ("Top of the day", "Топ дня"),
    "title_Week": ("Top of the week", "Топ недели"),
    "title_Month": ("Top of the month", "Топ месяца"),
    "title_Year": ("Top of the year", "Топ года"),
    "title_AllTime": ("All-time top", "Топ за всё время"),
    "sort": ("Sort by", "Сортировка"),
    "sort_Most Reactions": ("Most reactions", "По реакциям"),
    "sort_Most Comments": ("Most comments", "По комментариям"),
    "sort_Most Collected": ("Most collected", "По добавлениям в коллекции"),
    "sort_Newest": ("Newest", "Сначала новые"),
    "base_model": ("Base model", "Базовая модель"),
    "all_models": ("All models", "Все модели"),
    "next_batch": ("Load next batch", "Загрузить следующие работы"),
    "refresh": ("Refresh", "Обновить"),
    "always_on_top": ("Always on top", "Поверх всех окон"),
    "zen": ("Zen mode", "Режим Zen"),
    "exit_zen": ("Show controls (Esc)", "Показать панель (Esc)"),
    "autostart": ("Start on login", "Запускать при входе в систему"),
    "nsfw": ("Show NSFW content", "Показывать NSFW"),
    "nsfw_confirm_title": ("Enable NSFW content?", "Включить NSFW-контент?"),
    "nsfw_confirm_text": (
        "The widget will show adult content on your desktop. The choice is remembered between launches.",
        "Виджет начнёт показывать на рабочем столе контент для взрослых. Выбор сохранится между запусками.",
    ),
    "enable": ("Enable", "Включить"),
    "cancel": ("Cancel", "Отмена"),
    "menu": ("Menu", "Меню"),
    "quit": ("Quit", "Выход"),
    "show_widget": ("Show widget", "Показать виджет"),
    "hide_widget": ("Hide widget", "Скрыть виджет"),
    "loading": ("Loading images…", "Загружаем работы…"),
    "updating": ("Updating…", "Обновляем…"),
    "empty": ("Nothing found for these filters.", "По этим фильтрам ничего не найдено."),
    "retry": ("Try again", "Повторить"),
    "offline_cache": (
        "Civitai is unreachable — showing saved images",
        "Нет связи с Civitai — показаны сохранённые работы",
    ),
    "no_more": ("No more images in this selection", "В этой подборке больше нет работ"),
    "batch": ("batch {n}", "порция {n}"),
    "err_network": ("Cannot reach Civitai. Check your connection.", "Не удалось связаться с Civitai. Проверьте соединение."),
    "err_http": ("Civitai returned an error (HTTP {code}).", "Civitai вернул ошибку (HTTP {code})."),
    "err_rate_limited": ("Too many requests to Civitai. Try again later.", "Слишком много запросов к Civitai. Попробуйте позже."),
    "err_bad_response": ("Civitai returned an unexpected response.", "Civitai вернул неожиданный ответ."),
}


def _detect_russian() -> bool:
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return value.lower().startswith("ru")
    return False


_RU = _detect_russian()


def set_language(code: str) -> None:
    global _RU
    _RU = code.lower().startswith("ru")


def tr(key: str, **fmt) -> str:
    pair = _STRINGS.get(key)
    if pair is None:
        return key
    text = pair[1] if _RU else pair[0]
    return text.format(**fmt) if fmt else text
