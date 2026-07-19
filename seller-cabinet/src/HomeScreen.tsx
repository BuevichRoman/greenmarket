import { useEffect, useState } from 'react'
import { fetchSellerStatus } from './api'
import type { SellerStatusResult } from './api'

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU')
}

function HomeScreen({ accessToken }: { accessToken: string }) {
  const [result, setResult] = useState<SellerStatusResult | null>(null)

  useEffect(() => {
    fetchSellerStatus(accessToken).then(setResult)
  }, [accessToken])

  if (result === null) {
    return (
      <section className="screen">
        <h1>Главная</h1>
        <p className="hint">Загрузка…</p>
      </section>
    )
  }

  if (!result.ok) {
    return (
      <section className="screen">
        <h1>Главная</h1>
        <div className="result error">
          <h2>Не удалось загрузить статус ({result.error.code})</h2>
          <p>{result.error.message}</p>
        </div>
      </section>
    )
  }

  const status = result.data

  return (
    <section className="screen">
      <h1>Главная</h1>
      {!status.is_active && (
        <div className="notice">Продавец ожидает активации — публикация каталога недоступна.</div>
      )}
      <div className="status-card">
        <div className="status-row">
          <span>Статус</span>
          <span>{status.is_active ? 'Активен' : 'Ожидает активации'}</span>
        </div>
        <div className="status-row">
          <span>Текущая версия каталога</span>
          <span>{status.current_catalog_version}</span>
        </div>
        <div className="status-row">
          <span>Опубликовано товаров</span>
          <span>{status.published_product_count}</span>
        </div>
        <div className="status-row">
          <span>Дата последней публикации</span>
          <span>{formatDate(status.last_published_at)}</span>
        </div>
      </div>
    </section>
  )
}

export default HomeScreen
