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
class Priority(StrEnum):       EMERGENCY = "emergency"; CONNECTION = "connection"; REPAIR = "repair_or_addon"
                               # rank: emergency=2, connection=1, repair_or_addon=0
                               # дозаказ: навык connection, приоритет repair_or_addon
class ExecutionStatus(StrEnum): UNKNOWN = "unknown"; PENDING = "pending"; EN_ROUTE = "en_route"
                               IN_PROGRESS = "in_progress"; COMPLETED = "completed"; CANCELLED = "cancelled"
                               # closed = completed | cancelled — в новый план не входят
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
| `manual` | 8 | заявка снята с исполнителя вручную диспетчером |

`manual` имеет наивысший ранг намеренно: пересчёт причин по правилу «максимальный ранг»
не имеет права затереть решение человека машинной догадкой вроде «нет навыка».

`ReasonCode.rank` доступен как свойство. `no_engineers` выдаётся **только** когда
`scenario.engineers` пуст. `time_conflict` отличает две разные причины в тексте детали:
«не помещается даже в пустой день» (окно плюс норматив не влезают в смену независимо
от загрузки) и «занят / не успевает доехать». Инженер с `active=False` или без рабочих интервалов даёт
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
home_start: bool = False         # True -> start_point это условный домашний адрес
                                 # удалённого города, а не офис; комплект к старту
                                 # считается уже выданным
```

### 2.4. `Request`
```python
id: str
point: GeoPoint
window_start: datetime           # начало окна ПРИБЫТИЯ
window_end: datetime             # конец окна ПРИБЫТИЯ, >= window_start
duration_minutes: int            # > 0; работы+документы БЕЗ дороги:
                                 # подключение 70, авария 80, дозаказ 20, локальная 30
required_skill: Skill
region_key: str = "default"
priority: Priority = Priority.CONNECTION
required_transport: TransportMode | None = None    # None = ограничения нет
required_equipment: frozenset[str] = frozenset()
address: str = ""
district: str = ""
input_order: int = 0
received_at: datetime | None = None   # поступление; работа не раньше этого момента
execution_status: ExecutionStatus = PENDING
request_type_bk: str = ""             # категория BK; навык и приоритет берутся из неё
```
`is_emergency`, `is_closed`, `service_not_before = max(window_start, received_at or window_start)`.

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
ejection_depth: int = 1                 # сколько менее приоритетных заявок авария вправе вытеснить
                                        # ПОДРЯД из одного маршрута (и в основном расчёте,
                                        # и при перепланировании); 0 запрещает вытеснение

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
    as_of: datetime | None = None    # граница снимка: заявки с received_at > as_of
                                     # в этот расчёт не входят; None = все незакрытые
```
`Scenario.planning_requests()` — незакрытые заявки, поступившие не позже `as_of`.
`plan()`, `validate_plan` и инвариант § 9 п. 1 работают по этому срезу, а не по
полному `requests`.
`Scenario.validate()` → `list[str]` предупреждений (дубли id, окно с `end < start`,
`duration <= 0`, заявка вне даты, закрытые во входе, поступление позже `as_of`,
**заявка, не помещающаяся в смену ни одного инженера**). Дубли `id` — `ValueError`, остальное — предупреждения.

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
`TravelModel` — это `Protocol`, а не класс. Реализации:

| Реализация | Источник чисел | Симметрия |
|---|---|---|
| `HaversineTravelModel(settings)` | формула выше, режим по умолчанию | да |
| `MatrixTravelModel(distance, minutes, fallback)` | готовая матрица, задана снаружи | да |
| `planner.ors.OrsTravelModel` | матрицы openrouteservice (`/v2/matrix`) | **нет** |

* `distance_km(a, b, mode)` и `travel_minutes(a, b, mode)`, результаты кэшируются.
* Если `a == b` (точно те же координаты): `distance_km == 0.0`, `travel_minutes == 0.0`
  (накладные расходы не начисляются — инженер уже на месте). Выполняется для всех реализаций.
* Симметрия — свойство расчёта по координатам, а **не** требование протокола: реальная
  сеть улиц односторонняя, и `OrsTravelModel` даёт разные значения для A→B и B→A.
  Алгоритм на симметрию не опирается ни в одной фазе.
* `overhead_minutes[mode]` (парковка, подход, подъём) прибавляется в любой реализации:
  это требование базы знаний, а не часть дорожного графа.
