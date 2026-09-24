import { AlertDialog } from '@heroui/react'
import { RiCloseLine, RiDeleteBinLine } from '@remixicon/react'

type ReplanDialogProps = {
  /** Номер добавляемой заявки; null — окно закрыто. */
  ticketId: string | null
  engineerName?: string
  onConfirm: () => void
  onCancel: () => void
}

/** Подтверждение ручного изменения маршрута — как Modal «Изменение требует перепланирования». */
export function ReplanDialog({ ticketId, engineerName, onConfirm, onCancel }: ReplanDialogProps) {
  return (
    <AlertDialog.Backdrop
      isOpen={ticketId != null}
      onOpenChange={(open) => {
        if (!open) onCancel()
      }}
      isDismissable
      isKeyboardDismissDisabled={false}
      className="bg-black/50 backdrop-blur-[8px]"
    >
      <AlertDialog.Container size="sm" placement="center">
        <AlertDialog.Dialog
          className="relative flex w-[450px] max-w-[calc(100vw-32px)] flex-col gap-5 bg-white p-6 outline-none"
          style={{
            borderRadius: 24,
            boxShadow:
              '0 14px 28px rgb(0 0 0 / 0.08), 0 -6px 12px rgb(0 0 0 / 0.03), 0 2px 8px rgb(0 0 0 / 0.06)',
          }}
        >
          <div className="flex flex-col gap-2 pr-6">
            <span
              className="flex size-10 items-center justify-center bg-[#ff383c]/15 text-[#ff383c]"
              style={{ borderRadius: 8 }}
            >
              <RiDeleteBinLine size={16} />
            </span>
            <AlertDialog.Heading className="pt-1 text-base leading-7 font-medium text-[#18181b]">
              Изменение требует перепланирования
            </AlertDialog.Heading>
            <p className="text-sm leading-6 text-[#71717a]">
              Добавление заявки №{ticketId}
              {engineerName ? ` в маршрут: ${engineerName}` : ''}
            </p>
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onCancel}
              className="h-9 cursor-pointer border border-[#dedee0] bg-white px-4 text-sm leading-5 font-medium text-[#18181b] transition-colors hover:bg-[#f5f5f5]"
              style={{ borderRadius: 8 }}
            >
              Отмена
            </button>
            <button
              type="button"
              autoFocus
              onClick={onConfirm}
              className="h-9 cursor-pointer bg-[#0485f7] px-4 text-sm leading-5 font-medium text-[#fcfcfc] transition-colors hover:bg-[#0374d9]"
              style={{ borderRadius: 8 }}
            >
              Подтвердить
            </button>
          </div>

          <button
            type="button"
            aria-label="Закрыть"
            onClick={onCancel}
            className="absolute top-4 right-2.5 flex size-6 cursor-pointer items-center justify-center rounded-full bg-[#ebebec] text-[#71717a] transition-colors hover:bg-[#e0e0e2]"
          >
            <RiCloseLine size={16} />
          </button>
        </AlertDialog.Dialog>
      </AlertDialog.Container>
    </AlertDialog.Backdrop>
  )
}
