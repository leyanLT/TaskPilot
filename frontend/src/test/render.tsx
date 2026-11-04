import { App as AntApp, ConfigProvider } from 'antd'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'

export function renderWithApp(ui: ReactElement) {
  return render(
    <ConfigProvider button={{ autoInsertSpace: false }}>
      <AntApp>{ui}</AntApp>
    </ConfigProvider>,
  )
}
