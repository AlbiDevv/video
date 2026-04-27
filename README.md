# Video Unicalizator

Локальное десктоп-приложение на Python для пакетной генерации вариаций вертикальных видео: с цитатами поверх кадра, фоновой музыкой, лёгкой цветокоррекцией, quality-check и Excel-расписанием публикаций.

Проект ориентирован на ручную работу с исходниками и даёт удобный визуальный редактор поверх пайплайна рендера через FFmpeg.

## Что уже работает

- загрузка до `5` исходных `mp4`;
- загрузка музыки `mp3`;
- загрузка одного или нескольких `txt` с цитатами;
- генерация роликов даже без файла цитат;
- WYSIWYG-редактор текста поверх превью;
- drag-and-drop цитаты по кадру;
- изменение ширины блока, масштаба текста, фона, прозрачности и тени;
- финальный рендер через `FFmpeg` и quality-check через `OpenCV`;
- экспорт `Расписание_выкладки.xlsx`;
- сборка Windows-версии через `PyInstaller`.

## Что приложение делает для вариативности

- собирает разные video recipes по скорости, trim, crop и фильтрам;
- ведёт учёт уже использованных комбинаций;
- отсеивает слишком похожие ролики через visual quality-check;
- хранит состояние редактора и итоговую сводку генерации.

## Что проект не делает

- не обещает рост охватов;
- не подменяет device metadata;
- не пытается обходить алгоритмы платформ;
- не использует EXIF/XMP как отдельный источник «уникальности».

## Установка

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Проверка FFmpeg

```powershell
ffmpeg -version
ffprobe -version
```

## Запуск из исходников

```powershell
cd C:\path\to\VideoUnicalizator
.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m video_unicalizator
```

## Запуск `.exe`

```powershell
cd C:\path\to\VideoUnicalizator
.\dist\VideoUnicalizator.exe
```

## Сборка `.exe`

```powershell
.venv\Scripts\Activate.ps1
python scripts\build_exe.py
```

## Быстрая проверка

```powershell
.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python scripts\smoke_test.py
python -m unittest discover -s tests -v
```

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

- генерация требует локально доступный `ffmpeg`;
- итоговый экспорт рассчитан на вертикальные ролики `1080x1920`;
- время рендера зависит от длины видео и мощности машины.
