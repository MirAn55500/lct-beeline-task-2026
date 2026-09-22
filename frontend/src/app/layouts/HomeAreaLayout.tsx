import type { ReactNode } from 'react'

import { AppNav, AppPanel, BrandBar, ContextHeader } from '@/shared/ui'

type HomeAreaLayoutProps = {
  children?: ReactNode
  isUploadDisabled?: boolean
  onUploadClick?: () => void
}

export function HomeAreaLayout({
  children,
  isUploadDisabled,
  onUploadClick,
}: HomeAreaLayoutProps) {
  return (
    <div className="flex h-svh gap-4 bg-[#f5f5f5] p-4">
      <aside className="flex w-[346px] shrink-0 flex-col gap-4">
        <BrandBar className="w-full" />
        <AppNav />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <ContextHeader
          isUploadDisabled={isUploadDisabled}
          onUploadClick={onUploadClick}
        />
        <div className="flex min-h-0 flex-1 flex-col gap-4">
          {children ?? <AppPanel className="min-h-0 flex-1" />}
        </div>
      </div>
    </div>
  )
}
