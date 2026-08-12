# Урок 3. Загрузка данных

## Главное правило вставки в ClickHouse

**Вставляй батчами, не по одной строке.** Каждый INSERT создаёт новый Part на диске. Если вставлять по одной строке — тысячи мелких файлов, деградация производительности.

| Паттерн | Результат |
|---------|-----------|
| 1 INSERT с 10 000 строк | 1 Part → отлично |
| 10 000 INSERT по 1 строке | 10 000 Parts → плохо |

**Рекомендация**: вставлять батчами от 1 000 до 100 000 строк. Оптимально — раз в секунду.

> **Начиная с 26.3 LTS настройка `async_insert` включена по умолчанию.** Сервер сам копит мелкие вставки в буфер и сбрасывает их одним Part (по умолчанию не дольше 200 мс — `async_insert_busy_timeout_max_ms`). Проверить: `SELECT name, value FROM system.settings WHERE name = 'async_insert'`. Правило «вставляй батчами» это не отменяет: асинхронная вставка — страховка от чужого плохого клиента, а не замена батчам. Каждый мелкий INSERT всё так же тратит round-trip, парсинг и место в очереди буфера.

## INSERT VALUES

Самый простой способ — перечислить значения:

```sql
INSERT INTO tutorial.page_views VALUES
    ('2026-03-01', '2026-03-01 10:00:00', 1001, '/home', 5, 'US', 'desktop'),
    ('2026-03-01', '2026-03-01 10:01:30', 1002, '/products', 12, 'DE', 'mobile'),
    ('2026-03-01', '2026-03-01 10:02:45', 1001, '/products/123', 45, 'US', 'desktop'),
    ('2026-03-01', '2026-03-01 10:05:00', 1003, '/home', 3, 'FR', 'tablet'),
    ('2026-03-01', '2026-03-01 10:10:00', 1002, '/checkout', 120, 'DE', 'mobile');
```

## INSERT с FORMAT

ClickHouse поддерживает десятки форматов ввода. Основные:

### CSV

```sql
INSERT INTO tutorial.page_views FORMAT CSV
2026-03-02,2026-03-02 11:00:00,2001,/home,8,UK,desktop
2026-03-02,2026-03-02 11:05:00,2002,/about,15,UK,mobile
2026-03-02,2026-03-02 11:10:00,2003,/products,22,JP,desktop
```

### TSV (Tab-Separated Values)

```sql
INSERT INTO tutorial.page_views FORMAT TSV
2026-03-03	2026-03-03 12:00:00	3001	/home	6	BR	tablet
2026-03-03	2026-03-03 12:05:00	3002	/pricing	30	BR	desktop
```

### JSONEachRow

Самый удобный формат для интеграции с приложениями:

```sql
INSERT INTO tutorial.page_views FORMAT JSONEachRow
{"event_date": "2026-03-04", "event_time": "2026-03-04 14:00:00", "user_id": 4001, "page_url": "/home", "duration": 10, "country": "US", "device": "desktop"}
{"event_date": "2026-03-04", "event_time": "2026-03-04 14:05:00", "user_id": 4002, "page_url": "/api/docs", "duration": 60, "country": "CA", "device": "desktop"}
```

## Загрузка из файла

Сначала создай файлы в текущем каталоге — колонки в том же порядке, что и в таблице:

```bash
cat > data.csv <<'EOF'
2026-03-05,2026-03-05 09:00:00,5001,/home,7,US,desktop
2026-03-05,2026-03-05 09:03:00,5002,/pricing,25,DE,mobile
2026-03-05,2026-03-05 09:07:00,5003,/blog,90,FR,tablet
EOF

cat > data.jsonl <<'EOF'
{"event_date": "2026-03-06", "event_time": "2026-03-06 08:00:00", "user_id": 6001, "page_url": "/login", "duration": 5, "country": "UK", "device": "mobile"}
{"event_date": "2026-03-06", "event_time": "2026-03-06 08:02:00", "user_id": 6002, "page_url": "/signup", "duration": 40, "country": "CA", "device": "desktop"}
EOF
```

### Через clickhouse-client

```bash
# CSV-файл
docker exec -i clickhouse clickhouse-client \
    --user default --password clickhouse \
    --query="INSERT INTO tutorial.page_views FORMAT CSV" < data.csv

# JSON
docker exec -i clickhouse clickhouse-client \
    --user default --password clickhouse \
    --query="INSERT INTO tutorial.page_views FORMAT JSONEachRow" < data.jsonl
```

### Через HTTP-интерфейс (curl)

```bash
# Загрузка CSV через HTTP
curl 'http://localhost:8123/?user=default&password=clickhouse&query=INSERT+INTO+tutorial.page_views+FORMAT+CSV' \
    --data-binary @data.csv

# Загрузка JSON
curl 'http://localhost:8123/?user=default&password=clickhouse&query=INSERT+INTO+tutorial.page_views+FORMAT+JSONEachRow' \
    --data-binary @data.jsonl
```

## Генерация тестовых данных

ClickHouse имеет встроенные функции для генерации данных:

