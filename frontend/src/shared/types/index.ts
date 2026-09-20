/** Общие DTO/типы, не привязанные к одной фиче. */

export type HealthStatus = {
  status: string
}

export type ModuleHealth = {
  module: string
  status: string
}

export type Id = number
