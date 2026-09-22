import { Navigate, Route, Routes } from 'react-router'

import {
  HomeAreaLayout,
  WorkAreaGanttLayout,
  WorkAreaMapLayout,
} from '@/app/layouts'

export function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/layouts/home" replace />} />
      <Route path="/layouts/home" element={<HomeAreaLayout />} />
      <Route path="/layouts/gantt" element={<WorkAreaGanttLayout />} />
      <Route path="/layouts/map" element={<WorkAreaMapLayout />} />
      <Route path="/layouts/personnel" element={<HomeAreaLayout />} />
      <Route path="/layouts/config" element={<HomeAreaLayout />} />
      <Route path="/layouts/help" element={<HomeAreaLayout />} />
      <Route path="*" element={<Navigate to="/layouts/home" replace />} />
    </Routes>
  )
}