```sql
-- Генерация 1 000 000 строк за 90 дней: 2026-01-01 .. 2026-03-31
INSERT INTO tutorial.page_views
SELECT
    toDate(event_time)                                            AS event_date,
    event_time,
    rand(2) % 10000 + 1                                           AS user_id,
    arrayElement(
        ['/home', '/products', '/checkout', '/about', '/pricing',
         '/api/docs', '/blog', '/contact', '/login', '/signup'],
        rand(3) % 10 + 1
    )                                                             AS page_url,
    rand(4) % 300 + 1                                             AS duration,
    arrayElement(
        ['US', 'DE', 'FR', 'UK', 'JP', 'BR', 'CA', 'AU'],
        rand(5) % 8 + 1
    )                                                             AS country,
    arrayElement(['desktop', 'mobile', 'tablet'], rand(6) % 3 + 1) AS device
FROM (
    SELECT toDateTime('2026-01-01 00:00:00') + rand(1) % (90 * 86400) AS event_time
    FROM numbers(1000000)
);
```

**Два нюанса, без которых генератор даёт мусор.**

`rand()` без аргумента внутри одного запроса — это одно и то же выражение, и ClickHouse вычисляет его **один раз на строку**. Проверь сам:

```sql
SELECT count() FROM (SELECT rand() % 10 AS a, rand() % 10 AS b FROM numbers(1000)) WHERE a != b;
-- 0: a и b всегда равны
```

Значит все колонки оказались бы функциями одного числа: `page_url` жёстко связан с датой (`10` делит `90`), и на каждую дату пришлась бы ровно одна страница и один девайс. Разные аргументы — `rand(1)`, `rand(2)`, … — дают независимые потоки:

```sql
SELECT count() FROM (SELECT rand(1) % 10 AS a, rand(2) % 10 AS b FROM numbers(1000)) WHERE a != b;
-- около 900
```

Второй нюанс: `event_date` считается из `event_time` (`toDate(event_time)`), а не генерируется отдельно. Иначе дата и время события расходятся почти в каждой строке, и любая группировка по дате врёт.

> Диапазон дат зафиксирован (`2026-01-01 .. 2026-03-31`) намеренно: следующие уроки фильтруют по конкретным датам вроде `'2026-02-15'`. Если сгенерировать данные относительно `now()`, эти примеры вернут ноль строк.

### Проверка загруженных данных

```sql
-- Количество строк
SELECT count() FROM tutorial.page_views;

-- Первые 10 строк
SELECT * FROM tutorial.page_views LIMIT 10;

-- Размер таблицы на диске
SELECT
    formatReadableSize(sum(bytes_on_disk)) AS size,
    sum(rows) AS total_rows,
    count() AS parts_count
FROM system.parts
WHERE table = 'page_views' AND active;
```

## Таблица system.parts

Каждый INSERT создаёт Part (при `async_insert = 1` — каждый сброс буфера, то есть несколько мелких INSERT могут склеиться в один Part). Посмотреть их:

```sql
SELECT
    name,
    rows,
    formatReadableSize(bytes_on_disk) AS size,
    modification_time
FROM system.parts
WHERE table = 'page_views' AND active
ORDER BY modification_time DESC
LIMIT 10;
```

## OPTIMIZE TABLE

Принудительное слияние Parts (обычно не нужно, ClickHouse делает это сам):

```sql
-- Слить все Parts
OPTIMIZE TABLE tutorial.page_views FINAL;
```

## Форматы вывода

ClickHouse поддерживает множество форматов для SELECT:

```sql
-- Красивая таблица (по умолчанию в CLI)
SELECT * FROM tutorial.page_views LIMIT 3 FORMAT PrettyCompact;

-- JSON (для API)
SELECT * FROM tutorial.page_views LIMIT 3 FORMAT JSON;

-- Одна строка JSON на запись (для стриминга)
SELECT * FROM tutorial.page_views LIMIT 3 FORMAT JSONEachRow;

-- CSV
SELECT * FROM tutorial.page_views LIMIT 3 FORMAT CSV;

-- TSV с заголовками
SELECT * FROM tutorial.page_views LIMIT 3 FORMAT TSVWithNames;
```

## Практика

```sql
-- 1. Вставить данные VALUES-форматом (пример выше)

-- 2. Сгенерировать 1 000 000 строк (пример выше)

-- 3. Проверить количество и размер

-- 4. Посмотреть Parts таблицы

-- 5. Выполнить OPTIMIZE TABLE FINAL

-- 6. Снова посмотреть Parts — их стало меньше

-- 7. Вывести 5 строк в формате JSONEachRow
SELECT * FROM tutorial.page_views LIMIT 5 FORMAT JSONEachRow;
```

## Итоги урока

- Всегда вставляй батчами (1000+ строк за раз)
- `JSONEachRow` — лучший формат для интеграции с приложениями
- Каждый INSERT создаёт Part; Parts фоново сливаются. С 26.3 LTS `async_insert = 1` по умолчанию — сервер склеивает мелкие вставки в один Part
- `system.parts` — просмотр физических кусков таблицы
- `numbers(N)` + `rand()` — генерация тестовых данных
- ClickHouse поддерживает десятки форматов ввода/вывода
