# Контракт алгоритма планирования (`planner`)

Единый источник правды для реализации и для тестов. Всё, что описано здесь, обязано
выполняться; всё, чего здесь нет, — деталь реализации и тестами не фиксируется.

Задача: **TRSP** = VRPTW + skills + resources (open routes, фиксированный парк, разрешён отказ
от части заявок). Источники требований: ТЗ «Билайн Бизнес» (п. 2.2–2.4), база знаний
`lct-beeline-task-2026/docs` (Правила модели, Назначение на работу, Маршрут инженера,
Нормативы работ), концепция `алгоритм.pdf`.

---

## 0. Технические рамки

* Python ≥ 3.10, **только стандартная библиотека** (dataclasses, datetime, math, json, csv).
* Тесты — `pytest`, лежат в `solution/tests/`, импортируют пакет как `from planner import ...`.
* Все времена — timezone-aware `datetime` (Europe/Moscow, `timezone(timedelta(hours=3))`).
  Расчёты ведутся в минутах (float), расстояния — в километрах (float).
* **Детерминизм обязателен**: при одинаковом входе содержательная часть результата
  побайтово одинакова. Исключены из сравнения ровно два поля: `metrics.computation_ms`
  (замер времени) и `plan_id` (счётчик выданных планов). Все сравнения имеют явный
  tie-break по `id`. Никакого необъявленного `random`, никакого порядка, зависящего
  от хеширования.
* Входные модели живут в `planner.models`, выходные — в `planner.result`; и те и другие
  реэкспортируются из `planner`, импортировать следует оттуда.

---

## 1. Перечисления (`planner.enums`)

```python
class Skill(StrEnum):          LOCAL = "local"; CONNECTION = "connection"; EMERGENCY = "emergency"
class TransportMode(StrEnum):  CAR = "car"; WALKING = "walking"; BICYCLE = "bicycle"; PUBLIC_TRANSPORT = "public_transport"
class Priority(StrEnum):       NORMAL = "normal"; URGENT = "urgent"
class AssignmentStatus(StrEnum): ASSIGNED = "assigned"; UNASSIGNED = "unassigned"
class Algorithm(StrEnum):      BASELINE = "baseline"; OPTIMIZED = "optimized"
class EventType(StrEnum):      URGENT_REQUEST = "urgent_request"; CANCEL_REQUEST = "cancel_request"
                               ENGINEER_UNAVAILABLE = "engineer_unavailable"; CLIENT_REFUSAL = "client_refusal"
```

### 1.1. Коды причин неназначения — `ReasonCode`

Упорядочены по «глубине пройденной проверки». У каждого кода есть `rank` (целое).
Итоговая причина заявки = **код с максимальным rank среди всех инженеров**: если хоть кто-то
дошёл до проверки времени, значит навык и транспорт где-то есть, и честная причина — время.

| код | rank | смысл |
|---|---|---|
| `no_engineers` | 0 | во входе вообще нет инженеров |
| `no_region` | 1 | нет инженера региона заявки |
| `no_skill` | 2 | ни у кого из инженеров региона нет требуемого навыка |
| `no_transport` | 3 | нет инженера с требуемым типом транспорта |
| `no_equipment` | 4 | ни у кого нет требуемого снаряжения (только при `check_equipment=True`) |
| `no_work_time` | 5 | у подходящих инженеров нет рабочих интервалов на дату |
| `time_conflict` | 6 | подходящие инженеры есть, но заявка не влезает в окно/смену |
| `not_found` | 7 | исчерпан лимит поиска; глобальная невозможность не доказана |

`ReasonCode.rank` доступен как свойство. `no_engineers` выдаётся **только** когда
`scenario.engineers` пуст. Инженер с `active=False` или без рабочих интервалов даёт
`no_work_time`: статические проверки идут по всему входному составу, а не только по тем,
у кого есть маршрут.

---

## 2. Входные данные (`planner.models`)

Все входные модели — `@dataclass(frozen=True)` (кроме `Settings`), с `from_dict`/`to_dict`.

### 2.1. `GeoPoint`
```python
lat: float   # [-90, 90]
lon: float   # [-180, 180]
```
Валидация в `__post_init__` → `ValueError` при выходе за диапазон.

