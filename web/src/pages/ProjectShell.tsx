import { Suspense } from 'react'
import { Outlet, useParams } from 'react-router'
import Sidebar from '../components/Sidebar'
import TermTip from '../components/TermTip'
import AskDock from '../components/ask/AskDock'
import { AskProvider } from '../components/ask/AskContext'
import SelectionAsk from '../components/ask/SelectionAsk'

/** 项目内的外框：左侧阶段菜单 + 右侧内容 + 右下角的答疑对话框（内容区里选中文字就能提问）+ 行话的解释浮层。 */
export default function ProjectShell() {
  const { id = '' } = useParams()
  return (
    <AskProvider pid={id}>
      <div className="flex h-full">
        <Sidebar pid={id} />
        <main className="min-w-0 flex-1 overflow-hidden" data-ask-root>
          <Suspense fallback={<p className="p-6 text-sm text-slate-500">加载页面…</p>}>
            <Outlet />
          </Suspense>
        </main>
        <SelectionAsk />
        <AskDock />
        <TermTip />
      </div>
    </AskProvider>
  )
}
