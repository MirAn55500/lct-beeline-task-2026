import { forwardRef, type ComponentPropsWithoutRef } from 'react'

import { cn } from '@/shared/lib/cn'

type AppPanelProps = ComponentPropsWithoutRef<'div'>

export const AppPanel = forwardRef<HTMLDivElement, AppPanelProps>(
  function AppPanel({ className, ...props }, ref) {
    return (
      <div
        ref={ref}
        className={cn('rounded-[var(--border-radius-panel)] bg-white', className)}
        {...props}
      />
    )
  },
)
