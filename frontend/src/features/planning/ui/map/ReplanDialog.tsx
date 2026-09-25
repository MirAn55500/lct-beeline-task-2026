import { RiDeleteBinLine } from '@remixicon/react'

import { AppModal, buttonClass } from '@/shared/ui'

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
    <AppModal
      isOpen={ticketId != null}
      onClose={onCancel}
      icon={<RiDeleteBinLine size={16} />}
      title="Изменение требует перепланирования"
      description={`Добавление заявки №${ticketId}${engineerName ? ` в маршрут: ${engineerName}` : ''}`}
      footer={
        <>
          <button type="button" onClick={onCancel} className={buttonClass.outline}>
            Отмена
          </button>
          <button type="button" autoFocus onClick={onConfirm} className={buttonClass.primary}>
            Подтвердить
          </button>
        </>
      }
    />
  )
}
