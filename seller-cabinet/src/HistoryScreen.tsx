import { useEffect, useState } from 'react'
import { fetchPublicationHistory } from './api'
import type { PublicationHistoryResult } from './api'

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU')
}

function HistoryScreen({ accessToken }: { accessToken: string }) {
  const [result, setResult] = useState<PublicationHistoryResult | null>(null)

  useEffect(() => {
    fetchPublicationHistory(accessToken).then(setResult)
  }, [accessToken])

  if (result === null) {
    return (
      <section className="screen">
        <h1>История публикаций</h1>
        <p className="hint">Загрузка…</p>
      </section>
    )
  }

  if (!result.ok) {
    return (
      <section className="screen">
        <h1>История публикаций</h1>
        <div className="result error">
          <h2>Не удалось загрузить историю ({result.error.code})</h2>
          <p>{result.error.message}</p>
        </div>
      </section>
    )
  }

  const { publications } = result.data

  return (
    <section className="screen">
      <h1>История публикаций</h1>
      {publications.length === 0 ? (
        <p className="hint">Публикаций ещё не было.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Версия</th>
              <th>Дата</th>
              <th>Создано</th>
              <th>Обновлено</th>
              <th>Деактивировано</th>
            </tr>
          </thead>
          <tbody>
            {publications.map((p) => (
              <tr key={p.version}>
                <td>{p.version}</td>
                <td>{formatDate(p.published_at)}</td>
                <td>{p.created}</td>
                <td>{p.updated}</td>
                <td>{p.deactivated}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

export default HistoryScreen
