import { useMemo } from 'react'
import { ScrollShadow } from '@heroui/react'
import { RiArrowRightLine, RiCalendarScheduleLine } from '@remixicon/react'
import { Link, type To } from 'react-router'

import { routes } from '@/shared/config/routes'
import { cn } from '@/shared/lib/cn'

type BlockTone = 'soft' | 'strong'

type PlanBlock = {
  from: number
  to: number
  tone: BlockTone
}

export type PlanRow = {
  id: string
  name: string
  blocks: PlanBlock[]
}

const TONE_COLOR: Record<BlockTone, string> = {
  soft: '#ffedd1',
  strong: '#ffdda8',
}

const DEFAULT_START = 9
const DEFAULT_END = 18

function buildDayRange(rows: PlanRow[]) {
  let min = Number.POSITIVE_INFINITY
  let max = Number.NEGATIVE_INFINITY
  for (const row of rows) {
    for (const block of row.blocks) {
      min = Math.min(min, block.from)
      max = Math.max(max, block.to)
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max) || !(max > min)) {
    return { start: DEFAULT_START, end: DEFAULT_END }
  }
  const start = Math.max(0, Math.floor(min))
  const end = Math.min(24, Math.max(start + 1, Math.ceil(max)))
  return { start, end }
}

function buildLabels(start: number, end: number) {
  const span = end - start
  if (span <= 4) {
    return Array.from({ length: span + 1 }, (_, index) => start + index)
  }
  const step = span <= 8 ? 2 : 3
  const labels: number[] = [start]
  for (let hour = start + step; hour < end; hour += step) labels.push(hour)
  if (labels[labels.length - 1] !== end) labels.push(end)
  return labels
}

function hourToPercent(hour: number, start: number, span: number) {
  const clamped = Math.min(start + span, Math.max(start, hour))
  return ((clamped - start) / span) * 100
}

function formatHour(hour: number) {
  return `${hour}:00`
}

function TimeLabels({
  start,
  end,
  labels,
}: {
  start: number
  end: number
  labels: number[]
}) {
  const span = end - start
  return (
    <div className="relative h-5 min-w-0 flex-1 text-sm font-medium leading-5 text-[#71717a]">
      {labels.map((hour) => {
        const atStart = hour === start
        const atEnd = hour === end
        return (
          <span
            key={hour}
            className={cn(
              'absolute top-0',
              atStart && 'left-0',
              atEnd && 'right-0',
              !atStart && !atEnd && '-translate-x-1/2',
            )}
            style={
              !atStart && !atEnd
                ? { left: `${hourToPercent(hour, start, span)}%` }
                : undefined
            }
          >
            {formatHour(hour)}
          </span>
        )
      })}
    </div>
  )
}

function TimeGrid({ start, end }: { start: number; end: number }) {
  const span = end - start
  const hours = Array.from({ length: span + 1 }, (_, index) => start + index)
  return (
    <div className="pointer-events-none absolute inset-0">
      {hours.map((hour) => (
        <span
          key={hour}
          className="absolute top-0 bottom-0 border-l border-dashed border-[#dedee0]"
          style={{ left: `${hourToPercent(hour, start, span)}%` }}
        />
      ))}
    </div>
  )
}

function PlanBars({
  blocks,
  start,
  end,
}: {
  blocks: PlanBlock[]
  start: number
  end: number
}) {
  const span = end - start
  return (
    <div className="relative h-8 min-w-0 flex-1">
      {blocks.map((block) => {
        if (block.to <= start || block.from >= end) return null
        return (
          <span
            key={`${block.from}-${block.to}`}
            className="absolute top-1/2 h-4 -translate-y-1/2"
            style={{
              left: `calc(${hourToPercent(block.from, start, span)}% + 4px)`,
              width: `calc(${Math.max(hourToPercent(block.to, start, span) - hourToPercent(block.from, start, span), 0)}% - 8px)`,
              backgroundColor: TONE_COLOR[block.tone],
              borderRadius: 8,
            }}
          />
        )
      })}
    </div>
  )
}

type DayPlanPreviewProps = {
  className?: string
  rows?: PlanRow[]
  /** Куда ведёт «Перейти к плану» — Гант с тем же регионом, днём и версией. */
  planLink?: To
}

export function DayPlanPreview({
  className,
  rows = [],
  planLink = routes.planGantt,
}: DayPlanPreviewProps) {
  const { start, end } = useMemo(() => buildDayRange(rows), [rows])
  const labels = useMemo(() => buildLabels(start, end), [start, end])

  return (
    <div className={cn('flex min-h-0 w-full flex-1 flex-col', className)}>
      <div className="flex shrink-0 items-end gap-4 px-5 pt-5 pb-2">
        <h2 className="w-[136px] shrink-0 text-xl font-semibold leading-7 text-foreground">
          План работ
        </h2>
        <TimeLabels start={start} end={end} labels={labels} />
      </div>

      <ScrollShadow
        hideScrollBar
        size={40}
        className="min-h-0 flex-1"
        orientation="vertical"
      >
        <div className="relative">
          <div className="pointer-events-none absolute inset-y-0 right-5 left-[172px]">
            <TimeGrid start={start} end={end} />
          </div>

          {rows.length === 0 ? (
            <p className="px-5 py-6 text-sm leading-6 text-[#71717a]">
              Назначений пока нет
            </p>
          ) : (
            rows.map((row) => (
              <div key={row.id} className="flex h-8 items-center gap-4 px-5">
                <p className="w-[136px] shrink-0 truncate text-sm font-medium leading-5 text-foreground">
                  {row.name}
                </p>
                <PlanBars blocks={row.blocks} start={start} end={end} />
              </div>
            ))
          )}
        </div>
      </ScrollShadow>

      <div className="flex shrink-0 justify-end px-5 pt-2 pb-5">
        <Link
          to={planLink}
          className="inline-flex h-9 cursor-pointer items-center gap-2 bg-[#0485f7] px-4 text-sm font-medium text-[#fcfcfc] transition-colors hover:bg-[#0374d9]"
          style={{ borderRadius: 8 }}
        >
          <RiCalendarScheduleLine size={16} className="shrink-0" />
          Перейти к плану
          <RiArrowRightLine size={16} className="shrink-0" />
        </Link>
      </div>
    </div>
  )
}
