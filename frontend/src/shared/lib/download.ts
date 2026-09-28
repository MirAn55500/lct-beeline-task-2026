/** Скачивание текста как файла. Ссылку нужно вставить в документ: иначе браузер игнорирует download. */
export function downloadTextFile(body: string, type: string, fileName: string) {
  const url = URL.createObjectURL(new Blob([body], { type: `${type};charset=utf-8` }))
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
