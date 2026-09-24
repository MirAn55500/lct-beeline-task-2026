import { useEffect, useState } from 'react'
import { Checkbox, Popover } from '@heroui/react'
import { RiEqualizer2Line } from '@remixicon/react'

import {
  QUALIFICATION_LABEL,
  QUALIFICATION_ORDER,
  type QualificationCode,
} from '@/features/personnel/mocks'
import { cn } from '@/shared/lib/cn'
import { MultiSelectField } from '@/shared/ui'

export type EngineersFiltersState = {
  qualifications: QualificationCode[]
  skills: string[]
  transports: string[]
}

export const EMPTY_ENGINEERS_FILTERS: EngineersFiltersState = {
  qualifications: [],
  skills: [],
  transports: [],
}

function QualificationCheckbox({
  code,
  isSelected,
  onChange,
}: {
  code: QualificationCode
  isSelected: boolean
  onChange: (next: boolean) => void
}) {
  return (
    <Checkbox isSelected={isSelected} onChange={onChange} className="w-full">
      <Checkbox.Content className="flex w-full items-center gap-2">
        <Checkbox.Control
          className="before:!rounded-[4px]"
          style={{
            borderRadius: 4,
            borderWidth: 1,
            borderStyle: 'solid',
            borderColor: isSelected ? 'var(--accent)' : '#dedee0',
            ['--field-background' as string]: isSelected ? 'var(--accent)' : '#ffffff',
            ['--field-shadow' as string]: '0 0 #0000',
          }}
        >
          <Checkbox.Indicator className="!size-2.5">
            {({ isSelected: checked }) =>
              checked ? (
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
        <span className="text-sm leading-6 text-[#18181b]">
          {QUALIFICATION_LABEL[code]}
        </span>
      </Checkbox.Content>
    </Checkbox>
  )
}

type EngineersFiltersPopoverProps = {
  value: EngineersFiltersState
  onChange: (next: EngineersFiltersState) => void
  skillOptions: string[]
  transportOptions: string[]
}

export function EngineersFiltersPopover({
  value,
  onChange,
  skillOptions,
  transportOptions,
}: EngineersFiltersPopoverProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<EngineersFiltersState>(value)

  useEffect(() => {
    if (open) setDraft(value)
  }, [open, value])

  const filtersActive =
    value.qualifications.length > 0 || value.skills.length > 0 || value.transports.length > 0

  const toggleQualification = (code: QualificationCode, next: boolean) =>
    setDraft((prev) => ({
      ...prev,
      qualifications: next
        ? [...prev.qualifications, code]
        : prev.qualifications.filter((item) => item !== code),
    }))

  return (
    <Popover isOpen={open} onOpenChange={setOpen}>
      <Popover.Trigger
        aria-label={filtersActive ? 'Фильтры, есть выбранные' : 'Фильтры'}
        className={cn(
          'inline-flex h-9 shrink-0 cursor-pointer items-center gap-2 border border-[#dedee0] text-sm font-medium leading-5 text-[#18181b] transition-colors outline-none',
          open ? 'bg-[#ebebec]' : 'bg-white hover:bg-[#f5f5f5]',
        )}
        style={{ borderRadius: 8, padding: '8px 16px' }}
      >
        <span className="relative inline-flex size-4 shrink-0">
          <RiEqualizer2Line size={16} className="text-[#18181b]" />
          {filtersActive ? (
            <span
              aria-hidden
              className="absolute"
              style={{
                top: 0,
                right: 1,
                width: 4,
                height: 4,
                borderRadius: 999,
                backgroundColor: '#ef2c56',
                boxShadow: '0 0 0 1px #ffffff',
              }}
            />
          ) : null}
        </span>
        Фильтры
      </Popover.Trigger>

      <Popover.Content
        placement="bottom start"
        offset={8}
        className="w-[369px] border-0 bg-white p-0 text-[#18181b] outline-none"
        style={{
          borderRadius: 16,
          boxShadow:
            '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)',
        }}
      >
        <Popover.Dialog className="p-0 outline-none" style={{ borderRadius: 16 }}>
          <div className="flex flex-col" style={{ padding: '12px 20px 20px' }}>
            <Popover.Heading className="text-base font-semibold leading-6 text-[#18181b]">
              Фильтрация
            </Popover.Heading>
            <p className="text-sm leading-6 text-[#71717a]" style={{ marginTop: 4 }}>
              Найдите подходящего инженера
            </p>

            <div className="flex flex-col" style={{ marginTop: 16, gap: 16 }}>
              <div className="flex flex-col" style={{ gap: 8 }}>
                <span className="text-sm font-medium leading-6 text-[#18181b]">
                  Квалификация
                </span>
                <div className="flex flex-col" style={{ gap: 8 }}>
                  {QUALIFICATION_ORDER.map((code) => (
                    <QualificationCheckbox
                      key={code}
                      code={code}
                      isSelected={draft.qualifications.includes(code)}
                      onChange={(next) => toggleQualification(code, next)}
                    />
                  ))}
                </div>
              </div>

              <MultiSelectField
                label="Навыки"
                placeholder="Выберите навык"
                options={skillOptions}
                value={draft.skills}
                onChange={(skills) => setDraft((prev) => ({ ...prev, skills }))}
              />
              <MultiSelectField
                label="Транспорт"
                placeholder="Выберите транспорт"
                options={transportOptions}
                value={draft.transports}
                onChange={(transports) =>
                  setDraft((prev) => ({ ...prev, transports }))
                }
              />
            </div>

            <div className="flex" style={{ marginTop: 16, gap: 12 }}>
              <button
                type="button"
                className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center border border-[#dedee0] bg-white text-sm font-medium leading-5 text-[#18181b] transition-colors hover:bg-[#f5f5f5]"
                style={{ borderRadius: 8, padding: '8px 16px' }}
                onClick={() => setDraft(EMPTY_ENGINEERS_FILTERS)}
              >
                Сбросить
              </button>
              <button
                type="button"
                className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center bg-[#0485f7] text-sm font-medium leading-5 text-[#fcfcfc] transition-colors hover:bg-[#0374d9]"
                style={{ borderRadius: 8, padding: '8px 16px' }}
                onClick={() => {
                  onChange(draft)
                  setOpen(false)
                }}
              >
                Применить
              </button>
            </div>
          </div>
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  )
}
