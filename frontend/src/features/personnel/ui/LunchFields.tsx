import type { Dispatch, ReactNode, SetStateAction } from 'react'

import type { LunchPlace } from '@/features/personnel/types'

import { LUNCH_PLACES, type LunchDraft } from '../lib/lunch'
import { AddressPointField, type AddressPoint } from './AddressPointField'
import { FieldLabel, Hint, ToggleChip, WorkTimeField } from './formParts'

type LunchFieldsProps = {
  value: LunchDraft
  /** Что не так с окном (`lunchTimeError`); null — всё в порядке. */
  timeError: string | null
  onTime: (next: Partial<Pick<LunchDraft, 'timeFrom' | 'timeTo'>>) => void
  onPlace: (place: LunchPlace) => void
  onSpot: Dispatch<SetStateAction<AddressPoint>>
  /** Подпись под окном, когда оно в порядке: у инженера — «как у бригады» или своё. */
  timeHint?: ReactNode
  /** Подпись под местом: у инженера — «как у бригады» или своё. */
  placeHint?: ReactNode
}

/**
 * Обед: окно, в котором планировщик сам ставит час обеда между заявками, и место —
 * у последней заявки (без лишней дороги), в офисе или в своей точке. До офиса и своей
 * точки инженеру надо доехать, и эту дорогу план тоже учитывает.
 */
export function LunchFields({
  value,
  timeError,
  onTime,
  onPlace,
  onSpot,
  timeHint = 'Час внутри окна — когда именно, решит план',
  placeHint,
}: LunchFieldsProps) {
  return (
    <>
      <div className="flex flex-col gap-1">
        <FieldLabel required>Время обеда</FieldLabel>
        <div className="flex items-center">
          <WorkTimeField
            aria-label="Начало окна обеда"
            value={value.timeFrom}
            onChange={(timeFrom) => onTime({ timeFrom })}
          />
          <span
            className="shrink-0 text-sm leading-5 text-muted"
            style={{ width: 12, textAlign: 'center' }}
          >
            -
          </span>
          <WorkTimeField
            aria-label="Конец окна обеда"
            value={value.timeTo}
            onChange={(timeTo) => onTime({ timeTo })}
          />
        </div>
        {timeError ? (
          <p className="text-xs leading-5 text-danger">{timeError}</p>
        ) : (
          <Hint>{timeHint}</Hint>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <FieldLabel required>Место обеда</FieldLabel>
        <div className="flex flex-wrap gap-1 pt-1">
          {LUNCH_PLACES.map((option) => (
            <ToggleChip
              key={option.id}
              active={value.place === option.id}
              onToggle={() => onPlace(option.id)}
            >
              {option.label}
            </ToggleChip>
          ))}
        </div>
        {value.place === 'point' ? (
          <div className="pt-1">
            <AddressPointField
              value={value.spot}
              onChange={onSpot}
              label="Место обеда"
              pointName="место обеда"
              doneHint="Сюда инженер поедет на обед"
            />
          </div>
        ) : null}
        {placeHint ? <Hint>{placeHint}</Hint> : null}
      </div>
    </>
  )
}
