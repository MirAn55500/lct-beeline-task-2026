# Веб-интерфейс

React 19 + TypeScript + Vite, Tailwind CSS 4 и HeroUI 3.

## Локальная разработка

Node.js 24 LTS (при использовании nvm: `nvm use` в этой папке).

```bash
npm ci
npm run dev
```

- `npm run lint` — проверка исходников через Oxlint.
- `npm run build` — проверка TypeScript и сборка в `dist/`.
- `npm run preview` — локальный просмотр production-сборки.

Сервер доступен только на локальном компьютере (`127.0.0.1`).
Для запуска не нужны `.env`, API-ключи, Python или внешние CSV.

## HeroUI

Установлены `@heroui/react` и `@heroui/styles` версии 3.2.6.
Tailwind обрабатывается плагином `@tailwindcss/vite`.
В `src/index.css` сначала импортируется `tailwindcss`, затем `@heroui/styles`.
HeroUI v3 не требует `HeroUIProvider` или Framer Motion.

Компоненты импортируются напрямую:

```tsx
import { Button } from '@heroui/react'

<Button onPress={() => console.log('pressed')}>Действие</Button>
```

`src/App.tsx` содержит стартовый экран с `Card`, `Chip` и `Button`, счётчиком
нажатий, сбросом и доступным сообщением о результате. Это проверка подключения
библиотеки, а не готовый экран диспетчера. Python API в репозитории пока нет.

Документация: [HeroUI Quick Start](https://heroui.com/docs/react/getting-started/quick-start).
При добавлении компонентов используйте API v3: инструкции для v2 несовместимы.
