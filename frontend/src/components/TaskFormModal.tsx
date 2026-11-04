import { App, DatePicker, Form, Input, InputNumber, Modal, Select } from 'antd'
import type { Dayjs } from 'dayjs'
import { useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import type { Project, Task, TaskInput, TaskPriority } from '../types'
import { toAppTimezone, toIsoString } from '../utils/datetime'

const { TextArea } = Input

const PRIORITY_OPTIONS: Array<{ label: string; value: TaskPriority }> = [
  { label: '高', value: 'high' },
  { label: '中', value: 'medium' },
  { label: '弱', value: 'low' },
]

interface TaskFormValues {
  title: string
  description?: string
  dueAt?: Dayjs | null
  projectId?: string | null
  priority?: TaskPriority
  estimatedMinutes?: number | null
}

interface TaskFormModalProps {
  open: boolean
  task: Task | null
  onCancel: () => void
  onSubmit: (input: TaskInput) => Promise<void>
  projects?: Project[]
  defaultProjectId?: string | null
}

export function TaskFormModal({
  open,
  task,
  onCancel,
  onSubmit,
  projects = [],
  defaultProjectId = null,
}: TaskFormModalProps) {
  const [form] = Form.useForm<TaskFormValues>()
  const [saving, setSaving] = useState(false)
  const { message } = App.useApp()
  const isEditing = Boolean(task)
  const isSubtask = Boolean(task?.parentId)

  useEffect(() => {
    if (!open) {
      return
    }
    if (task) {
      form.setFieldsValue({
        title: task.title,
        description: task.description ?? undefined,
        dueAt: task.dueAt ? toAppTimezone(task.dueAt) : null,
        projectId: task.projectId,
        priority: task.priority,
        estimatedMinutes: task.estimatedMinutes,
      })
    } else {
      form.resetFields()
      form.setFieldsValue({
        priority: 'medium',
        projectId: defaultProjectId,
      })
    }
  }, [form, open, task, defaultProjectId])

  const handleCancel = () => {
    if (saving) {
      return
    }
    form.resetFields()
    onCancel()
  }

  const handleFinish = async (values: TaskFormValues) => {
    setSaving(true)
    try {
      await onSubmit({
        title: values.title.trim(),
        description: values.description?.trim() || null,
        dueAt: toIsoString(values.dueAt),
        projectId: isSubtask ? (task?.projectId ?? null) : (values.projectId ?? null),
        priority: values.priority ?? 'medium',
        estimatedMinutes: values.estimatedMinutes ?? null,
      })
      form.resetFields()
    } catch (error) {
      message.error(getApiErrorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      className="paper-modal"
      rootClassName="paper-modal-root"
      width={560}
      centered
      title={
        <div className="modal-title-wrap">
          <span className="modal-eyebrow">
            {isEditing ? 'EDITING A NOTE' : 'A NEW LITTLE THING'}
          </span>
          <span>{isEditing ? '编辑任务' : '新建任务'}</span>
        </div>
      }
      okText={isEditing ? '保存修改' : '创建任务'}
      cancelText="取消"
      confirmLoading={saving}
      onOk={() => form.submit()}
      onCancel={handleCancel}
      okButtonProps={{ className: 'paper-dialog-primary' }}
      cancelButtonProps={{ disabled: saving, className: 'paper-dialog-cancel' }}
      destroyOnHidden
      mask={{ closable: !saving }}
      closable={!saving}
      keyboard={!saving}
    >
      <p className="modal-note">写下一件要记住的小事，剩下的交给今天。</p>
      <Form
        form={form}
        layout="vertical"
        onFinish={handleFinish}
        className="task-form paper-form"
        initialValues={{ priority: 'medium' }}
      >
        <Form.Item
          name="title"
          label="标题"
          required
          rules={[
            {
              validator: (_, value: string | undefined) => {
                const title = typeof value === 'string' ? value.trim() : ''
                if (!title) {
                  return Promise.reject(new Error('请输入任务标题'))
                }
                if (title.length > 100) {
                  return Promise.reject(new Error('标题不能超过 100 个字符'))
                }
                return Promise.resolve()
              },
            },
          ]}
        >
          <Input
            placeholder="例如：完成实验报告"
            maxLength={100}
            showCount
            autoFocus
            onPressEnter={(event) => {
              if (!event.nativeEvent.isComposing) {
                form.submit()
              }
            }}
          />
        </Form.Item>
        <Form.Item
          name="description"
          label="描述"
          rules={[{ max: 500, message: '描述不能超过 500 个字符' }]}
        >
          <TextArea
            placeholder="补充任务背景、要点或验收标准（可选）"
            autoSize={{ minRows: 3, maxRows: 6 }}
            maxLength={500}
            showCount
          />
        </Form.Item>

        <div className="form-grid">
          <Form.Item name="priority" label="优先级">
            <Select options={PRIORITY_OPTIONS} aria-label="优先级" />
          </Form.Item>
          <Form.Item
            name="estimatedMinutes"
            label="预计耗时（分钟）"
            extra="5-1440 分钟，用于每日规划。"
          >
            <InputNumber
              min={5}
              max={1440}
              step={5}
              precision={0}
              placeholder="例如 60"
              style={{ width: '100%' }}
            />
          </Form.Item>
        </div>

        <Form.Item
          name="projectId"
          label="所属项目"
          extra={isSubtask ? '子任务的所属项目跟随父任务。' : '可以先不选项目。'}
        >
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="选择项目（可选）"
            disabled={isSubtask}
            aria-label="所属项目"
            options={projects.map((project) => ({
              label: project.name,
              value: project.id,
            }))}
          />
        </Form.Item>

        <Form.Item
          name="dueAt"
          label="截止时间"
          extra="按应用时区显示；不着急的话可以留空。"
        >
          <DatePicker
            showTime={{ format: 'HH:mm' }}
            format="YYYY-MM-DD HH:mm"
            placeholder="选择截止时间（可选）"
            style={{ width: '100%' }}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}
