function safeFilename(value: string): string {
  const cleaned = Array.from(value, (character) => {
    const code = character.charCodeAt(0)
    return code <= 31 || code === 127 || '/\\:*?"<>|'.includes(character) ? '_' : character
  }).join('').trim()
  return cleaned || 'alinea-download'
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = safeFilename(filename)
  anchor.hidden = true
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}
