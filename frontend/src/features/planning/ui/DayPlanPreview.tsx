import { ScrollShadow } from '@heroui/react'
import { RiArrowRightLine, RiCalendarScheduleLine } from '@remixicon/react'
import { Link } from 'react-router'

import { routes } from '@/shared/config/routes'
import { cn } from '@/shared/lib/cn'

const DAY_START = 9
const DAY_END = 18
const DAY_SPAN = DAY_END - DAY_START
const HOURS = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18] as const
const LABELS = [9, 12, 15, 18] as const

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

function hourToPercent(hour: number) {
  const clamped = Math.min(DAY_END, Math.max(DAY_START, hour))
  return ((clamped - DAY_START) / DAY_SPAN) * 100
}

function formatHour(hour: number) {
  return `${hour}:00`
}

function TimeLabels() {
  return (
    <div className="relative h-5 min-w-0 flex-1 text-sm font-medium leading-5 text-[#71717a]">
      {LABELS.map((hour) => {
        const atStart = hour === DAY_START
        const atEnd = hour === DAY_END
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
                ? { left: `${hourToPercent(hour)}%` }
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

function TimeGrid() {
  return (
    <div className="pointer-events-none absolute inset-0">
      {HOURS.map((hour) => (
        <span
          key={hour}
          className="absolute top-0 bottom-0 border-l border-dashed border-[#dedee0]"
          style={{ left: `${hourToPercent(hour)}%` }}
        />
      ))}
    </div>
  )
}

function PlanBars({ blocks }: { blocks: PlanBlock[] }) {
  return (
    <div className="relative h-8 min-w-0 flex-1">
      {blocks.map((block) => {
        if (block.to <= DAY_START || block.from >= DAY_END) return null
        return (
          <span
            key={`${block.from}-${block.to}`}
            className="absolute top-1/2 h-4 -translate-y-1/2"
            style={{
              left: `calc(${hourToPercent(block.from)}% + 4px)`,
              width: `calc(${Math.max(hourToPercent(block.to) - hourToPercent(block.from), 0)}% - 8px)`,
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
}

export function DayPlanPreview({
  className,
  rows = [],
}: DayPlanPreviewProps) {
  return (
    <div className={cn('flex min-h-0 w-full flex-1 flex-col', className)}>
      <div className="flex shrink-0 items-end gap-4 px-5 pt-5 pb-2">
        <h2 className="w-[136px] shrink-0 text-xl font-semibold leading-7 text-foreground">
          План работ
        </h2>
        <TimeLabels />
      </div>

      <ScrollShadow
        hideScrollBar
        size={40}
        className="min-h-0 flex-1"
        orientation="vertical"
      >
        <div className="relative">
          <div className="pointer-events-none absolute inset-y-0 right-5 left-[172px]">
            <TimeGrid />
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
                <PlanBars blocks={row.blocks} />
              </div>
            ))
          )}
        </div>
      </ScrollShadow>

      <div className="flex shrink-0 justify-end px-5 pt-2 pb-5">
        <Link
          to={routes.planGantt}
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
