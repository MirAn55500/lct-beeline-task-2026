import type { ReactNode } from 'react'

import { ASIDE_WIDTH_CLASS } from '@/shared/lib'
import { AppPanel, BrandBar } from '@/shared/ui'

type WorkAreaGanttLayoutProps = {
  /** Шапка рабочей области высотой 60px справа от бренда. */
  header?: ReactNode
  children?: ReactNode
}

export function WorkAreaGanttLayout({ header, children }: WorkAreaGanttLayoutProps) {
  return (
    <div className="flex h-svh flex-col gap-4 bg-[#f5f5f5] p-4">
      <div className="flex shrink-0 gap-4">
        <BrandBar className={ASIDE_WIDTH_CLASS} showMenu />
        <div className="min-w-0 flex-1">{header ?? <AppPanel className="h-[60px]" />}</div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4">
        {children ?? <AppPanel className="min-h-0 flex-1" />}
      </div>
    </div>
  )
}
