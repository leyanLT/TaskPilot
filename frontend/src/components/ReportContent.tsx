import type { ReactNode } from 'react'

function renderInline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={index}>{part.slice(2, -2)}</strong>
    }
    return <span key={index}>{part}</span>
  })
}

export function ReportContent({ content }: { content: string }) {
  const lines = content.split('\n')
  const blocks: ReactNode[] = []
  let listItems: string[] = []
  let listOrdered = false

  const flushList = () => {
    if (listItems.length === 0) {
      return
    }
    const items = listItems
    listItems = []
    blocks.push(
      listOrdered ? (
        <ol className="report-list" key={`list-${blocks.length}`}>
          {items.map((item, index) => (
            <li key={index}>{renderInline(item)}</li>
          ))}
        </ol>
      ) : (
        <ul className="report-list" key={`list-${blocks.length}`}>
          {items.map((item, index) => (
            <li key={index}>{renderInline(item)}</li>
          ))}
        </ul>
      ),
    )
  }

  lines.forEach((rawLine, index) => {
    const line = rawLine.trimEnd()
    const trimmed = line.trim()
    if (!trimmed) {
      flushList()
      return
    }
    if (trimmed === '---') {
      flushList()
      blocks.push(<hr className="report-rule" key={`hr-${index}`} />)
      return
    }
    if (trimmed.startsWith('# ')) {
      flushList()
      blocks.push(
        <h1 className="report-title" key={`h1-${index}`}>
          {renderInline(trimmed.slice(2))}
        </h1>,
      )
      return
    }
    if (trimmed.startsWith('## ')) {
      flushList()
      blocks.push(
        <h2 className="report-heading" key={`h2-${index}`}>
          {renderInline(trimmed.slice(3))}
        </h2>,
      )
      return
    }
    if (trimmed.startsWith('### ')) {
      flushList()
      blocks.push(
        <h3 className="report-subheading" key={`h3-${index}`}>
          {renderInline(trimmed.slice(4))}
        </h3>,
      )
      return
    }
    if (trimmed.startsWith('> ')) {
      flushList()
      blocks.push(
        <blockquote className="report-quote" key={`quote-${index}`}>
          {renderInline(trimmed.slice(2))}
        </blockquote>,
      )
      return
    }
    if (trimmed.startsWith('- ')) {
      if (listOrdered) {
        flushList()
        listOrdered = false
      }
      listOrdered = false
      listItems.push(trimmed.slice(2))
      return
    }
    const orderedMatch = /^(\d+)\.\s+(.*)$/.exec(trimmed)
    if (orderedMatch) {
      if (!listOrdered) {
        flushList()
        listOrdered = true
      }
      listItems.push(orderedMatch[2])
      return
    }
    flushList()
    blocks.push(
      <p className="report-paragraph" key={`p-${index}`}>
        {renderInline(trimmed)}
      </p>,
    )
  })
  flushList()

  return <div className="report-content">{blocks}</div>
}
