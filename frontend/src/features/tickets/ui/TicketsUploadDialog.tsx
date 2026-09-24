import { useState } from 'react'
import { Dropdown, Tooltip } from '@heroui/react'
import {
  RiArrowDownSLine,
  RiDeleteBinLine,
  RiDownload2Line,
  RiFileTextLine,
  RiInformationLine,
  RiLoopRightLine,
  RiUploadCloud2Line,
} from '@remixicon/react'
import { DropZone, FileTrigger, Button as AriaButton, isFileDropItem } from 'react-aria-components'

import { useGetRegionsQuery } from '@/features/catalogs'
import { cn } from '@/shared/lib/cn'
import { AppModal, AppTooltipContent, FieldLabel, buttonClass } from '@/shared/ui'

import type { UploadTicketsResult } from '../api'
import {
  TICKETS_FILE_TYPES,
  TICKETS_TEMPLATE_SIZE,
  downloadTicketsTemplate,
  formatFileSize,
  isTicketsFile,
} from '../lib/template'
import { useTicketsUpload } from '../lib/useTicketsUpload'

type TicketsUploadDialogProps = {
  isOpen: boolean
  onClose: () => void
  /** Регион из шапки — выбран сразу. */
  defaultRegionId?: number | null
  /** Выбранный день, YYYY-MM-DD: на него вешаются строки без даты. */
  date: string
  onUploaded?: (result: UploadTicketsResult) => void
}

