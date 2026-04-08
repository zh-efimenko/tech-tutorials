# Урок 4. SELECT и агрегации

## Базовый SELECT

```sql
-- Все колонки (в аналитике обычно плохая практика)
SELECT * FROM tutorial.page_views LIMIT 10;

-- Только нужные колонки (в колоночной БД это критически важно!)
SELECT user_id, page_url, duration
FROM tutorial.page_views
LIMIT 10;
```

**Правило**: в ClickHouse `SELECT *` читает все колонки с диска. Всегда указывай только нужные колонки.

## WHERE — фильтрация

```sql
-- Фильтр по дате (использует партиционирование)
SELECT count()
FROM tutorial.page_views
WHERE event_date = '2026-02-15';

-- Диапазон дат
SELECT count()
FROM tutorial.page_views
WHERE event_date BETWEEN '2026-02-01' AND '2026-02-28';

-- Несколько условий
SELECT user_id, page_url, duration
FROM tutorial.page_views
WHERE country = 'US'
  AND device = 'mobile'
  AND duration > 30
LIMIT 10;

-- IN для списка значений
SELECT count()
FROM tutorial.page_views
WHERE country IN ('US', 'DE', 'UK');
```

### Функции для дат в WHERE

```sql
-- Текущая дата
WHERE event_date = today()

-- Последние 7 дней
WHERE event_date >= today() - 7

-- Конкретный месяц
WHERE toYYYYMM(event_date) = 202603

-- Конкретный час
WHERE toHour(event_time) = 14
```

## ORDER BY и LIMIT

```sql
-- Топ-10 самых долгих визитов
SELECT user_id, page_url, duration
FROM tutorial.page_views
ORDER BY duration DESC
LIMIT 10;

-- LIMIT с offset (пагинация)
SELECT user_id, page_url, duration
FROM tutorial.page_views
ORDER BY duration DESC
LIMIT 10 OFFSET 20;
```

## Агрегатные функции

### Базовые

```sql
SELECT
    count()                    AS total_views,
    uniq(user_id)              AS unique_users,
    avg(duration)              AS avg_duration,
    min(duration)              AS min_duration,
    max(duration)              AS max_duration,
    sum(duration)              AS total_duration,
    median(duration)           AS median_duration,
    quantile(0.95)(duration)   AS p95_duration
FROM tutorial.page_views
WHERE event_date >= '2026-03-01';
```

### `uniq` vs `uniqExact`

```sql
-- uniq — приблизительный (HyperLogLog), быстрый, ошибка ~2%
SELECT uniq(user_id) FROM tutorial.page_views;

-- uniqExact — точный, медленный, больше памяти
SELECT uniqExact(user_id) FROM tutorial.page_views;
```

**Правило**: для дашбордов обычно достаточно `uniq`. Используй `uniqExact` только если точность критична.

## GROUP BY

```sql
-- Просмотры по странам
SELECT
    country,
    count()          AS views,
    uniq(user_id)    AS users,
    avg(duration)    AS avg_duration
FROM tutorial.page_views
GROUP BY country
ORDER BY views DESC;

-- По дате и стране
SELECT
    event_date,
    country,
    count() AS views
FROM tutorial.page_views
GROUP BY event_date, country
ORDER BY event_date, views DESC;
```

### GROUP BY с функциями дат

```sql
-- По месяцам
SELECT
    toYYYYMM(event_date)  AS month,
    count()               AS views,
    uniq(user_id)         AS users
FROM tutorial.page_views
GROUP BY month
ORDER BY month;

-- По часам (паттерн нагрузки)
SELECT
    toHour(event_time)    AS hour,
    count()               AS views
FROM tutorial.page_views
GROUP BY hour
ORDER BY hour;

-- По дням недели
SELECT
    toDayOfWeek(event_date) AS dow,
    count()                 AS views
FROM tutorial.page_views
GROUP BY dow
ORDER BY dow;
```

## HAVING — фильтрация после агрегации

```sql
-- Страны с более чем 1000 просмотров
SELECT
    country,
    count() AS views
FROM tutorial.page_views
GROUP BY country
HAVING views > 1000
ORDER BY views DESC;
```

## WITH — общие табличные выражения (CTE)

```sql
WITH daily_stats AS (
    SELECT
        event_date,
        count()        AS views,
        uniq(user_id)  AS users
    FROM tutorial.page_views
    GROUP BY event_date
)
SELECT
    event_date,
    views,
    users,
    round(views / users, 2) AS views_per_user
FROM daily_stats
ORDER BY event_date;
```

## Полезные функции

### Условные агрегации

```sql
SELECT
    count()                                          AS total,
    countIf(device = 'mobile')                       AS mobile,
    countIf(device = 'desktop')                      AS desktop,
    round(countIf(device = 'mobile') / count() * 100, 1) AS mobile_pct
FROM tutorial.page_views;
```

### `if` и `multiIf`

```sql
SELECT
    user_id,
    duration,
    if(duration > 60, 'long', 'short')   AS visit_type,
    multiIf(
        duration < 10,  'bounce',
        duration < 60,  'short',
        duration < 300, 'medium',
        'long'
    ) AS visit_category
FROM tutorial.page_views
LIMIT 10;
```

### Группировка с if

```sql
SELECT
    multiIf(
        duration < 10,  '0-10s',
        duration < 30,  '10-30s',
        duration < 60,  '30-60s',
        duration < 300, '1-5m',
        '5m+'
    ) AS duration_bucket,
    count() AS views,
    round(count() / (SELECT count() FROM tutorial.page_views) * 100, 1) AS pct
FROM tutorial.page_views
GROUP BY duration_bucket
ORDER BY min(duration);
```

## DISTINCT

```sql
-- Уникальные страницы
SELECT DISTINCT page_url FROM tutorial.page_views;

-- Уникальные комбинации
SELECT DISTINCT country, device FROM tutorial.page_views;
```

## Практика — построение аналитического отчёта

```sql
-- Дашборд: ежедневная статистика
SELECT
    event_date,
    count()                          AS page_views,
    uniq(user_id)                    AS unique_users,
    round(avg(duration), 1)          AS avg_duration_sec,
    quantile(0.5)(duration)          AS median_duration,
    quantile(0.95)(duration)         AS p95_duration,
    countIf(duration < 10)           AS bounces,
    round(countIf(duration < 10) / count() * 100, 1) AS bounce_rate
FROM tutorial.page_views
GROUP BY event_date
ORDER BY event_date;
```

## Итоги урока

- Указывай только нужные колонки в SELECT
- `uniq()` — быстрый приблизительный подсчёт уникальных значений
- `countIf()`, `sumIf()` — условные агрегации без подзапросов
- `toYYYYMM()`, `toHour()`, `toDayOfWeek()` — функции для группировки по времени
- `quantile(0.95)(col)` — перцентили (p50, p95, p99)
- `multiIf()` — аналог CASE WHEN, удобен для бакетирования
