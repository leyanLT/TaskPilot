import { App, DatePicker, Form, Input, Modal, Select } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import type { Project, ProjectInput, ProjectStatus } from '../types'

const { TextArea } = Input

const STATUS_OPTIONS: Array<{ label: string; value: ProjectStatus }> = [
  { label: '规划中', value: 'planning' },
  { label: '进行中', value: 'active' },
  { label: '已完成', value: 'completed' },
  { label: '已归档', value: 'archived' },
]

interface ProjectFormValues {
  name: string
  description?: string
  status?: ProjectStatus
  startDate?: Dayjs | null
  dueDate?: Dayjs | null
}

interface ProjectFormModalProps {
  open: boolean
  project: Project | null
  onCancel: () => void
  onSubmit: (input: ProjectInput) => Promise<void>
}

export function ProjectFormModal({
  open,
  project,
  onCancel,
  onSubmit,
}: ProjectFormModalProps) {
  const [form] = Form.useForm<ProjectFormValues>()
  const [saving, setSaving] = useState(false)
  const { message } = App.useApp()
  const isEditing = Boolean(project)

  useEffect(() => {
    if (!open) {
      return
    }
    if (project) {
      form.setFieldsValue({
        name: project.name,
        description: project.description ?? undefined,
        status: project.status,
        startDate: project.startDate ? dayjs(project.startDate) : null,
        dueDate: project.dueDate ? dayjs(project.dueDate) : null,
      })
    } else {
      form.resetFields()
      form.setFieldsValue({ status: 'planning' })
    }
  }, [form, open, project])

  const handleFinish = async (values: ProjectFormValues) => {
    setSaving(true)
    try {
      await onSubmit({
        name: values.name.trim(),
        description: values.description?.trim() || null,
        status: values.status ?? 'planning',
        startDate: values.startDate ? values.startDate.format('YYYY-MM-DD') : null,
        dueDate: values.dueDate ? values.dueDate.format('YYYY-MM-DD') : null,
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
            {isEditing ? 'EDITING A PROJECT' : 'A NEW PROJECT'}
          </span>
          <span>{isEditing ? '编辑项目' : '新建项目'}</span>
        </div>
      }
      okText={isEditing ? '保存修改' : '创建项目'}
      cancelText="取消"
      confirmLoading={saving}
      onOk={() => form.submit()}
      onCancel={() => {
        if (!saving) {
          form.resetFields()
          onCancel()
        }
      }}
      okButtonProps={{ className: 'paper-dialog-primary' }}
      cancelButtonProps={{ disabled: saving, className: 'paper-dialog-cancel' }}
      destroyOnHidden
      mask={{ closable: !saving }}
      closable={!saving}
      keyboard={!saving}
    >
      <p className="modal-note">把一段时间要做的事，装进一个可以看见进度的项目里。</p>
      <Form
        form={form}
        layout="vertical"
        onFinish={handleFinish}
        className="paper-form"
        initialValues={{ status: 'planning' }}
      >
        <Form.Item
          name="name"
          label="项目名称"
          rules={[
            {
              validator: (_, value: string | undefined) => {
                const name = typeof value === 'string' ? value.trim() : ''
                if (!name) {
                  return Promise.reject(new Error('请输入项目名称'))
                }
                if (name.length > 100) {
                  return Promise.reject(new Error('项目名称不能超过 100 个字符'))
                }
                return Promise.resolve()
              },
            },
          ]}
        >
          <Input placeholder="例如：AI Agent 项目" maxLength={100} showCount autoFocus />
        </Form.Item>
        <Form.Item name="description" label="项目描述">
          <TextArea
            placeholder="目标、范围和验收标准（可选）"
            autoSize={{ minRows: 3, maxRows: 6 }}
            maxLength={500}
            showCount
          />
        </Form.Item>
        <Form.Item name="status" label="项目状态">
          <Select options={STATUS_OPTIONS} aria-label="项目状态" />
        </Form.Item>
        <div className="form-grid">
          <Form.Item name="startDate" label="开始日期">
            <DatePicker format="YYYY-MM-DD" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="dueDate" label="截止日期">
            <DatePicker format="YYYY-MM-DD" style={{ width: '100%' }} />
          </Form.Item>
        </div>
      </Form>
    </Modal>
  )
}
