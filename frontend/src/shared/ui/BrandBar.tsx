import {
  useEffect,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
} from 'react'
import { RiFunctionLine } from '@remixicon/react'

import beelineLogotype from '@/shared/assets/beeline-logotype.svg'
import { cn } from '@/shared/lib/cn'
import { AppNavMenu } from '@/shared/ui/AppNavMenu'
import { AppPanel } from '@/shared/ui/AppPanel'

type BrandBarProps = ComponentPropsWithoutRef<'div'> & {
  showMenu?: boolean
}

export function BrandBar({
  className,
  showMenu = false,
  ...props
}: BrandBarProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return

    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <AppPanel
      ref={rootRef}
      className={cn(
        'relative flex h-[60px] shrink-0 items-center px-3',
        showMenu ? 'justify-between' : 'justify-start',
        className,
      )}
      {...props}
    >
      <img
        src={beelineLogotype}
        alt="билайн маршруты"
        width={272}
        height={36}
        className="h-9 w-[272px] min-w-0 shrink object-cover object-left"
      />

      {showMenu ? (
        <>
          <button
            type="button"
            aria-label="Меню"
            aria-expanded={open}
            aria-haspopup="menu"
            onClick={() => setOpen((value) => !value)}
            className="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-[var(--border-radius-button-md)] border border-[#dedee0] text-foreground transition-colors hover:bg-[#f5f5f5]"
          >
            <RiFunctionLine size={16} />
          </button>

          {open ? (
            <AppNavMenu
              className="absolute top-[calc(100%-4px)] left-3 z-50"
              onNavigate={() => setOpen(false)}
            />
          ) : null}
        </>
      ) : null}
    </AppPanel>
  )
}
