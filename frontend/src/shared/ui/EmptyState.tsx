import type { ReactNode } from 'react'

import { cn } from '@/shared/lib/cn'

type EmptyStateProps = {
  title: string
  description?: string
  action?: ReactNode
  className?: string
}

/** Плейсхолдер пустого списка / ещё не подключённого раздела. */
export function EmptyState({
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-start gap-3 rounded-xl border border-dashed border-default p-6',
        className,
      )}
    >
      <h2 className="text-base font-medium">{title}</h2>
      {description ? <p className="text-sm text-muted">{description}</p> : null}
      {action}
    </div>
  )
}
