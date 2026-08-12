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

> **Не выполняй `DROP PARTITION` на `page_views`.** Это треть данных курса (~345 000 строк) и обратного хода нет: следующий же пример этого урока перестанет упираться в `max_rows_to_read`, а примеры уроков 9 и 10 потеряют январь. Синтаксис ниже — для чтения; если хочешь попробовать руками, сделай это на копии: `CREATE TABLE tutorial.pv_copy AS tutorial.page_views` + `INSERT INTO tutorial.pv_copy SELECT * FROM tutorial.page_views`.

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

-- В логе будет строка вида:
-- Selected 4/4 parts by partition key, 4 parts by primary key,
-- 125/125 marks by primary key, 125 marks to read from 4 ranges
```

Читать её так: первая дробь — сколько партов прошло отсечение по партициям, вторая (`marks by primary key`) — сколько гранул осталось после sparse index. `125/125` означает, что индекс не отсёк ничего: `country` не входит в `ORDER BY (user_id, event_time)`, поэтому читается вся таблица. Для сравнения выполни запрос с фильтром по первой колонке ключа — `WHERE user_id = 42` — там дробь будет вида `3/125`.

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

**Проверь эффект — и не удивляйся нулю:**

```sql
SET send_logs_level = 'trace';
SELECT count() FROM tutorial.page_views WHERE duration > 200;
-- Index `idx_duration` has dropped 0/125 granules
```

Ноль — правильный результат на данных этого курса, а не поломка. `duration` сгенерирован равномерно в диапазоне 1..300 и никак не связан с `ORDER BY (user_id, event_time)`, поэтому почти в каждой грануле по 8192 строк найдётся значение и меньше 200, и больше. `minmax` отсекает гранулу, только если весь её диапазон лежит вне условия.

**Отсюда правило:** skip-индекс работает, когда значения колонки коррелируют с физическим порядком строк — растущие счётчики, идентификаторы, редкие категории. На равномерно случайной колонке он бесполезен и только занимает место.

### set — набор уникальных значений в грануле

```sql
ALTER TABLE tutorial.page_views
    ADD INDEX idx_page_url page_url TYPE set(100) GRANULARITY 3;

ALTER TABLE tutorial.page_views MATERIALIZE INDEX idx_page_url;
```

Запрос `WHERE page_url = '/checkout'` пропустит гранулы, где нет такого page_url. На данных курса это снова `0/125`: в наборе всего 10 URL, и в грануле из 8192 строк встречаются все. `set(100)` начинает окупаться, когда уникальных значений в колонке много, а в отдельной грануле — единицы.

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

Чтобы сравнить с исходным вариантом, проекцию надо отключить настройкой — иначе ClickHouse всегда возьмёт её:

```sql
EXPLAIN
SELECT country, count()
FROM tutorial.page_views
GROUP BY country
SETTINGS optimize_use_projections = 0;
-- ReadFromMergeTree (tutorial.page_views)
```

## Настройки запросов

```sql
-- Максимальное количество потоков для запроса
SET max_threads = 8;

-- Максимальный объём RAM для запроса (в байтах)
SET max_memory_usage = 10000000000;  -- 10 GB

-- Таймаут запроса
SET max_execution_time = 30;  -- 30 секунд

-- Жёсткий лимит на прочитанные строки: запрос не «упростится», а упадёт
SET max_rows_to_read = 1000000;

SELECT count() FROM tutorial.page_views WHERE duration > 5;
-- Code: 158. DB::Exception: Limit for rows or bytes to read exceeded,
-- max rows: 1.00 million, current rows: 1.00 million:
-- While executing MergeTreeSelect(pool: ReadPool, algorithm: Thread). (TOO_MANY_ROWS)

-- Чтобы вместо ошибки получить неполный (приблизительный) результат:
SET read_overflow_mode = 'break';
```

Обрати внимание: `WHERE` в запросе обязателен. `SELECT count()` без него берёт число строк из метаданных и в лимит не упирается вообще. Формулировка зависит от того, где сработала проверка. Если лимит ловится ещё на этапе планирования (например, до того как ты создал проекцию в предыдущем разделе), текст будет другим: `Limit for rows (controlled by 'max_rows_to_read' setting) exceeded, max rows: 1.00 million, current rows: 1.00 million.` Код `158` и `TOO_MANY_ROWS` одинаковы в обоих случаях — ориентируйся на них, а не на формулировку.

`max_rows_to_read` — предохранитель от случайного full scan, а не режим приблизительных вычислений. Лимит проверяется по мере чтения гранул, поэтому `current rows` в сообщении — это счётчик на момент срабатывания, он может совпасть с лимитом или чуть его превысить.

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

> На данных курса (1 млн строк) этот запрос вернёт пусто: секунду здесь не превышает ничего, самый долгий запрос — около 200 мс. Порог `1000` — production-значение; чтобы увидеть свои «тяжёлые» запросы сейчас, опусти его до `100`.

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
-- 2. Добавить minmax-индекс на duration и убедиться по trace-логу,
--    что он даёт 0/125 — объяснить себе почему
-- 3. Создать проекцию для группировки по стране
-- 4. Сравнить время запроса с проекцией и без
--    (без — через SETTINGS optimize_use_projections = 0)
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
