/** Инициалы из первых двух слов имени: «Павел Козлов» → «ПК». */
export function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join('')
}

/** Русское склонение по числу: pluralRu(2, ['человек', 'человека', 'человек']). */
export function pluralRu(count: number, forms: [one: string, few: string, many: string]): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return forms[0]
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1]
  return forms[2]
}
