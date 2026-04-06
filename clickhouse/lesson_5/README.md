# Урок 5. Движки таблиц (MergeTree Family)

## Зачем разные движки

В уроке 2 мы создали таблицу с `MergeTree()`. Но ClickHouse предлагает семейство движков, каждый из которых решает свою задачу при слиянии (merge) Parts.

| Движок | Поведение при merge | Типичное применение |
|--------|--------------------|--------------------|
| `MergeTree` | Просто сливает | Основной, для сырых данных |
| `ReplacingMergeTree` | Оставляет последнюю версию строки | Дедупликация, CDC |
| `SummingMergeTree` | Суммирует числовые колонки | Предагрегированные счётчики |
| `AggregatingMergeTree` | Объединяет агрегатные состояния | Материализованные агрегаты |
| `CollapsingMergeTree` | Схлопывает пары (+1/-1) | Изменяемые данные |

## ReplacingMergeTree

Решает проблему дублей. При merge оставляет **последнюю версию** строки по ORDER BY ключу.

### Сценарий: таблица пользователей

Пользователь может обновить профиль. В OLTP-БД — `UPDATE`. В ClickHouse — INSERT новой версии.

```sql
CREATE TABLE tutorial.users (
    user_id    UInt64,
    name       String,
    email      String,
    country    LowCardinality(String),
    updated_at DateTime
) ENGINE = ReplacingMergeTree(updated_at)  -- версия определяется по updated_at
ORDER BY user_id;                          -- дедупликация по user_id
```

### Вставка и "обновление"

```sql
-- Первая версия
INSERT INTO tutorial.users VALUES
    (1, 'Alice', 'alice@example.com', 'US', '2026-01-01 10:00:00'),
    (2, 'Bob', 'bob@example.com', 'DE', '2026-01-01 10:00:00');

-- "Обновление" — просто новый INSERT
INSERT INTO tutorial.users VALUES
    (1, 'Alice Smith', 'alice.smith@example.com', 'US', '2026-03-01 12:00:00');
```

### Важный нюанс: дедупликация не мгновенная

```sql
-- Сразу после INSERT — дубли видны!
SELECT * FROM tutorial.users WHERE user_id = 1;
-- Результат: 2 строки (старая и новая)

-- Способ 1: FINAL — дедупликация на лету (медленнее)
SELECT * FROM tutorial.users FINAL WHERE user_id = 1;
-- Результат: 1 строка (новая)

-- Способ 2: принудительный merge
OPTIMIZE TABLE tutorial.users FINAL;
SELECT * FROM tutorial.users WHERE user_id = 1;
-- Результат: 1 строка
```

**Правило**: для запросов, где нужна актуальная версия, используй `FINAL`. Для аналитических дашбордов (где 0.01% дублей не критичен) — можно без `FINAL`.

## SummingMergeTree

При merge **суммирует** значения числовых колонок для строк с одинаковым ORDER BY ключом.

### Сценарий: ежедневные счётчики

```sql
CREATE TABLE tutorial.daily_hits (
    event_date Date,
    page_url   String,
    hits       UInt64,
    users      UInt64,
    duration   UInt64
) ENGINE = SummingMergeTree()
ORDER BY (event_date, page_url);
```

### Инкрементальная вставка

```sql
-- Утренние данные
INSERT INTO tutorial.daily_hits VALUES
    ('2026-03-01', '/home', 1000, 500, 30000),
    ('2026-03-01', '/products', 800, 400, 50000);

-- Дневные данные (тот же ключ — будут просуммированы при merge)
INSERT INTO tutorial.daily_hits VALUES
    ('2026-03-01', '/home', 1500, 700, 45000),
    ('2026-03-01', '/products', 600, 300, 35000);

-- После merge или с FINAL:
SELECT * FROM tutorial.daily_hits FINAL;
-- /home: hits=2500, users=1200, duration=75000
-- /products: hits=1400, users=700, duration=85000
```

**Внимание**: `users` тоже суммируется — а это неправильно! 500 + 700 ≠ 1200 уникальных пользователей. Для уникальных пользователей нужен `AggregatingMergeTree`.

## AggregatingMergeTree

Хранит **агрегатные состояния** (не финальные значения), которые объединяются при merge.

### Сценарий: точный подсчёт уникальных пользователей

```sql
CREATE TABLE tutorial.daily_metrics (
    event_date Date,
    page_url   String,
    hits       SimpleAggregateFunction(sum, UInt64),
    users      AggregateFunction(uniq, UInt64),
    max_dur    SimpleAggregateFunction(max, UInt32)
) ENGINE = AggregatingMergeTree()
ORDER BY (event_date, page_url);
```

### Два типа агрегатных колонок

| Тип | Описание | Для каких функций |
|-----|----------|-------------------|
| `SimpleAggregateFunction(func, Type)` | Хранит обычное значение, применяет функцию при merge | `sum`, `min`, `max`, `any` |
| `AggregateFunction(func, Type)` | Хранит промежуточное состояние агрегатной функции | `uniq`, `quantile`, `avg`, любые |

### Вставка — через `*State` функции

```sql
INSERT INTO tutorial.daily_metrics
SELECT
    event_date,
    page_url,
    count()              AS hits,
    uniqState(user_id)   AS users,       -- сохраняет HyperLogLog-скетч
    max(duration)        AS max_dur
FROM tutorial.page_views
GROUP BY event_date, page_url;
```

### Чтение — через `*Merge` функции

```sql
SELECT
    event_date,
    page_url,
    sum(hits)            AS total_hits,
    uniqMerge(users)     AS unique_users,  -- объединяет скетчи
    max(max_dur)         AS max_duration
FROM tutorial.daily_metrics
GROUP BY event_date, page_url
ORDER BY event_date, total_hits DESC;
```

