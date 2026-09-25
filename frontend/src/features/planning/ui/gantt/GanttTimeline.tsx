import { useState, type PointerEvent, type RefObject } from 'react'
import { Link } from 'react-router'
import { RiArrowLeftSLine } from '@remixicon/react'

import { routes } from '@/shared/config/routes'
import { cn } from '@/shared/lib/cn'
import { AppPanel } from '@/shared/ui'

import type { GanttEngineer, GanttTask } from '../../ganttTypes'
import { GanttRoadPart, GanttTaskCard } from './cards'
import { EngineerCell } from './EngineerCell'

/** Размеры сетки из макета: час и строка. Колонка инженеров — общая левая колонка (useAsideWidth). */
export const GANTT_HOUR = 120
export const GANTT_HEADER = 48
export const GANTT_ROW = 60
/** Ширина раскрытой карточки визита. */
const FULL_CARD = 204

/** Подсветка часовых ячеек под перетаскиваемой заявкой. */
export type GanttTarget = {
  engineerId: string
  fromHour: number
  toHour: number
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
  /** Свободные ячейки для выбранной заявки — зелёные; ключ `${engineerId}:${час}`. */
  freeCells: Map<string, number> | null
  target: GanttTarget | null
  /** Идёт перетаскивание: наведение отключено, чужие строки приглушены. */
  dragging: boolean
  draggingTaskId: string | null
  scrollRef: RefObject<HTMLDivElement | null>
  lanesRef: RefObject<HTMLDivElement | null>
  onTaskPointerDown: (task: GanttTask, event: PointerEvent<HTMLElement>) => void
  onFreeCellClick: (engineerId: string, start: number) => void
  onBackgroundClick: () => void
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
  scrollRef,
  lanesRef,
  onTaskPointerDown,
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
          {/* Шкала часов прилипает сверху, угол с «План работ» — ещё и слева. */}
          <div className="sticky top-0 z-40 flex shrink-0 bg-white" style={{ height: GANTT_HEADER }}>
            <div
              className="sticky left-0 z-10 flex shrink-0 items-center border-r-[3px] border-b border-[#e4e4e7] bg-white px-1.5"
              style={{ width: column }}
            >
              <Link
                to={routes.overview}
                className="flex h-9 flex-1 items-center gap-1.5 px-1.5 text-sm leading-6 font-medium text-[#18181b] transition-colors hover:bg-[#f5f5f5]"
                style={{ borderRadius: 8 }}
              >
                <RiArrowLeftSLine size={16} className="shrink-0 text-[#71717a]" />
                План работ
              </Link>
            </div>
            <div className="relative flex">
              {hours.map((hour) => (
                <div
                  key={hour}
                  className="flex shrink-0 items-center justify-center border-r border-b border-[#e4e4e7] text-xs leading-4 font-medium text-black"
                  style={{ width: GANTT_HOUR }}
                >
                  {hour}:00
                </div>
              ))}
              {nowX != null ? (
                <>
                  <span
                    aria-hidden
                    className="absolute top-[33px] size-2.5 -translate-x-1/2 rounded-full bg-[#ea580c]"
                    style={{ left: nowX }}
                  />
                  <span
                    aria-hidden
                    className="absolute top-[38px] bottom-0 w-0.5 -translate-x-1/2 bg-[#ea580c]"
                    style={{ left: nowX }}
                  />
                </>
              ) : null}
            </div>
          </div>

          <div className="flex flex-1">
            <div
              className="sticky left-0 z-30 shrink-0 border-r-[3px] border-[#e4e4e7] bg-white"
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
                    className="relative border-b border-[#e4e4e7]"
                    style={{
                      height: GANTT_ROW,
                      backgroundImage: 'linear-gradient(to right, transparent calc(100% - 1px), #e4e4e7 0)',
                      backgroundSize: `${GANTT_HOUR}px 100%`,
                    }}
                  >
                    {freeCells
                      ? hours.map((hour) => {
                          const start = freeCells.get(`${engineer.id}:${hour}`)
                          if (start == null) return null
                          return (
                            <button
                              key={hour}
                              type="button"
                              aria-label={`Поставить к ${engineer.name} в ${hour}:00`}
                              onClick={(event) => {
                                event.stopPropagation()
                                onFreeCellClick(engineer.id, start)
                              }}
                              className="absolute top-0 h-full cursor-pointer border border-[#22c55e] bg-[#dcfce7] transition-colors hover:bg-[#bbf7d0]"
                              style={{ left: x(hour * 60), width: GANTT_HOUR }}
                            />
                          )
                        })
                      : null}

                    {target?.engineerId === engineer.id ? (
                      <div
                        aria-hidden
                        className={cn(
                          'pointer-events-none absolute top-0 h-full',
                          target.tone === 'target'
                            ? 'border border-[#8b5cf6] bg-[#ede9fe]'
                            : 'border-2 border-[#ff383c] bg-[#ff383c]/15',
                        )}
                        style={{
                          left: x(target.fromHour * 60),
                          width: (target.toHour - target.fromHour) * GANTT_HOUR,
                        }}
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
                            className={cn(task.status === 'assigned' && !dragging && 'cursor-grab')}
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
