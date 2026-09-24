import type { ComponentType } from 'react'
import { RiBus2Fill, RiCarFill, RiRidingFill, RiWalkFill } from '@remixicon/react'

import type { MapTransport } from '../../mapTypes'

export const TRANSPORT_FILL_ICON: Record<
  MapTransport,
  ComponentType<{ size?: number | string; className?: string }>
> = {
  car: RiCarFill,
  public: RiBus2Fill,
  bike: RiRidingFill,
  walking: RiWalkFill,
}

export const TRANSPORT_LABEL: Record<MapTransport, string> = {
  car: 'Автомобиль',
  public: 'Общественный транспорт',
  bike: 'Велосипед',
  walking: 'Пешком',
}
