import { useEffect, useRef, useState } from 'react'
import { Navigate, Route, Routes, useSearchParams } from 'react-router'
import { toast } from '@heroui/react'

import {
  HomeAreaLayout,
  WorkAreaGanttLayout,
  WorkAreaMapLayout,
} from '@/app/layouts'
import {
  AddEngineerPanel,
  BrigadesPanel,
  EngineersTable,
  PersonnelHeader,
  downloadEngineers,
  useGetBrigadesQuery,
  useGetPersonnelEngineersQuery,
  type PersonnelEngineer,
  type PersonnelTab,
} from '@/features/personnel'
import { DayOverviewWorkspace } from '@/features/planning'
import {
  UploadTicketsModal,
  downloadTickets,
  isAcceptedTicketFile,
  uploadSuccessDescription,
  useLazyGetTicketsQuery,
  useUploadTicketsMutation,
} from '@/features/tickets'
import { routes } from '@/shared/config/routes'
import { AppPanel } from '@/shared/ui'

function OverviewPage() {
  const exportContextRef = useRef<{
    regionId: number
    regionName: string | null
    date: string
    planId: number | null
  } | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [pending, setPending] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [uploadTickets, { isLoading }] = useUploadTicketsMutation()
  const [fetchTickets] = useLazyGetTicketsQuery()
  const isUploading = pending || isLoading

  const handleUpload = async (
    file: File,
    regionId: number,
    date: string,
    focusDay: (isoDate: string) => void,
    setRegionId: (regionId: number) => void,
  ) => {
    if (!isAcceptedTicketFile(file) || isUploading) {
      if (!isAcceptedTicketFile(file)) toast.danger('Нужен json или csv файл')
      return
    }

    const body = new FormData()
    body.append('file', file)
    body.append('region_id', String(regionId))
    body.append('date', date)

    setPending(true)
    try {
      const result = await uploadTickets(body).unwrap()
      setRegionId(regionId)
      if (result.date) focusDay(result.date)
      toast.success('Загрузка заявок завершена', {
        description: uploadSuccessDescription(result.created, result.updated),
      })
    } catch (error) {
      const description =
        error &&
        typeof error === 'object' &&
        'data' in error &&
        error.data &&
        typeof error.data === 'object' &&
        'detail' in error.data &&
        typeof (error.data as { detail: unknown }).detail === 'string'
          ? (error.data as { detail: string }).detail
          : 'Проверьте формат файла и попробуйте снова'
      toast.danger('Не удалось завершить загрузку', {
        description,
        actionProps: {
          children: 'Повторить',
          variant: 'outline',
          size: 'sm',
          onPress: () => setUploadOpen(true),
        },
      })
      throw error
    } finally {
      setPending(false)
    }
  }

  const handleFiles = async (
    files: File[],
    regionId: number,
    date: string,
    focusDay: (isoDate: string) => void,
    setRegionId: (regionId: number) => void,
  ) => {
    const file = files.find(isAcceptedTicketFile)
    if (!file) {
      if (files.length > 0) toast.danger('Нужен json или csv файл')
      return
    }
    try {
      await handleUpload(file, regionId, date, focusDay, setRegionId)
    } catch {
      // Тост уже показан в handleUpload.
    }
  }

  const handleExport = async (format: 'csv' | 'json') => {
    const ctx = exportContextRef.current
    if (ctx == null || exporting) return
    setExporting(true)
    try {
      const tickets = await fetchTickets({
        regionId: ctx.regionId,
        date: ctx.date,
        planId: ctx.planId,
      }).unwrap()
      if (tickets.length === 0) {
        toast.danger('Нет заявок для экспорта')
        return
      }
      const safeName = (ctx.regionName ?? 'region').replace(/\s+/g, '-')
      downloadTickets(tickets, format, `tickets-${safeName}-${ctx.date}`)
    } catch {
      toast.danger('Не удалось экспортировать заявки')
    } finally {
      setExporting(false)
    }
  }

  return (
    <HomeAreaLayout
      isUploadDisabled={isUploading}
      onUploadClick={() => {
        if (!isUploading) setUploadOpen(true)
      }}
      isExportDisabled={exporting}
      onExportCsv={() => void handleExport('csv')}
      onExportJson={() => void handleExport('json')}
    >
      {({ regionId, regionName, date, planId, focusDay, setRegionId }) => {
        if (regionId != null) {
          exportContextRef.current = { regionId, regionName, date, planId }
        } else {
          exportContextRef.current = null
        }
        return (
          <>
            <UploadTicketsModal
              isOpen={uploadOpen}
              onOpenChange={setUploadOpen}
              defaultRegionId={regionId}
              date={date}
              isUploading={isUploading}
              onUpload={async ({ file, regionId: uploadRegionId }) => {
                await handleUpload(file, uploadRegionId, date, focusDay, setRegionId)
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
                  : (files) => handleFiles(files, regionId, date, focusDay, setRegionId)
              }
            />
          </>
        )
      }}
    </HomeAreaLayout>
  )
}

// Сколько держится зелёная подсветка только что добавленных инженеров.
const HIGHLIGHT_MS = 4000

function PersonnelPage() {
  const [params, setParams] = useSearchParams()
  const [isAddOpen, setAddOpen] = useState(false)
  const [highlightIds, setHighlightIds] = useState<ReadonlySet<number>>(() => new Set())

  const { data: brigades = [], isLoading: brigadesLoading } = useGetBrigadesQuery()

  const requestedId = Number(params.get('brigade'))
  const brigadeId =
    brigades.find((item) => item.id === requestedId)?.id ?? brigades[0]?.id ?? null
  const brigade = brigades.find((item) => item.id === brigadeId)
  const tab: PersonnelTab = params.get('tab') === 'info' ? 'info' : 'engineers'

  const { data: engineers = [], isLoading: engineersLoading } = useGetPersonnelEngineersQuery(
    { brigadeId: brigadeId ?? 0 },
    { skip: brigadeId == null },
  )

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
  const leaderById = Object.fromEntries(
    brigades.map((item) => [item.id, item.leaderShortName ?? undefined]),
  )

  const handleAdded = (added: PersonnelEngineer[]) => {
    setHighlightIds(new Set(added.map((item) => item.id)))
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
          brigades={brigades}
          countById={countById}
          leaderById={leaderById}
          selectedId={brigadeId}
          isLoading={brigadesLoading}
          onSelect={(next) => update({ brigade: next })}
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
          <EngineersTable
            key={brigadeId}
            engineers={engineers}
            highlightIds={highlightIds}
            isLoading={engineersLoading}
          />
        ) : (
          <AppPanel className="flex min-h-0 flex-1 items-center justify-center">
            <p className="text-sm leading-6 text-[#71717a]">
              {brigadeId == null
                ? brigadesLoading
                  ? 'Загружаем бригады…'
                  : 'Выберите бригаду'
                : 'Информация о бригаде появится позже'}
            </p>
          </AppPanel>
        )}

        {isAddOpen ? (
          <AddEngineerPanel
            brigades={brigades}
            defaultBrigadeId={brigadeId}
            engineers={engineers}
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
