import { RiUploadCloud2Line } from '@remixicon/react'
import {
  Button,
  DropZone,
  FileTrigger,
  Text,
  isFileDropItem,
} from 'react-aria-components'

import { cn } from '@/shared/lib/cn'

const ACCEPTED_TYPES = ['application/json', 'text/csv'] as const

type TicketsDropzoneProps = {
  className?: string
  onFiles?: (files: File[]) => void
}

function isAccepted(file: File) {
  const name = file.name.toLowerCase()
  return (
    name.endsWith('.json') ||
    name.endsWith('.csv') ||
    ACCEPTED_TYPES.includes(file.type as (typeof ACCEPTED_TYPES)[number])
  )
}

function emitAccepted(files: File[], onFiles?: (files: File[]) => void) {
  const accepted = files.filter(isAccepted)
  if (accepted.length === 0) return
  onFiles?.(accepted)
}

export function TicketsDropzone({ className, onFiles }: TicketsDropzoneProps) {
  return (
    <div className={cn('flex min-h-0 flex-1 p-5 pt-4', className)}>
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
          emitAccepted(files, onFiles)
        }}
        className={cn(
          'flex min-h-0 w-full flex-1 flex-col items-center justify-center rounded-lg border border-dashed border-[#dedee0] bg-[#f5f5f5] px-5 py-5 text-center outline-none transition-colors',
          'data-[drop-target]:border-[#0485f7] data-[drop-target]:bg-[#0485f7]/[0.06]',
          'data-[focus-visible]:outline data-[focus-visible]:outline-2 data-[focus-visible]:-outline-offset-1 data-[focus-visible]:outline-[#0485f7]',
        )}
      >
        <FileTrigger
          acceptedFileTypes={[...ACCEPTED_TYPES]}
          onSelect={(list) => {
            if (!list) return
            emitAccepted(Array.from(list), onFiles)
          }}
        >
          <Button className="flex cursor-pointer flex-col items-center gap-2 bg-transparent outline-none">
            <RiUploadCloud2Line size={24} className="shrink-0 text-[#71717a]" />
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
    </div>
  )
}
