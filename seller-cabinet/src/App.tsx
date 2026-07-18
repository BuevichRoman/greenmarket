import { useState } from 'react'
import type { FormEvent } from 'react'
import { publish } from './api'
import type { PublishResult } from './api'

// Seller Cabinet MVP (docs/05-ui/Seller_MVP.md) описывает Экран 2 (скачать
// Excel) и Экран 3 (загрузить файл) — это устарело: реальная архитектура
// (CR-001) читает статический шаблон Google Sheets по spreadsheet_id/sheet_url
// через Service Account, файл не принимается (расхождение уже
// задокументировано в самом Seller_MVP.md). Этот прототип реализует
// Экраны 3+4 против РЕАЛЬНОГО API, не против устаревшего текста документа.
// Экраны 1 (статус продавца) и 5 (история публикаций) не реализованы — нет
// backing API (Seller API из REST_API.md в коде не существует, есть только
// Publication API).

type Status = 'idle' | 'loading' | 'done'

function App() {
  const [sellerId, setSellerId] = useState('')
  const [publishedBy, setPublishedBy] = useState('')
  const [sheetInput, setSheetInput] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [result, setResult] = useState<PublishResult | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setStatus('loading')
    setResult(null)
    const isUrl = sheetInput.includes('/')
    const res = await publish({
      seller_id: Number(sellerId),
      published_by: Number(publishedBy),
      ...(isUrl ? { sheet_url: sheetInput } : { spreadsheet_id: sheetInput }),
    })
    setResult(res)
    setStatus('done')
  }

  return (
    <div className="app">
      <header className="app-header">
        <span className="logo">🧑‍🌾 GreenMarket — Seller Cabinet</span>
      </header>

      <main>
        <section className="screen">
          <h1>Публикация каталога</h1>
          <p className="hint">
            Вставь <code>spreadsheet_id</code> или полную ссылку на рабочую книгу Google Sheets — сервер прочитает
            её, провалидирует и опубликует текущий каталог продавца.
          </p>

          <form className="publish-form" onSubmit={handleSubmit}>
            <label>
              Seller ID
              <input
                type="number"
                required
                value={sellerId}
                onChange={(e) => setSellerId(e.target.value)}
                placeholder="например, 1669"
              />
            </label>
            <label>
              Published by (id_user администратора/продавца)
              <input
                type="number"
                required
                value={publishedBy}
                onChange={(e) => setPublishedBy(e.target.value)}
                placeholder="например, 2566"
              />
            </label>
            <label>
              Spreadsheet ID или ссылка на таблицу
              <input
                type="text"
                required
                value={sheetInput}
                onChange={(e) => setSheetInput(e.target.value)}
                placeholder="1862KR9D3PdbGp2RD1FV6m1tVmhwdcxOOdtZ0XucQjtA"
              />
            </label>
            <button type="submit" disabled={status === 'loading'}>
              {status === 'loading' ? 'Публикуем…' : 'Опубликовать'}
            </button>
          </form>

          {result && result.ok && (
            <div className="result success">
              <h2>Публикация выполнена успешно</h2>
              <ul className="counts">
                <li>Создано: {result.data.created}</li>
                <li>Обновлено: {result.data.updated}</li>
                <li>Деактивировано: {result.data.deactivated}</li>
              </ul>
              <p className="publication-id">Publication ID: {result.data.publication_id}</p>
            </div>
          )}

          {result && !result.ok && (
            <div className="result error">
              <h2>Ошибка публикации ({result.error.code})</h2>
              <p>{result.error.message}</p>
              {result.error.details.length > 0 && (
                <table className="error-table">
                  <thead>
                    <tr>
                      <th>Лист</th>
                      <th>Строка</th>
                      <th>Колонка</th>
                      <th>Описание</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.error.details.map((d, i) => (
                      <tr key={i}>
                        <td>{d.sheet}</td>
                        <td>{d.row ?? '—'}</td>
                        <td>{d.column ?? '—'}</td>
                        <td>{d.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}

export default App
