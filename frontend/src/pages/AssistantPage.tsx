import { AssistantPanel } from '../components/AssistantPanel'
import { PageHeader, SectionCard } from '../components/ui/PaperBits'
import type { AppRoute, Project } from '../types'

interface AssistantPageProps {
  projects: Project[]
  onDataChanged: () => void
  onNavigate: (route: AppRoute) => void
}

const CAPABILITIES = [
  '把复杂目标拆成父任务与子任务，确认后一次创建',
  '根据今天的可用时间排出时间块，可先编辑再保存',
  '结合截止时间、优先级和项目日期给出优先级建议',
  '用真实任务与活动记录生成日报、周报和项目报告',
  '查询任务、项目、子任务和当前进度',
]

export function AssistantPage({
  projects,
  onDataChanged,
  onNavigate,
}: AssistantPageProps) {
  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="AI ASSISTANT / 小帮手"
        title={
          <>
            先商量，
            <br />
            <span className="marker">再动手。</span>
          </>
        }
        description="AI 只读取真实数据；所有创建、修改、计划与报告，都要你确认后才会写入。"
      />

      <div className="assistant-page-grid">
        <AssistantPanel
          projects={projects}
          onTasksChanged={onDataChanged}
          onOpenReport={(reportId) => onNavigate({ name: 'report', id: reportId })}
        />

        <aside className="assistant-aside">
          <SectionCard no="01 /" title="可以帮我做什么" subtitle="全部基于真实数据">
            <ul className="capability-list">
              {CAPABILITIES.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </SectionCard>

          <SectionCard no="02 /" title="安全边界" subtitle="写操作不越过你" tone="sticky">
            <ol className="capability-list numbered">
              <li>AI 不会直接写数据库，也不会执行代码或 Shell。</li>
              <li>每次写入先生成服务端待确认操作，有有效期。</li>
              <li>同一操作重复确认不会重复创建；未确认不会生效。</li>
              <li>报告中的统计由后端计算，AI 只负责措辞与建议。</li>
            </ol>
            <button
              className="paper-inline-button"
              type="button"
              onClick={() => onNavigate({ name: 'tasks' })}
            >
              回到任务清单
            </button>
          </SectionCard>
        </aside>
      </div>
    </div>
  )
}
