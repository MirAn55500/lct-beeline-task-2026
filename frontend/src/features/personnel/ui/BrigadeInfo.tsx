import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ScrollShadow, Tooltip, toast } from '@heroui/react'
import type { Time } from '@internationalized/date'
import { RiInformationLine, RiMapPinLine } from '@remixicon/react'

import {
  useGetBrigadeAreasQuery,
  useLazyReverseGeocodeQuery,
  useUpdateBrigadeMutation,
} from '@/features/personnel/api'
import type {
  PersonnelBrigade,
  PersonnelEngineer,
  UpdateBrigadeResult,
} from '@/features/personnel/types'
import { pluralRu } from '@/shared/lib/text'
import { AppPanel, AppTooltipContent } from '@/shared/ui'
import { MultiSelectField } from '@/shared/ui/MultiSelectField'

import { errorReason } from '../lib/errors'
import { formatTime, parseTime } from '../lib/time'
import { WEEKDAYS } from '../lib/weekdays'

import { BrigadeMap } from './BrigadeMap'
import { AddressField } from './AddressField'
import { FieldLabel, Hint, ToggleChip, WorkTimeField } from './formParts'

type Draft = {
  officeAddress: string
  /** Точка офиса [lng, lat]: сохранённая или новая — из подсказки или с карты. */
  officePoint: [number, number] | null
  /** Адрес выбран из подсказок или найден по точке, и в нём есть дом. Напечатанный — нет. */
  officeConfirmed: boolean
  /** Названия районов: мультиселект работает строками, в id переводим при сохранении. */
  areas: string[]
  workDays: number[]
  timeFrom: Time | null
  timeTo: Time | null
}

function draftOf(brigade: PersonnelBrigade, areaName: Map<number, string>): Draft {
  return {
    officeAddress: brigade.officeAddress ?? '',
    officePoint: brigade.officePoint,
    officeConfirmed: true,
    areas: brigade.areaIds.flatMap((id) => areaName.get(id) ?? []),
    workDays: [...brigade.workDays].sort(),
    timeFrom: parseTime(brigade.startWork),
    timeTo: parseTime(brigade.endWork),
  }
}

function sameDraft(a: Draft, b: Draft) {
  const time = (value: Time | null) => (value ? formatTime(value) : '')
  return (
    a.officeAddress === b.officeAddress &&
    a.officePoint?.join() === b.officePoint?.join() &&
    [...a.areas].sort().join('|') === [...b.areas].sort().join('|') &&
    [...a.workDays].sort().join() === [...b.workDays].sort().join() &&
    time(a.timeFrom) === time(b.timeFrom) &&
    time(a.timeTo) === time(b.timeTo)
  )
}

/** Текст ошибки backend: FastAPI кладёт его в detail. */
/** Что изменилось для плана — подпись тоста после сохранения. */
function savedNote(result: UpdateBrigadeResult, before: Draft, after: Draft) {
  const notes: string[] = []
  if (result.rescheduledEngineers > 0) {
    const count = result.rescheduledEngineers
    notes.push(
      `Рабочий день перенесён ${count} ${pluralRu(count, ['инженеру', 'инженерам', 'инженерам'])}`,
    )
  }
  const planning =
    result.officeMoved ||
    result.rescheduledEngineers > 0 ||
    before.workDays.join() !== after.workDays.join()
  if (planning) notes.push('План учтёт это при следующем пересчёте')
  return notes.length > 0 ? notes.join('. ') : undefined
}

function InfoHint({ children }: { children: ReactNode }) {
  return (
    <Tooltip delay={200}>
      <Tooltip.Trigger
        aria-label="Подробнее"
        className="inline-flex size-4 cursor-help items-center justify-center text-muted outline-none"
      >
        <RiInformationLine size={12} />
      </Tooltip.Trigger>
      <AppTooltipContent className="max-w-[280px] text-left break-normal">
        {children}
      </AppTooltipContent>
    </Tooltip>
  )
}

type BrigadeInfoProps = {
  brigade: PersonnelBrigade
  engineers: PersonnelEngineer[]
}

/**
 * Вкладка «Информация»: карта офиса и инженеров и карточка «Управление бригадой» —
 * офис (точка старта инженеров, её можно поставить на карте), рабочие дни и часы,
 * районы и участие в планировании. «Отменить» и «Сохранить» появляются после правки.
 */