* Допущение расчёта по координатам фиксируется в README: прямая линия × коэффициент
  извилистости, без пробок и графа дорог. Снимается подстановкой `OrsTravelModel`
  без единой правки в алгоритме.

### 3.3. Расписание визита

Для визита к заявке `r` из точки `prev` с моментом освобождения `t0` (`travel = travel_minutes(prev, r)`):
```
# 1. самый ранний возможный ход — он и решает допустимость визита
earliest_departure = calendar.first_moment_at_or_after(t0)
earliest_arrival   = calendar.add(earliest_departure, travel)
service_start      = calendar.first_moment_at_or_after(max(earliest_arrival, r.service_not_before))
service_end        = calendar.add(service_start, r.duration_minutes)

# 2. выезд откладывается: целимся приехать к началу работ, но не позже окна прибытия
aim            = min(service_start, r.window_end)
departure_at   = max(earliest_departure, calendar.sub(aim, travel))
arrival_at     = calendar.add(departure_at, travel)      # откат отменяется, если срывает окно

waiting        = calendar.working_between(arrival_at, service_start)
idle_before    = calendar.working_between(earliest_departure, departure_at)
latest_departure_at = calendar.sub(service_start, travel)   # справочно
```

**Отложенный выезд обязателен.** Расчёт «освободился — сразу поехал» отправляет инженера
к клиенту за два часа до открытия окна, и тот стоит у подъезда. Это неверно и по жизни,
и по отчётности: ожидание входит в `busy_minutes`, маршрут из четырёх заявок показывает
97 % загрузки, `free_minutes` близко к нулю, и диспетчер не видит, что у человека свободны
часы. При отложенном выезде свободное время остаётся простоем **до** выезда
(`Visit.idle_before_minutes`) и не выдаёт себя за занятость.

Откат выезда не меняет ни допустимость визита, ни `service_start`/`service_end`: их задаёт
самый ранний возможный ход (п. 1). Откат ограничен с двух сторон — нельзя выехать раньше,
чем инженер освободился, и нельзя прибыть позже `window_end`. Поэтому при выключенном
`service_must_start_within_window` остаточное ожидание у клиента сохраняется: приехать
обязаны в окно, а работа может начаться позже.
**Ограничения (все обязательны):**
1. `arrival_at is not None` и `arrival_at <= r.window_end` — иначе нарушено окно прибытия;
2. при `service_must_start_within_window`: `service_start <= r.window_end`;
3. `service_end is not None` — работа целиком укладывается в рабочее время;
4. окончание работы входит в рабочее время (следует из п. 3);
5. `service_start >= r.received_at`, если поступление задано — авария не выполняется до поступления.

Прибытие **раньше** `window_start` допустимо и означает ожидание, но алгоритм его
избегает, откладывая выезд. Прибытие **позже** `window_end` — не попадание в окно. Алгоритм окна сам не сдвигает: расчёт использует
актуальное окно из сценария; сохранённый старый план своё окно не меняет. Корректировку
времени визита вносит поддержка во вход следующего расчёта.

---

## 4. Жёсткие ограничения и проверки (`planner.feasibility`)

### 4.1. Статическая проверка `check_static(engineer, request, settings) -> FeasibilityResult`
Порядок строго такой (он же задаёт rank причины):
1. `engineer.active` → иначе `no_work_time` (исключённый из расчёта заслоняет всё остальное);
2. регион (`check_region`) → `no_region`;
3. навык: `request.required_skill in engineer.skills` → `no_skill`;
4. транспорт: `required_transport is None or == engineer.transport_mode` → `no_transport`;
5. снаряжение (`check_equipment`): `required_equipment <= engineer.equipment` → `no_equipment`;
6. непустой календарь → иначе `no_work_time`.

Порядок 2→3→4→5 зафиксирован: сначала территория, потом квалификация, потом ресурс.
Пустой график проверяется **последним**, а не первым: его ранг (5) выше ранга `no_skill` (2),
и при выборе причины по максимальному рангу один выходной сотрудник иначе заслонял бы
честное «ни у кого нет навыка» по всем остальным.

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
(emergency_unassigned_count, connection_unassigned_count, unassigned_count,
 used_engineer_count, round(total_travel_minutes, 6), round(total_distance_km, 6))
