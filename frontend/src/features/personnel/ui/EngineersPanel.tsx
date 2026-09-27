import { Avatar, ScrollShadow } from '@heroui/react'
import {
  RiArrowRightLine,
  RiBus2Fill,
  RiCarFill,
  RiRidingFill,
  RiToolsFill,
  RiWalkFill,
} from '@remixicon/react'
import { Link } from 'react-router'
import type { ComponentType } from 'react'

import { useGetEngineersQuery } from '@/features/personnel/api'
import type { Engineer } from '@/features/personnel/types'
import { routes } from '@/shared/config/routes'
import { cn } from '@/shared/lib/cn'
import { getInitials, pluralRu } from '@/shared/lib/text'

const TRANSPORT_ICON: Record<
  string,
  ComponentType<{ size?: number | string; className?: string }>
> = {
  public: RiBus2Fill,
  bike: RiRidingFill,
  car: RiCarFill,
  walking: RiWalkFill,
}

function EngineerCard({ engineer }: { engineer: Engineer }) {
  const TransportIcon = TRANSPORT_ICON[engineer.transport]

  return (
    <div className="flex items-center gap-4 border-b border-border px-5 py-3">
      <Avatar className="size-[52px] shrink-0 !rounded-[4px]">
        <Avatar.Fallback className="!rounded-[4px] bg-surface-tertiary text-xs font-medium text-foreground">
          {getInitials(engineer.name)}
        </Avatar.Fallback>
      </Avatar>

      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="truncate text-base font-semibold leading-6 text-foreground">
          {engineer.name}
        </p>
        <div className="flex min-w-0 items-center gap-2 text-sm font-medium leading-6 text-muted">
          <span className="flex min-w-0 items-center gap-1">
            {TransportIcon ? <TransportIcon size={16} className="shrink-0" /> : null}
            <span className="truncate">{engineer.transport_label}</span>
          </span>
          {engineer.skill ? (
            <>
              <span className="h-2.5 w-px shrink-0 bg-separator" />
              <span className="flex min-w-0 items-center gap-1">
                <RiToolsFill size={16} className="shrink-0" />
                <span className="truncate">{engineer.skill}</span>
              </span>
            </>
          ) : null}
        </div>
      </div>
    </div>
  )
}

type EngineersPanelProps = {
  className?: string
  regionId: number | null
}

export function EngineersPanel({ className, regionId }: EngineersPanelProps) {
  const { data: engineers = [], isError, isLoading } = useGetEngineersQuery(
    regionId ?? 0,
    { skip: regionId == null },
  )
  const count = engineers.length
  const title = isLoading ? 'Инженеры' : `${count} ${pluralRu(count, ['инженер', 'инженера', 'инженеров'])}`
  const works = pluralRu(count, ['Работает', 'Работают', 'Работают'])

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)}>
      <div className="flex shrink-0 flex-col gap-1 px-5 pb-2 pt-5">
        <h2 className="text-xl font-semibold leading-7 text-foreground">{title}</h2>
        <p className="text-sm leading-6 text-muted">
          {works} сегодня в рамках выбранного региона
        </p>
      </div>

      <ScrollShadow
        hideScrollBar
        size={80}
        className="min-h-0 flex-1"
        orientation="vertical"
      >
        {engineers.length === 0 && !isLoading ? (
          <p className="px-5 py-3 text-sm leading-6 text-muted">
            {isError ? 'Не удалось загрузить инженеров' : 'Инженеров пока нет'}
          </p>
        ) : (
          <div>
            {engineers.map((engineer) => (
              <EngineerCard key={engineer.id} engineer={engineer} />
            ))}
          </div>
        )}
      </ScrollShadow>

      <div className="flex shrink-0 justify-end px-5 pt-2 pb-5">
        <Link
          to={routes.personnel}
          className="inline-flex h-9 cursor-pointer items-center gap-2 border border-border px-4 text-sm font-medium text-foreground transition-colors hover:bg-surface-hover"
          style={{ borderRadius: 8 }}
        >
          Перейти к инженерам
          <RiArrowRightLine size={16} className="shrink-0" />
        </Link>
      </div>
    </div>
  )
}
