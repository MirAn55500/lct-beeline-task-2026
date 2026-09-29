/**
 * Моки страницы «План работ → Гант» — те же планы планировщика, что и у карты,
 * плюс времена визитов. Статусы считаются от моковых «сейчас», контакты клиентов выдуманы.
 */

import type {
  ClientContact,
  GanttEngineer,
  GanttStatus,
  GanttTask,
  GanttTicket,
  GanttUnassigned,
} from '../ganttTypes'
import type { MapEngineer } from '../mapTypes'
import {
  LEVEL_LABEL,
  MOCK_MAP_REGIONS,
  PLANS,
  buildMapDataset,
  getMapDataset,
  lunchPlaceLabel,
  shortAddress,
  type PlanExport,
} from './index'

/** «Сейчас» для моков: 15:40 дня плана — часть визитов прошла, часть впереди. */
export const MOCK_GANTT_NOW = 15 * 60 + 40

/** Тип заявки, который можно выбрать в «Управлении заявкой». */
export type GanttTicketType = {
  label: string
  skill: string
  duration: number
}

export type GanttDataset = {
  date: string
  engineers: GanttEngineer[]
  tasks: GanttTask[]
  unassigned: GanttUnassigned[]
  ticketTypes: GanttTicketType[]
  /** Квалификации инженеров региона по навыку — подсказка под типом заявки. */
  qualifications: Record<string, string[]>
}

// На карточках Ганта мало места: длинные типы БК — короткими словами, как в макете.
const TYPE_LABEL: Record<string, string> = {
  'Локальная заявка': 'Ремонт',
  'Глобальная проблема': 'Авария',
}

/** «2026-08-17T09:05:00+03:00» → 545 — минуты от полуночи в поясе региона. */
function minutes(iso: string | null | undefined) {
  if (!iso) return 0
  return Number(iso.slice(11, 13)) * 60 + Number(iso.slice(14, 16))
}

function statusAt(departure: number, start: number, end: number, now: number): GanttStatus {
  if (end <= now) return 'done'
  if (start <= now) return 'working'
  if (departure <= now) return 'onWay'
  return 'assigned'
}

/**
 * Всё для Ганта из одного плана — моковой выгрузки или ответа `/api/planning/plan`.
 * `now` — «сейчас» в минутах от полуночи дня плана: от него статусы визитов.
 */
export function buildGantt(
  plan: PlanExport,
  now: number = MOCK_GANTT_NOW,
  mapEngineers: MapEngineer[] = buildMapDataset(plan).engineers,
): GanttDataset {
  const requestById = new Map(plan.requests.map((request) => [request.id, request]))

  const toTicket = (requestId: string): GanttTicket => {
    const request = requestById.get(requestId)!
    return {
      id: request.id,
      typeLabel: TYPE_LABEL[request.type] ?? request.type,
      address: shortAddress(request.address),
      skill: request.skill,
      windowFrom: minutes(request.window[0]),
      windowTo: minutes(request.window[1]),
      duration: request.duration,
      needsRouter: request.equipment.includes('router'),
      needsBox: request.equipment.includes('set_top_box'),
    }
  }

  const lunchOf = new Map(
    plan.routes.flatMap((route) => (route.lunch ? [[route.engineerId, route.lunch] as const] : [])),
  )
  const engineers = plan.engineers.map((engineer, index): GanttEngineer => {
    const lunch = lunchOf.get(engineer.id)
    return {
      ...mapEngineers[index]!,
      skills: engineer.skills,
      equipment: engineer.equipment,
      shifts: engineer.workIntervals.map(([from, to]) => [minutes(from), minutes(to)]),
      lunch: lunch
        ? {
            departure: minutes(lunch.detour ? lunch.departureAt : lunch.startAt),
            arrival: minutes(lunch.detour ? lunch.arrivalAt : lunch.startAt),
            start: minutes(lunch.startAt),
            end: minutes(lunch.endAt),
            place: lunchPlaceLabel(lunch),
          }
        : null,
    }
  })

  const tasks = plan.routes.flatMap((route) =>
    route.visits.map((visit): GanttTask => {
      const start = minutes(visit.serviceStartAt)
      const end = minutes(visit.serviceEndAt)
      const departure = minutes(visit.departureAt)
      return {
        ...toTicket(visit.requestId),
        engineerId: route.engineerId,
        start,
        end,
        travel: Math.max(0, start - departure),
        status: statusAt(minutes(visit.departureAt), start, end, now),
      }
    }),
  )

  const unassigned = plan.unassigned.map(
    (item): GanttUnassigned => ({
      ...toTicket(item.requestId),
      reason: item.reason,
      explanation: item.explanation,
      // Снята вручную при замене: клиенту уже назвали время — нужно согласовать новое.
      needsApproval: item.reason === 'manual',
    }),
  )

  const ticketTypes = new Map<string, GanttTicketType>()
  for (const request of plan.requests) {
    const label = TYPE_LABEL[request.type] ?? request.type
    if (!ticketTypes.has(label)) ticketTypes.set(label, { label, skill: request.skill, duration: request.duration })
  }

  const qualifications: Record<string, string[]> = {}
  for (const engineer of plan.engineers) {
    for (const [skill, level] of engineer.skillLevels) {
      const label = LEVEL_LABEL[level]
      if (!label) continue
      const list = (qualifications[skill] ??= [])
      if (!list.includes(label)) list.push(label)
    }
  }
  const order = Object.values(LEVEL_LABEL).reverse()
  for (const list of Object.values(qualifications)) list.sort((a, b) => order.indexOf(a) - order.indexOf(b))

  return {
    date: plan.date,
    engineers,
    tasks,
    unassigned,
    ticketTypes: [...ticketTypes.values()],
    qualifications,
  }
}

const DATASETS = new Map(
  MOCK_MAP_REGIONS.map((region, index) => [
    region.id,
    buildGantt(PLANS[index]!, MOCK_GANTT_NOW, getMapDataset(region.id).engineers),
  ]),
)

/** План региона для Ганта; неизвестный регион — первый из списка. */
export function getGanttDataset(regionId: number | null): GanttDataset {
  return DATASETS.get(regionId ?? 0) ?? DATASETS.get(MOCK_MAP_REGIONS[0]!.id)!
}

const CLIENT_NAMES = ['Ирина', 'Алексей', 'Мария', 'Дмитрий', 'Ольга', 'Сергей', 'Наталья', 'Андрей']

/** Контакт клиента по номеру заявки — стабильный, чтобы окно не менялось между открытиями. */
export function getClientContact(ticketId: string): ClientContact {
  const seed = [...ticketId].reduce((sum, char) => sum * 31 + char.charCodeAt(0), 7) >>> 0
  const digits = String(seed).padStart(10, '0').slice(-7)
  return {
    name: CLIENT_NAMES[seed % CLIENT_NAMES.length]!,
    phone: `+7 9${digits.slice(0, 2)} ${digits.slice(2, 5)}-${digits.slice(5, 7)}-${String(seed % 97).padStart(2, '0')}`,
  }
}