### 2.2. `WorkInterval`
```python
start: datetime
end: datetime      # строго > start
```

### 2.3. `Engineer`
```python
id: str
name: str
start_point: GeoPoint            # офис бригады
work_intervals: tuple[WorkInterval, ...]   # отсортированы, не пересекаются; пусто = выходной
skills: frozenset[Skill]         # 1..N навыков
skill_levels: tuple[tuple[Skill, str], ...] = ()   # уровень по каждому навыку;
                                 # хранится и показывается, НА ОТБОР НЕ ВЛИЯЕТ
                                 # (шкала — открытый вопрос БЗ); `level_of(skill)`
transport_mode: TransportMode
region_key: str = "default"
equipment: frozenset[str] = frozenset()
active: bool = True              # False -> инженер исключён из расчёта
input_order: int = 0             # порядок во входе; определяет baseline и tie-break
```

### 2.4. `Request`
```python
id: str
point: GeoPoint
window_start: datetime           # начало окна ПРИБЫТИЯ
window_end: datetime             # конец окна ПРИБЫТИЯ, >= window_start
duration_minutes: int            # > 0, только работы+документы, БЕЗ дороги
required_skill: Skill
region_key: str = "default"
priority: Priority = Priority.NORMAL
required_transport: TransportMode | None = None    # None = ограничения нет
required_equipment: frozenset[str] = frozenset()
address: str = ""
district: str = ""
input_order: int = 0
```

### 2.5. `Settings` (мутабельный dataclass, все поля со значениями по умолчанию)
```python
# travel model
speed_kmh: dict[TransportMode, float] = {car: 28, walking: 4.5, bicycle: 13, public_transport: 18}
overhead_minutes: dict[TransportMode, float] = {car: 8, walking: 3, bicycle: 4, public_transport: 10}
detour_factor: dict[TransportMode, float] = {car: 1.35, walking: 1.25, bicycle: 1.30, public_transport: 1.40}

# hard constraints
check_region: bool = True
check_equipment: bool = False           # «Could have» по ТЗ
service_must_start_within_window: bool = True

# search
regret_k: int = 3
time_limit_seconds: float = 5.0
enable_local_search: bool = True
enable_fleet_minimization: bool = True
max_local_search_rounds: int = 30
or_opt_max_segment: int = 3
ejection_depth: int = 1                 # сколько обычных заявок срочная вправе вытеснить

# replan
stabilize_after_replan: bool = True

timezone_offset_hours: int = 3
```

### 2.6. `Scenario` — единый вход алгоритма
```python
@dataclass(frozen=True)
class Scenario:
    date: date
    requests: tuple[Request, ...]
    engineers: tuple[Engineer, ...]
    settings: Settings = field(default_factory=Settings)
    name: str = ""
```
`Scenario.validate()` → `list[str]` предупреждений (дубли id, окно с `end < start`,
`duration <= 0`, заявка вне даты и т.п.). Дубли `id` — `ValueError`, остальное — предупреждения.

### 2.7. `ReplanEvent`
```python
type: EventType
at: datetime                       # время события = граница «прошлого»
request: Request | None = None     # для URGENT_REQUEST
request_id: str | None = None      # для CANCEL_REQUEST / CLIENT_REFUSAL
engineer_id: str | None = None     # для ENGINEER_UNAVAILABLE
comment: str = ""
```

---

## 3. Модель времени

### 3.1. Рабочий календарь (`planner.calendar.WorkCalendar`)

Построен из `work_intervals` инженера. И **работа, и перемещение** потребляют только рабочее
время; в разрывах (перерывах) время не течёт.

| метод | смысл |
|---|---|
| `capacity_minutes` | сумма длительностей интервалов |
| `first_moment_at_or_after(t)` | ближайший рабочий момент ≥ `t`; `None`, если смена кончилась |
| `add(t, minutes)` | момент после расходования `minutes` рабочих минут начиная с `t`; `None`, если не хватает смены |
| `sub(t, minutes)` | обратная операция: момент, из которого через `minutes` рабочих минут попадём в `t`; `None`, если до начала смены |
| `working_between(a, b)` | рабочие минуты в `[a, b]`, `0.0` при `b <= a` |
| `contains(t)` | `t` внутри какого-либо интервала (границы включительно) |

