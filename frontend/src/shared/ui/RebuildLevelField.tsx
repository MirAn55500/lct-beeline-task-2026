import { REBUILD_LEVELS, type RebuildLevel } from '@/shared/config/rebuildLevels'

import { FieldLabel } from './AppModal'
import { SegmentedControl } from './SegmentedControl'

/** «Уровень перестроения плана»: Фикс / Инженерный / Свободный и подсказка под ним. */
export function RebuildLevelField({ value, onChange }: { value: RebuildLevel; onChange: (next: RebuildLevel) => void }) {
  return (
    <div className="flex flex-col gap-2">
      <FieldLabel>Уровень перестроения плана</FieldLabel>
      <SegmentedControl aria-label="Уровень перестроения плана" options={REBUILD_LEVELS} value={value} onChange={onChange} />
      <p className="text-xs leading-5 text-muted">{REBUILD_LEVELS.find((item) => item.id === value)?.hint}</p>
    </div>
  )
}