```
Порядок приоритетов БЗ: авария → подключение → ремонт / дозаказ. Первые два ключа —
неназначенные аварии и подключения; третий — общий объём (ремонт и дозаказ входят в него).
Затем минимум людей, время в пути, пробег.

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
   по убыванию (авария раньше подключения, подключение раньше ремонта/дозаказа;
   при равенстве — та, у кого меньше запасных вариантов, затем с более узким окном,
   затем более ранняя во входе).
   Заявка с ровно одним допустимым вариантом получает бесконечный regret.
   Заявка без допустимых вариантов уходит в неназначенные с причиной по п. 4.1/4.3.
   Затем неназначенные **аварии** пробуются повторно: вставка сдвигает хвост маршрута;
   если окна остальных не держат — вытеснение до `ejection_depth` заявок меньшего
   приоритета подряд из одного маршрута: места освобождаются по одному, пока авария
   не поместится либо не исчерпается глубина. Принимается тот вариант, где **все**
   потеснённые заявки нашли новое место; иначе — честная потеря менее важной работы.
2. **Локальный поиск** (если `enable_local_search`), до сходимости или `time_limit_seconds`:
   `or-opt` (сегменты 1..`or_opt_max_segment` внутри маршрута), `2-opt` (внутри маршрута),
   `relocate` (сегмент между маршрутами), `exchange` (обмен заявками между маршрутами),
   после каждого раунда — повторная попытка вставить неназначенные; для аварий —
   снова со сдвигом и вытеснением менее приоритетных.
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
и примечания к нему. Это важно для проверки: после события состав заявок меняется (аварийная
добавилась, отменённая исчезла, у заявки с отказом клиента длительность работы обнулилась),
и результат `replan()` описывает именно этот сценарий. Поэтому
`validate_plan(result, scenario)` вызывается с результатом `apply_event`, а не с исходным
сценарием; отдельного верификатора у ремонта нет.

Отменённая заявка **исчезает** из `assignments`: в действующем сценарии её нет. Инвариант
§ 9 п. 1 проверяется относительно сценария из `apply_event`.

Инкрементальный ремонт, а не пересчёт с нуля. Общий каркас:
1. **Заморозка.** Назначение считается `locked`, если `service_start_at < event.at`.
   Расписание locked-визитов переносится из предыдущего плана **как есть** и не
   пересчитывается: начатая работа — факт, а не решение планировщика. Поэтому исчезновение
   более раннего визита не сдвигает замороженный хвост во времени. Для каждого инженера
   точка и время старта сдвигаются на конец последнего locked-визита.
2. Событие применяется к снимку входа. Граница снимка сдвигается: `as_of = max(as_of, event.at)`,
   иначе заявка, поступившая позже прежнего `as_of`, попала бы в маршрут, но выпала
   из `planning_requests()` — а значит из назначений и метрик.
3. Ремонт:
   * `CANCEL_REQUEST` — заявка удаляется из маршрута, расписание **только этого** маршрута
     пересчитывается (остальные не трогаются);
   * `CLIENT_REFUSAL` — визит остаётся в маршруте как состоявшийся (поездка сохраняется),
     но работа не засчитывается; хвост маршрута пересчитывается;
   * `URGENT_REQUEST` — поступление аварии: `priority=EMERGENCY`, `received_at=event.at`
     если не задан; поиск лучшей допустимой позиции во всех маршрутах; если прямой
     вставки нет — вытеснение до `ejection_depth` заявок **меньшего** приоритета
     подряд из одного маршрута с их переразмещением; если и это не помогло —
     неназначена с причиной;
   * `ENGINEER_UNAVAILABLE` — незамороженные заявки инженера становятся «осиротевшими»
     и проходят regret-insertion **только по оставшимся** инженерам; остальные маршруты
     не пересобираются.
4. При `stabilize_after_replan` — ограниченный локальный поиск по затронутым маршрутам.
5. Строится `PlanDiff`.

**Гарантии:** locked-назначения не меняются никогда — ни исполнителем, ни временем; алгоритм окна сам не сдвигает;
заявки автоматически не отменяются; маршруты, которых событие не касается, остаются
идентичными (побайтово). Закрытые не попадают в новый список планирования.

---

## 7. Выход (`planner.models` / `planner.result`)

### 7.1. `Visit`
```python
request_id, position (1-based), engineer_id
departure_at, arrival_at, service_start_at, service_end_at: datetime
latest_departure_at: datetime | None
service_minutes: float             # чистая длительность работ (разность времён
                                   # включала бы перерыв, если работа его пересекла)
