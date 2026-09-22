import type { ReactNode } from 'react'

import { AppPanel, BrandBar } from '@/shared/ui'

type WorkAreaMapLayoutProps = {
  children?: ReactNode
}

export function WorkAreaMapLayout({ children }: WorkAreaMapLayoutProps) {
  return (
    <div className="flex h-svh gap-4 bg-[#f5f5f5] p-4">
      <aside className="flex w-[346px] shrink-0 flex-col gap-4">
        <BrandBar className="w-full" showMenu />
        <AppPanel className="min-h-0 flex-1" />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <AppPanel className="h-[60px] shrink-0" />
        <div className="flex min-h-0 flex-1 flex-col gap-4">
          {children ?? <AppPanel className="min-h-0 flex-1" />}
        </div>
      </div>
    </div>
  )
}
