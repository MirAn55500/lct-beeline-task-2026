import { cn } from '@/shared/lib/cn'

const BASE =
  'inline-flex h-9 shrink-0 cursor-pointer items-center justify-center gap-2 rounded-[8px] px-4 text-sm leading-5 font-medium whitespace-nowrap transition-colors outline-none focus-visible:ring-2 focus-visible:ring-[#0485f7]/40 disabled:cursor-not-allowed'

/** Кнопки макета (Button md): primary — синяя, outline — белая с рамкой. */
export const buttonClass = {
  primary: cn(
    BASE,
    'bg-[#0485f7] text-[#fcfcfc] hover:bg-[#0374d9] disabled:bg-[#0485f7]/50 disabled:hover:bg-[#0485f7]/50',
  ),
  outline: cn(
    BASE,
    'border border-[#dedee0] bg-white text-[#18181b] hover:bg-[#f5f5f5] disabled:opacity-50 disabled:hover:bg-white',
  ),
} as const

/** Сегмент из макета (Tabs): серый трек, белая «таблетка» с тенью у выбранного. */
export const segmentClass = (active: boolean) =>
  cn(
    'flex h-8 min-w-0 flex-1 cursor-pointer items-center justify-center rounded-[6px] px-3 text-sm leading-6 font-medium whitespace-nowrap transition-colors outline-none focus-visible:ring-2 focus-visible:ring-[#0485f7]/40',
    active
      ? 'bg-white text-[#18181b] shadow-[0_2px_8px_rgb(0_0_0/0.06)]'
      : 'text-[#71717a] hover:text-[#18181b]',
  )
