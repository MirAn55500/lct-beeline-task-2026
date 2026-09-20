import { EmptyState, PageShell } from '@/shared/ui'

/** Единственная страница SPA. Разделы/навигация появятся по дизайну. */
export function HomePage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      <PageShell
        title="Планирование выездов"
        description="Билайн Бизнес · интерфейс заявок, персонала и планов."
      >
        <EmptyState
          title="Страница-заглушка"
          description="Каркас RTK Query и features готов. Разметка разделов — по макету."
        />
      </PageShell>
    </main>
  )
}
