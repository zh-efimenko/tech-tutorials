# Урок 7. Оптимизация производительности

## Как ClickHouse выполняет запрос

```
SQL-запрос
    │
    ▼
1. Отсечение партиций (PARTITION BY)
    │  — пропускаются целые партиции по WHERE на дату
    ▼
2. Отсечение гранул (sparse index по ORDER BY)
    │  — в каждой партиции читаются только релевантные гранулы
    ▼
3. Чтение колонок с диска
    │  — читаются только колонки из SELECT и WHERE
    ▼
4. Фильтрация, агрегация, сортировка
    │  — параллельно на всех ядрах CPU
    ▼
Результат
```

## EXPLAIN — анализ запроса

```sql
-- План выполнения
EXPLAIN
SELECT country, count()
FROM tutorial.page_views
WHERE event_date = '2026-02-15'
GROUP BY country;

-- Подробный план с pipeline
EXPLAIN PIPELINE
SELECT country, count()
FROM tutorial.page_views
WHERE event_date = '2026-02-15'
GROUP BY country;

-- Оценка стоимости (сколько строк/гранул будет прочитано)
EXPLAIN ESTIMATE
SELECT count()
FROM tutorial.page_views
WHERE event_date = '2026-02-15';
```

## Партиционирование (PARTITION BY)

### Правильный выбор

```sql
-- По месяцам — хорошо для большинства случаев
PARTITION BY toYYYYMM(event_date)

-- По дням — если данных очень много (100M+ строк/день)
PARTITION BY event_date

-- По году — если данных мало
PARTITION BY toYear(event_date)
```

**Правило**: должно быть от 10 до 1000 партиций. Слишком много партиций (одна на каждую минуту) = слишком много Part-ов.

### Проверка партиций

```sql
SELECT
    partition,
    count()                           AS parts,
    sum(rows)                         AS total_rows,
    formatReadableSize(sum(bytes_on_disk)) AS size
FROM system.parts
WHERE table = 'page_views' AND active
GROUP BY partition
ORDER BY partition;
```

### Управление партициями

```sql
-- Удалить данные за январь (мгновенно — удаляется файл)
ALTER TABLE tutorial.page_views DROP PARTITION '202601';

-- Отсоединить партицию (не удаляет, перемещает в detached/)
ALTER TABLE tutorial.page_views DETACH PARTITION '202602';

-- Присоединить обратно
ALTER TABLE tutorial.page_views ATTACH PARTITION '202602';
```

## ORDER BY — правильный выбор ключа сортировки

ORDER BY — самый важный параметр для производительности. Он определяет sparse index.

### Принцип: от низкой кардинальности к высокой

```sql
-- ПРАВИЛЬНО: country (8 значений) → event_date → user_id
ORDER BY (country, event_date, user_id)

-- НЕПРАВИЛЬНО: user_id (10 000 значений) первым
ORDER BY (user_id, event_date, country)
-- sparse index отсечёт мало гранул при WHERE country = 'US'
```

### Принцип: часто фильтруемые колонки — первыми

Если 80% запросов содержат `WHERE event_date = ...`, то `event_date` должна быть в начале ORDER BY.

### Проверка эффективности

```sql
-- Включить логирование
SET send_logs_level = 'trace';

-- Выполнить запрос и посмотреть, сколько гранул прочитано
SELECT count() FROM tutorial.page_views WHERE country = 'US';

-- В логе будет:
-- Selected 15/120 parts, 1500/12000 marks (гранул) — хорошо
-- Selected 120/120 parts, 12000/12000 marks — плохо, читает всё
```

## Data Skipping Indexes

Дополнительные индексы поверх sparse index. Не заменяют ORDER BY, а дополняют.

### minmax — диапазон значений в грануле

```sql
ALTER TABLE tutorial.page_views
    ADD INDEX idx_duration duration TYPE minmax GRANULARITY 4;

-- Пересчитать индекс для существующих данных
ALTER TABLE tutorial.page_views MATERIALIZE INDEX idx_duration;
```

Запрос `WHERE duration > 200` пропустит гранулы, где max(duration) < 200.

### set — набор уникальных значений в грануле

