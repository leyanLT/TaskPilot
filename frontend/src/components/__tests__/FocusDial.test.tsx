import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { FocusDial } from '../FocusDial'
import { focusMotivation } from '../../utils/focus'

describe('FocusDial', () => {
  it('counts down from the remaining seconds', () => {
    render(
      <FocusDial elapsedSeconds={300} targetSeconds={1500} status="running" taskTitle="写周报" />,
    )
    expect(screen.getByText('20:00')).toBeInTheDocument()
    expect(screen.getByText('倒计时')).toBeInTheDocument()
    expect(screen.getByRole('timer')).toHaveAttribute(
      'aria-label',
      '剩余 20 分钟，已专注 5 分钟',
    )
  })

  it('shows the paused state without pretending to run', () => {
    render(
      <FocusDial elapsedSeconds={120} targetSeconds={1500} status="paused" taskTitle="写周报" />,
    )
    expect(screen.getByText('已暂停')).toBeInTheDocument()
    expect(screen.getByText('23:00')).toBeInTheDocument()
  })

  it('celebrates when the target is reached', () => {
    const { container } = render(
      <FocusDial elapsedSeconds={1500} targetSeconds={1500} status="running" taskTitle="写周报" />,
    )
    expect(screen.getByText('00:00')).toBeInTheDocument()
    expect(screen.getByText('已达标')).toBeInTheDocument()
    expect(container.querySelector('.focus-confetti')).not.toBeNull()
    expect(container.querySelectorAll('.focus-confetti i')).toHaveLength(16)
  })

  it('changes the motivational copy with progress', () => {
    expect(focusMotivation('running', 1200, 1500)).toContain('放远一点')
    expect(focusMotivation('running', 800, 1500)).toContain('过半')
    expect(focusMotivation('running', 200, 1500)).toContain('最后 5 分钟')
    expect(focusMotivation('running', 0, 1500)).toContain('时间到')
    expect(focusMotivation('paused', 900, 1500)).toContain('暂停')
  })
})
