import { useState } from 'react'
import { AlertDialog, Checkbox } from '@heroui/react'
import { RiCloseLine, RiEyeFill, RiEyeOffFill } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'

import type { ClientContact } from '../../ganttTypes'

type ClientApprovalDialogProps = {
  open: boolean
  contact: ClientContact | null
  /** «18:00–19:40» — новое время визита. */
  timeLabel: string
  onConfirm: () => void
  onCancel: () => void
}

/** «+7 916 245-89-79» → «+7***-***-89-79», как в макете. */
function maskPhone(phone: string) {
  return `+7***-***-${phone.slice(-5)}`
}

/**
 * Перенос заявки за окно клиента: диспетчер звонит клиенту и подтверждает
 * или отменяет изменение — Modal «Вы переместили заявку на другое время».
 */
export function ClientApprovalDialog(props: ClientApprovalDialogProps) {
  return (
    <AlertDialog.Backdrop
      isOpen={props.open}
      onOpenChange={(open) => {
        if (!open) props.onCancel()
      }}
      isDismissable
      isKeyboardDismissDisabled={false}
      className="bg-backdrop backdrop-blur-[8px]"
    >
      <AlertDialog.Container size="sm" placement="center">
        {/* Отдельный компонент — галочка и раскрытый номер сбрасываются при каждом открытии. */}
        {props.open ? <DialogBody {...props} /> : null}
      </AlertDialog.Container>
    </AlertDialog.Backdrop>
  )
}

function DialogBody({ contact, timeLabel, onConfirm, onCancel }: ClientApprovalDialogProps) {
  const [agreed, setAgreed] = useState(false)
  const [revealed, setRevealed] = useState(false)

  return (
    <AlertDialog.Dialog
      className="relative flex w-[450px] max-w-[calc(100vw-32px)] flex-col gap-5 bg-surface p-6 outline-none"
      style={{
        borderRadius: 24,
        boxShadow: '0 14px 28px rgb(0 0 0 / 0.08), 0 -6px 12px rgb(0 0 0 / 0.03), 0 2px 8px rgb(0 0 0 / 0.06)',
      }}
    >
      <div className="flex flex-col gap-2">
        <AlertDialog.Heading className="pr-6 text-base leading-7 font-medium text-foreground">
          Вы переместили заявку на другое время
        </AlertDialog.Heading>
        <div className="flex flex-col gap-3">
          <p className="text-sm leading-6 text-muted">Согласуйте новое время с клиентом: {timeLabel}</p>
          <span aria-hidden className="my-1.5 h-px bg-separator" />
          <p className="text-sm leading-6 font-medium text-foreground">Данные клиента</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col">
              <span className="text-sm leading-6 text-muted">Контактный номер</span>
              <span className="flex items-center gap-1 text-base leading-7 font-medium text-foreground">
                {contact ? (revealed ? contact.phone : maskPhone(contact.phone)) : '—'}
                {contact ? (
                  <button
                    type="button"
                    aria-label={revealed ? 'Скрыть номер' : 'Показать номер'}
                    onClick={() => setRevealed((value) => !value)}
                    className="flex size-6 cursor-pointer items-center justify-center text-foreground transition-colors hover:bg-surface-hover"
                    style={{ borderRadius: 6 }}
                  >
                    {revealed ? <RiEyeOffFill size={16} /> : <RiEyeFill size={16} />}
                  </button>
                ) : null}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-sm leading-6 text-muted">Имя</span>
              <span className="text-base leading-7 font-medium text-foreground">{contact?.name ?? '—'}</span>
            </div>
          </div>
          <div className="bg-surface-tertiary px-2 py-1" style={{ borderRadius: 8 }}>
            <Checkbox isSelected={agreed} onChange={setAgreed} className="w-full">
              <Checkbox.Content className="flex w-full cursor-pointer items-center gap-1.5">
                <Checkbox.Control
                  className="before:!rounded-[4px]"
                  style={{
                    borderRadius: 4,
                    borderWidth: 1,
                    borderStyle: 'solid',
                    borderColor: agreed ? 'var(--accent)' : 'var(--field-border)',
                    ['--field-background' as string]: agreed ? 'var(--accent)' : 'var(--field-background)',
                    ['--field-shadow' as string]: '0 0 #0000',
                  }}
                >
                  <Checkbox.Indicator className="!size-2.5">
                    {({ isSelected }) =>
                      isSelected ? (
                        <svg
                          viewBox="0 0 10 10"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth={2}
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <polyline points="1.75 5.25 4 7.5 8.25 2.75" />
                        </svg>
                      ) : null
                    }
                  </Checkbox.Indicator>
                </Checkbox.Control>
                <span className="text-sm leading-6 font-medium text-foreground">Время согласовано</span>
              </Checkbox.Content>
            </Checkbox>
          </div>
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="h-9 cursor-pointer border border-border bg-surface px-4 text-sm leading-5 font-medium text-foreground transition-colors hover:bg-surface-hover"
          style={{ borderRadius: 8 }}
        >
          Отмена
        </button>
        <button
          type="button"
          disabled={!agreed}
          onClick={onConfirm}
          className={cn(
            'h-9 bg-accent px-4 text-sm leading-5 font-medium text-accent-foreground transition-colors',
            agreed ? 'cursor-pointer hover:bg-accent-hover' : 'cursor-not-allowed opacity-50',
          )}
          style={{ borderRadius: 8 }}
        >
          Подтвердить
        </button>
      </div>

      <button
        type="button"
        aria-label="Закрыть"
        onClick={onCancel}
        className="absolute top-4 right-2.5 flex size-6 cursor-pointer items-center justify-center rounded-full bg-surface-tertiary text-muted transition-colors hover:bg-default-hover"
      >
        <RiCloseLine size={16} />
      </button>
    </AlertDialog.Dialog>
  )
}
