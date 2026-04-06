# Урок 9. Аналитические функции

## Оконные функции (Window Functions)

ClickHouse поддерживает стандартные оконные функции SQL. Они позволяют выполнять вычисления по "окну" строк без схлопывания результата в одну строку.

### Нумерация строк

```sql
-- Ранжирование страниц по просмотрам за каждый день
SELECT
    event_date,
    page_url,
    count() AS views,
    row_number() OVER (PARTITION BY event_date ORDER BY count() DESC) AS rank
FROM tutorial.page_views
GROUP BY event_date, page_url
ORDER BY event_date, rank
LIMIT 30;
```

### Топ-3 страницы каждого дня

```sql
SELECT *
FROM (
    SELECT
        event_date,
        page_url,
        count() AS views,
        row_number() OVER (PARTITION BY event_date ORDER BY count() DESC) AS rn
    FROM tutorial.page_views
    GROUP BY event_date, page_url
)
WHERE rn <= 3
ORDER BY event_date, rn;
```

### Накопительный итог (running total)

```sql
SELECT
    event_date,
    count() AS daily_views,
    sum(count()) OVER (ORDER BY event_date) AS cumulative_views
FROM tutorial.page_views
GROUP BY event_date
ORDER BY event_date;
```

### Скользящее среднее (moving average)

```sql
SELECT
    event_date,
    count() AS daily_views,
    avg(count()) OVER (
        ORDER BY event_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS moving_avg_7d
FROM tutorial.page_views
GROUP BY event_date
ORDER BY event_date;
```

### Сравнение с предыдущим периодом

```sql
SELECT
    event_date,
    views,
    prev_views,
    round((views - prev_views) / prev_views * 100, 1) AS growth_pct
FROM (
    SELECT
        event_date,
        count()                                         AS views,
        lagInFrame(count()) OVER (ORDER BY event_date)  AS prev_views
    FROM tutorial.page_views
    GROUP BY event_date
)
WHERE prev_views > 0
ORDER BY event_date;
```

## Работа с массивами (Arrays)

### Создание массивов

```sql
-- Литерал
SELECT [1, 2, 3] AS arr;

-- Из строки
SELECT splitByChar(',', 'a,b,c') AS arr;

-- Агрегация в массив
SELECT
    user_id,
    groupArray(page_url) AS pages_visited
FROM tutorial.page_views
WHERE event_date = '2026-03-01'
GROUP BY user_id
LIMIT 5;
```

### Разворачивание массива (ARRAY JOIN)

```sql
-- Развернуть массив тегов в строки
SELECT
    user_id,
    page
FROM (
    SELECT
        user_id,
        groupArray(page_url) AS pages
    FROM tutorial.page_views
    GROUP BY user_id
    LIMIT 5
)
ARRAY JOIN pages AS page;
```

### Функции массивов

```sql
SELECT
    [1, 2, 3, 4, 5]                          AS arr,
    length([1, 2, 3])                         AS len,          -- 3
    has([1, 2, 3], 2)                         AS contains,     -- 1 (true)
    indexOf([10, 20, 30], 20)                 AS idx,          -- 2
    arraySort([3, 1, 2])                      AS sorted,       -- [1, 2, 3]
    arrayReverse([1, 2, 3])                   AS reversed,     -- [3, 2, 1]
    arrayDistinct([1, 1, 2, 2, 3])            AS distinct_arr, -- [1, 2, 3]
    arrayIntersect([1, 2, 3], [2, 3, 4])      AS intersect,    -- [2, 3]
    arrayMap(x -> x * 2, [1, 2, 3])           AS doubled,      -- [2, 4, 6]
    arrayFilter(x -> x > 2, [1, 2, 3, 4, 5]) AS filtered;     -- [3, 4, 5]
```

### Практический пример: путь пользователя

```sql
-- Последовательность страниц для каждого пользователя за день
SELECT
    user_id,
    groupArray(page_url) AS journey,
    length(groupArray(page_url)) AS pages_count
FROM (
    SELECT user_id, page_url, event_time
    FROM tutorial.page_views
    WHERE event_date = '2026-03-01'
    ORDER BY user_id, event_time
)
GROUP BY user_id
HAVING pages_count >= 3
ORDER BY pages_count DESC
LIMIT 10;
```

## Словари (Dictionaries)

Словари — механизм для обогащения данных из внешних источников (PostgreSQL, файлы, HTTP). Данные кэшируются в памяти ClickHouse.

### Создание словаря из таблицы

