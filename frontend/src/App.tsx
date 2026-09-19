import { useState } from 'react'
import { Button, Card, Chip } from '@heroui/react'

function App() {
  const [pressCount, setPressCount] = useState(0)

  return (
    <main className="mx-auto flex min-h-svh max-w-3xl items-center px-4 py-12 sm:px-8">
      <Card className="w-full">
        <Card.Header>
          <Chip variant="soft">Стартовый экран</Chip>
          <h1 className="mt-4 text-3xl font-semibold">Планирование работы инженеров</h1>
          <Card.Description>
            Билайн Бизнес · Основа веб-интерфейса
          </Card.Description>
        </Card.Header>
        <Card.Content className="space-y-4">
          <p>
            Здесь будет интерфейс заявок, маршрутов и назначений. Подключение
            к планировщику ещё не настроено.
          </p>
          <p className="text-sm text-muted">
            Кнопка ниже проверяет работу компонентов интерфейса и не запускает
            расчёт плана.
          </p>
          <p role="status" aria-live="polite" aria-atomic="true">
            {pressCount === 0
              ? 'Компоненты готовы к проверке.'
              : `Кнопка работает. Нажатий: ${pressCount}.`}
          </p>
        </Card.Content>
        <Card.Footer className="flex flex-wrap gap-3">
          <Button size="lg" onPress={() => setPressCount((count) => count + 1)}>
            Проверить интерфейс
          </Button>
          <Button
            size="lg"
            variant="secondary"
            isDisabled={pressCount === 0}
            onPress={() => setPressCount(0)}
          >
            Сбросить
          </Button>
        </Card.Footer>
      </Card>
    </main>
  )
}

export default App
