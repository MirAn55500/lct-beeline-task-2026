# Планирование работы инженеров · Билайн Бизнес

## Структура

- `docs/` — предметная область, навигация и требования.
- `solution/` — Python 3.10+ планировщик, консольная демонстрация и тесты.
- `frontend/` — веб-приложение на React 19, TypeScript, Vite, Tailwind CSS 4 и HeroUI 3.

## Запуск веб-интерфейса

Требуется Node.js 24 LTS и npm (версия Node указана в `frontend/.nvmrc`).

```bash
cd frontend
npm ci
npm run dev
```

Откройте адрес из вывода Vite (обычно http://127.0.0.1:5173).
Стартовая страница содержит компоненты HeroUI и интерактивную проверку кнопок.
API и связь с Python-планировщиком пока не реализованы; страница не рассчитывает
маршруты и не показывает вымышленные результаты.

Проверка и production-сборка:

```bash
npm run lint
npm run build
npm run preview
```

Подробнее об интеграции: [frontend/README.md](frontend/README.md).

## Python-планировщик

Алгоритм работает отдельно от веб-приложения и использует стандартную библиотеку Python.
Описание API, формата данных и запуска: [solution/README.md](solution/README.md).
Для демонстрации нужны CSV-наборы, которых нет в этом репозитории; один только
`solution/data/geocache.json` их не заменяет.

Тесты в отдельном виртуальном окружении:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install pytest
cd solution
../.venv/bin/python -m pytest tests -q
```

Тесты на внешних CSV пропускаются, если наборы не предоставлены.
