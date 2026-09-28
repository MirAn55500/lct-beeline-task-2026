import type { PlanExport } from '../mocks'

export type PlanMetrics = {
  assigned: number
  unassigned: number
  engaged: number
  engineers: number
  averageLoad: number
  averageTravelMinutes: number
}

export function getPlanMetrics(plan: PlanExport | null | undefined): PlanMetrics | null {
  if (!plan) return null

  const activeRoutes = plan.routes.filter((route) => route.visits.length > 0)
  const visits = activeRoutes.flatMap((route) => route.visits)
  const travelMinutes = visits.reduce((sum, visit) => sum + (visit.travelMinutes ?? 0), 0)
  const utilization = activeRoutes.reduce((sum, route) => sum + route.utilization, 0)

  return {
    assigned: visits.length,
    unassigned: plan.unassigned.length,
    engaged: activeRoutes.length,
    engineers: plan.engineers.length,
    averageLoad: activeRoutes.length > 0 ? Math.round((utilization / activeRoutes.length) * 100) : 0,
    averageTravelMinutes: visits.length > 0 ? Math.round(travelMinutes / visits.length) : 0,
  }
}

function hour(iso: string) {
  const match = /T(\d{2}):(\d{2})/.exec(iso)
  return match ? Number(match[1]) + Number(match[2]) / 60 : null
}

export type OverviewPlanRow = {
  id: string
  name: string
  blocks: { from: number; to: number; tone: 'soft' | 'strong' }[]
}

export function getOverviewPlanRows(plan: PlanExport | null | undefined): OverviewPlanRow[] {
  if (!plan) return []
  const engineerById = new Map(plan.engineers.map((engineer) => [engineer.id, engineer.name]))
  const requestById = new Map(plan.requests.map((request) => [request.id, request]))

  return plan.routes
    .filter((route) => route.visits.length > 0)
    .map((route) => ({
      id: route.engineerId,
      name: engineerById.get(route.engineerId) ?? route.engineerId,
      blocks: route.visits.flatMap((visit) => {
        const from = hour(visit.serviceStartAt)
        const to = hour(visit.serviceEndAt)
        if (from == null || to == null || to <= from) return []
        const request = requestById.get(visit.requestId)
        return [{
          from,
          to,
          tone: request?.type.toLowerCase().includes('авар') ? 'strong' as const : 'soft' as const,
        }]
      }),
    }))
}
