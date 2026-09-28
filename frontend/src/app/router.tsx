import { useEffect, useState } from 'react'
import { toast } from '@heroui/react'
import { Navigate, Route, Routes, useSearchParams } from 'react-router'
import { getLocalTimeZone, parseDate, today } from '@internationalized/date'

import {
  HomeAreaLayout,
  WorkAreaGanttLayout,
  WorkAreaMapLayout,
  type HomeAreaContext,
} from '@/app/layouts'
import {
  BrigadeInfo,
  BrigadesPanel,
  CreateBrigadeDialog,
  EngineerCardPanel,
  EngineerFormPanel,
  EngineersTable,
  PersonnelHeader,
  downloadEngineers,
  useGetBrigadesQuery,
  useGetPersonnelEngineersQuery,
  type PersonnelEngineer,
  type PersonnelTab,
} from '@/features/personnel'
import {
  DayOverviewWorkspace,
  EngineersSidebar,
  PlanEventReport,
  UnavailableDialog,
  PlanGanttBoard,
  PlanMapBoard,
  PlanRebuildDialog,
  useApplyPlanEventMutation,
  usePlanContext,
  usePlanGanttBoard,
  usePlanMapBoard,
  type PlanContext,
} from '@/features/planning'
import {
  TicketsUploadDialog,
  isTicketsFile,
  useTicketsExport,
  useTicketsUpload,
} from '@/features/tickets'
import type { PlanEventResult } from '@/features/planning'
import { routes } from '@/shared/config/routes'
import { AppPanel, ContextHeader, PlanViewTabs } from '@/shared/ui'

function OverviewContent({ context }: { context: HomeAreaContext }) {
  const { regionId, date, planId, focusDay } = context
  const { upload, isUploading } = useTicketsUpload((result) => {
    if (result.date) focusDay(result.date)
  })

  return (
    <DayOverviewWorkspace
      regionId={regionId}
      regionName={context.regionName}
      date={date}
      planId={planId}
      isUploading={isUploading}
      onFiles={
        regionId == null
          ? undefined
          : async (files) => {
              const file = files.find(isTicketsFile)
              if (file) await upload({ file, regionId, date })
            }
      }
    />
  )
}

function OverviewPage() {
  return (
    <HomeAreaLayout>
      {(context) => <OverviewContent context={context} />}
    </HomeAreaLayout>
  )
}

// Сколько держится зелёная подсветка только что добавленных инженеров.
const HIGHLIGHT_MS = 4000

