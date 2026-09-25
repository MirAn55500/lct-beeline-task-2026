import type { ReactNode } from 'react'
import { Label, ListBox, Select } from '@heroui/react'
import { RiArrowDownSLine, RiCloseLine } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'

function FilterChip({
  label,
  onRemove,
}: {
  label: string
  onRemove: () => void
}) {
  return (
    <span
      className="inline-flex h-5 max-w-full items-center gap-1 text-xs font-medium leading-5 text-foreground"
      style={{
        borderRadius: 4,
        backgroundColor: 'var(--surface-tertiary)',
        padding: '2px 4px',
      }}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <span className="truncate">{label}</span>
      <span
        role="button"
        tabIndex={-1}
        aria-label={`Убрать ${label}`}
        className="inline-flex size-3 shrink-0 cursor-pointer items-center justify-center text-muted hover:text-foreground"
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          onRemove()
        }}
      >
        <RiCloseLine size={12} />
      </span>
    </span>
  )
}

type MultiSelectFieldProps = {
  label: string
  placeholder: string
  options: readonly string[]
  value: string[]
  onChange: (next: string[]) => void
  /** Что встать после подписи: звёздочка обязательного поля, значок подсказки. */
  labelAddon?: ReactNode
  /** Сколько чипов показать; остальные — счётчиком «+N». */
  maxVisible?: number
}

/** Мультиселект фильтров: выбранные значения — чипы с крестиком. */
export function MultiSelectField({
  label,
  placeholder,
  options,
  value,
  onChange,
  labelAddon,
  maxVisible,
}: MultiSelectFieldProps) {
  return (
    <Select
      className="w-full"
      placeholder={placeholder}
      selectionMode="multiple"
      value={value}
      onChange={(keys) => onChange(keys as string[])}
    >
      <div className="mb-1 flex items-center gap-1">
        <Label className="text-sm font-medium leading-6 text-foreground">{label}</Label>
        {labelAddon}
      </div>
      <Select.Trigger
        className={cn(
          'flex min-h-9 w-full items-center justify-between gap-2 border border-border bg-surface !px-3 !py-2 text-left shadow-none outline-none',
          'data-[focus-visible]:outline data-[focus-visible]:outline-2 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-focus',
        )}
        style={{ borderRadius: 8 }}
      >
        <Select.Value className="min-w-0 flex-1">
          {({ defaultChildren, isPlaceholder, state }) => {
            if (isPlaceholder || state.selectedItems.length === 0) {
              return (
                <span className="text-sm leading-5 text-muted">
                  {defaultChildren}
                </span>
              )
            }

            const hidden =
              maxVisible != null ? Math.max(0, state.selectedItems.length - maxVisible) : 0
            const shown = hidden > 0 ? state.selectedItems.slice(0, maxVisible) : state.selectedItems
            return (
              <span className="flex flex-wrap items-center gap-1.5 py-0.5">
                {shown.map((item) => {
                  const id = String(item.key)
                  return (
                    <FilterChip
                      key={id}
                      label={item.textValue || id}
                      onRemove={() =>
                        onChange(value.filter((entry) => entry !== id))
                      }
                    />
                  )
                })}
                {hidden > 0 ? (
                  <span className="text-xs font-medium leading-5 text-muted">+{hidden}</span>
                ) : null}
              </span>
            )
          }}
        </Select.Value>
        <Select.Indicator className="shrink-0 self-center text-muted">
          <RiArrowDownSLine size={16} />
        </Select.Indicator>
      </Select.Trigger>
      <Select.Popover
        className="min-w-[240px] border border-border bg-surface p-1 shadow-lg outline-none"
        style={{ borderRadius: 16 }}
      >
        <ListBox selectionMode="multiple" className="outline-none">
          {options.map((option) => (
            <ListBox.Item
              key={option}
              id={option}
              textValue={option}
              className="cursor-pointer px-3 py-2 text-sm text-foreground outline-none data-[focused]:bg-surface-hover data-[selected]:bg-surface-hover"
              style={{ borderRadius: 8 }}
            >
              {option}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  )
}
