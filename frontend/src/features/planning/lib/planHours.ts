import { buildGantt } from '../mocks/gantt'
import type { PlanExportResponse } from '../planApi'

/** Часы шкалы по сменам и визитам планов: от раннего начала до позднего конца. */
export function planHours(plans: (PlanExportResponse | undefined)[]): [number, number] {
  let from = Infinity
  let to = -Infinity
  for (const plan of plans) {
    if (!plan) continue
    const dataset = buildGantt(plan, -1)
    for (const engineer of dataset.engineers) {
      for (const [start, end] of engineer.shifts) {
        from = Math.min(from, start)
        to = Math.max(to, end)
      }
    }
    for (const task of dataset.tasks) {
      from = Math.min(from, task.start - task.travel)
      to = Math.max(to, task.end)
    }
  }
  if (!Number.isFinite(from) || !Number.isFinite(to)) return [8, 20]
  return [Math.max(0, Math.floor(from / 60)), Math.min(24, Math.max(Math.floor(from / 60) + 1, Math.ceil(to / 60)))]
}
