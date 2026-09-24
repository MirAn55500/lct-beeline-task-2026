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

export type PersonnelTab = 'info' | 'engineers'
export type EngineersExportFormat = 'csv' | 'json'

const TABS: { id: PersonnelTab; label: string }[] = [
  { id: 'info', label: 'Информация' },
  { id: 'engineers', label: 'Инженеры' },
]

const MENU_ITEM =
  'flex h-9 cursor-pointer items-center gap-2 px-3 text-sm font-medium leading-5 text-[#18181b] outline-none data-[focused]:bg-[#f5f5f5]'

type PersonnelHeaderProps = {
  tab: PersonnelTab
  onTabChange: (tab: PersonnelTab) => void
  onAddEngineer: () => void
  onExport: (format: EngineersExportFormat) => void
}

export function PersonnelHeader({
  tab,
  onTabChange,
  onAddEngineer,
  onExport,
}: PersonnelHeaderProps) {
  return (
    <AppPanel className="grid h-[60px] shrink-0 grid-cols-[1fr_334px_1fr] items-center gap-4 p-3">
      <h1 className="truncate px-1 text-xl font-semibold leading-7 text-[#18181b]">
        Бригада
      </h1>

      <div
        role="tablist"
        aria-label="Раздел бригады"
        className="flex h-9 items-center bg-[#ebebec]"
        style={{ borderRadius: 8, padding: 2 }}
      >
        {TABS.map((item) => {
          const active = item.id === tab
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onTabChange(item.id)}
              className={cn(
                'h-8 flex-1 cursor-pointer text-sm font-medium leading-6 transition-colors',
                active
                  ? 'bg-white text-[#18181b] shadow-[0_1px_2px_rgb(0_0_0/0.06)]'
                  : 'text-[#71717a] hover:text-[#18181b]',
              )}
              style={{ borderRadius: 6 }}
            >
              {item.label}
            </button>
          )
        })}
      </div>

      <div className="flex justify-end">
        <div
          className="inline-flex h-9 items-center overflow-hidden bg-[#0485f7] text-[#fcfcfc]"
          style={{ borderRadius: 8 }}
        >
          <button
            type="button"
            onClick={onAddEngineer}
            className="h-full cursor-pointer px-4 text-sm font-medium leading-5 transition-colors hover:bg-[#0374d9]"
          >
            Инженеры
          </button>
          <span aria-hidden className="h-5 w-px bg-[#fcfcfc]/40" />
          <Dropdown>
            <Dropdown.Trigger
              aria-label="Действия с инженерами"
              className="flex size-9 cursor-pointer items-center justify-center bg-transparent text-[#fcfcfc] outline-none transition-colors hover:bg-[#0374d9] data-[pressed]:bg-[#0374d9]"
            >
              <RiArrowDownSLine size={16} />
            </Dropdown.Trigger>
            <Dropdown.Popover
              placement="bottom end"
              offset={8}
              className="w-[193px] border-0 bg-white p-1 outline-none"
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
                  else onExport(key as EngineersExportFormat)
                }}
              >
                <Dropdown.Item id="csv" textValue="Экспорт csv" className={MENU_ITEM} style={{ borderRadius: 8 }}>
                  <RiFileTextLine size={16} className="shrink-0 text-[#71717a]" />
                  Экспорт csv
                </Dropdown.Item>
                <Dropdown.Item id="json" textValue="Экспорт json" className={MENU_ITEM} style={{ borderRadius: 8 }}>
                  <RiDownload2Line size={16} className="shrink-0 text-[#71717a]" />
                  Экспорт json
                </Dropdown.Item>
                <Separator className="mx-2 my-1 h-px border-0 bg-[#e4e4e7]" />
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
