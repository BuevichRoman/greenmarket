import { useState } from 'react'
import type { FormEvent } from 'react'

interface Props {
  onSubmit: (query: string) => void
  initialValue?: string
}

export function SearchBar({ onSubmit, initialValue }: Props) {
  const [value, setValue] = useState(initialValue ?? '')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (value.trim()) onSubmit(value.trim())
  }

  return (
    <form className="search-bar" onSubmit={handleSubmit}>
      <input
        type="search"
        placeholder="Найти товар…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        aria-label="Поиск товара"
      />
      <button type="submit">Найти</button>
    </form>
  )
}