Конструктор: `WorkCalendar(intervals: tuple[WorkInterval, ...], origin: datetime)`.
`origin` — полночь даты плана в поясе данных, одна на весь расчёт.

**Границы интервалов включительные во всех методах.** Момент окончания утреннего интервала
является рабочим моментом: `contains(13:00)`, `first_moment_at_or_after(13:00)` и
`add(13:00, 0)` дают `13:00`. Работать из него дальше нельзя, пока не начнётся следующий
интервал, и это обеспечивает само расходование времени: `add(13:00, 30) == 14:30` при
перерыве 13:00–14:00. `add(t, 0) == sub(t, 0) == first_moment_at_or_after(t)`, и `sub` —
точная обратная операция к `add`.

Пустой календарь: `capacity_minutes == 0`, все методы возвращают `None`/`0.0`.

### 3.2. Модель перемещения (`planner.travel.TravelModel`)

```
haversine_km(a, b)                       # сфера, R = 6371.0088 км
distance_km  = haversine_km * detour_factor[mode]
travel_minutes = distance_km / speed_kmh[mode] * 60 + overhead_minutes[mode]
```
`TravelModel` — это `Protocol`, а не класс. Реализации: `HaversineTravelModel(settings)`
(расчёт по координатам) и `MatrixTravelModel(distance, minutes, fallback)` (готовая матрица,
например ответ OSRM `/table`; неизвестная пара делегируется в `fallback`).

* `distance_km(a, b, mode)` и `travel_minutes(a, b, mode)` — симметричны, результаты кэшируются.
* Если `a == b` (точно те же координаты): `distance_km == 0.0`, `travel_minutes == 0.0`
  (накладные расходы не начисляются — инженер уже на месте).
* Допущение фиксируется в README: прямая линия × коэффициент извилистости, без пробок и
  графа дорог. Интерфейс `TravelModel` позволяет подменить реализацию (OSRM) без правок алгоритма.

### 3.3. Расписание визита

Для визита к заявке `r` из точки `prev` с моментом освобождения `t0`:
```
departure_at   = calendar.first_moment_at_or_after(t0)
arrival_at     = calendar.add(departure_at, travel_minutes(prev, r))
service_start  = calendar.first_moment_at_or_after(max(arrival_at, r.window_start))
service_end    = calendar.add(service_start, r.duration_minutes)
waiting        = calendar.working_between(arrival_at, service_start)
latest_departure_at = calendar.sub(service_start, travel_minutes(prev, r))   # справочно
```
**Ограничения (все обязательны):**
1. `arrival_at is not None` и `arrival_at <= r.window_end` — иначе нарушено окно прибытия;
2. при `service_must_start_within_window`: `service_start <= r.window_end`;
3. `service_end is not None` — работа целиком укладывается в рабочее время;
4. окончание работы входит в рабочее время (следует из п. 3).

Прибытие **раньше** `window_start` допустимо и означает ожидание. Прибытие **позже**
`window_end` — не попадание в окно. Окна не сдвигаются никогда.

---

## 4. Жёсткие ограничения и проверки (`planner.feasibility`)

### 4.1. Статическая проверка `check_static(engineer, request, settings) -> FeasibilityResult`
Порядок строго такой (он же задаёт rank причины):
1. `engineer.active` и календарь непуст → иначе `no_work_time`;
2. регион (`check_region`) → `no_region`;
3. навык: `request.required_skill in engineer.skills` → `no_skill`;
4. транспорт: `required_transport is None or == engineer.transport_mode` → `no_transport`;
5. снаряжение (`check_equipment`): `required_equipment <= engineer.equipment` → `no_equipment`.

Порядок 2→3→4→5 зафиксирован: сначала территория, потом квалификация, потом ресурс.

### 4.2. `FeasibilityResult`
```python
ok: bool
reason: ReasonCode | None
detail: str = ""          # человекочитаемое уточнение на русском
```
Единственная функция проверки используется и в конструктивной фазе, и в локальном поиске,
и при перепланировании — дублирования логики нет.

