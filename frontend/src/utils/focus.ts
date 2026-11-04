export function focusMotivation(
  status: 'running' | 'paused',
  remainingSeconds: number,
  targetSeconds: number,
): string {
  if (status === 'paused') {
    return '已经暂停，时间停在原地；回来时从这一秒接着走。'
  }
  if (remainingSeconds <= 0) {
    return '时间到。这一块已经做完了，收个尾，别急着开下一件。'
  }
  const ratio = targetSeconds > 0 ? remainingSeconds / targetSeconds : 0
  if (remainingSeconds <= 300) {
    return '最后 5 分钟，先别开新话题，把手上这段收干净。'
  }
  if (ratio <= 0.34) {
    return '只剩不到三分之一了，比刚才更接近结束。'
  }
  if (ratio <= 0.6) {
    return '已经过半，节奏是对的，保持住。'
  }
  return '刚开始，先把手机放远一点，让这一块完整一点。'
}
