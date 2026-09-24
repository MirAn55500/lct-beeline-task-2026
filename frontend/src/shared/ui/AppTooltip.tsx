import type { ComponentPropsWithoutRef, ReactNode } from 'react'
import { Tooltip } from '@heroui/react'

import { cn } from '@/shared/lib/cn'

/**
 * Стили тултипа по Figma Ready for dev:
 * тёмный фон #18181b, белый текст 12/20, padding 4×8, radius 8, стрелка.
 */
export const appTooltipContentClass =
  'z-50 max-w-[340px] rounded-lg bg-[#18181b] px-2 py-1 text-center text-xs font-normal leading-5 text-white shadow-none outline-none'

type AppTooltipContentProps = Omit<
  ComponentPropsWithoutRef<typeof Tooltip.Content>,
  'children'
> & {
  children: ReactNode
}

/** Контент тултипа в едином стиле макета. */
export function AppTooltipContent({
  children,
  className,
  showArrow = true,
  ...props
}: AppTooltipContentProps) {
  return (
    <Tooltip.Content
      showArrow={showArrow}
      className={cn(appTooltipContentClass, className)}
      {...props}
    >
      {children}
      {showArrow ? (
        <Tooltip.Arrow className="fill-[#18181b] text-[#18181b]" />
      ) : null}
    </Tooltip.Content>
  )
}
