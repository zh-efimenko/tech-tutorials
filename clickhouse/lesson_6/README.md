# Урок 6. Материализованные представления (Materialized Views)

## Что такое Materialized View

Материализованное представление (MV) — это триггер на INSERT. При каждой вставке в исходную таблицу ClickHouse автоматически выполняет запрос MV и записывает результат в целевую таблицу.

```
INSERT INTO source_table
        │
        ├──► данные записываются в source_table
        │
        └──► MV выполняет SELECT ... GROUP BY
                    │
                    └──► результат записывается в target_table
```

**Это НЕ кэш запроса.** MV обрабатывает только новые данные из текущего INSERT, а не пересчитывает всю таблицу.

## Зачем нужны MV

| Без MV | С MV |
|--------|------|
| Запрос агрегации по 1 млрд строк при каждом обращении к дашборду | Агрегаты предрассчитаны, запрос по 10 000 строкам |
| Время ответа: 5-30 секунд | Время ответа: 10-50 мс |
| Нагрузка на CPU при каждом запросе | CPU тратится при INSERT |

## Архитектура MV

MV состоит из трёх частей:

1. **Исходная таблица** — куда приходят сырые данные
2. **Целевая таблица** — куда записываются агрегаты (создаётся явно)
3. **Сам MV** — SELECT-запрос, трансформирующий данные

## Пример 1: Простой счётчик (SummingMergeTree)

### Задача: ежедневная статистика по страницам

```sql
-- 1. Целевая таблица
CREATE TABLE tutorial.page_stats_daily (
    event_date Date,
    page_url   String,
    views      UInt64,
    total_dur  UInt64,
    max_dur    UInt32
) ENGINE = SummingMergeTree()
ORDER BY (event_date, page_url);

-- 2. Материализованное представление
CREATE MATERIALIZED VIEW tutorial.page_stats_daily_mv
TO tutorial.page_stats_daily
AS
SELECT
    event_date,
    page_url,
    count()        AS views,
    sum(duration)  AS total_dur,
    max(duration)  AS max_dur
FROM tutorial.page_views
GROUP BY event_date, page_url;
```

### Что происходит при INSERT

```sql
-- Вставка в исходную таблицу
INSERT INTO tutorial.page_views VALUES
    ('2026-04-01', '2026-04-01 10:00:00', 5001, '/home', 15, 'US', 'desktop'),
    ('2026-04-01', '2026-04-01 10:01:00', 5002, '/home', 30, 'DE', 'mobile'),
    ('2026-04-01', '2026-04-01 10:02:00', 5003, '/products', 45, 'US', 'desktop');

-- Автоматически в page_stats_daily появляются агрегаты:
-- ('2026-04-01', '/home', 2, 45, 30)
-- ('2026-04-01', '/products', 1, 45, 45)
```

### Чтение из целевой таблицы

```sql
SELECT
    event_date,
    page_url,
    sum(views)     AS total_views,
    sum(total_dur) AS total_duration,
    max(max_dur)   AS max_duration
FROM tutorial.page_stats_daily
GROUP BY event_date, page_url
ORDER BY total_views DESC;
```

**Важно**: `sum(views)` при чтении — потому что данные из разных INSERT-батчей могут быть ещё не смержены.

## Пример 2: Уникальные пользователи (AggregatingMergeTree)

### Задача: ежедневное количество уникальных пользователей по странам

```sql
-- 1. Целевая таблица
CREATE TABLE tutorial.country_users_daily (
    event_date Date,
    country    LowCardinality(String),
    views      SimpleAggregateFunction(sum, UInt64),
    users      AggregateFunction(uniq, UInt64),
    p95_dur    AggregateFunction(quantile(0.95), UInt32)
) ENGINE = AggregatingMergeTree()
ORDER BY (event_date, country);

-- 2. MV
CREATE MATERIALIZED VIEW tutorial.country_users_daily_mv
TO tutorial.country_users_daily
AS
SELECT
    event_date,
    country,
    count()                     AS views,
    uniqState(user_id)          AS users,
    quantileState(0.95)(duration) AS p95_dur
FROM tutorial.page_views
GROUP BY event_date, country;
```

