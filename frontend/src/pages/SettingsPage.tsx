import { App, Spin } from 'antd'
import { useEffect, useState } from 'react'
import { InlineError, PageHeader, SectionCard } from '../components/ui/PaperBits'
import { getApiErrorMessage } from '../services/http'
import { preferenceApi } from '../services/v2'
import type { Preferences } from '../types/v2'

const WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export function SettingsPage() {
  const { message } = App.useApp()
  const [preferences, setPreferences] = useState<Preferences | null>(null)
  const [timezone, setTimezone] = useState('Asia/Shanghai')
  const [availableMinutes, setAvailableMinutes] = useState('300')
  const [focusMinutes, setFocusMinutes] = useState('25')
  const [workdays, setWorkdays] = useState<number[]>([0, 1, 2, 3, 4])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    preferenceApi
      .get()
      .then((data) => {
        if (!active) {
          return
        }
        setPreferences(data)
        setTimezone(data.timezone)
        setAvailableMinutes(String(data.dailyAvailableMinutes))
        setFocusMinutes(String(data.defaultFocusMinutes))
        setWorkdays(data.workdays)
      })
      .catch((loadError: unknown) => {
        if (active) {
          setError(getApiErrorMessage(loadError))
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })
    return () => {
      active = false
    }
  }, [])

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const updated = await preferenceApi.update({
        timezone,
        dailyAvailableMinutes: Number(availableMinutes),
        defaultFocusMinutes: Number(focusMinutes),
        workdays,
      })
      setPreferences(updated)
      message.success('偏好已保存。')
    } catch (saveError) {
      setError(getApiErrorMessage(saveError))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="center-state page-state">
        <Spin size="large" />
        <p>正在读取设置…</p>
      </div>
    )
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="SETTINGS / 自己的节奏"
        title={
          <>
            按你的作息，
            <br />
            <span className="marker">排你的时间。</span>
          </>
        }
        description="这些设置会影响可用时间计算、日历默认容量和专注时长。"
      />

      {error ? <InlineError message={error} /> : null}

      <SectionCard no="01 /" title="时间与节奏" subtitle="单用户本地设置">
        <div className="settings-form">
          <label>
            时区
            <select
              aria-label="时区"
              value={timezone}
              onChange={(event) => setTimezone(event.target.value)}
            >
              {[
                'Asia/Shanghai',
                'Asia/Tokyo',
                'Europe/London',
                'America/New_York',
                'UTC',
              ].map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>
          </label>
          <label>
            每日可用工作时间（分钟）
            <input
              type="number"
              min={5}
              max={1440}
              value={availableMinutes}
              aria-label="每日可用工作时间"
              onChange={(event) => setAvailableMinutes(event.target.value)}
            />
          </label>
          <label>
            默认专注时长（分钟）
            <input
              type="number"
              min={5}
              max={240}
              value={focusMinutes}
              aria-label="默认专注时长"
              onChange={(event) => setFocusMinutes(event.target.value)}
            />
          </label>

          <fieldset className="settings-workdays">
            <legend>常用工作日</legend>
            {WEEKDAY_NAMES.map((name, index) => (
              <label key={name}>
                <input
                  type="checkbox"
                  checked={workdays.includes(index)}
                  onChange={(event) =>
                    setWorkdays((current) =>
                      event.target.checked
                        ? [...current, index].sort()
                        : current.filter((day) => day !== index),
                    )
                  }
                />
                {name}
              </label>
            ))}
          </fieldset>

          <div className="settings-actions">
            <button
              className="paper-inline-button primary"
              type="button"
              disabled={saving || workdays.length === 0}
              onClick={() => void save()}
            >
              {saving ? '保存中…' : '保存设置'}
            </button>
            <span className="muted-note">
              上次更新：
              {preferences ? new Date(preferences.updatedAt).toLocaleString() : '未知'}
            </span>
          </div>
        </div>
      </SectionCard>

      <SectionCard no="02 /" title="AI 与提醒" subtitle="只读提示">
        <p className="muted-note">
          AI 模型与密钥由服务端环境变量配置（DEEPSEEK_API_KEY / DEEPSEEK_MODEL），
          不在浏览器里保存。应用内提醒的提前小时数使用服务端默认值，V2.0 暂未提供单独的开关。
        </p>
      </SectionCard>
    </div>
  )
}