idle_before_minutes: float         # свободные РАБОЧИЕ минуты перед выездом: инженер
                                   # закончил прошлую работу, но ехать ещё рано.
                                   # Это резерв дня, а не занятость
slack_minutes: float               # запас до срыва: на сколько РАБОЧИХ минут можно
                                   # задержать начало, не сломав ни окно визита,
                                   # ни один из последующих визитов маршрута.
                                   # Для последнего визита предел равен
                                   # min(window_end, sub(shift_end, duration));
                                   # перерывы в запас не засчитываются
travel_minutes, distance_km, waiting_minutes: float
from_point, to_point: GeoPoint
locked: bool = False
geometry_range: tuple[int, int] | None = None   # границы участка внутри
                                   # RouteResult.geometry: от предыдущей точки
                                   # маршрута сюда. Индексы, а не копия координат.
                                   # None — реальной геометрии нет
```

### 7.2. `RouteResult`
```python
engineer_id, engineer_name, transport_mode, start_point
visits: tuple[Visit, ...]
start_at, end_at: datetime | None
distance_km, travel_minutes, service_minutes, waiting_minutes: float
capacity_minutes: float               # ёмкость календаря; минуты могут быть дробными
explanation: str                      # краткое описание маршрута для диспетчера
busy_minutes      = service + travel + waiting
free_minutes      = capacity - busy
utilization       = busy / capacity   (0.0 при capacity == 0)
polyline: tuple[GeoPoint, ...]        # старт + точки визитов (прямые), для карты
geometry: tuple[GeoPoint, ...] = ()   # линия по улицам из маршрутного сервиса;
                                      # пустая, пока план считался по координатам
geometry_source: str = "straight"     # "ors" | "mixed" | "straight" — чтобы
                                      # интерфейс не выдавал прямую за реальный
                                      # маршрут. "mixed" — линия по улицам, но
                                      # отдельные участки внутри неё остались
                                      # прямыми: сервис их построить не смог
```

`geometry` заполняется постобработкой `planner.ors.attach_route_geometry`, а не
`plan()`: ядро остаётся офлайновым и в сеть не ходит.

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
unassigned_count, emergency_unassigned_count, connection_unassigned_count, used_engineer_count,
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
def validate_plan(result: PlanResult, scenario: Scenario, travel: TravelModel | None = None) -> list[str]: ...
```

`plan`, `replan` и `validate_plan` принимают `travel: TravelModel | None` (keyword-only
у первых двух). Проверка обязана получать **ту же** модель, которой считался план:
иначе она сравнивает расписание по улицам с расписанием по прямой и сообщает о
несуществующих нарушениях.

### 8.1. Реальная маршрутизация (`planner.ors`, опционально)

```python
def setup_routing(scenario, *, url=None, api_key=None, cache_path=DEFAULT_CACHE_PATH,
                  refresh=False, max_routes=25000, timeout=180.0) -> Routing: ...

class Routing:
    travel: TravelModel | None        # None = расчёт по координатам
    enabled: bool                     # True, только если матрица реально получена
    def attach(self, result: PlanResult) -> PlanResult: ...   # геометрия + warnings
    def save(self) -> Path | None                             # ответы сервиса в кэш
```

Контракт интеграции:

* **никаких исключений из-за сети.** Недоступный сервис, несобранный профиль, точка вне
  графа (`null` в ответе матрицы) — всё это откат на `HaversineTravelModel` для
  соответствующего перемещения и запись в `PlanResult.warnings`, а не отказ в расчёте;
* **режимы независимы.** Матрица собрана только для авто — пешие перемещения считаются
  по координатам, а не берут чужие числа;
* **матрица берётся не у каждого профиля.** `planner.ors.GEOMETRY_ONLY_PROFILES` —
  профили, чей ответ на `/v2/matrix` не отражает способ передвижения. Сейчас это
  `public-transport`: у эндпойнта нет параметра времени отправления, поэтому расписания в
  матрицу не попадают и ORS отдаёт по ней пешее время. Матрица по таким профилям не
  запрашивается и не читается из кэша, режим остаётся на расчёте по координатам, причина
  пишется в `warnings`. На `attach_route_geometry` правило не распространяется:
  `/v2/directions` расписания учитывает, и линия на карте строится настоящая;
