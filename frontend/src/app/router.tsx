import { Navigate, Route, Routes } from 'react-router'

import {
  HomeAreaLayout,
  WorkAreaGanttLayout,
  WorkAreaMapLayout,
} from '@/app/layouts'
import { DayOverviewWorkspace } from '@/features/planning'
import { routes } from '@/shared/config/routes'

function OverviewPage() {
  return (
    <HomeAreaLayout>
      <DayOverviewWorkspace />
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
