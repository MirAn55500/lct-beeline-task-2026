import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useSearchParams } from 'react-router'
import { toast } from '@heroui/react'

import {
  HomeAreaLayout,
  WorkAreaGanttLayout,
  WorkAreaMapLayout,
  type HomeAreaContext,
} from '@/app/layouts'
import {
  AddEngineerPanel,
  BrigadesPanel,
  EngineersTable,
  MOCK_BRIGADES,
  MOCK_ENGINEERS,
  PersonnelHeader,
  downloadEngineers,
  shortName,
  type PersonnelEngineer,
  type PersonnelTab,
} from '@/features/personnel'
import {
  DayOverviewWorkspace,
  EngineersSidebar,
  MOCK_MAP_PLANNED_DATES,
  MOCK_MAP_REGIONS,
  PlanGanttBoard,
  PlanMapBoard,
  PlanRebuildDialog,
  usePlanContext,
  usePlanGanttBoard,
  usePlanMapBoard,
} from '@/features/planning'
import { TicketsUploadDialog, isTicketsFile, useTicketsUpload } from '@/features/tickets'
import { routes } from '@/shared/config/routes'
import { AppPanel, ContextHeader, PlanViewTabs } from '@/shared/ui'

function OverviewContent({ context }: { context: HomeAreaContext }) {
  const { regionId, regionName, date, planId, focusDay } = context
  const { upload, isUploading } = useTicketsUpload((result) => {
    if (result.date) focusDay(result.date)
  })

  return (
    <DayOverviewWorkspace
      regionId={regionId}
      regionName={regionName}
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
  return <HomeAreaLayout>{(context) => <OverviewContent context={context} />}</HomeAreaLayout>
}

// Сколько держится зелёная подсветка только что добавленных инженеров.
const HIGHLIGHT_MS = 4000

function PersonnelPage() {
  const [params, setParams] = useSearchParams()
  // Список на моках живёт в состоянии страницы, чтобы форма могла его пополнять.
  const [allEngineers, setAllEngineers] = useState<PersonnelEngineer[]>(MOCK_ENGINEERS)
  const [isAddOpen, setAddOpen] = useState(false)
  const [highlightIds, setHighlightIds] = useState<ReadonlySet<number>>(() => new Set())

  useEffect(() => {
    if (highlightIds.size === 0) return
    const timer = setTimeout(() => setHighlightIds(new Set()), HIGHLIGHT_MS)
    return () => clearTimeout(timer)
  }, [highlightIds])

  const requestedId = Number(params.get('brigade'))
  const brigadeId =
    MOCK_BRIGADES.find((item) => item.id === requestedId)?.id ??
    MOCK_BRIGADES[0]?.id ??
    null
  const brigade = MOCK_BRIGADES.find((item) => item.id === brigadeId)
  const tab: PersonnelTab = params.get('tab') === 'info' ? 'info' : 'engineers'
  const engineers = allEngineers.filter((item) => item.brigadeId === brigadeId)
  const countById = Object.fromEntries(
    MOCK_BRIGADES.map((item) => [
      item.id,
      allEngineers.filter((engineer) => engineer.brigadeId === item.id).length,
    ]),
  )

  const leaderById = Object.fromEntries(
    MOCK_BRIGADES.map((item) => {
      const lead = allEngineers.find(
        (engineer) => engineer.brigadeId === item.id && engineer.isLead,
      )
      return [item.id, lead ? shortName(lead.name) : undefined]
    }),
  )

  const handleAdded = (added: PersonnelEngineer[]) => {
    setAllEngineers((prev) => [...prev, ...added])
    setHighlightIds(new Set(added.map((item) => item.id)))
    // Показываем бригаду, куда попали новые инженеры.
    const target = added[0]?.brigadeId
    if (target != null && target !== brigadeId) update({ brigade: target, tab: 'engineers' })
    else if (tab !== 'engineers') update({ tab: 'engineers' })
  }

  const update = (next: { brigade?: number; tab?: PersonnelTab }) =>
    setParams(
      (prev) => {
        const copy = new URLSearchParams(prev)
        if (next.brigade != null) copy.set('brigade', String(next.brigade))
        if (next.tab != null) copy.set('tab', next.tab)
        return copy
      },
      { replace: true },
    )

  return (
    <WorkAreaMapLayout
      sidebar={
        <BrigadesPanel
          brigades={MOCK_BRIGADES}
          countById={countById}
          leaderById={leaderById}
          selectedId={brigadeId}
          onSelect={(brigade) => update({ brigade })}
        />
      }
      header={
        <PersonnelHeader
          title={brigade?.name ?? 'Бригада'}
          tab={tab}
          onTabChange={(next) => update({ tab: next })}
          onAddEngineer={() => setAddOpen(true)}
          onExport={(format) =>
            downloadEngineers(engineers, format, `engineers-${brigade?.name ?? 'all'}`)
          }
        />
      }
    >
      <div className="flex min-h-0 flex-1 gap-4">
        {tab === 'engineers' && brigadeId != null ? (
          <EngineersTable key={brigadeId} engineers={engineers} highlightIds={highlightIds} />
        ) : (
          <AppPanel className="flex min-h-0 flex-1 items-center justify-center">
            <p className="text-sm leading-6 text-[#71717a]">
              {brigadeId == null ? 'Выберите бригаду' : 'Информация о бригаде появится позже'}
            </p>
          </AppPanel>
        )}

        {isAddOpen ? (
          <AddEngineerPanel
            brigades={MOCK_BRIGADES}
            defaultBrigadeId={brigadeId}
            engineers={allEngineers}
            onAdd={handleAdded}
            onClose={() => setAddOpen(false)}
          />
        ) : null}
      </div>
    </WorkAreaMapLayout>
  )
}

type PlanContextState = ReturnType<typeof usePlanContext>

/**
 * Шапка плана работ — одна на Гант и карту: те же регион, день, версия плана
 * и окна «Загрузить заявки» / «Обновить план», чтобы при переключении вида ничего не менялось.
 */
function PlanWorkHeader({ context, hasPlan }: { context: PlanContextState; hasPlan: boolean }) {
  const [uploadOpen, setUploadOpen] = useState(false)
  const [rebuildOpen, setRebuildOpen] = useState(false)

  return (
    <>
      <ContextHeader
        regions={MOCK_MAP_REGIONS}
        regionId={context.regionId}
        onRegionIdChange={context.setRegionId}
        date={context.date}
        onDateChange={context.setDate}
        plannedDates={MOCK_MAP_PLANNED_DATES}
        plans={hasPlan ? context.plans : []}
        planId={hasPlan ? context.planId : null}
        onPlanIdChange={context.setPlanId}
        onUploadClick={() => setUploadOpen(true)}
        onRecalculate={() => setRebuildOpen(true)}
        center={<PlanViewTabs />}
      />
      <TicketsUploadDialog
        isOpen={uploadOpen}
        onClose={() => setUploadOpen(false)}
        date={context.date.toString()}
      />
      <PlanRebuildDialog
        isOpen={rebuildOpen}
        onClose={() => setRebuildOpen(false)}
        onConfirm={() => {
          // План работ пока на моках: новая версия с теми же назначениями.
          const plan = context.addPlan()
          toast.success(`План №${plan.version} составлен`)
        }}
      />
    </>
  )
}

function PlanMapPage() {
  const context = usePlanContext()
  const board = usePlanMapBoard(context.regionId, context.date.toString())

  return (
    <WorkAreaMapLayout
      sidebar={
        <EngineersSidebar
          engineers={board.engineers}
          selectedId={board.selectedId}
          hoveredId={board.hoveredId}
          onSelect={board.select}
          onHover={board.hover}
        />
      }
      header={<PlanWorkHeader context={context} hasPlan={board.hasPlan} />}
    >
      <PlanMapBoard board={board} />
    </WorkAreaMapLayout>
  )
}

function PlanGanttPage() {
  const context = usePlanContext()
  const board = usePlanGanttBoard(context.regionId, context.date.toString())

  return (
    <WorkAreaGanttLayout header={<PlanWorkHeader context={context} hasPlan={board.hasPlan} />}>
      <PlanGanttBoard board={board} viewKey={`${context.regionId}:${context.date.toString()}`} />
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

      <Route
        path={routes.plan}
        element={<Navigate to={routes.planGantt} replace />}
      />
      <Route path={routes.planGantt} element={<PlanGanttPage />} />
      <Route path={routes.planMap} element={<PlanMapPage />} />

      <Route path={routes.personnel} element={<PersonnelPage />} />
      <Route path={routes.config} element={<PlaceholderPage />} />
      <Route path={routes.help} element={<PlaceholderPage />} />

      <Route
        path="/layouts/home"
        element={<Navigate to={routes.overview} replace />}
      />
      <Route
        path="/layouts/gantt"
        element={<Navigate to={routes.planGantt} replace />}
      />
      <Route
        path="/layouts/map"
        element={<Navigate to={routes.planMap} replace />}
      />
      <Route
        path="/layouts/personnel"
        element={<Navigate to={routes.personnel} replace />}
      />
      <Route
        path="/layouts/config"
        element={<Navigate to={routes.config} replace />}
      />
      <Route
        path="/layouts/help"
        element={<Navigate to={routes.help} replace />}
      />

      <Route path="*" element={<Navigate to={routes.overview} replace />} />
    </Routes>
  )
}