* **кэш направленный и «сырой».** `RoutingCache` хранит километры и чистое дорожное
  время; `overhead_minutes` прибавляется при запросе, поэтому смена параметра не требует
  повторного похода в сервис;
* **геометрия кэшируется участками, тем же ключом «откуда→куда», что и матрица.** Запросов
  это добавляет (один `directions` на участок вместо одного на маршрут), а взамен даёт
  два свойства: непостроенный участок заменяется прямой внутри линии и стоит участка, а не
  всего маршрута (`geometry_source = "mixed"`), и кэш не обнуляется от перестановки
  визитов при перепланировании.

```python
def apply_event(scenario: Scenario, previous: PlanResult, event: ReplanEvent) -> tuple[Scenario, list[str]]: ...
def reassign(previous: PlanResult, scenario: Scenario, request_id: str,
             engineer_id: str | None, position: int | None = None) -> PlanResult: ...
def solve(ctx: PlanContext, algorithm: Algorithm = Algorithm.OPTIMIZED, *, deadline: float | None = None) -> Solution: ...
```

`reassign` — ручное вмешательство диспетчера. Уточнения контракта:

* `position` отсчитывается по маршруту **после** изъятия заявки из её текущего места.
  Для маршрута из трёх визитов `position=4` — отказ, а не «в конец». При переносе между
  инженерами разницы нет, при перестановке внутри одного маршрута — есть.
* состав заявок ручной ход не меняет, поэтому результат проверяется
  `validate_plan(result, scenario)` с **исходным** сценарием; `apply_event` здесь не нужен.
* заявка, снятая вручную, получает `reason = ReasonCode.MANUAL`.
* `locked`-визит ручным ходом не трогается: признак заморозки хранится в самом плане
  (`Visit.locked`) и переживает восстановление независимо от того, передан ли момент времени.

`reassign` — ручное вмешательство диспетчера. `engineer_id=None` снимает заявку с
исполнителя; `position` нумеруется с 1, `None` означает «лучшее место». Жёсткие
ограничения ручное решение **не обходит**: недопустимый ход отклоняется, план
возвращается **неизменным**, причина попадает в `warnings` и в `diff.summary`.

`validate_plan` — независимый верификатор: пересчитывает расписание каждого маршрута с нуля и
возвращает список нарушений. Пустой список = план корректен. Он намеренно **не** использует
внутренние структуры планировщика, чтобы тесты могли проверять результат независимо.
Проверяет: навык, регион, транспорт, снаряжение, окна прибытия, границы смены,
непересечение работ, соответствие заявленных времён пересчитанным, уникальность назначений,
покрытие всех планируемых заявок ровно одним `Assignment` **и наличие `Assignment`
у каждого визита в маршруте**.

Визиты с `locked=True` — зафиксированный факт предыдущего плана: их времена не
пересчитываются, проверяется только допуск исполнителя и непересечение работ.

---

## 9. Инварианты (обязаны выполняться всегда)

1. Каждая **планируемая** заявка (`Scenario.planning_requests()`) имеет ровно один `Assignment`.
   Закрытые и ещё не поступившие на момент `as_of` в назначения не входят.
2. Заявка назначена не более чем одному инженеру.
3. У назначенной заявки: `arrival_at <= window_end`, `service_start_at >= window_start`,
   `service_start_at >= arrival_at`, `service_start_at >= received_at` если задан,
   `service_end_at` внутри рабочего времени.
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
→ вид работ, длительность и снаряжение задаётся таблицей `data/work_types.json` (данные, не код).
Порядок разбора: точная пара `BK|HD` (явное исключение) → BK → HD → значение по умолчанию.
Вид работ, длительность, требуемый навык и приоритет берутся **только из BK**: норматив
привязан к виду работ, а вид работ — к категории BK. HD уточняет лишь снаряжение (он знает
про замену приставки или роутера) и применяется целиком только при неизвестном BK.
Нормативы обслуживания без дороги: подключение 70, авария 80, дозаказ 20, локальная 30.
Дорожные 20 минут из Excel не копируются — перемещение считается отдельно.
Приоритет заявки берётся только из BK: глобальная проблема →
`emergency`, подключение → `connection`, дозаказ и локальная заявка → `repair_or_addon`.
Закрытые статусы источника («Выполнена», «Отменена») в сценарий не попадают.
Координаты берутся из кэша `data/geocache.json`; при отсутствии — детерминированная
подстановка по району с явным предупреждением в `PlanResult.warnings`.
