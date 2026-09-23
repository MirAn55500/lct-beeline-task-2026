import { useRef, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router'

import {
  HomeAreaLayout,
  WorkAreaGanttLayout,
  WorkAreaMapLayout,
} from '@/app/layouts'
import { DayOverviewWorkspace } from '@/features/planning'
import { useUploadTicketsMutation } from '@/features/tickets'
import { routes } from '@/shared/config/routes'

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

      <Route path={routes.personnel} element={<PlaceholderPage />} />
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
