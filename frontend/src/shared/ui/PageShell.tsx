import type { ReactNode } from 'react'

import { cn } from '@/shared/lib/cn'

type PageShellProps = {
  title: string
  description?: string
  actions?: ReactNode
  children?: ReactNode
  className?: string
}

/**
 * Каркас страницы: заголовок + опциональные actions + контент.
 * Используйте на pages; фичи кладут сюда свои компоненты.
 */
export function PageShell({
  title,
  description,
  actions,
  children,
  className,
}: PageShellProps) {
  return (
    <section className={cn('flex flex-col gap-6', className)}>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {description ? (
            <p className="text-sm text-muted">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </header>
      {children}
    </section>
  )
}
