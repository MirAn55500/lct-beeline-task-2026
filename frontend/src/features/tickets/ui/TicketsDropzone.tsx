import { useState, type ReactNode } from 'react'
import { ProgressCircle } from '@heroui/react'
import { RiDownload2Line, RiUploadCloud2Line } from '@remixicon/react'
import {
  Button,
  DropZone,
  FileTrigger,
  Text,
  isFileDropItem,
} from 'react-aria-components'

import { cn } from '@/shared/lib/cn'
import { buttonClass } from '@/shared/ui'

import {
  TICKETS_FILE_TYPES,
  TICKETS_TEMPLATE_SIZE,
  downloadTicketsTemplate,
  isTicketsFile,
} from '../lib/template'

export { isTicketsFile as isAcceptedTicketFile }

type TicketsDropzoneProps = {
  className?: string
  isUploading?: boolean
  onFiles?: (files: File[]) => void | Promise<void>
}

function DropzoneSurface({
  className,
  children,
}: {
  className?: string
  children: ReactNode
}) {
  return (
    <div
      className={cn(
        'flex min-h-0 w-full flex-1 flex-col items-center justify-center rounded-lg border border-dashed border-border bg-surface-hover px-5 py-5 text-center',
        className,
      )}
    >
      {children}
    </div>
  )
}

function UploadingState() {
  return (
    <DropzoneSurface>
      <div className="flex max-w-[435px] flex-col items-center gap-3">
        <ProgressCircle
          isIndeterminate
          aria-label="Загружаем заявки"
          size="md"
          className="size-9"
        >
          <ProgressCircle.Track>
            <ProgressCircle.TrackCircle className="stroke-surface-tertiary" />
            <ProgressCircle.FillCircle className="stroke-accent" />
          </ProgressCircle.Track>
        </ProgressCircle>
        <div className="flex flex-col items-center">
          <p className="text-base font-medium leading-7 text-foreground">
            Загружаем заявки
          </p>
          <p className="text-xs leading-5 text-muted">
            Это не займет больше 5 секунд
          </p>
        </div>
      </div>
    </DropzoneSurface>
  )
}

export function TicketsDropzone({
  className,
  isUploading = false,
  onFiles,
}: TicketsDropzoneProps) {
  const [pending, setPending] = useState(false)
  const uploading = isUploading || pending

  const handleFiles = async (files: File[]) => {
    const accepted = files.filter(isTicketsFile)
    if (accepted.length === 0 || uploading) return

    setPending(true)
    try {
      await onFiles?.(accepted)
    } finally {
      setPending(false)
    }
  }

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col gap-4 p-5 pt-4', className)}>
      {uploading ? (
        <UploadingState />
      ) : (
        <DropZone
          aria-label="Загрузка заявок"
          getDropOperation={() => 'copy'}
          onDrop={async (event) => {
            const files: File[] = []
            for (const item of event.items) {
              if (isFileDropItem(item)) {
                files.push(await item.getFile())
              }
            }
            await handleFiles(files)
          }}
          className={cn(
            'flex min-h-0 w-full flex-1 flex-col items-center justify-center rounded-lg border border-dashed border-border bg-surface-hover px-5 py-5 text-center outline-none transition-colors',
            'data-[drop-target]:border-focus data-[drop-target]:bg-accent/[0.06]',
            'data-[focus-visible]:outline data-[focus-visible]:outline-2 data-[focus-visible]:-outline-offset-1 data-[focus-visible]:outline-focus',
          )}
        >
          <FileTrigger
            acceptedFileTypes={TICKETS_FILE_TYPES}
            onSelect={async (list) => {
              if (!list) return
              await handleFiles(Array.from(list))
            }}
          >
            <Button className="flex cursor-pointer flex-col items-center gap-2 bg-transparent outline-none">
              <RiUploadCloud2Line
                size={24}
                className="shrink-0 text-muted"
              />
              <div className="flex max-w-[435px] flex-col items-center">
                <Text
                  slot="label"
                  className="text-base font-medium leading-7 text-foreground"
                >
                  Загрузите заявки
                </Text>
                <span className="text-xs leading-5 text-muted">
                  Нажмите на это поле или перетащите
                  <br />в него json или csv файл
                </span>
              </div>
            </Button>
          </FileTrigger>
        </DropZone>
      )}
      <button type="button" onClick={downloadTicketsTemplate} className={cn(buttonClass.outline, 'self-end')}>
        <RiDownload2Line size={16} />
        Скачать шаблон ({TICKETS_TEMPLATE_SIZE})
      </button>
    </div>
  )
}
