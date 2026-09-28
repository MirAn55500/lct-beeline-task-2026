export const routes = {
  overview: '/',
  plan: '/plan',
  planGantt: '/plan/gantt',
  planMap: '/plan/map',
  planComparison: '/plans/compare',
  personnel: '/personnel',
  config: '/config',
  help: '/help',
} as const

export type AppRoute = (typeof routes)[keyof typeof routes]
