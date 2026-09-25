import { cn } from '@/shared/lib/cn'

const BASE =
  'inline-flex h-9 shrink-0 cursor-pointer items-center justify-center gap-2 rounded-[8px] px-4 text-sm leading-5 font-medium whitespace-nowrap transition-colors outline-none focus-visible:ring-2 focus-visible:ring-focus/40 disabled:cursor-not-allowed'

/** Кнопки макета (Button md), привязанные к семантике HeroUI. */
export const buttonClass = {
  primary: cn(
    BASE,
    'bg-accent text-accent-foreground hover:bg-accent-hover disabled:bg-accent/50 disabled:hover:bg-accent/50',
  ),
  outline: cn(
    BASE,
    'border border-border bg-surface text-foreground hover:bg-surface-hover disabled:opacity-50 disabled:hover:bg-surface',
  ),
} as const

/** Сегмент из макета (Tabs): серый трек, белая «таблетка» с тенью у выбранного. */
export const segmentClass = (active: boolean) =>
  cn(
    'flex h-8 min-w-0 flex-1 cursor-pointer items-center justify-center rounded-[6px] px-3 text-sm leading-6 font-medium whitespace-nowrap transition-colors outline-none focus-visible:ring-2 focus-visible:ring-focus/40',
    active
      ? 'bg-surface text-foreground shadow-[0_2px_8px_rgb(0_0_0/0.06)]'
      : 'text-muted hover:text-foreground',
  )
