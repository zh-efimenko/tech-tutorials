# Урок 2. Типы данных и создание таблиц

## Система типов ClickHouse

ClickHouse — строго типизированная СУБД. Правильный выбор типа данных напрямую влияет на сжатие и скорость запросов.

## Основные типы данных

### Целые числа

| Тип | Размер | Диапазон |
|-----|--------|----------|
| `UInt8` | 1 байт | 0 .. 255 |
| `UInt16` | 2 байта | 0 .. 65 535 |
| `UInt32` | 4 байта | 0 .. 4 294 967 295 |
| `UInt64` | 8 байт | 0 .. 18.4 × 10¹⁸ |
| `Int8` | 1 байт | -128 .. 127 |
| `Int16` | 2 байта | -32 768 .. 32 767 |
| `Int32` | 4 байта | ±2.1 × 10⁹ |
| `Int64` | 8 байт | ±9.2 × 10¹⁸ |

**Правило**: используй минимальный достаточный тип. `UInt8` для статусов, `UInt16` для портов, `UInt32` для ID.

### Числа с плавающей точкой

| Тип | Описание |
|-----|----------|
| `Float32` | 4 байта, ~7 значащих цифр |
| `Float64` | 8 байт, ~15 значащих цифр |
| `Decimal(P, S)` | Точная арифметика. `Decimal(18, 2)` для денег |

**Правило**: для денег и точных вычислений — только `Decimal`. `Float` даёт ошибки округления.

### Строки

| Тип | Описание |
|-----|----------|
| `String` | Произвольная длина (аналог TEXT) |
| `FixedString(N)` | Ровно N байт, дополняется нулями |
| `LowCardinality(String)` | Строки с малым числом уникальных значений |
| `Enum8` / `Enum16` | Перечисления (хранит числа, показывает строки) |

**Правило**: для колонок с малым числом уникальных значений (статус, страна, тип) — используй `LowCardinality(String)` или `Enum`. Это сжимается на порядок лучше.

```sql
-- LowCardinality — хранит словарь + индексы вместо полных строк
CREATE TABLE events (
    event_type LowCardinality(String)  -- 'click', 'view', 'purchase' — всего ~20 вариантов
) ENGINE = MergeTree() ORDER BY tuple();
```

### Дата и время

| Тип | Описание | Пример |
|-----|----------|--------|
| `Date` | Дата (дни с 1970-01-01) | `2026-03-15` |
| `Date32` | Расширенный диапазон дат | `1900-01-01` |
| `DateTime` | Секунды с Unix epoch | `2026-03-15 14:30:00` |
| `DateTime64(3)` | Миллисекунды | `2026-03-15 14:30:00.123` |

**Правило**: `DateTime` для большинства случаев. `DateTime64(3)` если нужны миллисекунды.

### Nullable

```sql
-- Nullable оборачивает любой тип, разрешая NULL
Nullable(UInt32)
Nullable(String)
```

**Правило**: избегай `Nullable` где возможно. Он добавляет отдельный файл-маску и замедляет запросы. Используй значения по умолчанию: `0` для чисел, `''` для строк, `'1970-01-01'` для дат.

### UUID

```sql
UUID  -- 128-бит, '550e8400-e29b-41d4-a716-446655440000'
```

### Массивы и вложенные структуры

```sql
Array(UInt32)           -- [1, 2, 3]
Array(String)           -- ['a', 'b', 'c']
Tuple(String, UInt32)   -- ('hello', 42)
Map(String, UInt64)     -- {'key1': 1, 'key2': 2}
```

## Движок MergeTree

MergeTree — основной и самый важный движок таблиц в ClickHouse. Все остальные движки семейства MergeTree наследуют от него.

### Как работает MergeTree

```
INSERT батч (например 10 000 строк)
        │
        ▼
  Создаётся Part (кусок)
  - отсортирован по ORDER BY
  - каждая колонка в отдельном файле
  - sparse index записан
        │
        ▼
  Фоновый процесс Merge
  - объединяет мелкие Parts в крупные
  - данные пересортируются
  - индекс пересчитывается
```

### Создание таблицы