/** Modal «Загрузить заявки»: регион, файл выгрузки, шаблон. */
export function TicketsUploadDialog({ isOpen, onClose, defaultRegionId = null, date, onUploaded }: TicketsUploadDialogProps) {
  const { data: regions = [] } = useGetRegionsQuery()
  const [regionId, setRegionId] = useState<number | null>(defaultRegionId)
  const [file, setFile] = useState<File | null>(null)
  const { upload, isUploading } = useTicketsUpload(onUploaded)
  const [prevOpen, setPrevOpen] = useState(isOpen)

  // Каждое открытие — с чистого листа и регионом из шапки.
  if (prevOpen !== isOpen) {
    setPrevOpen(isOpen)
    if (isOpen) {
      setRegionId(defaultRegionId)
      setFile(null)
    }
  }

  const region = regions.find((item) => item.id === regionId) ?? null
  const canUpload = region != null && file != null && !isUploading

  const pick = (files: File[]) => {
    const next = files.find(isTicketsFile)
    if (next) setFile(next)
  }

  const submit = async () => {
    if (!region || !file) return
    onClose()
    await upload({ file, regionId: region.id, date })
  }

  return (
    <AppModal
      isOpen={isOpen}
      onClose={onClose}
      title="Загрузить заявки"
      description="Новые заявки будут добавлены, существующие из того же источника - обновлены"
      footer={
        <>
          <button type="button" onClick={onClose} className={buttonClass.outline}>
            Отмена
          </button>
          <button type="button" disabled={!canUpload} onClick={() => void submit()} className={buttonClass.primary}>
            Загрузить
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <FieldLabel
            required
            hint={
              <Tooltip delay={200}>
                <Tooltip.Trigger className="inline-flex cursor-help text-[#71717a] outline-none">
                  <RiInformationLine size={12} />
                </Tooltip.Trigger>
                <AppTooltipContent>
                  Все заявки должны относиться к выбранному региону
                </AppTooltipContent>
              </Tooltip>
            }
          >
            Регион
          </FieldLabel>
          <Dropdown>
            <Dropdown.Trigger
              className="flex h-9 w-full cursor-pointer items-center justify-between rounded-[8px] border border-[#dedee0] bg-white pr-3 pl-3 text-sm leading-5 outline-none transition-colors hover:bg-[#fafafa] focus-visible:border-[#0485f7]"
            >
              <span className={cn('truncate', region ? 'text-[#18181b]' : 'text-[#71717a]')}>
                {region?.name ?? 'Выберите регион'}
              </span>
              <RiArrowDownSLine size={16} className="shrink-0 text-[#18181b]" />
            </Dropdown.Trigger>
            <Dropdown.Popover
              placement="bottom start"
              offset={4}
              className="w-[402px] max-w-[calc(100vw-80px)] border-0 bg-white p-1 outline-none"
              style={{ borderRadius: 12, boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)' }}
            >
              <Dropdown.Menu
                aria-label="Регион"
                selectionMode="single"
                selectedKeys={regionId != null ? new Set([String(regionId)]) : new Set()}
                onAction={(key) => setRegionId(Number(key))}
                className="flex flex-col outline-none"
              >
                {regions.map((item) => (
                  <Dropdown.Item
                    key={item.id}
                    id={String(item.id)}
                    textValue={item.name}
                    className="flex h-9 cursor-pointer items-center rounded-[8px] px-3 text-sm leading-5 font-medium text-[#18181b] outline-none data-[focused]:bg-[#f5f5f5] data-[selected]:bg-[#f5f5f5]"
                  >
                    {item.name}
                  </Dropdown.Item>
                ))}
              </Dropdown.Menu>
            </Dropdown.Popover>
          </Dropdown>
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel required>Выгрузка</FieldLabel>
          {file ? (
            <div className="flex items-center gap-3 rounded-[8px] border border-[#dedee0] bg-white p-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-[8px] bg-[#ebebec] text-[#18181b]">
                <RiFileTextLine size={16} />
              </span>
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-xs leading-5 font-medium text-[#18181b]">{file.name}</span>
                <span className="text-xs leading-4 text-[#71717a]">{formatFileSize(file.size)}</span>
              </div>
              <FileTrigger acceptedFileTypes={TICKETS_FILE_TYPES} onSelect={(list) => list && pick(Array.from(list))}>
                <AriaButton
                  aria-label="Заменить файл"
                  className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-[8px] bg-[#ebebec] text-[#18181b] outline-none transition-colors hover:bg-[#e0e0e2]"
                >
                  <RiLoopRightLine size={16} />
                </AriaButton>
              </FileTrigger>
              <button
                type="button"
                aria-label="Убрать файл"
                onClick={() => setFile(null)}
                className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-[8px] bg-[#ff383c]/15 text-[#ff383c] transition-colors hover:bg-[#ff383c]/25"
              >
                <RiDeleteBinLine size={16} />
              </button>
            </div>
          ) : (
            <>
              <DropZone
                aria-label="Выгрузка заявок"
                getDropOperation={() => 'copy'}
                onDrop={async (event) => {
                  const files: File[] = []
                  for (const item of event.items) {
                    if (isFileDropItem(item)) files.push(await item.getFile())
                  }
                  pick(files)
                }}
                className="flex h-[148px] flex-col items-center justify-center rounded-[8px] border border-dashed border-[#dedee0] bg-[#f5f5f5] outline-none transition-colors data-[drop-target]:border-[#0485f7] data-[drop-target]:bg-[#0485f7]/[0.06]"
              >
                <FileTrigger acceptedFileTypes={TICKETS_FILE_TYPES} onSelect={(list) => list && pick(Array.from(list))}>
                  <AriaButton className="flex size-full cursor-pointer flex-col items-center justify-center gap-2 outline-none">
                    <RiUploadCloud2Line size={24} className="text-[#71717a]" />
                    <span className="flex flex-col items-center">
                      <span className="text-base leading-7 font-medium text-[#18181b]">Загрузите заявки</span>
                      <span className="text-xs leading-5 text-[#71717a]">
                        Нажмите на это поле или перетащите
                        <br />в него csv или json файл
                      </span>
                    </span>
                  </AriaButton>
                </FileTrigger>
              </DropZone>
              <button
                type="button"
                onClick={downloadTicketsTemplate}
                className="flex h-9 cursor-pointer items-center gap-2 self-start text-sm leading-5 font-medium text-[#18181b] transition-colors hover:text-[#0485f7]"
              >
                <RiDownload2Line size={16} />
                Скачать шаблон ({TICKETS_TEMPLATE_SIZE})
              </button>
            </>
          )}
        </div>
      </div>
    </AppModal>
  )
}
