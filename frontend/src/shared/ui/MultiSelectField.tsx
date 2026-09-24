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
      className="inline-flex h-5 max-w-full items-center gap-1 text-xs font-medium leading-5 text-[#18181b]"
      style={{
        borderRadius: 4,
        backgroundColor: '#ebebec',
        padding: '2px 4px',
      }}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <span className="truncate">{label}</span>
      <span
        role="button"
        tabIndex={-1}
        aria-label={`Убрать ${label}`}
        className="inline-flex size-3 shrink-0 cursor-pointer items-center justify-center text-[#71717a] hover:text-[#18181b]"
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
}

/** Мультиселект фильтров: выбранные значения — чипы с крестиком. */
export function MultiSelectField({
  label,
  placeholder,
  options,
  value,
  onChange,
}: MultiSelectFieldProps) {
  return (
    <Select
      className="w-full"
      placeholder={placeholder}
      selectionMode="multiple"
      value={value}
      onChange={(keys) => onChange(keys as string[])}
    >
      <Label className="mb-1 text-sm font-medium leading-6 text-[#18181b]">
        {label}
      </Label>
      <Select.Trigger
        className={cn(
          'flex min-h-9 w-full items-center justify-between gap-2 border border-[#dedee0] bg-white !px-3 !py-2 text-left shadow-none outline-none',
          'data-[focus-visible]:outline data-[focus-visible]:outline-2 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-[#0485f7]',
        )}
        style={{ borderRadius: 8 }}
      >
        <Select.Value className="min-w-0 flex-1">
          {({ defaultChildren, isPlaceholder, state }) => {
            if (isPlaceholder || state.selectedItems.length === 0) {
              return (
                <span className="text-sm leading-5 text-[#71717a]">
                  {defaultChildren}
                </span>
              )
            }

            return (
              <span className="flex flex-wrap gap-1.5 py-0.5">
                {state.selectedItems.map((item) => {
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
              </span>
            )
          }}
        </Select.Value>
        <Select.Indicator className="shrink-0 self-center text-[#71717a]">
          <RiArrowDownSLine size={16} />
        </Select.Indicator>
      </Select.Trigger>
      <Select.Popover
        className="min-w-[240px] border border-[#dedee0] bg-white p-1 shadow-lg outline-none"
        style={{ borderRadius: 16 }}
      >
        <ListBox selectionMode="multiple" className="outline-none">
          {options.map((option) => (
            <ListBox.Item
              key={option}
              id={option}
              textValue={option}
              className="cursor-pointer px-3 py-2 text-sm text-[#18181b] outline-none data-[focused]:bg-[#f5f5f5] data-[selected]:bg-[#0485f7]/[0.08]"
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
