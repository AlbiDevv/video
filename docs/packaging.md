# Packaging

## Сборка через PyInstaller

```powershell
.venv\Scripts\Activate.ps1
python scripts\build_exe.py
```

## Что используется

- `pyinstaller.spec` как основной сценарий сборки
- `scripts/build_exe.py` как удобная обёртка

## Проверка после сборки

1. Убедиться, что приложение запускается из `dist/`.
2. Проверить открытие окна и вкладок.
3. Проверить, что статус `FFmpeg` виден сразу после старта.
4. Проверить загрузку `mp4`, `mp3` и `txt`.
5. Проверить создание `output/schedules/Расписание_выкладки.xlsx`.
