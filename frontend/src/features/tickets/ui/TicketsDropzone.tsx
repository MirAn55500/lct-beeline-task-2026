import { useState, type ReactNode } from 'react'
import { ProgressCircle, toast } from '@heroui/react'
import { RiDownloadLine, RiUploadCloud2Line } from '@remixicon/react'
import {
  Button,
  DropZone,
  FileTrigger,
  Text,
  isFileDropItem,
} from 'react-aria-components'

import { cn } from '@/shared/lib/cn'

type TicketsDropzoneProps = {
  className?: string
  isUploading?: boolean
  onFiles?: (files: File[]) => void | Promise<void>
}

export function isAcceptedTicketFile(file: File) {
  const name = file.name.toLowerCase()
  return (
    name.endsWith('.csv') ||
    name.endsWith('.json') ||
    file.type === 'text/csv' ||
    file.type === 'application/json' ||
    file.type === 'text/json'
  )
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
        'flex min-h-0 w-full flex-1 flex-col items-center justify-center rounded-lg border border-dashed border-[#dedee0] bg-[#f5f5f5] px-5 py-5 text-center',
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
            <ProgressCircle.TrackCircle className="stroke-[#ebebec]" />
            <ProgressCircle.FillCircle className="stroke-[#0485f7]" />
          </ProgressCircle.Track>
        </ProgressCircle>
        <div className="flex flex-col items-center">
          <p className="text-base font-medium leading-7 text-foreground">
            Загружаем заявки
          </p>
          <p className="text-xs leading-5 text-[#71717a]">
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
    if (uploading) return
    const accepted = files.filter(isAcceptedTicketFile)
    if (accepted.length === 0) {
      toast.danger('Нужен json или csv файл')
      return
    }

    setPending(true)
    try {
      await onFiles?.(accepted)
    } finally {
      setPending(false)
    }
  }

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)}>
      <div className="flex min-h-0 flex-1 px-5 pt-4">
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
              'flex min-h-0 w-full flex-1 flex-col items-center justify-center rounded-lg border border-dashed border-[#dedee0] bg-[#f5f5f5] px-5 py-5 text-center outline-none transition-colors',
              'data-[drop-target]:border-[#0485f7] data-[drop-target]:bg-[#0485f7]/[0.06]',
              'data-[focus-visible]:outline data-[focus-visible]:outline-2 data-[focus-visible]:-outline-offset-1 data-[focus-visible]:outline-[#0485f7]',
            )}
          >
            <FileTrigger
              acceptedFileTypes={[
                '.csv',
                'text/csv',
                '.json',
                'application/json',
              ]}
              onSelect={async (list) => {
                if (!list) return
                await handleFiles(Array.from(list))
              }}
            >
              <Button className="flex cursor-pointer flex-col items-center gap-2 bg-transparent outline-none">
                <RiUploadCloud2Line
                  size={24}
                  className="shrink-0 text-[#71717a]"
                />
                <div className="flex max-w-[435px] flex-col items-center">
                  <Text
                    slot="label"
                    className="text-base font-medium leading-7 text-foreground"
                  >
                    Загрузите заявки
                  </Text>
                  <span className="text-xs leading-5 text-[#71717a]">
                    Нажмите на это поле или перетащите
                    <br />в него json или csv файл
                  </span>
                </div>
              </Button>
            </FileTrigger>
          </DropZone>
        )}
      </div>

      <div className="flex shrink-0 flex-wrap justify-center gap-2 px-5 pt-3 pb-5">
        <a
          href="/templates/tickets-template.csv"
          download="tickets-template.csv"
          className="inline-flex h-9 cursor-pointer items-center gap-2 border border-[#dedee0] bg-white px-4 text-sm font-medium leading-5 text-[#18181b] transition-colors hover:bg-[#f5f5f5]"
          style={{ borderRadius: 8 }}
        >
          <RiDownloadLine size={16} className="shrink-0" />
          Шаблон csv
        </a>
        <a
          href="/templates/tickets-template.json"
          download="tickets-template.json"
          className="inline-flex h-9 cursor-pointer items-center gap-2 border border-[#dedee0] bg-white px-4 text-sm font-medium leading-5 text-[#18181b] transition-colors hover:bg-[#f5f5f5]"
          style={{ borderRadius: 8 }}
        >
          <RiDownloadLine size={16} className="shrink-0" />
          Шаблон json
        </a>
      </div>
    </div>
  )
}
