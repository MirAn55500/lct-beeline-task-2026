import { useEffect, useRef, useState } from 'react'
import { Navigate, Route, Routes, useSearchParams } from 'react-router'

import {
  HomeAreaLayout,
  WorkAreaGanttLayout,
  WorkAreaMapLayout,
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
import { DayOverviewWorkspace } from '@/features/planning'
import { useUploadTicketsMutation } from '@/features/tickets'
import { routes } from '@/shared/config/routes'
import { AppPanel } from '@/shared/ui'

function isAcceptedTicketFile(file: File) {
  const name = file.name.toLowerCase()
  return name.endsWith('.csv') || file.type === 'text/csv'
}

function OverviewPage() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [pending, setPending] = useState(false)
  const [uploadTickets, { isLoading }] = useUploadTicketsMutation()
  const isUploading = pending || isLoading

  const handleFiles = async (
    files: File[],
    regionId: number,
    date: string,
    focusDay: (isoDate: string) => void,
  ) => {
    const file = files.find(isAcceptedTicketFile)
    if (!file || isUploading) return

    const body = new FormData()
    body.append('file', file)
    body.append('region_id', String(regionId))
    body.append('date', date)

    setPending(true)
    try {
      const result = await uploadTickets(body).unwrap()
      if (result.date) focusDay(result.date)
    } catch {
      // Ошибка загрузки возвращает дропзону в покой.
    } finally {
      setPending(false)
    }
  }

  return (
    <HomeAreaLayout
      isUploadDisabled={isUploading}
      onUploadClick={() => {
        if (!isUploading) inputRef.current?.click()
      }}
    >
      {({ regionId, regionName, date, planId, focusDay }) => (
        <>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            tabIndex={-1}
            disabled={isUploading || regionId == null}
            onChange={async (event) => {
              const files = Array.from(event.target.files ?? [])
              event.target.value = ''
              if (files.length > 0 && regionId != null) {
                await handleFiles(files, regionId, date, focusDay)
              }
            }}
          />
          <DayOverviewWorkspace
            regionId={regionId}
            regionName={regionName}
            date={date}
            planId={planId}
            isUploading={isUploading}
            onFiles={
              regionId == null
                ? undefined
                : (files) => handleFiles(files, regionId, date, focusDay)
            }
          />
        </>
      )}
    </HomeAreaLayout>
  )
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
      <Route path={routes.planGantt} element={<WorkAreaGanttLayout />} />
      <Route path={routes.planMap} element={<WorkAreaMapLayout />} />

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
