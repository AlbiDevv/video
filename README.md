# Video Unicalizator

Локальное десктоп-приложение на Python для пакетной генерации вариаций вертикальных видео: с цитатами поверх кадра, фоновой музыкой, лёгкой цветокоррекцией, quality-check и Excel-расписанием публикаций.

## Что уже работает

- загрузка до `5` оригинальных `mp4`
- загрузка музыки `mp3`
- загрузка одного или нескольких `txt` с цитатами
- генерация и без `txt`
  если `txt` не выбран, используется поле `Цитата для макета`
  если макет пустой, ролики генерируются без текстового блока
- WYSIWYG-редактор цитаты поверх превью
- drag-and-drop цитаты по кадру
- изменение ширины блока и масштаба цитаты прямо в превью
- zoom preview: колесо мыши, `+`, `-`, `Fit`
- pan по кадру при увеличении
- скруглённый фон цитаты
- мягкая тень через alpha-mask + blur
- emoji через локальные Twemoji assets с fallback на системные шрифты Windows
- живой прогресс генерации в нижней read-only консоли
- финальный рендер через `FFmpeg`, preview и quality-check через `OpenCV`
- экспорт `Расписание_выкладки.xlsx`
- сборка в `.exe` через `PyInstaller`

## Что приложение реально делает для уникальности

- строит уникальные `video recipes` по скорости, trim, crop, filter и цветовым вариантам
- держит per-source ledger принятых и отклонённых комбинаций
- использует visual quality-check, чтобы не пропускать слишком похожие ролики
- поддерживает таймлайн цитат и музыки для каждого исходника
- сохраняет per-video editor state и runtime summary генерации
- рендерит финальные mp4 через `FFmpeg`

## Что приложение не делает

- не обещает влияние на reach или рекомендации Instagram
- не пишет fake camera/device metadata
- не пытается "обмануть" алгоритм через соцсетевые теги контейнера
- не использует EXIF/XMP как отдельный источник уникальности видео

## Safe Export Metadata

- итоговый export работает в режиме `safe_normalize`
- приложение не наследует metadata и chapters из исходного mp4
- итоговый mp4 получает чистый контейнерный export и fresh `creation_time`
- safe export нужен для предсказуемого upload-файла, а не как гарантия продвижения

## Формат `txt` с цитатами

`txt` опционален.

Если используете `txt`, формат такой:

- одна цитата = один блок текста
- блоки разделяются пустой строкой
- переносы строк внутри блока сохраняются

Пример:

```text
Первая строка
Вторая строка 😎

Отдельная короткая цитата

Ещё одна цитата
в две строки
```

После загрузки `txt` первая цитата автоматически подставляется в поле `Цитата для макета`.

## Зависимости

- Python 3.11+
- FFmpeg
- customtkinter
- moviepy
- ffmpeg-python
- opencv-python
- pillow
- pandas
- openpyxl
- pyinstaller

## Установка

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Установка FFmpeg

Нужны `ffmpeg.exe` и `ffprobe.exe`.

Проверка:

```powershell
ffmpeg -version
ffprobe -version
```

Если `ffmpeg` установлен через `winget`, приложение умеет находить его автоматически и вне текущей PowerShell-сессии.

## Запуск из исходников

```powershell
cd C:\Users\binbi\Desktop\VideoUnicalizator
.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m video_unicalizator
```

## Запуск `.exe`

```powershell
cd C:\Users\binbi\Desktop\VideoUnicalizator
.\dist\VideoUnicalizator.exe
```

## Сборка `.exe`

```powershell
.venv\Scripts\Activate.ps1
python scripts\build_exe.py
```

Готовый файл появится в `dist/`.

## Быстрая проверка

```powershell
.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python scripts\smoke_test.py
python -m unittest discover -s tests -v
```

## Рабочий сценарий

1. Загрузите оригиналы кнопкой `Выбрать mp4` или `Папка`.
2. При необходимости загрузите музыку.
3. При необходимости загрузите `txt` с цитатами.
4. Отредактируйте `Цитату для макета`.
5. Перетащите цитату по превью.
6. Сузьте или расширьте блок хэндлами.
7. Отмасштабируйте цитату угловыми хэндлами.
8. Настройте шрифт, размер, цвет, фон, прозрачность, скругление и тень.
9. При необходимости выберите свою папку вывода.
10. Нажмите `Применить ко всем`.
11. Нажмите `Начать генерацию`.
12. Следите за этапами в нижней консоли: `Подготовка`, `Чтение файлов`, `Рендер`, `Проверка качества`, `Экспорт расписания`, `Готово`.

## Структура проекта

```text
assets/
  emoji/
data/
  originals/
  music/
  quotes/
docs/
output/
  variations/
  schedules/
  logs/
scripts/
src/video_unicalizator/
tests/
```

## Ограничения

- генерация требует локально доступный `ffmpeg`
- итоговый экспорт рассчитан на вертикальные ролики `1080x1920`
- время рендера зависит от длины видео и мощности машины
