// Вырезает из выгрузок планировщика (solution/viz/data/<регион>.json) то, что нужно мокам карты и Ганта,
// и кладёт компактные JSON в src/features/planning/mocks/plan-<регион>.json.
// Запуск: npm run mocks:map [-- east southeast southcentral]
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const rootDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const dataDir = path.resolve(rootDir, '../solution/viz/data')
const outDir = path.resolve(rootDir, 'src/features/planning/mocks')
const regions = process.argv.slice(2).length > 0 ? process.argv.slice(2) : ['east', 'southeast', 'southcentral']

const round = (value) => Math.round(value * 1e5) / 1e5
const coord = (point) => [round(point.lon), round(point.lat)]
const pair = ([lon, lat]) => [round(lon), round(lat)]

for (const region of regions) {
  const data = JSON.parse(fs.readFileSync(path.join(dataDir, `${region}.json`), 'utf8'))
  const plan = data.plans.optimized

  const result = {
    key: region,
    region: data.scenario.name,
    date: data.scenario.date,
    engineers: data.scenario.engineers.map((engineer) => ({
      id: engineer.id,
      name: engineer.name,
      start: coord(engineer.start_point),
      workIntervals: engineer.work_intervals.map((item) => [item.start, item.end]),
      skills: engineer.skills,
      skillLevels: engineer.skill_levels,
      transport: engineer.transport_mode,
      equipment: engineer.equipment,
    })),
    requests: data.scenario.requests.map((request) => ({
      id: request.id,
      point: coord(request.point),
      window: [request.window_start, request.window_end],
      address: request.address,
      type: request.request_type_bk,
      skill: request.required_skill,
      duration: request.duration_minutes,
      equipment: request.required_equipment,
    })),
    routes: plan.routes.map((route) => ({
      engineerId: route.engineer_id,
      startAt: route.start_at,
      endAt: route.end_at,
      utilization: route.utilization,
      // "ors" — всё по улицам, "mixed" — часть участков прямые, "straight" — линии нет вовсе.
      geometrySource: route.geometry_source,
      // Старт и точки визитов — по ним рисуются прямые, где сервис не построил путь.
      polyline: (route.polyline ?? []).map(pair),
      geometry: (route.geometry ?? []).map(pair),
      visits: route.visits.map((visit) => ({
        requestId: visit.request_id,
        geometryRange: visit.geometry_range,
        // Времена визита — для диаграммы Ганта: выезд, прибытие, работа на адресе.
        departureAt: visit.departure_at,
        serviceStartAt: visit.service_start_at,
        serviceEndAt: visit.service_end_at,
        transit: (visit.transit ?? []).map((leg) => leg.title),
      })),
    })),
    unassigned: plan.unassigned.map((item) => ({
      requestId: item.request_id,
      reason: item.reason,
      explanation: item.explanation,
    })),
  }

  const output = path.join(outDir, `plan-${region}.json`)
  fs.writeFileSync(output, JSON.stringify(result))
  const sources = result.routes.reduce((acc, route) => {
    acc[route.geometrySource] = (acc[route.geometrySource] ?? 0) + 1
    return acc
  }, {})
  console.log(
    `${result.region}: ${result.engineers.length} инженеров, ${result.routes.length} маршрутов ` +
      `${JSON.stringify(sources)}, ${result.unassigned.length} неназначенных -> ` +
      `${path.relative(rootDir, output)} (${Math.round(fs.statSync(output).size / 1024)} KB)`,
  )
}
