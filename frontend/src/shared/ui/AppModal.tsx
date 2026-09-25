import type { ReactNode } from 'react'
import { AlertDialog } from '@heroui/react'
import { RiCloseLine } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'

type AppModalProps = {
  isOpen: boolean
  onClose: () => void
  title: ReactNode
  /**
   * Значок в плашке над заголовком — окно подтверждения («Перестроить маршрут?»):
   * заголовок тогда 16/28, как _ModalHeader с showIcon.
   */
  icon?: ReactNode
  /** Цвет плашки значка: danger — красная, как в макете. */
  iconTone?: 'danger' | 'accent'
  description?: ReactNode
  /** Кнопки справа внизу. */
  footer?: ReactNode
  children?: ReactNode
  className?: string
}

/**
 * Modal из макета: 450px, скругление 24, заголовок 20/28 (с значком — 16/28), серое описание,
 * круглый крестик в углу, кнопки справа внизу. Фон размывается.
 * Тело монтируется заново при каждом открытии — черновик формы не переживает закрытие.
 */
const ICON_TONE = {
  danger: 'bg-[#ff383c]/15 text-[#ff383c]',
  accent: 'bg-[#0485f7]/15 text-[#0485f7]',
}

export function AppModal({
  isOpen,
  onClose,
  title,
  icon,
  iconTone = 'danger',
  description,
  footer,
  children,
  className,
}: AppModalProps) {
  return (
    <AlertDialog.Backdrop
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
      isDismissable
      isKeyboardDismissDisabled={false}
      className="bg-black/50 backdrop-blur-[8px]"
    >
      <AlertDialog.Container size="sm" placement="center">
        {isOpen ? (
          <AlertDialog.Dialog
            className={cn(
              'relative flex w-[450px] max-w-[calc(100vw-32px)] flex-col gap-5 bg-white p-6 outline-none',
              className,
            )}
            style={{
              borderRadius: 24,
              boxShadow: '0 14px 28px rgb(0 0 0 / 0.08), 0 -6px 12px rgb(0 0 0 / 0.03), 0 2px 8px rgb(0 0 0 / 0.06)',
            }}
          >
            <div className="flex flex-col gap-4">
              {icon ? (
                <div className="flex flex-col gap-2">
                  <div className="flex flex-col gap-3 pr-6">
                    <span
                      className={cn('flex size-10 items-center justify-center', ICON_TONE[iconTone])}
                      style={{ borderRadius: 8 }}
                    >
                      {icon}
                    </span>
                    <AlertDialog.Heading className="text-base leading-7 font-medium text-[#18181b]">
                      {title}
                    </AlertDialog.Heading>
                  </div>
                  {description ? <p className="pr-4 text-sm leading-6 text-[#71717a]">{description}</p> : null}
                </div>
              ) : (
                <div className="flex flex-col gap-1">
                  <AlertDialog.Heading className="pr-6 text-xl leading-7 font-semibold text-[#18181b]">
                    {title}
                  </AlertDialog.Heading>
                  {description ? <p className="text-sm leading-6 text-[#71717a]">{description}</p> : null}
                </div>
              )}
              {children}
            </div>

            {footer ? <div className="flex justify-end gap-2">{footer}</div> : null}

            <button
              type="button"
              aria-label="Закрыть"
              onClick={onClose}
              className="absolute top-4 right-2.5 flex size-6 cursor-pointer items-center justify-center rounded-full bg-[#ebebec] text-[#71717a] transition-colors hover:bg-[#e0e0e2]"
            >
              <RiCloseLine size={16} />
            </button>
          </AlertDialog.Dialog>
        ) : null}
      </AlertDialog.Container>
    </AlertDialog.Backdrop>
  )
}

/** Подпись поля формы: «Регион *» и значок подсказки. */
export function FieldLabel({ children, required, hint }: { children: ReactNode; required?: boolean; hint?: ReactNode }) {
  return (
    <div className="flex items-center gap-1 text-sm leading-6 font-medium text-[#18181b]">
      {children}
      {required ? <span className="text-[#ff383c]">*</span> : null}
      {hint}
    </div>
  )
}