### Чтение

```sql
SELECT
    event_date,
    country,
    sum(views)                    AS total_views,
    uniqMerge(users)              AS unique_users,
    quantileMerge(0.95)(p95_dur)  AS p95_duration
FROM tutorial.country_users_daily
GROUP BY event_date, country
ORDER BY event_date, total_views DESC;
```

## Заполнение MV историческими данными

MV обрабатывает только **новые** INSERT-ы. Если в `page_views` уже есть данные, нужно заполнить целевую таблицу вручную:

```sql
-- Вставить исторические данные в целевую таблицу
INSERT INTO tutorial.page_stats_daily
SELECT
    event_date,
    page_url,
    count()        AS views,
    sum(duration)  AS total_dur,
    max(duration)  AS max_dur
FROM tutorial.page_views
GROUP BY event_date, page_url;
```

## MV-цепочки

MV можно выстраивать в цепочки: MV_A триггерится на таблицу A и пишет в таблицу B, MV_B триггерится на таблицу B и пишет в таблицу C.

```
raw_events → [MV1] → hourly_stats → [MV2] → daily_stats
```

```sql
-- Часовая агрегация
CREATE TABLE tutorial.page_stats_hourly (
    event_date Date,
    event_hour UInt8,
    page_url   String,
    views      UInt64
) ENGINE = SummingMergeTree()
ORDER BY (event_date, event_hour, page_url);

CREATE MATERIALIZED VIEW tutorial.page_stats_hourly_mv
TO tutorial.page_stats_hourly
AS
SELECT
    event_date,
    toHour(event_time) AS event_hour,
    page_url,
    count()            AS views
FROM tutorial.page_views
GROUP BY event_date, event_hour, page_url;
```

## Управление MV

```sql
-- Список всех MV
SELECT name, engine, create_table_query
FROM system.tables
WHERE engine = 'MaterializedView' AND database = 'tutorial';

-- Удаление MV (целевая таблица остаётся!)
DROP VIEW tutorial.page_stats_daily_mv;

-- Удаление целевой таблицы
DROP TABLE tutorial.page_stats_daily;

-- Пересоздание: удалить MV → очистить целевую → создать MV → заполнить историю
```

## Типичные ошибки

### 1. Чтение без агрегации

```sql
-- НЕПРАВИЛЬНО: данные из разных батчей ещё не смержены
SELECT * FROM tutorial.page_stats_daily;

-- ПРАВИЛЬНО: всегда агрегируй при чтении из SummingMergeTree
SELECT event_date, page_url, sum(views) AS views
FROM tutorial.page_stats_daily
GROUP BY event_date, page_url;
```

### 2. Забыть про `*State`/`*Merge`

```sql
-- НЕПРАВИЛЬНО: uniq в AggregatingMergeTree
uniq(user_id) AS users

-- ПРАВИЛЬНО: uniqState при записи
uniqState(user_id) AS users
-- uniqMerge при чтении
uniqMerge(users) AS unique_users
```

### 3. Ожидание пересчёта при UPDATE исходных данных

MV не пересчитывает данные ретроактивно. Если исходные данные изменились — нужно пересоздать целевую таблицу и заполнить заново.

## Практика

```sql
-- 1. Создать page_stats_daily + MV (пример 1)
-- 2. Заполнить историческими данными
-- 3. Вставить новые данные в page_views — убедиться, что MV работает
-- 4. Создать country_users_daily + MV (пример 2)
-- 5. Сравнить скорость запроса по page_views vs по целевой таблице MV
```

## Итоги урока

- MV — триггер на INSERT, не кэш запроса
- Состоит из: исходная таблица → MV (SELECT) → целевая таблица
- `SummingMergeTree` — для простых sum/max/min
- `AggregatingMergeTree` + `*State`/`*Merge` — для uniq, quantile, avg
- Исторические данные нужно загружать в целевую таблицу отдельно
- Всегда агрегируй при чтении из целевой таблицы
