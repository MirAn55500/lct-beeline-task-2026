import { useEffect, useState, type RefObject } from 'react'
import { Dropdown } from '@heroui/react'
import { RiArrowDownSLine, RiArrowLeftSLine, RiArrowRightSLine } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'

import { TICKET_SORT_LABEL as SORT_LABEL, type TicketSortKey } from '../lib/ticketSort'

const MENU_ITEM =
  'flex h-9 cursor-pointer items-center gap-2 px-3 text-sm font-medium leading-5 text-foreground outline-none data-[focused]:bg-surface-hover data-[selected]:bg-surface-hover'

export function TicketSortMenu({
  value,
  onChange,
}: {
  value: TicketSortKey
  onChange: (key: TicketSortKey) => void
}) {
  return (
    <Dropdown>
      <Dropdown.Trigger
        className="flex h-8 shrink-0 cursor-pointer items-center gap-1 px-3 text-sm leading-5 font-medium text-foreground outline-none transition-colors hover:bg-surface-hover data-[pressed]:bg-surface-hover"
        style={{ borderRadius: 8 }}
      >
        Сортировать по
        <RiArrowDownSLine size={16} />
      </Dropdown.Trigger>
      <Dropdown.Popover
        placement="bottom start"
        offset={8}
        className="w-[220px] border-0 bg-surface p-1 outline-none"
        style={{
          borderRadius: 12,
          boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)',
        }}
      >
        <Dropdown.Menu
          aria-label="Сортировка"
          selectionMode="single"
          selectedKeys={new Set([value])}
          onAction={(key) => onChange(key as TicketSortKey)}
          className="flex flex-col outline-none"
        >
          {(Object.keys(SORT_LABEL) as TicketSortKey[]).map((key) => (
            <Dropdown.Item
              key={key}
              id={key}
              textValue={SORT_LABEL[key]}
              className={MENU_ITEM}
              style={{ borderRadius: 8 }}
            >
              {SORT_LABEL[key]}
            </Dropdown.Item>
          ))}
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown>
  )
}

const ARROW =
  'flex size-8 items-center justify-center text-foreground transition-colors enabled:cursor-pointer enabled:border enabled:border-border enabled:hover:bg-surface-hover disabled:cursor-default'

/** Стрелки листания ленты карточек: активна та, в сторону которой ещё есть что показать. */
export function PagingArrows({
  scrollRef,
  itemCount,
  className,
}: {
  className?: string
  scrollRef: RefObject<HTMLDivElement | null>
  /** Меняется — пересчитываем края. */
  itemCount: number
}) {
  const [edges, setEdges] = useState({ start: true, end: true })

  useEffect(() => {
    const node = scrollRef.current
    if (!node) {
      setEdges({ start: true, end: true })
      return
    }
    const update = () =>
      setEdges({
        start: node.scrollLeft <= 1,
        end: node.scrollLeft + node.clientWidth >= node.scrollWidth - 1,
      })
    update()
    node.addEventListener('scroll', update, { passive: true })
    const observer = new ResizeObserver(update)
    observer.observe(node)
    return () => {
      node.removeEventListener('scroll', update)
      observer.disconnect()
    }
  }, [scrollRef, itemCount])

  const page = (direction: 1 | -1) => {
    const node = scrollRef.current
    node?.scrollBy({ left: direction * node.clientWidth, behavior: 'smooth' })
  }

  return (
    <div className={cn('flex shrink-0 items-center gap-1', className)}>
      <button
        type="button"
        aria-label="Предыдущие заявки"
        disabled={edges.start}
        onClick={() => page(-1)}
        className={ARROW}
        style={{ borderRadius: 8 }}
      >
        <RiArrowLeftSLine size={16} />
      </button>
      <button
        type="button"
        aria-label="Следующие заявки"
        disabled={edges.end}
        onClick={() => page(1)}
        className={ARROW}
        style={{ borderRadius: 8 }}
      >
        <RiArrowRightSLine size={16} />
      </button>
    </div>
  )
}