### 4.3. Проверка вставки
`RouteState.evaluate_insertion(request, position)` проверяет п. 3.3 для самой заявки **и**
для всех последующих визитов маршрута (time propagation). Возвращает либо стоимость вставки,
либо `FeasibilityResult` с `time_conflict`.

---

## 5. Стоимость и критерии оптимизации

### 5.1. Лексикографический вектор стоимости вставки — `planner.cost.InsertionCost`
```python
opens_new_engineer: int      # 0 / 1
delta_travel_minutes: float
delta_distance_km: float
delta_waiting_minutes: float
```
Сравнение **лексикографическое** по этому порядку. Никаких магических весов вида
`FIXED_ENGINEER_COST = 100000` — порядок критериев выражен явно структурой, а не подбором
констант. `regret = second_best - best` — покомпонентная разность, сравнивается тоже
лексикографически.

Порядок соответствует базе знаний: число исполнителей важнее, время в пути важнее пробега.

### 5.2. Качество плана — `PlanMetrics.quality_key()`
Лексикографический ключ для сравнения планов (меньше = лучше):
```
(urgent_unassigned_count, unassigned_count, used_engineer_count,
 round(total_travel_minutes, 6), round(total_distance_km, 6))
```
Первый приоритет — выполнить срочные, затем максимум заявок, затем минимум людей,
затем время в пути, затем пробег.

---

## 6. Алгоритмы

### 6.1. Базовый (`Algorithm.BASELINE`) — обязателен по ТЗ п. 2.3
Заявки в порядке `input_order`. Для каждой — инженеры в порядке `input_order`; первый,
кто проходит статическую проверку **и** у кого заявка допустима **в конец** его маршрута,
получает её. Порядок посещения = порядок назначения. Никакой оптимизации.

### 6.2. Оптимизированный (`Algorithm.OPTIMIZED`)
1. **Конструктивная фаза — regret-k insertion.**
   На каждой итерации для каждой неназначенной заявки считаются лучшие позиции вставки
   во все допустимые маршруты; берётся `regret` между лучшей и k-й по стоимости.
   Выбирается заявка с ключом `(priority_rank, regret, -window_width, -input_order)`
   по убыванию (срочные всегда раньше обычных; при равенстве — та, у кого меньше запасных
   вариантов, затем с более узким окном, затем более ранняя во входе).
   Заявка с ровно одним допустимым вариантом получает бесконечный regret.
   Заявка без допустимых вариантов уходит в неназначенные с причиной по п. 4.1/4.3.
2. **Локальный поиск** (если `enable_local_search`), до сходимости или `time_limit_seconds`:
   `or-opt` (сегменты 1..`or_opt_max_segment` внутри маршрута), `2-opt` (внутри маршрута),
   `relocate` (сегмент между маршрутами), `exchange` (обмен заявками между маршрутами),
   после каждого раунда — повторная попытка вставить неназначенные.
   Ход принимается, только если он **не ухудшает** `quality_key()` и не нарушает ограничения.
3. **Минимизация числа исполнителей** (если `enable_fleet_minimization`):
   маршруты перебираются от самых «лёгких»; маршрут распускается, его заявки пробуются
   к остальным инженерам без открытия новых. Если размещены **все** — маршрут удаляется
   и цикл повторяется. Иначе изменение откатывается. Число назначенных заявок при этом
   не имеет права уменьшиться.
4. Финальный пересчёт расписаний и метрик.

**Гарантии, проверяемые тестами:**
* `optimized.quality_key() <= baseline.quality_key()` на любом валидном сценарии;
* ни один результат (baseline или optimized) не нарушает жёстких ограничений;
* время работы на 15 инженерах / 100 заявках — секунды, не минуты.

### 6.3. Перепланирование (`planner.replan`)

`apply_event(scenario, previous, event) -> tuple[Scenario, list[str]]` — публичная функция,
которую `replan()` применяет внутри. Она возвращает **действующий** сценарий после события
и примечания к нему. Это важно для проверки: после события состав заявок меняется (срочная
добавилась, отменённая исчезла, у заявки с отказом клиента длительность работы обнулилась),
и результат `replan()` описывает именно этот сценарий. Поэтому
`validate_plan(result, scenario)` вызывается с результатом `apply_event`, а не с исходным
сценарием; отдельного верификатора у ремонта нет.

