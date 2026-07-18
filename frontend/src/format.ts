// price/stock приходят от backend строками (Decimal), см. types.ts.
export function formatPrice(value: string): string {
  return `${value.replace('.', ',')} ₽`
}

export function formatStock(value: string, unit: string): string {
  const n = Number(value)
  const trimmed = Number.isInteger(n) ? String(n) : value.replace('.', ',')
  return `${trimmed} ${unit}`
}
