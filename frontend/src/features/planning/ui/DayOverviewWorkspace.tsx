import beesPromo from '@/shared/assets/day-overview-bees-promo.png'
import { EngineersPanel } from '@/features/personnel'
import {
  MOCK_TICKETS,
  TicketsDropzone,
  TicketsPanel,
  type UnassignedTicket,
} from '@/features/tickets'
import { DEFAULT_REGION } from '@/shared/config/context'
import { cn } from '@/shared/lib/cn'
import { AppPanel } from '@/shared/ui'

function PanelHeading({
  title,
  description,
  className,
}: {
  title: string
  description: string
  className?: string
}) {
  return (
    <div className={cn('flex shrink-0 flex-col gap-1 px-5 pt-5', className)}>
      <h2 className="text-xl font-semibold leading-7 text-foreground">{title}</h2>
      <p className="text-sm leading-6 text-[#71717a]">{description}</p>
    </div>
  )
}

function SummaryCounter({
  value,
  total,
  label,
}: {
  value: number
  total: number
  label: string
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      <div className="flex items-baseline gap-1 text-xl font-semibold leading-7">
        <span className="text-foreground">{value}</span>
        <span className="text-[#71717a]">из {total}</span>
      </div>
      <p className="text-sm leading-6 text-[#71717a]">{label}</p>
    </div>
  )
}

type DayOverviewWorkspaceProps = {
  className?: string
  isUploading?: boolean
  onFiles?: (files: File[]) => void | Promise<void>
  /** Временно: мок загруженных заявок. Пустой массив → uploader. */
  tickets?: UnassignedTicket[]
}

export function DayOverviewWorkspace({
  className,
  isUploading = false,
  onFiles,
  // Временно показываем заполненное состояние списка заявок
  tickets = MOCK_TICKETS,
}: DayOverviewWorkspaceProps) {
  const hasTickets = tickets.length > 0

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col gap-4', className)}>
      <AppPanel className="flex h-24 shrink-0 items-center justify-between gap-4 px-5">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h2 className="text-xl font-semibold leading-7 text-foreground">
            Создайте план работ
          </h2>
          <p className="truncate text-sm leading-6 text-[#71717a]">
            Загрузите заявки для региона «{DEFAULT_REGION}»
          </p>
        </div>

        <div className="flex min-w-0 flex-1 gap-4">
          <SummaryCounter
            value={0}
            total={hasTickets ? tickets.length : 0}
            label="заявок назначено"
          />
          <SummaryCounter value={0} total={0} label="инженеров задействовано" />
        </div>
      </AppPanel>

      <div className="flex min-h-0 flex-1 gap-4">
        <AppPanel className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {hasTickets ? (
            <TicketsPanel tickets={tickets} />
          ) : (
            <>
              <PanelHeading
                title="Нет ни одной заявки"
                description="Загрузите заявки для начала работы алгоритма"
              />
              <TicketsDropzone isUploading={isUploading} onFiles={onFiles} />
            </>
          )}
        </AppPanel>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
          <AppPanel className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <EngineersPanel />
          </AppPanel>

          <AppPanel className="relative aspect-[515/208] w-full shrink-0 overflow-hidden">
            <img
              src={beesPromo}
              alt="Наши пчелки распределят заявки — а ты станешь не нужен!"
              className="absolute inset-0 size-full object-cover"
              draggable={false}
            />
          </AppPanel>
        </div>
      </div>
    </div>
  )
}