```sql
ALTER TABLE tutorial.page_views
    ADD INDEX idx_page_url page_url TYPE set(100) GRANULARITY 3;

ALTER TABLE tutorial.page_views MATERIALIZE INDEX idx_page_url;
```

Запрос `WHERE page_url = '/checkout'` пропустит гранулы, где нет такого page_url.

### bloom_filter — вероятностный фильтр

```sql
ALTER TABLE tutorial.page_views
    ADD INDEX idx_url_bloom page_url TYPE bloom_filter(0.01) GRANULARITY 3;

ALTER TABLE tutorial.page_views MATERIALIZE INDEX idx_url_bloom;
```

Хорош для строковых колонок с высокой кардинальностью. Ложно-положительные ~1%, ложно-отрицательных нет.

## Проекции (Projections)

Проекция — скрытая копия таблицы с другим ORDER BY. ClickHouse автоматически выбирает проекцию, если она подходит для запроса.

```sql
ALTER TABLE tutorial.page_views
    ADD PROJECTION proj_by_country (
        SELECT
            country,
            event_date,
            count()       AS views,
            uniq(user_id) AS users,
            avg(duration) AS avg_dur
        GROUP BY country, event_date
    );

-- Материализовать для существующих данных
ALTER TABLE tutorial.page_views MATERIALIZE PROJECTION proj_by_country;
```

Теперь запрос вида `SELECT country, count() FROM page_views GROUP BY country` автоматически использует проекцию.

### Проверка использования проекции

```sql
EXPLAIN
SELECT country, count()
FROM tutorial.page_views
GROUP BY country;
-- В плане будет: ReadFromMergeTree (proj_by_country)
```

## Настройки запросов

```sql
-- Максимальное количество потоков для запроса
SET max_threads = 8;

-- Максимальный объём RAM для запроса (в байтах)
SET max_memory_usage = 10000000000;  -- 10 GB

-- Таймаут запроса
SET max_execution_time = 30;  -- 30 секунд

-- Приблизительный результат (быстрее, но не точный)
SET max_rows_to_read = 1000000;
```

## Мониторинг запросов

```sql
-- Лог запросов (последние 10)
SELECT
    query_id,
    query,
    read_rows,
    formatReadableSize(read_bytes)   AS read_data,
    formatReadableSize(memory_usage) AS memory,
    query_duration_ms
FROM system.query_log
WHERE type = 'QueryFinish'
  AND query NOT LIKE '%system.query_log%'
ORDER BY event_time DESC
LIMIT 10;

-- Медленные запросы (> 1 секунды)
SELECT
    query,
    query_duration_ms,
    read_rows,
    formatReadableSize(read_bytes) AS read_data
FROM system.query_log
WHERE type = 'QueryFinish'
  AND query_duration_ms > 1000
ORDER BY query_duration_ms DESC
LIMIT 10;
```

## Чек-лист оптимизации

1. **WHERE по партиции** — всегда фильтруй по дате
2. **ORDER BY** — часто фильтруемые колонки первыми, от низкой кардинальности к высокой
3. **Только нужные колонки** — не `SELECT *`
4. **Data Skipping Indexes** — для колонок, не входящих в ORDER BY
5. **Проекции** — для частых запросов с другой группировкой
6. **Materialized Views** — предрассчитанные агрегаты (урок 6)
7. **LowCardinality** — для строковых колонок с малым числом значений
8. **Правильные типы** — `UInt16` вместо `UInt64`

## Практика

```sql
-- 1. EXPLAIN ESTIMATE — оценить стоимость запроса
-- 2. Добавить minmax-индекс на duration, проверить эффективность
-- 3. Создать проекцию для группировки по стране
-- 4. Сравнить время запроса с проекцией и без
-- 5. Посмотреть query_log — найти самые тяжёлые запросы
-- 6. Проверить партиции и их размеры
```

## Итоги урока

- ClickHouse отсекает данные на 3 уровнях: партиции → гранулы → колонки
- `ORDER BY` — самый важный параметр производительности
- Data Skipping Indexes (minmax, set, bloom_filter) — для колонок вне ORDER BY
- Проекции — скрытая копия таблицы с другой сортировкой/агрегацией
- `system.query_log` — главный инструмент анализа производительности
- `EXPLAIN` / `EXPLAIN ESTIMATE` — анализ плана запроса
