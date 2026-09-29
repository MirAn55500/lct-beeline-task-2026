import { useEffect, useLayoutEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '@heroui/react'

const STORAGE_KEY = 'beeline-general-onboarding:v1'

type TourStep = {
  id: string
  title: string
  description: string
  target?: string
}

const STEPS: TourStep[] = [
  {
    id: 'welcome',
    title: 'Добро пожаловать в Билайн Маршруты',
    description:
      'За пару минут покажем, где смотреть состояние дня, управлять планом и работать с заявками.',
  },
  {
    id: 'sections',
    title: 'Основные разделы',
    description:
      'В «Обзоре дня» собраны показатели, в «Плане работ» — Гант и карта, в «Сравнении» — версии расчёта, а в «Персонале» — бригады и инженеры.',
    target: '[data-onboarding="main-navigation"]',
  },
  {
    id: 'context',
    title: 'Регион и рабочий день',
    description:
      'Выбранные регион и дата задают контекст для заявок, инженеров и всех версий плана.',
    target: '[data-onboarding="planning-context"]',
  },
  {
    id: 'tickets',
    title: 'Работа с заявками',
    description:
      'Кнопка открывает загрузку CSV или JSON. В дополнительном меню рядом доступны экспорт и другие действия с заявками.',
    target: '[data-onboarding="tickets-actions"]',
  },
  {
    id: 'finish',
    title: 'Основы готовы',
    description:
      'Дальше каждый рабочий экран можно изучать отдельно. Общий тур всегда можно запустить заново через раздел «Помощь».',
  },
]

type AnchorRect = {
  top: number
  right: number
  bottom: number
  left: number
  width: number
  height: number
}

export function resetGeneralOnboarding() {
  window.localStorage.removeItem(STORAGE_KEY)
}

function readInitialStep() {
  return window.localStorage.getItem(STORAGE_KEY) ? -1 : 0
}

function cardPosition(rect: AnchorRect | null) {
  const width = Math.min(360, window.innerWidth - 32)
  if (!rect) {
    return {
      width,
      left: Math.max(16, (window.innerWidth - width) / 2),
      top: Math.max(16, (window.innerHeight - 280) / 2),
    }
  }

  const left = Math.min(
    Math.max(16, rect.left),
    Math.max(16, window.innerWidth - width - 16),
  )
  const below = rect.bottom + 16
  const top = below + 260 <= window.innerHeight
    ? below
    : Math.max(16, rect.top - 276)

  return { width, left, top }
}

export function GeneralOnboarding() {
  const [stepIndex, setStepIndex] = useState(readInitialStep)
  const [anchor, setAnchor] = useState<AnchorRect | null>(null)
  const step = stepIndex >= 0 ? STEPS[stepIndex] : null

  useLayoutEffect(() => {
    if (!step?.target) {
      setAnchor(null)
      return
    }

    const target = document.querySelector<HTMLElement>(step.target)
    if (!target) {
      setAnchor(null)
      return
    }

    target.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    const update = () => {
      const rect = target.getBoundingClientRect()
      setAnchor({
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        left: rect.left,
        width: rect.width,
        height: rect.height,
      })
    }

    update()
    const observer = new ResizeObserver(update)
    observer.observe(target)
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
    }
  }, [step])

  useEffect(() => {
    if (!step) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        window.localStorage.setItem(STORAGE_KEY, 'skipped')
        setStepIndex(-1)
      }
      if (event.key === 'ArrowRight') {
        setStepIndex((current) => Math.min(current + 1, STEPS.length - 1))
      }
      if (event.key === 'ArrowLeft') {
        setStepIndex((current) => Math.max(current - 1, 0))
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [step])

  const position = useMemo(() => cardPosition(anchor), [anchor])
  if (!step) return null

  const close = (status: 'completed' | 'skipped') => {
    window.localStorage.setItem(STORAGE_KEY, status)
    setStepIndex(-1)
  }

  return createPortal(
    <div className="fixed inset-0 z-[80]" aria-live="polite">
      {anchor ? (
        <div
          className="pointer-events-none fixed rounded-2xl border-2 border-focus"
          style={{
            top: anchor.top - 6,
            left: anchor.left - 6,
            width: anchor.width + 12,
            height: anchor.height + 12,
            boxShadow: '0 0 0 9999px rgb(15 23 42 / 0.62)',
          }}
        />
      ) : (
        <div className="fixed inset-0 bg-backdrop/60" />
      )}

      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby={`onboarding-${step.id}-title`}
        className="fixed flex flex-col gap-4 rounded-[var(--border-radius-panel)] bg-surface p-5 text-foreground shadow-overlay"
        style={position}
      >
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-4 text-xs leading-4 text-muted">
            <span>Знакомство с интерфейсом</span>
            <span>{stepIndex + 1} из {STEPS.length}</span>
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-surface-tertiary">
            <div
              className="h-full rounded-full bg-accent transition-[width]"
              style={{ width: `${((stepIndex + 1) / STEPS.length) * 100}%` }}
            />
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <h2 id={`onboarding-${step.id}-title`} className="text-xl leading-7 font-semibold">
            {step.title}
          </h2>
          <p className="text-sm leading-6 text-muted">{step.description}</p>
        </div>

        <div className="flex items-center justify-between gap-3">
          <Button variant="ghost" onPress={() => close('skipped')}>
            Пропустить
          </Button>
          <div className="flex items-center gap-2">
            {stepIndex > 0 ? (
              <Button variant="secondary" onPress={() => setStepIndex(stepIndex - 1)}>
                Назад
              </Button>
            ) : null}
            <Button
              onPress={() => {
                if (stepIndex === STEPS.length - 1) close('completed')
                else setStepIndex(stepIndex + 1)
              }}
            >
              {stepIndex === STEPS.length - 1 ? 'Готово' : 'Далее'}
            </Button>
          </div>
        </div>
      </section>
    </div>,
    document.body,
  )
}
