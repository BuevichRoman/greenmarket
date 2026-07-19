import { useState } from 'react'
import type { FormEvent } from 'react'
import { publish } from './api'
import type { PublishResult } from './api'

type Status = 'idle' | 'loading' | 'done'

function PublishScreen({ accessToken }: { accessToken: string }) {
  const [sheetInput, setSheetInput] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [result, setResult] = useState<PublishResult | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setStatus('loading')
    setResult(null)
    const isUrl = sheetInput.includes('/')
    const res = await publish({
      access_token: accessToken,
      ...(isUrl ? { sheet_url: sheetInput } : { spreadsheet_id: sheetInput }),
    })
    setResult(res)
    setStatus('done')
  }

  return (
    <section className="screen">
      <h1>Публикация каталога</h1>
      <p className="hint">
        Вставь <code>spreadsheet_id</code> или полную ссылку на рабочую книгу Google Sheets — сервер прочитает
        её, провалидирует и опубликует текущий каталог продавца.
      </p>

      <form className="publish-form" onSubmit={handleSubmit}>
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
          <h2>
            Публикация выполнена успешно{' '}
            <span className={`mode-badge mode-${result.data.mode}`}>
              {result.data.mode === 'test' ? 'ТЕСТ' : 'БОЙ'}
            </span>
          </h2>
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
            <table className="data-table">
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
  )
}

export default PublishScreen
