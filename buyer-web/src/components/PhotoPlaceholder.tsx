// Buyer_MVP.md, "Фотографии": если фото нет — заглушка платформы.
export function PhotoPlaceholder({ label }: { label: string }) {
  return (
    <div className="photo-placeholder" role="img" aria-label={label}>
      🥬
    </div>
  )
}
