import { useState, type PointerEvent, type RefObject } from 'react'
import { RiCupLine } from '@remixicon/react'

import { cn } from '@/shared/lib/cn'
import { AppPanel } from '@/shared/ui'

import type { GanttEngineer, GanttLunch, GanttTask } from '../../ganttTypes'
import { SNAP_MINUTES, formatClock, formatRange, type FreeCells } from '../../lib/ganttPlacement'
import type { MapTransport } from '../../mapTypes'
import { EngineerSearchFilters } from '../EngineerSearchFilters'
import { GanttRoadPart, GanttTaskCard } from './cards'
import { EngineerCell } from './EngineerCell'

/** Размеры сетки из макета: час и строка. Колонка инженеров — общая левая колонка (useAsideWidth). */
export const GANTT_HOUR = 120
export const GANTT_HEADER = 60
export const GANTT_ROW = 60
/** Ширина раскрытой карточки визита. */
const FULL_CARD = 204

/** Подсветка под перетаскиваемой заявкой — ровно её работа, минуты дня. */
export type GanttTarget = {
  engineerId: string
  from: number
  to: number
  /** Позиция голубой линии, которая перемещается по 10-минутным шагам. */
  snapStart: number
  /** target — сюда встанет (фиолетовая), danger — замена или нельзя (красная). */
  tone: 'target' | 'danger'
}

type GanttTimelineProps = {
  /** Ширина колонки инженеров — совпадает с брендом над ней. */
  column: number
  engineers: GanttEngineer[]
  tasks: GanttTask[]
  fromHour: number
  toHour: number
  /** Текущее время для красной линии; null — день не сегодняшний. */
  now: number | null
  /** Свободные 10-минутные ячейки для выбранной заявки — зелёные. */
  freeCells: FreeCells | null
  target: GanttTarget | null
  /** Идёт перетаскивание: наведение отключено, чужие строки приглушены. */
  dragging: boolean
  draggingTaskId: string | null
  engineerQuery: string
  onEngineerQueryChange: (query: string) => void
  engineerTransports: ReadonlySet<MapTransport>
  onEngineerTransportsChange: (transports: ReadonlySet<MapTransport>) => void
  scrollRef: RefObject<HTMLDivElement | null>
  lanesRef: RefObject<HTMLDivElement | null>
  onTaskPointerDown: (task: GanttTask, event: PointerEvent<HTMLElement>) => void
  /** Визит можно схватить; неподвижные не показывают курсор «взять». */
  canDrag: (task: GanttTask) => boolean
  onFreeCellClick: (engineerId: string, start: number) => void
  onBackgroundClick: () => void
}

/**
 * Зелёные ячейки по 10 минут: подряд идущие — одной полосой, под курсором — своя ячейка.
 * Зелёная ячейка — начать работу в эти 10 минут можно.
 */
function FreeRuns({
  cells,
  name,
  x,
  onPick,
}: {
  cells: Map<number, number>
  name: string
  x: (minute: number) => number
  onPick: (start: number) => void
}) {
  const minutes = [...cells.keys()].sort((a, b) => a - b)
  const runs: number[][] = []
  for (const minute of minutes) {
    const run = runs[runs.length - 1]
    if (run && minute - run[run.length - 1]! === SNAP_MINUTES) run.push(minute)
    else runs.push([minute])
  }
  const cellWidth = x(SNAP_MINUTES) - x(0)
  return runs.map((run) => (
    <div
      key={run[0]}
      className="absolute top-0 flex h-full overflow-hidden border border-[#22c55e] bg-[#dcfce7]"
      style={{ left: x(run[0]!), width: cellWidth * run.length }}
    >
      {run.map((minute) => {
        const start = cells.get(minute)!
        return (
          <button
            key={minute}
            type="button"
            title={formatClock(start)}
            aria-label={`Поставить к ${name} в ${formatClock(start)}`}
            onClick={(event) => {
              event.stopPropagation()
              onPick(start)
            }}
            className="h-full shrink-0 cursor-pointer transition-colors hover:bg-[#86efac]"
            style={{ width: cellWidth }}
          />
        )
      })}
    </div>
  ))
}

