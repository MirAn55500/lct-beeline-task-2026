import type { ReactNode } from 'react'

import { AppPanel, BrandBar } from '@/shared/ui'

type WorkAreaGanttLayoutProps = {
  children?: ReactNode
}

export function WorkAreaGanttLayout({ children }: WorkAreaGanttLayoutProps) {
  return (
    <div className="flex h-svh flex-col gap-4 bg-[#f5f5f5] p-4">
      <div className="flex shrink-0 gap-4">
        <BrandBar className="w-[346px]" showMenu />
        <AppPanel className="h-[60px] min-w-0 flex-1" />
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4">
        {children ?? <AppPanel className="min-h-0 flex-1" />}
      </div>
    </div>
  )
}
