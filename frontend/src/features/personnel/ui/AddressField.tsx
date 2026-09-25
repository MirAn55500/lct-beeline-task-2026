import { useEffect, useId, useRef, useState } from 'react'
import { RiLoader4Line, RiMapPin2Line, RiSearchLine } from '@remixicon/react'

import { useLazySuggestAddressQuery } from '@/features/personnel/api'
import type { AddressSuggestion } from '@/features/personnel/types'
import { cn } from '@/shared/lib/cn'

/** Пауза после последней буквы перед запросом подсказок. */
const DEBOUNCE_MS = 250

type AddressFieldProps = {
  value: string
  /** Адрес выбран из подсказок или на карте — список не нужен. */
  confirmed: boolean
  busy?: boolean
  placeholder?: string
  onType: (text: string) => void
  /** Выбран адрес с домом. */
  onSelect: (suggestion: AddressSuggestion) => void
  /** Подсказок нет — предложить поставить офис на карте. */
  onPickOnMap?: () => void
}

/**
 * Поле адреса с подсказками, как на сайтах доставки: печатаете — под полем адреса
 * Москвы и области; выбрать можно только адрес с домом. Улица без дома подставляется
 * в поле, чтобы дописать номер.
 */
export function AddressField({
  value,
  confirmed,
  busy = false,
  placeholder,
  onType,
  onSelect,
  onPickOnMap,
}: AddressFieldProps) {
  const listId = useId()
  const [suggestAddress, { isFetching }] = useLazySuggestAddressQuery()
  // Подсказки помнят, к какому тексту пришли: к другому тексту их не показываем
  const [result, setResult] = useState<{ query: string; items: AddressSuggestion[] }>({
    query: '',
    items: [],
  })
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)
  const request = useRef(0)

  // Подсказки по последнему тексту; ответы на старый текст отбрасываются
  const query = value.trim()
  useEffect(() => {
    if (confirmed || query.length < 3) return
    const id = ++request.current
    const timer = setTimeout(() => {
      suggestAddress(query, true)
        .unwrap()
        .then((found) => {
          if (request.current !== id) return
          setResult({ query, items: found })
          setActive(-1)
        })
        .catch(() => {
          if (request.current === id) setResult({ query, items: [] })
        })
    }, DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [query, confirmed, suggestAddress])
  // Пока идёт ответ на новую букву, видны прошлые подсказки — список не мигает.
  // «Ничего не нашлось» — только когда пустой ответ пришёл на этот самый текст
  const fresh = result.query === query
  const items = result.items
  const nothing = fresh && items.length === 0

  const choose = (item: AddressSuggestion) => {
    if (item.hasHouse) {
      onSelect(item)
      setOpen(false)
      return
    }
    // Улица без дома — в поле, дописать номер; список подтянется заново
    onType(`${item.address}, `)
    setOpen(true)
    inputRef.current?.focus()
  }

  const showList = open && !confirmed && query.length >= 3 && (items.length > 0 || nothing)

  return (
    <div className="relative">
      <div
        className="flex h-9 w-full items-center gap-2 border border-border bg-surface px-3 focus-within:border-focus"
        style={{ borderRadius: 8 }}
      >
        {busy || isFetching ? (
          <RiLoader4Line size={16} className="shrink-0 animate-spin text-muted" />
        ) : (
          <RiSearchLine size={16} className="shrink-0 text-muted" />
        )}
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-label="Адрес офиса"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          value={value}
          placeholder={placeholder}
          onChange={(event) => {
            onType(event.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={(event) => {
            if (!showList || nothing) return
            if (event.key === 'ArrowDown') {
              event.preventDefault()
              setActive((index) => (index + 1) % items.length)
            } else if (event.key === 'ArrowUp') {
              event.preventDefault()
              setActive((index) => (index <= 0 ? items.length - 1 : index - 1))
            } else if (event.key === 'Enter' && active >= 0) {
              event.preventDefault()
              choose(items[active]!)
            } else if (event.key === 'Escape') {
              setOpen(false)
            }
          }}
          className="h-full min-w-0 flex-1 bg-transparent text-sm leading-5 text-foreground outline-none placeholder:text-muted"
        />
      </div>

      {showList && nothing ? (
        <div
          id={listId}
          className="absolute top-[calc(100%+4px)] right-0 left-0 z-30 flex flex-col gap-1 border border-border bg-surface px-3 py-2 shadow-lg"
          style={{ borderRadius: 12 }}
        >
          <p className="text-sm leading-5 text-foreground">Ничего не нашлось</p>
          <p className="text-xs leading-5 text-muted">
            Проверьте, как пишется улица, или поставьте офис на карте
          </p>
          {onPickOnMap ? (
            <button
              type="button"
              // mousedown: до blur поля, иначе блок закроется раньше клика
              onMouseDown={(event) => {
                event.preventDefault()
                setOpen(false)
                onPickOnMap()
              }}
              className="inline-flex w-fit cursor-pointer items-center gap-1 text-xs font-medium leading-5 text-link hover:underline"
            >
              <RiMapPin2Line size={12} className="shrink-0" />
              Указать на карте
            </button>
          ) : null}
        </div>
      ) : null}

      {showList && !nothing ? (
        <ul
          id={listId}
          role="listbox"
          aria-label="Подсказки адресов"
          className="absolute top-[calc(100%+4px)] right-0 left-0 z-30 max-h-[280px] overflow-y-auto border border-border bg-surface p-1 shadow-lg"
          style={{ borderRadius: 12 }}
        >
          {items.map((item, index) => (
            <li
              key={`${item.address}-${index}`}
              role="option"
              aria-selected={index === active}
              // mousedown, а не click: иначе поле теряет фокус и список закрывается раньше
              onMouseDown={(event) => {
                event.preventDefault()
                choose(item)
              }}
              onMouseEnter={() => setActive(index)}
              className={cn(
                'flex cursor-pointer items-start gap-2 px-2 py-1.5 text-sm leading-5 text-foreground',
                index === active && 'bg-surface-hover',
              )}
              style={{ borderRadius: 8 }}
            >
              <RiMapPin2Line size={16} className="mt-0.5 shrink-0 text-muted" />
              <span className="min-w-0">
                {item.address}
                {item.hasHouse ? null : (
                  <span className="block text-xs leading-5 text-muted">Укажите номер дома</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