/** Обед на ленте: дорога к месту обеда штриховкой и сам час — между заявками, под ними. */
function LunchBar({
  lunch,
  transport,
  x,
  dimmed,
  passive,
}: {
  lunch: GanttLunch
  transport: GanttEngineer['transport']
  x: (minute: number) => number
  dimmed: boolean
  /** Идёт постановка заявки: обед не перехватывает клики по зелёным ячейкам под ним. */
  passive: boolean
}) {
  const road = Math.max(0, x(lunch.arrival) - x(lunch.departure))
  const wait = Math.max(0, x(lunch.start) - x(lunch.arrival))
  const width = Math.max(x(lunch.end) - x(lunch.start) - 4, 12)
  const title = `Обед ${formatRange(lunch.start, lunch.end)} · ${lunch.place}`
  return (
    <div
      title={title}
      className={cn(
        'absolute top-1 bottom-1 z-[4] flex items-stretch transition-[left] duration-150',
        dimmed && 'opacity-40',
        passive && 'pointer-events-none',
      )}
      style={{ left: x(lunch.departure) + 2 }}
    >
      {road > 0 ? (
        <GanttRoadPart
          task={{ status: 'assigned', travel: Math.round(lunch.arrival - lunch.departure) }}
          transport={transport}
          width={road}
        />
      ) : null}
      {/* Приехали раньше окна обеда — ждут на месте, без дороги */}
      {wait > 0 ? <span aria-hidden className="shrink-0" style={{ width: wait }} /> : null}
      <span
        className="flex min-w-0 items-center gap-1 overflow-hidden border border-[#fcd34d] bg-[#fef3c7] px-1.5 text-xs leading-4 font-medium text-[#92400e]"
        style={{ width, borderRadius: road > 0 && wait <= 0 ? '0 6px 6px 0' : 6 }}
      >
        <RiCupLine size={12} className="shrink-0" />
        {width > 40 ? <span className="truncate">Обед</span> : null}
      </span>
    </div>
  )
}

