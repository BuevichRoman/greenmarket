import { useState } from 'react'
import HistoryScreen from './HistoryScreen'
import HomeScreen from './HomeScreen'
import PublishScreen from './PublishScreen'

// Токен — единственный способ идентифицировать продавца (см. app/publication/
// seller_access.py на бэкенде): персональная ссылка вида /?token=... вместо
// открытых полей seller_id/published_by, которые раньше позволяли
// опубликовать каталог от имени любого чужого продавца.
function readAccessToken(): string | null {
  return new URLSearchParams(window.location.search).get('token')
}

// Чисто визуальная подсказка "какая это ссылка" (?env=test|prod в самой ссылке,
// проставляется вручную при раздаче ссылки продавцу/себе) — НЕ связана с реальным
// режимом публикации: тот определяется полем Mode в самой Google-таблице и
// становится известен только после ответа POST /publications (см. mode-badge в
// PublishScreen). Тут просто напоминание, чтобы не перепутать, какую ссылку кому дали.
function readEnvLabel(): 'test' | 'prod' | null {
  const value = new URLSearchParams(window.location.search).get('env')
  return value === 'test' || value === 'prod' ? value : null
}

type Screen = 'home' | 'history' | 'publish'

function App() {
  const [accessToken] = useState(readAccessToken)
  const [envLabel] = useState(readEnvLabel)
  const [screen, setScreen] = useState<Screen>('publish')

  if (!accessToken) {
    return (
      <div className="app">
        <header className="app-header">
          <span className="logo">🧑‍🌾 GreenMarket — Seller Cabinet</span>
          {envLabel && (
            <span className={`mode-badge mode-${envLabel}`}>{envLabel === 'test' ? 'ТЕСТ' : 'БОЙ'}</span>
          )}
        </header>
        <main>
          <section className="screen">
            <h1>Нет доступа</h1>
            <p className="hint">
              В ссылке нет персонального токена продавца (<code>?token=…</code>). Обратитесь за своей ссылкой к
              GreenMarket — вводить чужой Seller ID вручную больше нельзя.
            </p>
          </section>
        </main>
      </div>
    )
  }

  return (
    <div className="app">
      <header className="app-header">
        <span className="logo">🧑‍🌾 GreenMarket — Seller Cabinet</span>
        {envLabel && (
          <span className={`mode-badge mode-${envLabel}`}>{envLabel === 'test' ? 'ТЕСТ' : 'БОЙ'}</span>
        )}
        <nav className="nav-tabs">
          <button className={screen === 'home' ? 'active' : ''} onClick={() => setScreen('home')}>
            Главная
          </button>
          <button className={screen === 'history' ? 'active' : ''} onClick={() => setScreen('history')}>
            История
          </button>
          <button className={screen === 'publish' ? 'active' : ''} onClick={() => setScreen('publish')}>
            Публикация
          </button>
        </nav>
      </header>

      <main>
        {screen === 'home' && <HomeScreen accessToken={accessToken} />}
        {screen === 'history' && <HistoryScreen accessToken={accessToken} />}
        {screen === 'publish' && <PublishScreen accessToken={accessToken} />}
      </main>
    </div>
  )
}

export default App
