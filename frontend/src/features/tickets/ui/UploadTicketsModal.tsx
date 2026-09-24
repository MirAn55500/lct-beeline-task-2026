import { useEffect, useState } from 'react'
import {
  ListBox,
  Modal,
  Select,
  Tooltip,
  useOverlayState,
} from '@heroui/react'
import {
  RiArrowDownSLine,
  RiCloseLine,
  RiDeleteBinLine,
  RiDownloadLine,
  RiFileList3Line,
  RiInformationLine,
  RiRefreshLine,
  RiUploadCloud2Line,
} from '@remixicon/react'
import {
  Button,
  DropZone,
  FileTrigger,
  Text,
  isFileDropItem,
} from 'react-aria-components'

import { useGetRegionsQuery } from '@/features/catalogs'
import { isAcceptedTicketFile } from '@/features/tickets/ui/TicketsDropzone'
import { cn } from '@/shared/lib/cn'
import { pluralRu } from '@/shared/lib/text'
import { AppTooltipContent } from '@/shared/ui'

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`
}

type UploadTicketsModalProps = {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  /** Регион из шапки — предвыбор в форме. */
  defaultRegionId: number | null
  date: string
  isUploading?: boolean
  onUpload: (args: {
    file: File
    regionId: number
  }) => Promise<void>
}

export function UploadTicketsModal({
  isOpen,
  onOpenChange,
  defaultRegionId,
  date: _date,
  isUploading = false,
  onUpload,
}: UploadTicketsModalProps) {
  const state = useOverlayState({
    isOpen,
    onOpenChange: (next) => {
      if (!next && isUploading) return
      onOpenChange(next)
    },
  })
  const { data: regions = [], isLoading: regionsLoading } = useGetRegionsQuery()
  const [regionId, setRegionId] = useState<number | null>(defaultRegionId)
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!isOpen) return
    setRegionId(defaultRegionId)
    setFile(null)
    setSubmitting(false)
  }, [isOpen, defaultRegionId])

  useEffect(() => {
    if (regionId != null) return
    if (regions.length === 0) return
    setRegionId(regions[0]!.id)
  }, [regionId, regions])

  const uploading = isUploading || submitting
  const canSubmit = regionId != null && file != null && !uploading

  const acceptFiles = (files: File[]) => {
    const next = files.find(isAcceptedTicketFile)
    if (!next) return false
    setFile(next)
    return true
  }

  const submit = async () => {
    if (regionId == null || file == null || uploading) return
    setSubmitting(true)
    try {
      await onUpload({ file, regionId })
      onOpenChange(false)
    } catch {
      // Ошибка уже в toast; закрываем модалку — повтор через «Повторить».
      onOpenChange(false)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal state={state}>
      <Modal.Backdrop
        isDismissable={!uploading}
        className="bg-black/40"
        style={{ backdropFilter: 'blur(4px)' }}
      >
        <Modal.Container placement="center" className="p-4">
          <Modal.Dialog
            className="flex w-full max-w-[480px] flex-col overflow-hidden bg-white outline-none"
            style={{ borderRadius: 16 }}
          >
            <Modal.Header className="relative flex flex-col gap-1 px-5 pt-5 pb-0">
              <Modal.Heading className="pr-10 text-xl font-semibold leading-7 text-[#18181b]">
                Загрузить заявки
              </Modal.Heading>
              <p className="pr-10 text-sm leading-6 text-[#71717a]">
                Новые заявки будут добавлены, существующие из того же источника —
                обновлены
              </p>
              <Modal.CloseTrigger
                aria-label="Закрыть"
                isDisabled={uploading}
                className="absolute top-4 right-4 flex size-8 cursor-pointer items-center justify-center text-[#71717a] transition-colors hover:bg-[#f5f5f5] disabled:cursor-not-allowed disabled:opacity-40"
                style={{ borderRadius: 8 }}
              >
                <RiCloseLine size={16} />
              </Modal.CloseTrigger>
            </Modal.Header>

            <Modal.Body className="flex flex-col gap-4 px-5 py-4">
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-1">
                  <span className="text-sm font-medium leading-6 text-[#18181b]">
                    Регион
                  </span>
                  <span className="text-sm font-medium text-[#ef2c56]">*</span>
                  <Tooltip delay={200}>
                    <Tooltip.Trigger
                      aria-label="Подсказка по региону"
                      className="inline-flex cursor-help text-[#71717a] outline-none"
                    >
                      <RiInformationLine size={16} />
                    </Tooltip.Trigger>
                    <AppTooltipContent>
                      Все заявки должны относиться к выбранному региону
                    </AppTooltipContent>
                  </Tooltip>
                </div>
                <Select
                  aria-label="Регион"
                  className="w-full"
                  placeholder={
                    regionsLoading ? 'Загрузка регионов…' : 'Выберите регион'
                  }
                  value={regionId}
                  onChange={(key) => {
                    if (key != null) setRegionId(Number(key))
                  }}
                  isDisabled={uploading || regions.length === 0}
                >
                  <Select.Trigger
                    className={cn(
                      'flex h-9 w-full items-center justify-between gap-2 border border-[#dedee0] bg-white text-left shadow-none outline-none',
                      'data-[focus-visible]:outline data-[focus-visible]:outline-2 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-[#0485f7]',
                    )}
                    style={{ borderRadius: 8, padding: '8px 12px' }}
                  >
                    <Select.Value className="min-w-0 flex-1 truncate text-sm leading-5 text-[#18181b] data-[placeholder]:text-[#71717a]" />
                    <Select.Indicator className="shrink-0 text-[#18181b]">
                      <RiArrowDownSLine size={16} />
                    </Select.Indicator>
                  </Select.Trigger>
                  <Select.Popover
                    className="min-w-[240px] border border-[#dedee0] bg-white p-1 shadow-lg outline-none"
                    style={{ borderRadius: 16 }}
                  >
                    <ListBox className="outline-none">
                      {regions.map((region) => (
                        <ListBox.Item
                          key={region.id}
                          id={region.id}
                          textValue={region.name}
                          className="cursor-pointer px-3 py-2 text-sm text-[#18181b] outline-none data-[focused]:bg-[#f5f5f5] data-[selected]:bg-[#0485f7]/[0.08]"
                          style={{ borderRadius: 8 }}
                        >
                          {region.name}
                          <ListBox.ItemIndicator />
                        </ListBox.Item>
                      ))}
                    </ListBox>
                  </Select.Popover>
                </Select>
              </div>

              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-1">
                  <span className="text-sm font-medium leading-6 text-[#18181b]">
                    Выгрузка
                  </span>
                  <span className="text-sm font-medium text-[#ef2c56]">*</span>
                </div>

                {file ? (
                  <div
                    className="flex items-center gap-3 border border-[#dedee0] bg-white p-3"
                    style={{ borderRadius: 8 }}
                  >
                    <span
                      className="flex size-8 shrink-0 items-center justify-center bg-[#ebebec] text-[#18181b]"
                      style={{ borderRadius: 8 }}
                    >
                      <RiFileList3Line size={16} />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate text-xs font-medium leading-5 text-[#18181b]">
                        {file.name}
                      </span>
                      <span className="text-xs leading-4 text-[#71717a]">
                        {formatFileSize(file.size)}
                      </span>
                    </span>
                    <FileTrigger
                      acceptedFileTypes={[
                        '.csv',
                        'text/csv',
                        '.json',
                        'application/json',
                      ]}
                      onSelect={(list) => {
                        if (!list) return
                        acceptFiles(Array.from(list))
                      }}
                    >
                      <Button
                        aria-label="Заменить файл"
                        isDisabled={uploading}
                        className="flex size-8 shrink-0 cursor-pointer items-center justify-center border border-[#dedee0] bg-white text-[#18181b] outline-none transition-colors hover:bg-[#f5f5f5] disabled:cursor-not-allowed disabled:opacity-40"
                        style={{ borderRadius: 8 }}
                      >
                        <RiRefreshLine size={16} />
                      </Button>
                    </FileTrigger>
                    <button
                      type="button"
                      aria-label="Удалить файл"
                      disabled={uploading}
                      onClick={() => setFile(null)}
                      className="flex size-8 shrink-0 cursor-pointer items-center justify-center bg-[#ff383c]/15 text-[#ff383c] transition-colors hover:bg-[#ff383c]/25 disabled:cursor-not-allowed disabled:opacity-40"
                      style={{ borderRadius: 8 }}
                    >
                      <RiDeleteBinLine size={16} />
                    </button>
                  </div>
                ) : (
                  <DropZone
                    aria-label="Загрузка файла заявок"
                    getDropOperation={() => 'copy'}
                    isDisabled={uploading}
                    onDrop={async (event) => {
                      const files: File[] = []
                      for (const item of event.items) {
                        if (isFileDropItem(item)) {
                          files.push(await item.getFile())
                        }
                      }
                      acceptFiles(files)
                    }}
                    className={cn(
                      'flex w-full flex-col items-center justify-center border border-dashed border-[#dedee0] bg-[#f5f5f5] px-5 py-8 text-center outline-none transition-colors',
                      'data-[drop-target]:border-[#0485f7] data-[drop-target]:bg-[#0485f7]/[0.06]',
                      'data-[focus-visible]:outline data-[focus-visible]:outline-2 data-[focus-visible]:-outline-offset-1 data-[focus-visible]:outline-[#0485f7]',
                    )}
                    style={{ borderRadius: 8 }}
                  >
                    <FileTrigger
                      acceptedFileTypes={[
                        '.csv',
                        'text/csv',
                        '.json',
                        'application/json',
                      ]}
                      onSelect={(list) => {
                        if (!list) return
                        acceptFiles(Array.from(list))
                      }}
                    >
                      <Button className="flex cursor-pointer flex-col items-center gap-2 bg-transparent outline-none">
                        <RiUploadCloud2Line
                          size={24}
                          className="shrink-0 text-[#71717a]"
                        />
                        <div className="flex max-w-[360px] flex-col items-center">
                          <Text
                            slot="label"
                            className="text-base font-medium leading-6 text-[#18181b]"
                          >
                            Загрузите заявки
                          </Text>
                          <span className="text-xs leading-5 text-[#71717a]">
                            Нажмите на это поле или перетащите
                            <br />в него csv или json файл
                          </span>
                        </div>
                      </Button>
                    </FileTrigger>
                  </DropZone>
                )}

                {!file ? (
                  <div className="flex flex-wrap gap-2 pt-1">
                    <a
                      href="/templates/tickets-template.csv"
                      download="tickets-template.csv"
                      className="inline-flex h-9 cursor-pointer items-center gap-2 text-sm font-medium leading-5 text-[#0485f7] transition-colors hover:text-[#0374d9]"
                    >
                      <RiDownloadLine size={16} className="shrink-0" />
                      Скачать шаблон csv
                    </a>
                    <a
                      href="/templates/tickets-template.json"
                      download="tickets-template.json"
                      className="inline-flex h-9 cursor-pointer items-center gap-2 text-sm font-medium leading-5 text-[#0485f7] transition-colors hover:text-[#0374d9]"
                    >
                      <RiDownloadLine size={16} className="shrink-0" />
                      json
                    </a>
                  </div>
                ) : (
                  <p className="pt-1 text-xs leading-5 text-[#71717a]">
                    Файл формата csv или json
                  </p>
                )}
              </div>
            </Modal.Body>

            <Modal.Footer className="flex justify-end gap-3 px-5 pt-0 pb-5">
              <button
                type="button"
                disabled={uploading}
                onClick={() => onOpenChange(false)}
                className="inline-flex h-9 cursor-pointer items-center justify-center border border-[#dedee0] bg-white px-4 text-sm font-medium leading-5 text-[#18181b] transition-colors hover:bg-[#f5f5f5] disabled:cursor-not-allowed disabled:opacity-40"
                style={{ borderRadius: 8 }}
              >
                Отмена
              </button>
              <button
                type="button"
                disabled={!canSubmit}
                onClick={() => void submit()}
                className="inline-flex h-9 cursor-pointer items-center justify-center bg-[#0485f7] px-4 text-sm font-medium leading-5 text-[#fcfcfc] transition-colors hover:bg-[#0374d9] disabled:cursor-not-allowed disabled:bg-[#0485f7]/40"
                style={{ borderRadius: 8 }}
              >
                {uploading ? 'Загружаем…' : 'Загрузить'}
              </button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  )
}

/** Текст успешного тоста по ответу upload. */
export function uploadSuccessDescription(created: number, updated: number) {
  return `Добавлено ${created} ${pluralRu(created, ['заявка', 'заявки', 'заявок'])}, обновлено: ${updated}`
}