export function GanttTimeline({
  column,
  engineers,
  tasks,
  fromHour,
  toHour,
  now,
  freeCells,
  target,
  dragging,
  draggingTaskId,
  engineerQuery,
  onEngineerQueryChange,
  engineerTransports,
  onEngineerTransportsChange,
  scrollRef,
  lanesRef,
  onTaskPointerDown,
  canDrag,
  onFreeCellClick,
  onBackgroundClick,
}: GanttTimelineProps) {
  const [hoveredTaskId, setHoveredTaskId] = useState<string | null>(null)
  const [hoveredEngineerId, setHoveredEngineerId] = useState<string | null>(null)
  const hours = Array.from({ length: toHour - fromHour }, (_, index) => fromHour + index)
  const width = hours.length * GANTT_HOUR
  const x = (minute: number) => ((minute - fromHour * 60) / 60) * GANTT_HOUR
  const nowX = now != null && now >= fromHour * 60 && now <= toHour * 60 ? x(now) : null

  return (
    <AppPanel className="relative flex min-h-0 flex-1 overflow-hidden">
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-auto [scrollbar-color:#e1e1e1_transparent] [scrollbar-width:thin]"
      >
        <div className="relative flex min-h-full flex-col" style={{ width: column + width }}>
          {/* Шкала часов и фильтры инженеров остаются на месте при прокрутке. */}
          <div className="sticky top-0 z-40 flex shrink-0 bg-surface" style={{ height: GANTT_HEADER }}>
            <div
              className="sticky left-0 z-10 flex shrink-0 items-center border-r-[3px] border-b border-separator bg-surface"
              style={{ width: column }}
            >
              <EngineerSearchFilters
                query={engineerQuery}
                onQueryChange={onEngineerQueryChange}
                transports={engineerTransports}
                onTransportsChange={onEngineerTransportsChange}
                className="w-full p-3"
              />
            </div>
            <div className="relative flex">
              {hours.map((hour) => (
                <div
                  key={hour}
                  className="flex shrink-0 items-center justify-center border-r border-b border-separator text-xs leading-4 font-medium text-foreground"
                  style={{ width: GANTT_HOUR }}
                >
                  {hour}:00
                </div>
              ))}
              {nowX != null ? (
                <>
                  <span
                    aria-hidden
                    className="absolute top-[45px] size-2.5 -translate-x-1/2 rounded-full bg-[#ea580c]"
                    style={{ left: nowX }}
                  />
                  <span
                    aria-hidden
                    className="absolute top-[50px] bottom-0 w-0.5 -translate-x-1/2 bg-[#ea580c]"
                    style={{ left: nowX }}
                  />
                </>
              ) : null}
            </div>
          </div>

          <div className="flex flex-1">
            <div
              className="sticky left-0 z-30 shrink-0 border-r-[3px] border-separator bg-surface"
              style={{ width: column }}
            >
              {engineers.map((engineer) => (
                <EngineerCell
                  key={engineer.id}
                  engineer={engineer}
                  hovered={hoveredEngineerId === engineer.id || (dragging && target?.engineerId === engineer.id)}
                  onHover={(id) => {
                    if (!dragging) setHoveredEngineerId(id)
                  }}
                />
              ))}
            </div>

            <div ref={lanesRef} className="relative" style={{ width }} onClick={onBackgroundClick}>
              {engineers.map((engineer) => {
                const row = tasks.filter((task) => task.engineerId === engineer.id)
                const dimmed = dragging && target != null && target.engineerId !== engineer.id
                return (
                  <div
                    key={engineer.id}
                    className="relative border-b border-separator"
                    style={{
                      height: GANTT_ROW,
                      backgroundImage:
                        'linear-gradient(to right, transparent calc(100% - 1px), var(--separator) 0)',
                      backgroundSize: `${GANTT_HOUR}px 100%`,
                    }}
                  >
                    {freeCells?.get(engineer.id) ? (
                      <FreeRuns
                        cells={freeCells.get(engineer.id)!}
                        name={engineer.name}
                        x={x}
                        onPick={(start) => onFreeCellClick(engineer.id, start)}
                      />
                    ) : null}

                    {target?.engineerId === engineer.id ? (
                      <div
                        aria-hidden
                        className={cn(
                          'pointer-events-none absolute top-0 h-full',
                          target.tone === 'target'
                            ? 'border border-[#8b5cf6] bg-[#ede9fe]'
                            : 'border-2 border-danger bg-danger-soft',
                        )}
                        style={{
                          left: x(target.from),
                          width: x(target.to) - x(target.from),
                        }}
                      />
                    ) : null}

                    {target?.engineerId === engineer.id ? (
                      <div
                        aria-hidden
                        className="pointer-events-none absolute inset-y-0 z-[5] w-0.5 -translate-x-1/2 bg-[var(--beeline-accent-03-blue-primary)]"
                        style={{ left: x(target.snapStart) }}
                      >
                        <span className="absolute top-0 left-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--beeline-accent-03-blue-primary)]" />
                        <span className="absolute bottom-0 left-1/2 size-2.5 -translate-x-1/2 translate-y-1/2 rounded-full bg-[var(--beeline-accent-03-blue-primary)]" />
                      </div>
                    ) : null}

                    {engineer.lunch ? (
                      <LunchBar
                        lunch={engineer.lunch}
                        transport={engineer.transport}
                        x={x}
                        dimmed={dimmed}
                        passive={dragging || freeCells != null}
                      />
                    ) : null}

                    {row.map((task) => {
                      // Плашка визита: слева дорога от выезда, справа работа на адресе.
                      const roadWidth = task.travel > 0 ? x(task.start) - x(task.start - task.travel) : 0
                      const left = x(task.start - task.travel) + 2
                      const cardWidth = Math.max(x(task.end) - x(task.start) - (roadWidth > 0 ? 2 : 4), 20)
                      const full = task.status === 'draft' || (!dragging && hoveredTaskId === task.id)
                      const fullWidth = Math.max(cardWidth, FULL_CARD)
                      return (
                        <div
                          key={task.id}
                          className={cn(
                            'absolute top-1 flex items-stretch transition-opacity',
                            full ? 'z-20' : 'z-10',
                            (dimmed || task.id === draggingTaskId) && 'opacity-40',
                          )}
                          style={{ left: full ? Math.min(left, width - roadWidth - fullWidth) : left }}
                          onPointerEnter={() => setHoveredTaskId(task.id)}
                          onPointerLeave={() => setHoveredTaskId((current) => (current === task.id ? null : current))}
                        >
                          {roadWidth > 0 ? (
                            <GanttRoadPart
                              task={task}
                              transport={engineer.transport}
                              full={full}
                              width={roadWidth}
                            />
                          ) : null}
                          <GanttTaskCard
                            task={task}
                            full={full}
                            joined={roadWidth > 0}
                            className={cn(canDrag(task) && !dragging && 'cursor-grab')}
                            style={{ width: full ? fullWidth : cardWidth }}
                            onPointerDown={(event) => onTaskPointerDown(task, event)}
                          />
                        </div>
                      )
                    })}
                  </div>
                )
              })}

              {nowX != null ? (
                <span
                  aria-hidden
                  className="pointer-events-none absolute top-0 bottom-0 z-[15] w-0.5 -translate-x-1/2 bg-[#ea580c]"
                  style={{ left: nowX }}
                />
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </AppPanel>
  )
}
