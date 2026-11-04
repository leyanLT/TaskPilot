/* oxlint-disable react/set-state-in-effect -- data loading on mount; state is set after the request resolves. */
import { App, Modal, Spin } from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import { recurrenceApi } from '../services/v2'
import type { RecurrenceFrequency, RecurrenceRule } from '../types/v2'
import { APP_TIMEZONE } from '../utils/datetime'

const FREQUENCY_LABELS: Record<RecurrenceFrequency, string> = {
  daily: '每天',
  weekly: '每周',
  monthly: '每月',
  custom_weekly: '自定义每周',
}

const WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

function todayIso(): string {
  return dayjs().tz(APP_TIMEZONE).format('YYYY-MM-DD')
}

export function RecurrencePanel({ dataVersion }: { dataVersion: number }) {
  const { message } = App.useApp()
  const [rules, setRules] = useState<RecurrenceRule[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [title, setTitle] = useState('')
  const [frequency, setFrequency] = useState<RecurrenceFrequency>('daily')
  const [weekdays, setWeekdays] = useState<number[]>([0])
  const [startDate, setStartDate] = useState(todayIso())
  const [endDate, setEndDate] = useState('')
  const [dueTime, setDueTime] = useState('09:00')
  const [estimated, setEstimated] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRules(await recurrenceApi.list())
    } catch (error) {
      message.error(getApiErrorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    void load()
  }, [load, dataVersion])

  const reset = () => {
    setTitle('')
    setFrequency('daily')
    setWeekdays([0])
    setStartDate(todayIso())
    setEndDate('')
    setDueTime('09:00')
    setEstimated('')
  }

  const create = async () => {
    if (!title.trim()) {
      message.warning('给重复任务起个名字。')
      return
    }
    setSaving(true)
    try {
      await recurrenceApi.create({
        title: title.trim(),
        frequency,
        weekdays: frequency === 'custom_weekly' ? weekdays : null,
        startDate,
        endDate: endDate || null,
        dueTime: dueTime || null,
        estimatedMinutes: estimated ? Number(estimated) : null,
        interval: 1,
      })
      message.success('重复规则已创建，近期任务已生成。')
      setOpen(false)
      reset()
      await load()
    } catch (error) {
      message.error(getApiErrorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  const togglePaused = async (rule: RecurrenceRule) => {
    try {
      await recurrenceApi.setPaused(rule.id, !rule.paused)
      message.success(rule.paused ? '已恢复生成。' : '已暂停生成。')
      await load()
    } catch (error) {
      message.error(getApiErrorMessage(error))
    }
  }

  const remove = async (rule: RecurrenceRule) => {
    try {
      await recurrenceApi.remove(rule.id)
      message.success('重复系列已删除，已完成的历史任务仍然保留。')
      await load()
    } catch (error) {
      message.error(getApiErrorMessage(error))
    }
  }

  return (
    <div className="recurrence-panel">
      {loading && rules.length === 0 ? (
        <div className="center-state small">
          <Spin size="small" />
          <p>正在读取重复规则…</p>
        </div>
      ) : null}
      {!loading && rules.length === 0 ? (
        <p className="muted-note">还没有重复任务。每天读书、每周写周报都可以放在这里。</p>
      ) : null}
      <ul className="recurrence-list">
        {rules.map((rule) => (
          <li key={rule.id} className={rule.paused ? 'is-paused' : ''}>
            <div className="recurrence-top">
              <strong>{rule.title}</strong>
              <span className="recurrence-freq">
                {FREQUENCY_LABELS[rule.frequency]}
                {rule.frequency === 'custom_weekly' && rule.weekdays
                  ? ` · ${rule.weekdays.map((day) => WEEKDAY_NAMES[day]).join('、')}`
                  : ''}
              </span>
            </div>
            <p className="recurrence-meta">
              {rule.paused ? '已暂停生成' : `下次 ${rule.nextOccurrence ?? '待定'}`}
              {rule.dueTime ? ` · ${rule.dueTime}` : ''} · 已生成 {rule.generatedCount} 个，
              完成 {rule.completedCount} 个
            </p>
            <div className="recurrence-actions">
              <button
                className="paper-inline-button"
                type="button"
                onClick={() => void togglePaused(rule)}
              >
                {rule.paused ? '恢复' : '暂停'}
              </button>
              <button
                className="task-action danger"
                type="button"
                aria-label={`删除重复系列 ${rule.title}`}
                onClick={() => void remove(rule)}
              >
                删除系列
              </button>
            </div>
          </li>
        ))}
      </ul>
      <button className="paper-inline-button" type="button" onClick={() => setOpen(true)}>
        ＋ 新建重复任务
      </button>

      <Modal
        open={open}
        title="新建重复任务"
        okText="创建规则"
        cancelText="取消"
        confirmLoading={saving}
        onOk={() => void create()}
        onCancel={() => setOpen(false)}
      >
        <div className="recurrence-form">
          <label>
            名称
            <input
              className="paper-input"
              value={title}
              aria-label="重复任务名称"
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label>
            重复方式
            <select
              aria-label="重复方式"
              value={frequency}
              onChange={(event) => setFrequency(event.target.value as RecurrenceFrequency)}
            >
              {Object.entries(FREQUENCY_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {frequency === 'custom_weekly' ? (
            <div className="recurrence-weekdays">
              {WEEKDAY_NAMES.map((name, index) => (
                <label key={name}>
                  <input
                    type="checkbox"
                    checked={weekdays.includes(index)}
                    onChange={(event) =>
                      setWeekdays((current) =>
                        event.target.checked
                          ? [...current, index].sort()
                          : current.filter((day) => day !== index),
                      )
                    }
                  />
                  {name}
                </label>
              ))}
            </div>
          ) : null}
          <div className="recurrence-form-row">
            <label>
              开始日期
              <input
                type="date"
                value={startDate}
                aria-label="开始日期"
                onChange={(event) => setStartDate(event.target.value)}
              />
            </label>
            <label>
              结束日期（可选）
              <input
                type="date"
                value={endDate}
                aria-label="结束日期"
                onChange={(event) => setEndDate(event.target.value)}
              />
            </label>
          </div>
          <div className="recurrence-form-row">
            <label>
              截止时刻
              <input
                type="time"
                value={dueTime}
                aria-label="截止时刻"
                onChange={(event) => setDueTime(event.target.value)}
              />
            </label>
            <label>
              预计耗时（分钟）
              <input
                type="number"
                min={5}
                max={1440}
                value={estimated}
                aria-label="预计耗时"
                onChange={(event) => setEstimated(event.target.value)}
              />
            </label>
          </div>
          <p className="muted-note">最多提前生成 14 天的任务；修改规则会重建今天之后的未完成实例。</p>
        </div>
      </Modal>
    </div>
  )
}