export function BrigadeInfo({ brigade, engineers }: BrigadeInfoProps) {
  const { data: areas = [] } = useGetBrigadeAreasQuery(brigade.regionId)
  const [updateBrigade, { isLoading: saving }] = useUpdateBrigadeMutation()
  const [reverseGeocode] = useLazyReverseGeocodeQuery()
  const [picking, setPicking] = useState(false)
  // Точка, для которой ищем адрес: пока ищем, её можно сдвинуть — ответ для старой не нужен
  const [locatingAt, setLocatingAt] = useState<string | null>(null)
  const [pickNote, setPickNote] = useState<string | null>(null)
  // Карта ещё едет или только встала: точка под булавкой вот-вот сменится
  const [settling, setSettling] = useState(false)
  // Точка последнего поиска адреса: ответы для прежних точек не трогают ни поле, ни подсказку
  const lastLocate = useRef<string | null>(null)

  const areaName = new Map(areas.map((area) => [area.id, area.name]))
  const areaId = new Map(areas.map((area) => [area.name, area.id]))
  const saved = draftOf(brigade, areaName)

  // Правка живёт отдельно от сохранённого; пока её нет, форма показывает данные бригады
  const [edit, setEdit] = useState<Draft | null>(null)
  const draft = edit ?? saved
  // Функциональное обновление: адрес по точке приходит позже, другие правки не затираются
  const patch = (next: Partial<Draft>) => setEdit((prev) => ({ ...(prev ?? saved), ...next }))
  // Только что сохранённая правка: пока список бригад не перезагрузился, она и есть сохранённое
  const [justSaved, setJustSaved] = useState<Draft | null>(null)
  const dirty = edit != null && edit !== justSaved && !sameDraft(edit, saved)

  // «Повторить» со старого тоста не должен перезаписать более позднее сохранение
  // или сохранить бригаду, с которой уже ушли
  const attempt = useRef(0)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  // Карта остановилась под булавкой — ищем адрес этой точки
  const locateAt = async (point: [number, number]) => {
    const key = point.join()
    lastLocate.current = key
    setPickNote(null)
    patch({ officePoint: point, officeConfirmed: false })
    setLocatingAt(key)
    const current = () => alive.current && lastLocate.current === key
    try {
      const { address, hasHouse } = await reverseGeocode({ lat: point[1], lon: point[0] }).unwrap()
      if (!current()) return
      setEdit((prev) =>
        prev?.officePoint?.join() === key && address
          ? { ...prev, officeAddress: address, officeConfirmed: hasHouse }
          : prev,
      )
      if (!hasHouse) setPickNote('Здесь не нашёлся дом — поставьте булавку на здание')
    } catch (error) {
      if (current()) setPickNote(errorReason(error))
    } finally {
      if (alive.current) setLocatingAt((at) => (at === key ? null : at))
    }
  }

  /** Сбросить выбор на карте: ждущие ответы больше ничего не пишут. */
  const stopLocating = () => {
    lastLocate.current = null
    setLocatingAt(null)
    setPickNote(null)
  }

  const moved = draft.officePoint?.join() !== brigade.officePoint?.join()

  const locating = locatingAt != null && draft.officePoint?.join() === locatingAt
  const officeHint =
    pickNote ??
    (locating
      ? 'Ищем адрес точки…'
      : picking
        ? 'Двигайте карту: офис — под булавкой'
        : !draft.officeConfirmed
          ? 'Выберите адрес с номером дома из списка'
          : moved
            ? 'Офис переедет сюда после сохранения'
            : 'Точка старта инженеров')

  const timeError =
    draft.timeFrom != null &&
    draft.timeTo != null &&
    formatTime(draft.timeTo) <= formatTime(draft.timeFrom)
  const isValid =
    draft.officeAddress.trim() !== '' &&
    draft.officeConfirmed &&
    !locating &&
    !settling &&
    draft.workDays.length > 0 &&
    draft.timeFrom != null &&
    draft.timeTo != null &&
    !timeError

  const save = async (snapshot: Draft) => {
    if (snapshot.timeFrom == null || snapshot.timeTo == null) return
    const id = ++attempt.current
    try {
      const result = await updateBrigade({
        id: brigade.id,
        body: {
          office_address: snapshot.officeAddress.trim(),
          ...(snapshot.officePoint
            ? {
                office_lon: snapshot.officePoint[0],
                office_lat: snapshot.officePoint[1],
              }
            : {}),
          area_ids: snapshot.areas.flatMap((name) => areaId.get(name) ?? []),
          work_days: [...snapshot.workDays].sort(),
          start_work: formatTime(snapshot.timeFrom),
          end_work: formatTime(snapshot.timeTo),
        },
      }).unwrap()
      // Правку, сделанную во время сохранения, не трогаем; сохранённую держим, пока список
      // бригад не перезагрузится, — иначе на миг мелькнут старые значения
      const stored = { ...snapshot, officeAddress: snapshot.officeAddress.trim() }
      setEdit((prev) => (prev === snapshot ? stored : prev))
      setJustSaved(stored)
      setPicking(false)
      stopLocating()
      toast.success('Сведения по бригаде обновлены', {
        description: savedNote(result, saved, snapshot),
      })
    } catch (error) {
      toast.danger('Сведения по бригаде не обновлены', {
        description: errorReason(error),
        actionProps: {
          children: 'Повторить',
          variant: 'outline',
          size: 'sm',
          onPress: () => {
            if (alive.current && attempt.current === id) void save(snapshot)
          },
        },
      })
    }
  }

  return (
    <>
      <BrigadeMap
        brigade={brigade}
        engineers={engineers}
        officePoint={draft.officePoint}
        officeLabel={draft.officeAddress}
        picking={picking}
        onSettling={setSettling}
        onCenter={(point) => void locateAt(point)}
        onDone={() => setPicking(false)}
      />
      <AppPanel className="flex min-h-0 w-[346px] shrink-0 flex-col">
        <div className="flex shrink-0 flex-col gap-1 px-5 pt-5">
          <h2 className="text-xl font-semibold leading-7 text-foreground">Управление бригадой</h2>
          <p className="text-sm leading-6 text-muted">Адрес офиса и рабочий день инженеров</p>
        </div>

        <ScrollShadow hideScrollBar size={40} className="min-h-0 flex-1" orientation="vertical">
          <div className="flex flex-col gap-4 px-5 py-4">
            <div className="flex flex-col gap-1">
              <FieldLabel required>Адрес офиса</FieldLabel>
              <AddressField
                value={draft.officeAddress}
                confirmed={draft.officeConfirmed}
                busy={locating}
                placeholder="Улица и дом"
                onType={(officeAddress) => {
                  // Напечатанный адрес — только поиск: офис на прежнем месте, пока не выбран
                  stopLocating()
                  setPicking(false)
                  patch({
                    officeAddress,
                    officePoint: brigade.officePoint,
                    officeConfirmed: false,
                  })
                }}
                onPickOnMap={() => {
                  setPickNote(null)
                  setPicking(true)
                }}
                onSelect={(item) => {
                  stopLocating()
                  setPicking(false)
                  patch({
                    officeAddress: item.address,
                    officePoint: [item.lon, item.lat],
                    officeConfirmed: true,
                  })
                }}
              />
              <div className="flex items-start justify-between gap-2">
                <Hint>{officeHint}</Hint>
                <button
                  type="button"
                  aria-pressed={picking}
                  onClick={() => {
                    setPickNote(null)
                    setPicking((value) => !value)
                  }}
                  className="inline-flex shrink-0 cursor-pointer items-center gap-1 text-xs font-medium leading-5 text-link hover:underline"
                >
                  <RiMapPinLine size={12} className="shrink-0" />
                  {picking ? 'Готово' : 'Указать на карте'}
                </button>
              </div>
            </div>

            <MultiSelectField
              label="Районы"
              placeholder="Выберите районы"
              options={areas.map((area) => area.name)}
              value={draft.areas}
              onChange={(next) => patch({ areas: next })}
              maxVisible={5}
              labelAddon={
                <InfoHint>
                  Районы региона, которые обслуживает бригада. Пока справочно: план распределяет
                  заявки всего региона
                </InfoHint>
              }
            />

            <div className="h-px w-full bg-border" />

            <div className="flex flex-col gap-2">
              <FieldLabel required>Рабочий график</FieldLabel>
              <div className="flex gap-1">
                {WEEKDAYS.map(({ day, label }) => (
                  <ToggleChip
                    key={day}
                    active={draft.workDays.includes(day)}
                    onToggle={() =>
                      patch({
                        workDays: draft.workDays.includes(day)
                          ? draft.workDays.filter((item) => item !== day)
                          : [...draft.workDays, day].sort(),
                      })
                    }
                    className="!h-8 min-w-0 flex-1 justify-center !px-0"
                  >
                    {label}
                  </ToggleChip>
                ))}
              </div>
              {draft.workDays.length === 0 ? <Hint>Выберите хотя бы один день</Hint> : null}
            </div>

            <div className="flex flex-col gap-1">
              <FieldLabel required>Рабочий день</FieldLabel>
              <div className="flex items-center">
                <WorkTimeField
                  aria-label="Начало рабочего дня"
                  value={draft.timeFrom}
                  onChange={(timeFrom) => patch({ timeFrom })}
                />
                <span
                  className="shrink-0 text-sm leading-5 text-muted"
                  style={{ width: 12, textAlign: 'center' }}
                >
                  -
                </span>
                <WorkTimeField
                  aria-label="Конец рабочего дня"
                  value={draft.timeTo}
                  onChange={(timeTo) => patch({ timeTo })}
                />
              </div>
              {timeError ? (
                <p className="text-xs leading-5 text-danger">Конец дня должен быть позже начала</p>
              ) : draft.timeFrom == null || draft.timeTo == null ? (
                <p className="text-xs leading-5 text-danger">Укажите начало и конец рабочего дня</p>
              ) : null}
            </div>

          </div>
        </ScrollShadow>

        {dirty ? (
          <div className="flex shrink-0 gap-2 px-5 pt-2 pb-5">
            <button
              type="button"
              disabled={saving}
              onClick={() => {
                setEdit(null)
                setPicking(false)
                stopLocating()
              }}
              className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center border border-border bg-surface text-sm font-medium leading-5 text-foreground transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40"
              style={{ borderRadius: 8, padding: '8px 16px' }}
            >
              Отменить
            </button>
            <button
              type="button"
              disabled={!isValid || saving}
              onClick={() => void save(draft)}
              className="inline-flex h-9 flex-1 cursor-pointer items-center justify-center bg-accent text-sm font-medium leading-5 text-accent-foreground transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-accent"
              style={{ borderRadius: 8, padding: '8px 16px' }}
            >
              {saving ? 'Сохраняем…' : 'Сохранить'}
            </button>
          </div>
        ) : null}
      </AppPanel>
    </>
  )
}
