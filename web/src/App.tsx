import { lazy, Suspense, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import TopBar from './components/TopBar'
import { NavContext } from './lib/nav'
import BoardPage from './pages/board/BoardPage'
import OverviewLayout from './pages/OverviewLayout'
import ProjectShell from './pages/ProjectShell'
import StageLayout from './pages/stage/StageLayout'
import Welcome from './pages/Welcome'
// 流程图（React Flow）、步骤工作区（Markdown/KaTeX/高亮）、数据视图较大，按需加载
const DataPage = lazy(() => import('./pages/data/DataPage'))
const LifecyclePage = lazy(() => import('./pages/lifecycle/LifecyclePage'))
const StepPage = lazy(() => import('./pages/step/StepPage'))
const RunsPage = lazy(() => import('./pages/runs/RunsPage'))
const TrackerPage = lazy(() => import('./pages/tracker/TrackerPage'))
const ModelsPage = lazy(() => import('./pages/models/ModelsPage'))
const StageOverview = lazy(() => import('./pages/stage/StageOverview'))
const StageData = lazy(() => import('./pages/stage/StageData'))
const StageFiles = lazy(() => import('./pages/stage/StageFiles'))

/**
 * 导航：顶栏切换项目；进入项目后左侧是「总览」+ 生命周期的各个阶段。
 * 总览与每个阶段都有分组选项卡（业务层｜数据层｜执行层）；阶段里的页面只显示本阶段步骤的内容。
 */
export default function App() {
  const [open, setOpen] = useState(false)
  return (
    <NavContext.Provider value={{ open, setOpen }}>
      <div className="flex h-full flex-col">
        <TopBar />
        <div className="min-h-0 flex-1">
          <Suspense fallback={<p className="p-6 text-sm text-slate-500">加载页面…</p>}>
            <Routes>
              <Route path="/" element={<Welcome />} />
              <Route path="/p/:id" element={<ProjectShell />}>
                <Route element={<OverviewLayout />}>
                  <Route index element={<BoardPage />} />
                  <Route path="flow" element={<LifecyclePage />} />
                  <Route path="data" element={<DataPage />} />
                  <Route path="runs" element={<RunsPage />} />
                  <Route path="runs/:runId" element={<RunsPage />} />
                  <Route path="models" element={<ModelsPage />} />
                  <Route path="models/:name/:version" element={<ModelsPage />} />
                  <Route path="tracker" element={<TrackerPage />} />
                  <Route path="knowledge" element={<Navigate to=".." relative="path" replace />} />
                </Route>
                <Route path="stage/:stageId" element={<StageLayout />}>
                  <Route index element={<StageOverview />} />
                  <Route path="data" element={<StageData />} />
                  <Route path="files" element={<StageFiles />} />
                  <Route path="runs" element={<RunsPage />} />
                  <Route path="runs/:runId" element={<RunsPage />} />
                  <Route path="models" element={<ModelsPage />} />
                  <Route path="models/:name/:version" element={<ModelsPage />} />
                  <Route path="tracker" element={<Navigate to=".." relative="path" replace />} />
                  <Route path="knowledge" element={<Navigate to=".." relative="path" replace />} />
                </Route>
                <Route path="steps/:stepId" element={<StepPage />} />
                <Route path="overview" element={<Navigate to=".." relative="path" replace />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </div>
      </div>
    </NavContext.Provider>
  )
}