```sql
CREATE TABLE tutorial.page_views (
    event_date Date,
    event_time DateTime,
    user_id    UInt64,
    page_url   String,
    duration   UInt32,
    country    LowCardinality(String),
    device     Enum8('desktop' = 1, 'mobile' = 2, 'tablet' = 3)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_date)
ORDER BY (user_id, event_time)
SETTINGS index_granularity = 8192;
-- TTL добавляется отдельно при необходимости (см. урок 10)
```

### Разбор каждого параметра

#### `ENGINE = MergeTree()`

Движок таблицы. MergeTree — стандартный выбор для аналитики.

#### `PARTITION BY toYYYYMM(event_date)`

Разделяет данные на физические директории по месяцам. Запрос `WHERE event_date = '2026-03-15'` читает только партицию `202603`.

```
/var/lib/clickhouse/data/tutorial/page_views/
├── 202601_1_5_2/     ← январь (parts объединены)
├── 202602_6_10_1/    ← февраль
└── 202603_11_11_0/   ← март
```

#### `ORDER BY (user_id, event_time)`

Определяет физическую сортировку данных на диске и sparse index. Это **самый важный** параметр таблицы.

**Правило выбора ORDER BY**: ставь первыми колонки, по которым чаще всего фильтруешь.

```sql
-- Если большинство запросов: WHERE user_id = X AND event_time BETWEEN ...
ORDER BY (user_id, event_time)  -- правильно

-- Если большинство запросов: WHERE country = X AND event_date = ...
ORDER BY (country, event_date)  -- правильно для другого сценария
```

#### `TTL event_date + INTERVAL 90 DAY`

Автоматическое удаление данных старше 90 дней. ClickHouse удаляет целые Parts при merge.

#### `SETTINGS index_granularity = 8192`

Sparse index записывает значение ORDER BY каждые 8192 строк (гранула). Это значение по умолчанию и менять его обычно не нужно.

## Sparse Index (разреженный индекс)

В отличие от B-tree в PostgreSQL, sparse index хранит **не каждое значение**, а значение каждые N строк:

```
Granule 0: user_id=100,  event_time=2026-01-01 00:00:00  (строки 0-8191)
Granule 1: user_id=250,  event_time=2026-01-01 01:30:00  (строки 8192-16383)
Granule 2: user_id=500,  event_time=2026-01-01 03:00:00  (строки 16384-24575)
...
```

Запрос `WHERE user_id = 300` → нужна гранула 1 (между 250 и 500) → читаются только 8192 строки вместо миллионов.

## DEFAULT и MATERIALIZED

```sql
CREATE TABLE tutorial.orders (
    id           UInt64,
    created_at   DateTime DEFAULT now(),
    amount       Decimal(18, 2),
    currency     LowCardinality(String) DEFAULT 'USD',
    -- MATERIALIZED — вычисляется автоматически, не принимается в INSERT
    created_date Date MATERIALIZED toDate(created_at)
) ENGINE = MergeTree()
ORDER BY (created_at, id);
```

- `DEFAULT` — используется, если значение не передано в INSERT
- `MATERIALIZED` — всегда вычисляется, нельзя вставить явно, не отображается в `SELECT *`

## Практика

```sql
-- 1. Создать базу (если ещё нет)
CREATE DATABASE IF NOT EXISTS tutorial;

-- 2. Создать таблицу page_views (см. выше)

-- 3. Посмотреть структуру
DESCRIBE TABLE tutorial.page_views;

-- 4. Посмотреть CREATE-запрос
SHOW CREATE TABLE tutorial.page_views;

-- 5. Создать таблицу orders (см. выше)

-- 6. Удалить таблицу (если нужно пересоздать)
DROP TABLE IF EXISTS tutorial.page_views;
```

## Итоги урока

- Выбирай минимальный достаточный тип: `UInt16` вместо `UInt64` где можно
- `LowCardinality(String)` — для колонок с малым числом уникальных строк
- Избегай `Nullable` — используй значения по умолчанию
- `ORDER BY` — самый важный параметр, определяет sparse index
- `PARTITION BY` — физическое разделение данных (обычно по дате)
- MergeTree записывает данные кусками (Parts), которые фоново объединяются