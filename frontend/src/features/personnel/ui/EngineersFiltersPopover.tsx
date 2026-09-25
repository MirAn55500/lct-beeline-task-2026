import { useEffect, useState } from 'react'
import { Checkbox, Popover } from '@heroui/react'
import { RiEqualizer2Line } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'
import { MultiSelectField } from '@/shared/ui'

export type EngineersFiltersState = {
  qualifications: string[]
  skills: string[]
  transports: string[]
}

export const EMPTY_ENGINEERS_FILTERS: EngineersFiltersState = {
  qualifications: [],
  skills: [],
  transports: [],
}

type EngineersFiltersPopoverProps = {
  value: EngineersFiltersState
  onChange: (next: EngineersFiltersState) => void
  qualificationOptions: string[]
  skillOptions: string[]
  transportOptions: string[]
}

export function EngineersFiltersPopover({
  value,
  onChange,
  qualificationOptions,
  skillOptions,
  transportOptions,
}: EngineersFiltersPopoverProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<EngineersFiltersState>(value)

  useEffect(() => {
    if (open) setDraft(value)
  }, [open, value])

  const filtersActive =
    value.qualifications.length > 0 ||
    value.skills.length > 0 ||
    value.transports.length > 0

  const toggleQualification = (label: string) =>
    setDraft((prev) => ({
      ...prev,
      qualifications: prev.qualifications.includes(label)
        ? prev.qualifications.filter((item) => item !== label)
        : [...prev.qualifications, label],
    }))

  return (
    <Popover isOpen={open} onOpenChange={setOpen}>
      <Popover.Trigger
        aria-label={filtersActive ? 'Фильтры, есть выбранные' : 'Фильтры'}
        className={cn(
          'inline-flex h-9 shrink-0 cursor-pointer items-center gap-2 border border-border text-sm font-medium leading-5 text-foreground transition-colors outline-none',
          open ? 'bg-surface-tertiary' : 'bg-surface hover:bg-surface-hover',
        )}
        style={{ borderRadius: 8, padding: '8px 16px' }}
      >
        <span className="relative inline-flex size-4 shrink-0">
          <RiEqualizer2Line size={16} className="text-foreground" />
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
                backgroundColor: 'var(--danger)',
                boxShadow: '0 0 0 1px var(--surface)',
              }}
            />
          ) : null}
        </span>
        Фильтры
      </Popover.Trigger>

      <Popover.Content
        placement="bottom start"
        offset={8}
        className="w-[369px] border-0 bg-surface p-0 text-foreground outline-none"
        style={{
          borderRadius: 16,
          boxShadow:
            '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)',
        }}
      >
        <Popover.Dialog className="p-0 outline-none" style={{ borderRadius: 16 }}>
          {/* padding body по Figma: 8 / 12 / 12 */}
          <div className="flex flex-col" style={{ padding: '8px 12px 12px' }}>
            <Popover.Heading className="text-base font-semibold leading-6 text-foreground">
              Фильтрация
            </Popover.Heading>
            <p className="text-sm leading-6 text-muted" style={{ marginTop: 4 }}>
              Найдите подходящего инженера
            </p>

            <div className="flex flex-col" style={{ marginTop: 16, gap: 16 }}>
              <div className="flex flex-col gap-1">
                <span className="text-sm font-medium leading-6 text-foreground">
                  Квалификация
                </span>
                <div className="flex flex-col gap-2">
                  {qualificationOptions.map((label) => (
                    <Checkbox
                      key={label}
                      isSelected={draft.qualifications.includes(label)}
                      onChange={() => toggleQualification(label)}
                    >
                      <Checkbox.Content className="flex cursor-pointer items-center gap-2">
                        <Checkbox.Control
                          className="before:!rounded-[4px]"
                          style={{
                            borderRadius: 4,
                            borderWidth: 1,
                            borderStyle: 'solid',
                            borderColor: draft.qualifications.includes(label)
                              ? 'var(--accent)'
                              : 'var(--field-border)',
                            ['--field-background' as string]:
                              draft.qualifications.includes(label)
                                ? 'var(--accent)'
                                : 'var(--field-background)',
                            ['--field-shadow' as string]: '0 0 #0000',
                          }}
                        >
                          <Checkbox.Indicator />
                        </Checkbox.Control>
                        <span className="text-sm leading-6 text-foreground">
                          {label}
                        </span>
                      </Checkbox.Content>
                    </Checkbox>
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
                className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center border border-border bg-surface text-sm font-medium leading-5 text-foreground transition-colors hover:bg-surface-hover"
                style={{ borderRadius: 8, padding: '8px 16px' }}
                onClick={() => setDraft(EMPTY_ENGINEERS_FILTERS)}
              >
                Сбросить
              </button>
              <button
                type="button"
                className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center bg-accent text-sm font-medium leading-5 text-accent-foreground transition-colors hover:bg-accent-hover"
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
