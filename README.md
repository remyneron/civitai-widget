# Civitai Desktop Widget / Виджет трендового AI-арта Civitai

<img src="civitai_widget/assets/icon.svg" width="96" align="right" alt="Иконка">

Полупрозрачный десктопный виджет для Linux, который показывает самые популярные работы с [Civitai](https://civitai.com) прямо на рабочем столе.

<table>
  <tr>
    <td width="25%" align="center"><img src="docs/screenshots/base_view.png" width="170" alt="Базовый вид"><br><sub>Базовый вид</sub></td>
    <td width="25%" align="center"><img src="docs/screenshots/hover.png" width="170" alt="Подпись при наведении"><br><sub>Подпись при наведении</sub></td>
    <td width="25%" align="center"><img src="docs/screenshots/video_poster.png" width="170" alt="Видео-постер"><br><sub>Видео-постер</sub></td>
    <td width="25%" align="center"><img src="docs/screenshots/zen_mode.png" width="170" alt="Zen Mode"><br><sub>Zen Mode</sub></td>
  </tr>
</table>

---: | :---: | :---: | :---: |
| <img src="docs/screenshots/base_view.png" width="200" alt="Базовый вид"> | <img src="docs/screenshots/hover.png" width="200" alt="Подпись при наведении"> | <img src="docs/screenshots/video_poster.png" width="200" alt="Постер видео со значком"> | <img src="docs/screenshots/zen_mode.png" width="200" alt="Zen Mode"> |

---

## Возможности

- **Галерея популярных работ Civitai** на рабочем столе: картинки и видео, с автором и числом реакций при наведении.
- **Слайд-шоу**: страницы плавно сменяют друг друга с интервалом от 5 до 120 секунд; есть пауза, а пока курсор над виджетом, показ ждёт.
- **Видео** проигрываются прямо в плитке, без звука и по кругу. Автовоспроизведение можно отключить в меню.
- **Фильтры**: период (день / неделя / месяц / год / всё время), сортировка, базовая модель.
- **Бесконечная лента**: новые работы подгружаются по мере просмотра, а пункт «Загрузить ещё» добавляет их сразу.
- **Открытие на сайте**: клик по плитке открывает работу на Civitai.
- **Zen Mode**: только арт, без панели и кнопок.
- **Окно под себя**: перемещается за любое место, меняет размер за любой край, число рядов подстраивается под высоту; можно закрепить поверх всех окон.
- **Управление с клавиатуры и колесом мыши**, значок в трее, автозапуск при входе в систему.
- **Настройки запоминаются**: позиция, размер, интервал, фильтры и режимы восстанавливаются при следующем запуске.
- **SFW по умолчанию**; показ NSFW включается в меню.
- **Работа без сети**: просмотренные работы сохраняются в кэше (до 300 МБ) и показываются, когда Civitai недоступен.

---

## Установка

```bash
git clone https://github.com/remyneron/civitai-widget.git
cd civitai-widget
./install.sh
```

Скрипт создаёт виртуальное окружение в `~/.local/share/civitai-widget/venv` (около 400 МБ: Qt и модуль мультимедиа для видео), ставит пакет, команду `civitai-widget` в `~/.local/bin`, иконку и ярлык в меню приложений.

| Команда | Действие |
| :--- | :--- |
| `./install.sh` | Установить или обновить |
| `./install.sh --autostart` | Установить и включить автозапуск |
| `./install.sh --uninstall` | Удалить (настройки и кэш остаются) |

### Требования

- Linux с X11 или XWayland, Python 3.10+
- Для Qt 6.5+ нужна библиотека `libxcb-cursor0` (`sudo apt install libxcb-cursor0`)
- Значок в трее на GNOME требует расширения AppIndicator (в Ubuntu включено по умолчанию)

В сессии Wayland виджет по умолчанию запускается через XWayland: только так окно может запоминать позицию и держаться поверх остальных. Чтобы выбрать платформу самостоятельно, задайте `QT_QPA_PLATFORM`.

---

## Управление

| Действие | Назначение |
| :--- | :--- |
| Клик по карточке | Открыть работу на Civitai |
| Перетаскивание за любое место | Переместить виджет |
| Перетаскивание за край | Изменить размер |
| Двойной клик, `Esc`, `Z` | Zen Mode |
| Колесо мыши, `←` `→`, `PgUp` `PgDn` | Листать страницы |
| `Space` | Пауза |
| `R`, `F5` | Обновить |
| `N` | Загрузить ещё |
| `P` | Поверх всех окон |
| `Ctrl+Q` | Выход |
| Правый клик или кнопка ☰ | Меню со всеми настройками |

---

## Разработка

```bash
python3 -m venv venv
venv/bin/pip install -e ".[dev]"
venv/bin/python -m civitai_widget --debug
venv/bin/ruff check .
QT_QPA_PLATFORM=offscreen venv/bin/pytest
```

```
civitai_widget/
├── app.py         # точка входа, логирование, запуск в одном экземпляре
├── window.py      # окно, жесты, меню
├── card.py        # плитка: картинка или видео, плавная смена
├── widgets.py     # точки пагинации, полоса прогресса
├── slideshow.py   # таймер слайд-шоу с паузой
├── client.py      # сеть: лента, миниатюры и видео (QNetworkAccessManager)
├── feed.py        # фильтрация и пагинация ленты (без Qt)
├── cache.py       # дисковый кэш (без Qt)
├── blurhash.py    # декодер BlurHash (без Qt)
├── config.py      # константы, пути, настройки
├── autostart.py   # автозапуск
├── i18n.py        # строки интерфейса (ru / en)
├── icons.py, styles.py
└── assets/icon.svg
```

Журнал работы: `~/.local/state/civitai-widget/widget.log`. Настройки: `~/.config/civitai-widget/civitai-widget.conf`.

---

## Лицензия

[MIT](LICENSE)
