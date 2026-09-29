import { Button, Popover } from '@heroui/react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate } from 'react-router'

import { routes } from '@/shared/config/routes'

const STORAGE_KEY = 'beeline-general-onboarding:v2'
const START_EVENT = 'beeline:start-general-onboarding'

type Step = {
  title: string
  description: string
  target?: string
  placement?: 'bottom' | 'right' | 'left'
}

type AnchorRect = {
  top: number
  left: number
  width: number
  height: number
}

const steps: Step[] = [
  {
    title: 'Как устроен рабочий день',
    description:
      'Покажем, как выбрать регион и дату, загрузить заявки, проверить результат расчёта и перейти к плану работ.',
  },
  {
    title: 'Разделы планировщика',
    description:
      '«Обзор дня» показывает готовность и итоги расчёта. В «Плане работ» можно менять назначения на Ганте и смотреть маршруты на карте, в «Сравнении планов» — сопоставлять версии, а в «Персонале» — управлять инженерами и бригадами.',
    target: 'main-navigation',
    placement: 'right',
  },
  {
    title: 'Контекст планирования',
    description:
      'Сначала выберите регион и дату. К ним привязаны заявки, доступные инженеры и все версии плана — при переключении меняется весь рабочий контекст.',
    target: 'planning-context',
    placement: 'bottom',
  },
  {
    title: 'Статус и показатели плана',
    description:
      'Здесь видно, загружены ли заявки и рассчитан ли план. После расчёта появятся назначенные и неназначенные заявки, занятые инженеры, среднее время в пути, загрузка и пробег.',
    target: 'overview-summary',
    placement: 'bottom',
  },
  {
    title: 'Заявки выбранного дня',
    description:
      'Загрузите CSV или JSON, если список пуст. После загрузки здесь можно искать заявки по адресу или номеру и фильтровать их по назначению, типу работ, причине и времени.',
    target: 'overview-tickets',
    placement: 'right',
  },
  {
    title: 'Инженеры и график',
    description:
      'До загрузки заявок здесь показаны доступные инженеры региона. После расчёта блок сменится на мини-Гант с назначениями, дорогой и обедами выбранной версии плана.',
    target: 'overview-secondary',
    placement: 'left',
  },
  {
    title: 'Импорт и экспорт заявок',
    description:
      'Основная кнопка открывает загрузку CSV или JSON. В меню по стрелке можно выгрузить заявки выбранного дня в CSV или JSON.',
    target: 'tickets-actions',
    placement: 'bottom',
  },
  {
    title: 'Начните с данных',
    description:
      'Выберите регион и дату, затем загрузите заявки — расчёт плана запустится автоматически. К этому туру всегда можно вернуться через «Помощь».',
  },
]

export function startGeneralOnboarding() {
  localStorage.removeItem(STORAGE_KEY)
  window.dispatchEvent(new Event(START_EVENT))
}

export function resetGeneralOnboarding() {
  localStorage.removeItem(STORAGE_KEY)
}

export function GeneralOnboarding() {
  const navigate = useNavigate()
  const location = useLocation()
  const [stepIndex, setStepIndex] = useState<number | null>(() =>
    localStorage.getItem(STORAGE_KEY) ? null : 0,
  )
  const [anchor, setAnchor] = useState<AnchorRect | null>(null)
  const targetRef = useRef<Element | null>(null)

  const step = stepIndex === null ? null : steps[stepIndex]

  useEffect(() => {
    const start = () => {
      if (location.pathname !== routes.overview) {
        navigate({ pathname: routes.overview, search: location.search })
      }
      setStepIndex(0)
    }

    window.addEventListener(START_EVENT, start)
    return () => window.removeEventListener(START_EVENT, start)
  }, [location.pathname, location.search, navigate])

  useEffect(() => {
    if (stepIndex !== null && location.pathname !== routes.overview) {
      navigate({ pathname: routes.overview, search: location.search }, { replace: true })
    }
  }, [location.pathname, location.search, navigate, stepIndex])

  useLayoutEffect(() => {
    if (!step?.target) {
      targetRef.current = null
      setAnchor(null)
      return
    }

    const element = document.querySelector<HTMLElement>(
      `[data-onboarding="${step.target}"]`,
    )

    if (!element) {
      targetRef.current = null
      setAnchor(null)
      return
    }

    targetRef.current = element

    element.scrollIntoView({ block: 'nearest', inline: 'nearest' })

    const update = () => {
      const rect = element.getBoundingClientRect()
      setAnchor({
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
      })
    }

    update()
    const observer = new ResizeObserver(update)
    observer.observe(element)
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)

    return () => {
      observer.disconnect()
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
    }
  }, [step])

  useEffect(() => {
    if (stepIndex === null) return

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') finish()
      if (event.key === 'ArrowRight') next()
      if (event.key === 'ArrowLeft') previous()
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  })

  const finish = () => {
    localStorage.setItem(STORAGE_KEY, 'completed')
    setStepIndex(null)
  }

  const next = () => {
    if (stepIndex === null) return
    if (stepIndex === steps.length - 1) finish()
    else setStepIndex(stepIndex + 1)
  }

  const previous = () => {
    if (stepIndex === null || stepIndex === 0) return
    setStepIndex(stepIndex - 1)
  }

  if (!step || stepIndex === null) return null

  return createPortal(
    <>
      {anchor ? (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed z-[80] rounded-xl ring-2 ring-accent"
          style={{
            top: anchor.top - 4,
            left: anchor.left - 4,
            width: anchor.width + 8,
            height: anchor.height + 8,
            boxShadow: '0 0 0 9999px rgb(15 23 42 / 0.38)',
          }}
        />
      ) : (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed inset-0 z-[80] bg-backdrop/40"
        />
      )}

      <Popover isOpen>
        <Popover.Trigger
          aria-hidden="true"
          className="pointer-events-none fixed z-[81]"
          style={{ top: '50%', left: '50%', width: 1, height: 1 }}
        />
        <Popover.Content
          className={`z-[90] w-80 p-0${anchor ? '' : ' onboarding-popover--centered'}`}
          offset={12}
          placement={step.placement ?? 'bottom'}
          triggerRef={anchor ? targetRef : undefined}
        >
          {anchor ? <Popover.Arrow /> : null}
          <Popover.Dialog className="flex flex-col gap-3 p-4">
            <div className="flex items-center justify-between gap-3 text-xs text-foreground-500">
              <span>Общий тур</span>
              <span>
                {stepIndex + 1} из {steps.length}
              </span>
            </div>

            <div className="h-1 overflow-hidden rounded-full bg-default-100">
              <div
                className="h-full rounded-full bg-accent transition-[width]"
                style={{ width: `${((stepIndex + 1) / steps.length) * 100}%` }}
              />
            </div>

            <div className="space-y-1">
              <Popover.Heading className="text-base font-semibold text-foreground">
                {step.title}
              </Popover.Heading>
              <p className="text-sm leading-5 text-foreground-600">{step.description}</p>
            </div>

            <div className="flex items-center justify-between gap-2 pt-1">
              <Button size="sm" variant="ghost" onPress={finish}>
                Пропустить
              </Button>
              <div className="flex gap-2">
                {stepIndex > 0 && (
                  <Button size="sm" variant="secondary" onPress={previous}>
                    Назад
                  </Button>
                )}
                <Button size="sm" onPress={next}>
                  {stepIndex === steps.length - 1 ? 'Готово' : 'Далее'}
                </Button>
              </div>
            </div>
          </Popover.Dialog>
        </Popover.Content>
      </Popover>
    </>,
    document.body,
  )
}