function PersonnelPage() {
  const [params, setParams] = useSearchParams()
  const [isAddOpen, setAddOpen] = useState(false)
  const [addSingle, setAddSingle] = useState(false)
  const [createBrigadeOpen, setCreateBrigadeOpen] = useState(false)
  const [activeEngineerId, setActiveEngineerId] = useState<number | null>(null)
  // Открытая карточка — в форме редактирования
  const [isEditing, setEditing] = useState(false)
  const [highlightIds, setHighlightIds] = useState<ReadonlySet<number>>(
    () => new Set(),
  )

  const { data: brigades = [], isLoading: brigadesLoading } = useGetBrigadesQuery()

  const requestedId = Number(params.get('brigade'))
  const brigadeId =
    brigades.find((item) => item.id === requestedId)?.id ?? brigades[0]?.id ?? null
  const brigade = brigades.find((item) => item.id === brigadeId)
  const tab: PersonnelTab = params.get('tab') === 'engineers' ? 'engineers' : 'info'

  const { data: engineers = [], isLoading: engineersLoading } =
    useGetPersonnelEngineersQuery(
      { brigadeId: brigadeId ?? 0 },
      { skip: brigadeId == null },
    )

  const activeEngineer =
    activeEngineerId == null
      ? null
      : (engineers.find((item) => item.id === activeEngineerId) ?? null)

  useEffect(() => {
    if (highlightIds.size === 0) return
    const timer = setTimeout(() => setHighlightIds(new Set()), HIGHLIGHT_MS)
    return () => clearTimeout(timer)
  }, [highlightIds])

  // Если в URL нет/устарела бригада — подставляем первую из ответа API.
  useEffect(() => {
    if (brigades.length === 0 || brigadeId == null) return
    if (String(brigadeId) === params.get('brigade')) return
    setParams(
      (prev) => {
        const copy = new URLSearchParams(prev)
        copy.set('brigade', String(brigadeId))
        return copy
      },
      { replace: true },
    )
  }, [brigades, brigadeId, params, setParams])

  const countById = Object.fromEntries(
    brigades.map((item) => [item.id, item.engineersCount]),
  )

  const update = (next: { brigade?: number; tab?: PersonnelTab }) =>
    setParams(
      (prev) => {
        const copy = new URLSearchParams(prev)
        if (next.brigade != null) copy.set('brigade', String(next.brigade))
        if (next.tab === 'engineers') copy.set('tab', 'engineers')
        else if (next.tab === 'info') copy.delete('tab')
        return copy
      },
      { replace: true },
    )

  const handleAdded = (added: PersonnelEngineer[]) => {
    setHighlightIds(new Set(added.map((item) => item.id)))
    const target = added[0]?.brigadeId
    // Новых инженеров видно в таблице — туда и переключаемся
    update({ brigade: target != null && target !== brigadeId ? target : undefined, tab: 'engineers' })
  }

  return (
    <WorkAreaMapLayout
      sidebar={
        <BrigadesPanel
          brigades={brigades}
          countById={countById}
          selectedId={brigadeId}
          isLoading={brigadesLoading}
          onSelect={(next) => {
            // Другая бригада — другой состав: карточка прежнего инженера закрывается
            if (next !== brigadeId) {
              setActiveEngineerId(null)
              setEditing(false)
            }
            update({ brigade: next })
          }}
          onAddBrigade={() => {
            setAddOpen(false)
            setActiveEngineerId(null)
            setEditing(false)
            setCreateBrigadeOpen(true)
          }}
        />
      }
      header={
        <PersonnelHeader
          title={brigade?.name ?? 'Бригада'}
          tab={tab}
          onTabChange={(next) => {
            setAddOpen(false)
            setCreateBrigadeOpen(false)
            setActiveEngineerId(null)
            setEditing(false)
            update({ tab: next })
          }}
          onAddEngineer={() => {
            setActiveEngineerId(null)
            setEditing(false)
            setAddSingle(false)
            setCreateBrigadeOpen(false)
            setAddOpen(true)
            update({ tab: 'engineers' })
          }}
          onAddSingleEngineer={() => {
            setActiveEngineerId(null)
            setEditing(false)
            setAddSingle(true)
            setCreateBrigadeOpen(false)
            setAddOpen(true)
            update({ tab: 'engineers' })
          }}
          onExport={(format) =>
            downloadEngineers(
              engineers,
              format,
              `engineers-${brigade?.name ?? 'all'}`,
            )
          }
        />
      }
    >
      <div className="flex min-h-0 flex-1 gap-4">
        {brigade && tab === 'info' ? (
          <BrigadeInfo key={brigade.id} brigade={brigade} engineers={engineers} />
        ) : brigadeId != null ? (
          <EngineersTable
            key={brigadeId}
            engineers={engineers}
            highlightIds={highlightIds}
            isLoading={engineersLoading}
            activeId={activeEngineerId}
            onOpenEngineer={(engineer) => {
              setAddOpen(false)
              setEditing(false)
              setActiveEngineerId(engineer.id)
            }}
            onEditEngineer={(engineer) => {
              setAddOpen(false)
              setActiveEngineerId(engineer.id)
              setEditing(true)
            }}
          />
        ) : (
          <AppPanel className="flex min-h-0 flex-1 items-center justify-center">
            <p className="text-sm leading-6 text-muted">
              {brigadesLoading ? 'Загружаем бригады…' : 'Выберите бригаду'}
            </p>
          </AppPanel>
        )}

        {isAddOpen ? (
          <EngineerFormPanel
            key={addSingle ? 'single' : 'file'}
            brigades={brigades}
            defaultBrigadeId={brigadeId}
            startInSingle={addSingle}
            onAdd={handleAdded}
            onClose={() => setAddOpen(false)}
          />
        ) : activeEngineer && isEditing ? (
          <EngineerFormPanel
            key={activeEngineer.id}
            brigades={brigades}
            defaultBrigadeId={brigadeId}
            engineer={activeEngineer}
            onSaved={(saved) => {
              setEditing(false)
              // Переведён в другую бригаду — открываем её состав, карточка остаётся
              if (saved.brigadeId !== brigadeId) update({ brigade: saved.brigadeId })
            }}
            onClose={() => setEditing(false)}
          />
        ) : activeEngineer ? (
          <EngineerCardPanel
            engineer={activeEngineer}
            onClose={() => setActiveEngineerId(null)}
            onEdit={() => setEditing(true)}
          />
        ) : null}
      </div>
      <CreateBrigadeDialog
        isOpen={createBrigadeOpen}
        onClose={() => setCreateBrigadeOpen(false)}
        defaultRegionId={brigade?.regionId ?? null}
        onCreated={(created) => {
          update({ brigade: created.id, tab: 'info' })
        }}
      />
    </WorkAreaMapLayout>
  )
}

