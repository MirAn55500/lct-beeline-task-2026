import type { ReactNode } from 'react'

import { ASIDE_WIDTH_CLASS, cn } from '@/shared/lib'
import { AppPanel, BrandBar } from '@/shared/ui'

type WorkAreaMapLayoutProps = {
  /** Содержимое левой колонки под брендом. */
  sidebar?: ReactNode
  /** Шапка рабочей области высотой 60px. */
  header?: ReactNode
  children?: ReactNode
}

export function WorkAreaMapLayout({
  sidebar,
  header,
  children,
}: WorkAreaMapLayoutProps) {
  return (
    <div className="flex h-svh gap-4 bg-[#f5f5f5] p-4">
      <aside className={cn('flex shrink-0 flex-col gap-4', ASIDE_WIDTH_CLASS)}>
        <BrandBar className="w-full" showMenu />
        {sidebar ?? <AppPanel className="min-h-0 flex-1" />}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        {header ?? <AppPanel className="h-[60px] shrink-0" />}
        <div className="flex min-h-0 flex-1 flex-col gap-4">
          {children ?? <AppPanel className="min-h-0 flex-1" />}
        </div>
      </div>
    </div>
  )
}