Отменённая заявка **исчезает** из `assignments`: в действующем сценарии её нет. Инвариант
§ 9 п. 1 проверяется относительно сценария из `apply_event`.

Инкрементальный ремонт, а не пересчёт с нуля. Общий каркас:
1. **Заморозка.** Назначение считается `locked`, если `service_start_at < event.at`.
   Для каждого инженера точка и время старта сдвигаются на конец последнего locked-визита.
2. Событие применяется к снимку входа.
3. Ремонт:
   * `CANCEL_REQUEST` — заявка удаляется из маршрута, расписание **только этого** маршрута
     пересчитывается (остальные не трогаются);
   * `CLIENT_REFUSAL` — визит остаётся в маршруте как состоявшийся (поездка сохраняется),
     но работа не засчитывается; хвост маршрута пересчитывается;
   * `URGENT_REQUEST` — поиск лучшей допустимой позиции во всех маршрутах; если прямой
     вставки нет — вытеснение до `ejection_depth` обычных заявок с их переразмещением;
     если и это не помогло — неназначена с причиной;
   * `ENGINEER_UNAVAILABLE` — незамороженные заявки инженера становятся «осиротевшими»
     и проходят regret-insertion **только по оставшимся** инженерам; остальные маршруты
     не пересобираются.
4. При `stabilize_after_replan` — ограниченный локальный поиск по затронутым маршрутам.
5. Строится `PlanDiff`.

**Гарантии:** locked-назначения не меняются никогда; окна не сдвигаются; заявки автоматически
не отменяются; маршруты, которых событие не касается, остаются идентичными (побайтово).

---

## 7. Выход (`planner.models` / `planner.result`)

### 7.1. `Visit`
```python
request_id, position (1-based), engineer_id
departure_at, arrival_at, service_start_at, service_end_at: datetime
latest_departure_at: datetime | None
service_minutes: float             # чистая длительность работ (разность времён
                                   # включала бы перерыв, если работа его пересекла)
slack_minutes: float               # запас до срыва: на сколько можно задержать начало,
                                   # не сломав ни окно визита, ни хвост маршрута
travel_minutes, distance_km, waiting_minutes: float
from_point, to_point: GeoPoint
locked: bool = False
```

### 7.2. `RouteResult`
```python
engineer_id, engineer_name, transport_mode, start_point
visits: tuple[Visit, ...]
start_at, end_at: datetime | None
distance_km, travel_minutes, service_minutes, waiting_minutes: float
capacity_minutes: int
explanation: str                      # краткое описание маршрута для диспетчера
busy_minutes      = service + travel + waiting
free_minutes      = capacity - busy
utilization       = busy / capacity   (0.0 при capacity == 0)
polyline: tuple[GeoPoint, ...]        # старт + точки визитов, для карты
```

### 7.3. `Assignment`
```python
request_id, status, engineer_id | None, position | None
arrival_at, service_start_at, service_end_at: datetime | None
reason: ReasonCode | None          # обязателен при UNASSIGNED
explanation: str                   # обязателен при UNASSIGNED, всегда заполнен при ASSIGNED
checked_qualification_level: str | None   # уровень исполнителя по требуемому навыку
checked_skill, checked_transport, checked_equipment   # снимок требований заявки:
                                                     # заполняются всегда, в том числе
                                                     # при check_equipment=False
incremental_distance_km: float | None
```

### 7.4. `PlanMetrics`
```python
assigned_count, feasible_count, tight_visit_count,
unassigned_count, urgent_unassigned_count, used_engineer_count,
available_engineer_count, total_distance_km, total_travel_minutes, total_service_minutes,
total_waiting_minutes, avg_utilization, computation_ms, constraints_valid: bool
per_engineer: tuple[EngineerMetrics, ...]
```

