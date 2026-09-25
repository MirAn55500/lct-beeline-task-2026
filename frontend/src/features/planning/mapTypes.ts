/** Типы страницы «План работ → Карта». Пока живут на моках из выгрузки планировщика, см. mocks/. */

export type LngLat = [lng: number, lat: number]

export type MapTransport = 'car' | 'public' | 'bike' | 'walking'

/** Код причины неназначения — как ReasonCode в planner/enums.py. */
export type UnassignedReason =
  | 'no_engineers'
  | 'no_region'
  | 'no_skill'
  | 'no_transport'
  | 'no_equipment'
  | 'no_work_time'
  | 'time_conflict'
  | 'not_found'
  | 'manual'

export type MapTicket = {
  /** Номер заявки из БК, например «74198». */
  id: string
  /** Тип заявки из БК: «Подключение», «Локальная заявка»… */
  typeLabel: string
  address: string
  coord: LngLat
  /** Окно визита клиента, например «17:00–20:00». */
  window: string
  needsRouter: boolean
  needsBox: boolean
}

export type UnassignedTicket = MapTicket & {
  reason: UnassignedReason
  /** Объяснение планировщика — в подсказке на теге причины. */
  explanation: string
}

/** Путь от предыдущей точки маршрута до заявки. */
export type RouteLeg = {
  line: LngLat[]
  /**
   * Сервис маршрутов не построил путь, и участок — прямая между точками
   * (geometry_source "mixed"/"straight" у планировщика или заявка добавлена вручную).
   * На карте такой участок серый пунктирный.
   */
  straight: boolean
}

export type RouteStop = MapTicket & {
  leg: RouteLeg
  /** Шаги на общественном транспорте, например «автобус с799 от «Есенинский бульв.», 5 ост., 6 мин». */
  transit: string[]
  /** Время в пути от предыдущей точки, мин. */
  travelMinutes: number
  /** Путь по улицам от предыдущей точки, км; нет — оцениваем по прямой. */
  distanceKm?: number
}

export type MapEngineer = {
  id: string
  name: string
  avatarUrl?: string
  transport: MapTransport
  qualification: string
  /** Окно маршрута на день, например «9:00»–«18:00». */
  routeFrom: string
  routeTo: string
  /** Рабочая смена из графика — в подсказке при наведении. */
  shift: string
  /** Загрузка смены в процентах. */
  load: number
  /** Цвет маршрута на карте и значка транспорта в списке. */
  color: string
  routers: number
  boxes: number
  start: { address: string; coord: LngLat }
}

export type EngineerRoute = {
  engineerId: string
  stops: RouteStop[]
}
