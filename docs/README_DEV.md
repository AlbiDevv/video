# README_DEV

## Архитектура

- `ui/`: интерфейс на `customtkinter`
- `core/`: видеопайплайн, текст, аудио и quality gate
- `services/`: загрузка файлов, логирование и экспорт
- `scheduler/`: построение графика публикаций и Excel
- `utils/`: общие проверки и графические утилиты

## Основной поток

1. `ui.main_window.VideoUnicalizatorApp` собирает состояние.
2. `core.variation_generator.VariationGenerator` создаёт пакет вариаций.
3. `core.video_processor.VideoProcessor` рендерит каждый ролик.
4. `core.quality_checker.QualityChecker` проверяет результат.
5. `services.export_service.ExportService` формирует Excel-расписание.

## Замечания

- комментарии в коде и строки интерфейса на русском
- тяжёлая обработка выполняется в фоне через `threading.Thread`
- превью построено на `tk.Canvas`, потому что `customtkinter` не даёт готового видеовиджета