### 7.5. `PlanResult`
```python
plan_id: str
algorithm: Algorithm
date: date
routes: tuple[RouteResult, ...]          # только задействованные, отсортированы по engineer.input_order
assignments: tuple[Assignment, ...]      # по всем заявкам входа, отсортированы по request.input_order
unassigned: tuple[Assignment, ...]       # срез assignments со status == UNASSIGNED
metrics: PlanMetrics
warnings: tuple[str, ...]
diff: PlanDiff | None = None
to_dict() -> dict                        # полностью JSON-сериализуемо (json.dumps без default=)
```

### 7.6. `PlanDiff` (заполняется только при перепланировании)
```python
previous_plan_id: str
event_type: EventType
changed_request_ids, changed_route_engineer_ids, removed_route_engineer_ids,
newly_assigned_request_ids, newly_unassigned_request_ids: tuple[str, ...]
unchanged_route_engineer_ids: tuple[str, ...]
summary: str                              # человекочитаемо, на русском
```

---

## 8. Публичный API (`planner/__init__.py`)

```python
def plan(scenario: Scenario, algorithm: Algorithm = Algorithm.OPTIMIZED) -> PlanResult: ...
def replan(previous: PlanResult, scenario: Scenario, event: ReplanEvent) -> PlanResult: ...
def compare(baseline: PlanResult, optimized: PlanResult) -> dict: ...
def validate_plan(result: PlanResult, scenario: Scenario) -> list[str]: ...
```

```python
def apply_event(scenario: Scenario, previous: PlanResult, event: ReplanEvent) -> tuple[Scenario, list[str]]: ...
def reassign(previous: PlanResult, scenario: Scenario, request_id: str,
             engineer_id: str | None, position: int | None = None) -> PlanResult: ...
def solve(ctx: PlanContext, algorithm: Algorithm = Algorithm.OPTIMIZED, *, deadline: float | None = None) -> Solution: ...
```

`reassign` — ручное вмешательство диспетчера. `engineer_id=None` снимает заявку с
исполнителя; `position` нумеруется с 1, `None` означает «лучшее место». Жёсткие
ограничения ручное решение **не обходит**: недопустимый ход отклоняется, план
возвращается **неизменным**, причина попадает в `warnings` и в `diff.summary`.

`validate_plan` — независимый верификатор: пересчитывает расписание каждого маршрута с нуля и
возвращает список нарушений. Пустой список = план корректен. Он намеренно **не** использует
внутренние структуры планировщика, чтобы тесты могли проверять результат независимо.
Проверяет: навык, регион, транспорт, снаряжение, окна прибытия, границы смены,
непересечение работ, соответствие заявленных времён пересчитанным, уникальность назначений,
покрытие всех заявок входа ровно одним `Assignment`.

---

## 9. Инварианты (обязаны выполняться всегда)

1. Каждая заявка входа имеет ровно один `Assignment`.
2. Заявка назначена не более чем одному инженеру.
3. У назначенной заявки: `arrival_at <= window_end`, `service_start_at >= window_start`,
   `service_start_at >= arrival_at`, `service_end_at` внутри рабочего времени.
4. Внутри маршрута работы не пересекаются: `service_end_at[i] <= departure_at[i+1]`.
5. `position` в маршруте — непрерывная нумерация с 1.
6. У неназначенной заявки заполнены `reason` и непустой `explanation`.
7. `used_engineer_count` == число маршрутов с ≥ 1 визитом; маршрут без визитов не создаётся.
8. Сумма `RouteResult.distance_km` == `metrics.total_distance_km` (с точностью 1e-6).
9. Маршрут стартует в `engineer.start_point`; возврат в стартовую точку не планируется.
10. `plan()` не мутирует переданный `Scenario` и его объекты.

---

## 10. Загрузка данных (`planner.io_csv`, вспомогательное)

Читает предоставленные выгрузки (`;`-разделитель, cp1251/utf-8-sig, заголовок в 1-й строке,
служебная строка «Адрес Офиса» — не заявка). Сопоставление `Тип заявки BK` + `Тип заявки HD`
→ навык и длительность задаётся таблицей `data/work_types.json` (данные, не код).
Нормативы: 70 / 80 / 20 / 30 минут (технические работы + документы, **без** дорожных 20 минут).
Координаты берутся из кэша `data/geocache.json`; при отсутствии — детерминированная
подстановка по району с явным предупреждением в `PlanResult.warnings`.
