import { useMemo } from 'react'

import { cn } from '@/shared/lib/cn'

import type { GanttTask } from '../ganttTypes'
import { formatRange } from '../lib/ganttPlacement'
import { buildGantt } from '../mocks/gantt'
import type { PlanExportResponse } from '../planApi'

const ROW = 24
const NAME_COLUMN = 132

/** «Иванов Пётр Сергеевич» → «Иванов П. С.» — в узкой колонке помещается фамилия. */
function shortName(name: string) {
  const [surname, ...rest] = name.split(/\s+/).filter(Boolean)
  if (!surname) return name
  return [surname, ...rest.map((part) => `${part[0]}.`)].join(' ')
}

function taskTitle(task: GanttTask) {
  const road = task.travel > 0 ? ` · дорога ${Math.round(task.travel)} мин` : ''
  return `№${task.id} · ${task.typeLabel} · ${formatRange(task.start, task.end)}${road}\n${task.address}`
}

type PlanMiniGanttProps = {
  plan: PlanExportResponse
  /** Часы шкалы — общие для обеих колонок сравнения, чтобы ленты совпадали по времени. */
  fromHour: number
  toHour: number
  /** Высота задаётся снаружи — лента прокручивается, шкала часов остаётся сверху. */
  className?: string
}

/**
 * Лента плана — для сравнения планов и обзора дня, только просмотр. Инженеры — строками, визиты — плашками
 * (светлая часть — дорога), аварийные — красным, обед — жёлтым. Подробности — в подсказке.
 */
export function PlanMiniGantt({ plan, fromHour, toHour, className }: PlanMiniGanttProps) {
  const dataset = useMemo(() => buildGantt(plan, -1), [plan])
  const span = Math.max(1, (toHour - fromHour) * 60)
  const pos = (minute: number) => `${((minute - fromHour * 60) / span) * 100}%`
  const len = (from: number, to: number) => `${(Math.max(0, to - from) / span) * 100}%`
  const hours = Array.from({ length: toHour - fromHour }, (_, index) => fromHour + index)
  const grid = {
    backgroundImage: 'linear-gradient(to right, var(--separator) 1px, transparent 0)',
    backgroundSize: `${100 / hours.length}% 100%`,
  }

  return (
    <div
      className={cn('flex flex-col overflow-y-auto border border-separator', className)}
      style={{ borderRadius: 12 }}
    >
      <div className="sticky top-0 z-10 flex shrink-0 border-b border-separator bg-surface-secondary text-xs leading-4 text-muted">
        <div className="shrink-0 px-2 py-1" style={{ width: NAME_COLUMN }}>
          Инженер
        </div>
        <div className="relative h-6 min-w-0 flex-1">
          {hours.map((hour, index) =>
            // Узкая шкала: подписываем каждый второй час, если часов много.
            hours.length > 8 && index % 2 === 1 ? null : (
              <span
                key={hour}
                className="absolute top-1 -translate-x-1/2 first:translate-x-0"
                style={{ left: pos(hour * 60) }}
              >
                {hour}
              </span>
            ),
          )}
        </div>
      </div>

      {dataset.engineers.map((engineer) => {
        const row = dataset.tasks.filter((task) => task.engineerId === engineer.id)
        const lunch = engineer.lunch
        return (
          <div key={engineer.id} className="flex shrink-0 border-b border-separator last:border-b-0" style={{ height: ROW }}>
            <div
              className="flex shrink-0 items-center justify-between gap-1 px-2 text-xs leading-4"
              style={{ width: NAME_COLUMN }}
              title={`${engineer.name} · загрузка ${engineer.load}%`}
            >
              <span className={cn('truncate', row.length === 0 ? 'text-muted' : 'text-foreground')}>
                {shortName(engineer.name)}
              </span>
              <span className="shrink-0 text-muted">{engineer.load}%</span>
            </div>
            <div className="relative min-w-0 flex-1 bg-surface-secondary">
              {/* Вне смены — серым: видно, где у инженера нет рабочего времени. */}
              {engineer.shifts.map(([from, to]) => (
                <span
                  key={from}
                  aria-hidden
                  className="absolute inset-y-0 bg-surface"
                  style={{ left: pos(from), width: len(from, to) }}
                />
              ))}
              <span aria-hidden className="absolute inset-0" style={grid} />
              {lunch ? (
                <span
                  className="absolute inset-y-1 bg-[#fef3c7]"
                  style={{ left: pos(lunch.start), width: len(lunch.start, lunch.end), borderRadius: 3 }}
                  title={`Обед ${formatRange(lunch.start, lunch.end)} · ${lunch.place}`}
                />
              ) : null}
              {row.map((task) => {
                const emergency = task.skill === 'emergency'
                return (
                  <span
                    key={task.id}
                    title={taskTitle(task)}
                    className="absolute inset-y-1 flex overflow-hidden"
                    style={{ left: pos(task.start - task.travel), width: len(task.start - task.travel, task.end), borderRadius: 3 }}
                  >
                    {task.travel > 0 ? (
                      <span
                        className={emergency ? 'bg-danger-soft' : 'bg-[#fde68a]/50'}
                        style={{ width: `${(task.travel / (task.end - task.start + task.travel)) * 100}%` }}
                      />
                    ) : null}
                    <span className={cn('min-w-0 flex-1', emergency ? 'bg-danger' : 'bg-[#f59e0b]')} />
                  </span>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