## CollapsingMergeTree

Для обработки изменяемых данных через пары "вставка/отмена". Каждая строка имеет `sign`: `1` (вставка) или `-1` (отмена).

```sql
CREATE TABLE tutorial.sessions (
    user_id    UInt64,
    session_id String,
    duration   UInt32,
    page_count UInt16,
    sign       Int8
) ENGINE = CollapsingMergeTree(sign)
ORDER BY (user_id, session_id);
```

### Обновление через "схлопывание"

```sql
-- Начальные данные
INSERT INTO tutorial.sessions VALUES (1, 'abc', 30, 3, 1);

-- "Обновление": отмена старой строки + вставка новой
INSERT INTO tutorial.sessions VALUES
    (1, 'abc', 30, 3, -1),    -- отмена
    (1, 'abc', 120, 7, 1);    -- новое значение

-- Чтение
SELECT
    user_id,
    session_id,
    sum(duration * sign)   AS duration,
    sum(page_count * sign) AS page_count
FROM tutorial.sessions
GROUP BY user_id, session_id
HAVING sum(sign) > 0;
```

## argMax / argMin — альтернатива ReplacingMergeTree

`argMax(value, comparator)` — агрегатная функция, которая возвращает `value` из строки с максимальным `comparator`. Позволяет получить "последнюю версию" без ReplacingMergeTree и без FINAL.

### Синтаксис

```sql
argMax(value, comparator)  -- value из строки где comparator максимален
argMin(value, comparator)  -- value из строки где comparator минимален
```

### Простой пример

```sql
-- Таблица с дублями (обычный MergeTree, не Replacing)
CREATE TABLE tutorial.bets (
    line_id    UInt64,
    coupon_id  UInt64,
    bet_id     UInt64,
    status     LowCardinality(String),
    amount     Decimal(18, 2),
    odds       Decimal(10, 3),
    updated_at DateTime
) ENGINE = MergeTree()
ORDER BY (line_id, coupon_id, bet_id);

-- Вставки: два обновления одной ставки
INSERT INTO tutorial.bets VALUES (1, 100, 500, 'pending', 50.00, 1.85, '2026-04-01 10:00:00');
INSERT INTO tutorial.bets VALUES (1, 100, 500, 'won',     50.00, 1.85, '2026-04-01 12:00:00');
```

### Получение последней версии

```sql
SELECT
    line_id,
    coupon_id,
    bet_id,
    argMax(status, updated_at)   AS last_status,
    argMax(amount, updated_at)   AS last_amount,
    argMax(odds, updated_at)     AS last_odds
FROM tutorial.bets
GROUP BY line_id, coupon_id, bet_id;
-- Результат: status = 'won' (updated_at больше)
```

- `GROUP BY` — определяет уникальность (составной ключ из 3 колонок)
- `argMax(колонка, updated_at)` — из каждой группы берёт значение с максимальным `updated_at`

### Составной comparator через Tuple

Если "последняя версия" определяется несколькими полями:

```sql
-- Сначала по updated_at, при равенстве — по version
argMax(status, tuple(updated_at, version))
```

### argMax vs ReplacingMergeTree

| Аспект | ReplacingMergeTree + FINAL | MergeTree + argMax |
|--------|---------------------------|-------------------|
| Дедупликация | физическая (при merge) | логическая (при SELECT) |
| Совместимость с MV | плохая (MV видит дубли) | хорошая (argMax работает в MV) |
| Хранение | дубли удаляются с диска | все версии хранятся |
| Скорость чтения | быстрее (меньше данных) | медленнее (читает все версии) |
| Простота | проще запросы | нужен argMax в каждом запросе |

**Когда argMax лучше**: когда данные используются в MV или когда нужна история версий.

**Когда ReplacingMergeTree лучше**: когда данных много и важна экономия диска.

## Другие полезные движки (не MergeTree)

| Движок | Назначение |
|--------|-----------|
| `Log` / `TinyLog` | Маленькие таблицы, быстрая запись, нет индексов |
| `Memory` | Данные только в RAM, теряются при рестарте |
| `Buffer` | Буфер перед MergeTree для частых мелких вставок |
| `Distributed` | Распределённые запросы по кластеру |
| `MaterializedView` | Автоматическая трансформация при INSERT |
| `Dictionary` | Подключение внешних словарей |
| `Null` | /dev/null — данные отбрасываются (для тестов) |

## Как выбрать движок

```
Сырые события, логи
  → MergeTree

Нужна дедупликация / "UPDATE"
  → ReplacingMergeTree

Простые накопительные счётчики (sum, max, min)
  → SummingMergeTree

Сложные агрегаты (uniq, quantile, avg)
  → AggregatingMergeTree

Нужно "удалять/обновлять" строки
  → CollapsingMergeTree
```

## Практика

```sql
-- 1. Создать таблицу users с ReplacingMergeTree
-- 2. Вставить данные, затем "обновить" пользователя
-- 3. Сравнить SELECT и SELECT ... FINAL
-- 4. Создать daily_hits с SummingMergeTree
-- 5. Вставить данные двумя батчами, проверить суммирование с FINAL
-- 6. Создать daily_metrics с AggregatingMergeTree
-- 7. Заполнить из page_views, прочитать через *Merge функции
```

## Итоги урока

- `MergeTree` — основной движок для сырых данных
- `ReplacingMergeTree` — дедупликация по ORDER BY, используй FINAL для актуальных данных
- `SummingMergeTree` — автоматическое суммирование при merge (только для простых сумм)
- `AggregatingMergeTree` — хранит промежуточные агрегатные состояния (`*State`/`*Merge`)
- Дедупликация/суммирование происходят при merge, не при INSERT
- `FINAL` — принудительная дедупликация на лету
