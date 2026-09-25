import type { ReactNode } from 'react'
import { Tooltip } from '@heroui/react'

import { cn } from '@/shared/lib/cn'

/**
 * Стили тултипа по Figma Ready for dev:
 * инверсный фон темы, белый текст 12/20, padding 4×8, radius 8, стрелка.
 */
export const appTooltipContentClass =
  'z-50 max-w-[340px] rounded-lg bg-background-inverse px-2 py-1 text-center text-xs font-normal leading-5 text-[var(--beeline-white)] shadow-none outline-none'

type AppTooltipContentProps = {
  children: ReactNode
  className?: string
  showArrow?: boolean
}

/** Контент тултипа в едином стиле макета. */
export function AppTooltipContent({
  children,
  className,
  showArrow = true,
}: AppTooltipContentProps) {
  return (
    <Tooltip.Content
      showArrow={showArrow}
      className={cn(appTooltipContentClass, className)}
    >
      {children}
      {showArrow ? (
        <Tooltip.Arrow className="fill-background-inverse text-background-inverse" />
      ) : null}
    </Tooltip.Content>
  )
}