/**
 * Шапка плана работ — одна на Гант и карту: те же регион, день, версия плана
 * и окна «Загрузить заявки» / «Обновить план», чтобы при переключении вида ничего не менялось.
 */
function PlanWorkHeader({ context }: { context: PlanContext }) {
  const [uploadOpen, setUploadOpen] = useState(false)
  const [rebuildOpen, setRebuildOpen] = useState(false)
  const exportTickets = useTicketsExport()
  const { regionId, regions, date, planId } = context
  const regionName = regions.find((item) => item.id === regionId)?.name ?? regionId

  return (
    <>
      <ContextHeader
        regions={regions}
        regionId={regionId}
        onRegionIdChange={context.setRegionId}
        date={date}
        onDateChange={context.setDate}
        plannedDates={context.plannedDates}
        plans={context.plans}
        planId={planId}
        onPlanIdChange={context.setPlanId}
        isRegionsLoading={context.isRegionsLoading}
        isRegionsError={context.isRegionsError}
        onUploadClick={() => setUploadOpen(true)}
        isRecalculating={context.isRebuilding}
        isPlanning={context.isPlanning}
        planningSeconds={context.planningSeconds}
        onRecalculate={regionId == null ? undefined : () => setRebuildOpen(true)}
        onExport={
          regionId == null
            ? undefined
            : (format) =>
                exportTickets(
                  { regionId, date: date.toString(), planId, offline: context.offline },
                  format,
                  `Заявки_${regionName}_${date.toString()}`,
                )
        }
        center={<PlanViewTabs />}
      />
      <TicketsUploadDialog
        isOpen={uploadOpen}
        onClose={() => setUploadOpen(false)}
        defaultRegionId={regionId}
        date={date.toString()}
        onUploaded={(result) => {
          if (result.date) context.setDate(parseDate(result.date))
        }}
      />
      <PlanRebuildDialog
        isOpen={rebuildOpen}
        onClose={() => setRebuildOpen(false)}
        onConfirm={(options) => void context.rebuild(options)}
      />
    </>
  )
}

