import { Dropdown } from '@heroui/react'
import {
  RiAddCircleLine,
  RiArrowDownSLine,
  RiDownload2Line,
  RiFileTextLine,
} from '@remixicon/react'
import { Separator } from 'react-aria-components'

import { cn } from '@/shared/lib/cn'
import { AppPanel } from '@/shared/ui'

export type PersonnelTab = 'engineers'
export type EngineersExportFormat = 'csv' | 'json'

const MENU_ITEM =
  'flex h-9 cursor-pointer items-center gap-2 px-3 text-sm font-medium leading-5 text-foreground outline-none data-[focused]:bg-surface-hover'

type PersonnelHeaderProps = {
  /** Название выбранной бригады. */
  title: string
  onAddEngineer: () => void
  onExport: (format: EngineersExportFormat) => void
}

export function PersonnelHeader({
  title,
  onAddEngineer,
  onExport,
}: PersonnelHeaderProps) {
  return (
    <AppPanel className="flex h-[60px] shrink-0 items-center justify-between gap-4 p-3">
      <h1 className="min-w-0 truncate px-1 text-xl font-semibold leading-7 text-foreground">
        {title}
      </h1>

      <div className="flex shrink-0 justify-end">
        <div
          className="inline-flex h-9 items-center overflow-hidden bg-accent text-accent-foreground"
          style={{ borderRadius: 8 }}
        >
          <button
            type="button"
            onClick={onAddEngineer}
            className="h-full cursor-pointer px-4 text-sm font-medium leading-5 transition-colors hover:bg-accent-hover"
          >
            Инженеры
          </button>
          <span aria-hidden className="h-5 w-px bg-surface/40" />
          <Dropdown>
            <Dropdown.Trigger
              aria-label="Действия с инженерами"
              className="flex size-9 cursor-pointer items-center justify-center bg-transparent text-accent-foreground outline-none transition-colors hover:bg-accent-hover data-[pressed]:bg-accent-hover"
            >
              <RiArrowDownSLine size={16} />
            </Dropdown.Trigger>
            <Dropdown.Popover
              placement="bottom end"
              offset={8}
              className="w-[193px] border-0 bg-surface p-1 outline-none"
              style={{
                borderRadius: 12,
                boxShadow:
                  '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)',
              }}
            >
              <Dropdown.Menu
                aria-label="Действия с инженерами"
                className="flex flex-col outline-none"
                onAction={(key) => {
                  if (key === 'add') onAddEngineer()
                  else if (key === 'csv' || key === 'json') onExport(key)
                }}
              >
                <Dropdown.Item
                  id="csv"
                  textValue="Экспорт csv"
                  className={MENU_ITEM}
                  style={{ borderRadius: 8 }}
                >
                  <RiFileTextLine size={16} className="shrink-0 text-muted" />
                  Экспорт csv
                </Dropdown.Item>
                <Dropdown.Item
                  id="json"
                  textValue="Экспорт json"
                  className={MENU_ITEM}
                  style={{ borderRadius: 8 }}
                >
                  <RiDownload2Line size={16} className="shrink-0 text-muted" />
                  Экспорт json
                </Dropdown.Item>
                <Separator className="mx-2 my-1 h-px border-0 bg-separator" />
                <Dropdown.Item
                  id="add"
                  textValue="Добавить"
                  className={cn(MENU_ITEM, 'justify-center')}
                  style={{ borderRadius: 8 }}
                >
                  <RiAddCircleLine size={16} className="shrink-0" />
                  Добавить
                </Dropdown.Item>
              </Dropdown.Menu>
            </Dropdown.Popover>
          </Dropdown>
        </div>
      </div>
    </AppPanel>
  )
}
