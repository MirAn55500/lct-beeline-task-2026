import type { ComponentType } from 'react'
import { RiBikeLine, RiBus2Line, RiCarLine, RiWalkLine } from '@remixicon/react'

import type { TransportCode } from '@/features/personnel/mocks'

export const TRANSPORT_ICON: Record<
  TransportCode,
  ComponentType<{ size?: number | string; className?: string }>
> = {
  car: RiCarLine,
  public: RiBus2Line,
  bike: RiBikeLine,
  walking: RiWalkLine,
}