```sql
-- Таблица-источник
CREATE TABLE tutorial.countries (
    code String,
    name String,
    region String
) ENGINE = MergeTree()
ORDER BY code;

INSERT INTO tutorial.countries VALUES
    ('US', 'United States', 'North America'),
    ('DE', 'Germany', 'Europe'),
    ('FR', 'France', 'Europe'),
    ('UK', 'United Kingdom', 'Europe'),
    ('JP', 'Japan', 'Asia'),
    ('BR', 'Brazil', 'South America'),
    ('CA', 'Canada', 'North America'),
    ('AU', 'Australia', 'Oceania');

-- Словарь
CREATE DICTIONARY tutorial.country_dict (
    code  String,
    name  String,
    region String
)
PRIMARY KEY code
SOURCE(CLICKHOUSE(
    DB 'tutorial'
    TABLE 'countries'
))
LAYOUT(FLAT())
LIFETIME(MIN 300 MAX 600);
```

### Использование словаря

```sql
-- Обогащение запроса
SELECT
    country,
    dictGet('tutorial.country_dict', 'name', country)   AS country_name,
    dictGet('tutorial.country_dict', 'region', country)  AS region,
    count() AS views
FROM tutorial.page_views
GROUP BY country
ORDER BY views DESC;

-- Группировка по данным из словаря
SELECT
    dictGet('tutorial.country_dict', 'region', country) AS region,
    count() AS views,
    uniq(user_id) AS users
FROM tutorial.page_views
GROUP BY region
ORDER BY views DESC;
```

### Словарь из PostgreSQL

```sql
CREATE DICTIONARY tutorial.users_dict (
    id        UInt64,
    name      String,
    email     String
)
PRIMARY KEY id
SOURCE(POSTGRESQL(
    HOST 'localhost'
    PORT 5432
    DB 'myapp'
    TABLE 'users'
    USER 'postgres'
    PASSWORD 'secret'
))
LAYOUT(HASHED())
LIFETIME(MIN 300 MAX 600);
```

## Аппроксимации

ClickHouse предоставляет приблизительные функции, которые работают на порядки быстрее точных.

```sql
SELECT
    -- Точный подсчёт уникальных
    uniqExact(user_id) AS exact_users,

    -- Приблизительный (HyperLogLog, ошибка ~2%)
    uniq(user_id) AS approx_users,

    -- Приблизительная медиана
    median(duration) AS approx_median,

    -- Точный перцентиль
    quantileExact(0.95)(duration) AS exact_p95,

    -- Приблизительный перцентиль (t-digest)
    quantile(0.95)(duration) AS approx_p95,

    -- Несколько перцентилей за один проход
    quantiles(0.5, 0.9, 0.95, 0.99)(duration) AS percentiles
FROM tutorial.page_views;
```

## Функции для работы с URL

```sql
SELECT
    page_url,
    protocol(page_url)             AS proto,
    domain(page_url)               AS host,
    path(page_url)                 AS url_path,
    extractURLParameter(page_url, 'utm_source') AS utm
FROM (
    SELECT 'https://example.com/products?utm_source=google&page=1' AS page_url
);
```

## Функции для работы с датами

```sql
SELECT
    now()                              AS current_time,
    today()                            AS current_date,
    yesterday()                        AS prev_date,
    toStartOfMonth(today())            AS month_start,
    toStartOfWeek(today())             AS week_start,
    toStartOfHour(now())               AS hour_start,
    toStartOfInterval(now(), INTERVAL 15 MINUTE) AS interval_15m,
    dateDiff('day', '2026-01-01', today())       AS days_since_ny,
    addDays(today(), 30)               AS plus_30_days,
    formatDateTime(now(), '%Y-%m-%d %H:%M') AS formatted;
```

## Функции для работы с JSON

```sql
-- Извлечение из JSON-строки
SELECT
    JSONExtractString('{"name": "Alice", "age": 30}', 'name')   AS name,
    JSONExtractInt('{"name": "Alice", "age": 30}', 'age')       AS age,
    JSONExtract('{"tags": ["a", "b"]}', 'tags', 'Array(String)') AS tags;
```

## Практика

```sql
-- 1. Найти топ-3 страницы каждого дня (оконная функция)
-- 2. Рассчитать 7-дневное скользящее среднее просмотров
-- 3. Построить путь пользователя (groupArray)
-- 4. Создать словарь стран и обогатить запрос
-- 5. Сравнить uniq vs uniqExact на таблице page_views
-- 6. Рассчитать рост трафика день к дню (lagInFrame)
```

## Итоги урока

- Оконные функции: `row_number`, `lag`, `sum() OVER` — аналитика без подзапросов
- Массивы: `groupArray`, `ARRAY JOIN`, `arrayMap/Filter` — работа с коллекциями
- Словари: обогащение данных из внешних источников с кэшированием в памяти
- Аппроксимации: `uniq`, `quantile` — быстрые приблизительные вычисления
- Богатая библиотека функций для дат, URL, JSON