function PlanMapPage() {
  const context = usePlanContext()
  const [applyEvent] = useApplyPlanEventMutation()
  const [eventReport, setEventReport] = useState<PlanEventResult | null>(null)
  const [awayEngineerId, setAwayEngineerId] = useState<string | null>(null)
  // Старая версия плана и прошедший день — история: события и правки только в последней
  // версии текущего или будущего дня
  const editable = !context.offline && !isFrozenPlan(context)
  const board = usePlanMapBoard(context.regionId, context.date.toString(), context.queryPlanId, {
    onSaved: context.setPlanId,
    readOnly: isFrozenPlan(context),
  })

  const runEvent = async (body: {
    type: 'cancel_request' | 'engineer_unavailable'
    requestId?: number
    engineerId?: number
    at?: string
  }) => {
    if (context.offline || context.regionId == null) return
    try {
      const result = await applyEvent({
        regionId: context.regionId,
        date: context.date.toString(),
        ...body,
      }).unwrap()
      context.setPlanId(result.plan_id)
      setEventReport(result)
    } catch (error) {
      const detail = (error as { data?: { detail?: unknown } } | null)?.data?.detail
      toast.danger('Событие не применено', {
        description: typeof detail === 'string' ? detail : 'Текущий план остался без изменений',
      })
    }
  }

  return (
    <WorkAreaMapLayout
      sidebar={
        <EngineersSidebar
          engineers={board.engineers}
          selectedId={board.selectedId}
          hoveredId={board.hoveredId}
          onSelect={board.select}
          onHover={board.hover}
          onUnavailable={editable ? setAwayEngineerId : undefined}
        />
      }
      header={<PlanWorkHeader context={context} />}
    >
      <PlanMapBoard
        board={board}
        readOnly={isFrozenPlan(context)}
        onCancelStop={
          !editable
            ? undefined
            : (requestId) => {
                const id = Number(requestId)
                if (Number.isInteger(id) && id > 0) {
                  void runEvent({ type: 'cancel_request', requestId: id })
                }
              }
        }
      />
      <UnavailableDialog
        engineerId={awayEngineerId}
        onClose={() => setAwayEngineerId(null)}
        onConfirm={(at) => {
          const id = Number(awayEngineerId)
          setAwayEngineerId(null)
          if (Number.isInteger(id) && id > 0) {
            void runEvent({ type: 'engineer_unavailable', engineerId: id, at })
          }
        }}
      />
      <PlanEventReport result={eventReport} onClose={() => setEventReport(null)} />
    </WorkAreaMapLayout>
  )
}

/**
 * Руками не правится: старая версия плана (история) или прошедший день — ставить заявки
 * уже некуда. На моках без backend перетаскивание остаётся для показа.
 */
function isFrozenPlan(context: PlanContext) {
  if (context.offline) return false
  return context.queryPlanId != null || context.date.compare(today(getLocalTimeZone())) < 0
}

function PlanGanttPage() {
  const context = usePlanContext()
  const board = usePlanGanttBoard(context.regionId, context.date.toString(), context.queryPlanId, {
    // Ручной ход сохранён новой версией — переключаемся на неё.
    onSaved: context.setPlanId,
    readOnly: isFrozenPlan(context),
  })

  return (
    <WorkAreaGanttLayout header={<PlanWorkHeader context={context} />}>
      <PlanGanttBoard board={board} viewKey={`${context.regionId}:${context.date.toString()}:${context.planId}`} />
    </WorkAreaGanttLayout>
  )
}

function PlaceholderPage() {
  return <HomeAreaLayout />
}

export function AppRouter() {
  return (
    <Routes>
      <Route path={routes.overview} element={<OverviewPage />} />

      <Route path={routes.plan} element={<Navigate to={routes.planGantt} replace />} />
      <Route path={routes.planGantt} element={<PlanGanttPage />} />
      <Route path={routes.planMap} element={<PlanMapPage />} />

      <Route path={routes.personnel} element={<PersonnelPage />} />
      <Route path={routes.config} element={<PlaceholderPage />} />
      <Route path={routes.help} element={<PlaceholderPage />} />

      <Route path="/layouts/home" element={<Navigate to={routes.overview} replace />} />
      <Route path="/layouts/gantt" element={<Navigate to={routes.planGantt} replace />} />
      <Route path="/layouts/map" element={<Navigate to={routes.planMap} replace />} />
      <Route
        path="/layouts/personnel"
        element={<Navigate to={routes.personnel} replace />}
      />
      <Route path="/layouts/config" element={<Navigate to={routes.config} replace />} />
      <Route path="/layouts/help" element={<Navigate to={routes.help} replace />} />

      <Route path="*" element={<Navigate to={routes.overview} replace />} />
    </Routes>
  )
}
