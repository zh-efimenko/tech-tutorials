# Урок 10. Дашборды и Production

## Grafana + ClickHouse

Grafana — стандартный инструмент для дашбордов поверх ClickHouse.

### Добавляем Grafana в compose.yml

```yaml
# Добавить в services в compose.yml
  grafana:
    image: grafana/grafana:13.1.3
    container_name: grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      # Плагин ClickHouse не входит в образ — Grafana ставит его при старте.
      # GF_INSTALL_PLUGINS в Grafana 13 объявлена deprecated (пишет WARN в лог),
      # актуальная переменная — GF_PLUGINS_PREINSTALL
      - GF_PLUGINS_PREINSTALL=grafana-clickhouse-datasource
    volumes:
      - grafana-data:/var/lib/grafana
    depends_on:
      clickhouse:
        condition: service_healthy

# Добавить в volumes
  grafana-data:
```

### Подключение ClickHouse к Grafana

1. Открыть `http://localhost:3000` (admin / admin)
2. Connections → Data Sources → Add data source
3. Выбрать **ClickHouse** (появляется только если плагин `grafana-clickhouse-datasource` установлен — см. `GF_PLUGINS_PREINSTALL` выше)
4. Server address: `clickhouse` (имя сервиса в Docker), порт: `9000`, Protocol: **Native**
5. Database: `tutorial`
6. Username: `default`, Password: `clickhouse`
7. Save & Test → «Data source is working»

> Порт `9000` — нативный протокол, `8123` — HTTP. Порт и Protocol в настройках должны совпадать: `9000` + Native или `8123` + HTTP. Перепутанная пара даёт таймаут при Save & Test.

### Примеры запросов для дашбордов

#### Временной ряд (Time Series)

```sql
SELECT
    toStartOfHour(event_time) AS time,
    count()                   AS views,
    uniq(user_id)             AS users
FROM tutorial.page_views
WHERE event_date >= $__fromTime AND event_date <= $__toTime
GROUP BY time
ORDER BY time
```

`$__fromTime` и `$__toTime` — переменные Grafana, привязанные к time picker.

> **Первым делом выставь диапазон.** Данные курса лежат в `2026-01-01 .. 2026-03-31`, а time picker по умолчанию показывает последние 6 часов — все панели будут пустые с «No data». Поставь в правом верхнем углу абсолютный диапазон `2026-01-01` — `2026-04-01`, иначе будешь искать ошибку в SQL, которого она не касается.

#### Таблица (Table)

```sql
SELECT
    page_url,
    count()                          AS views,
    uniq(user_id)                    AS users,
    round(avg(duration), 1)          AS avg_duration,
    quantile(0.95)(duration)         AS p95
FROM tutorial.page_views
WHERE event_date >= $__fromTime AND event_date <= $__toTime
GROUP BY page_url
ORDER BY views DESC
LIMIT 20
```

#### Pie Chart (страны)

```sql
SELECT
    country,
    count() AS views
FROM tutorial.page_views
WHERE event_date >= $__fromTime AND event_date <= $__toTime
GROUP BY country
ORDER BY views DESC
LIMIT 10
```

#### Stat Panel (ключевые метрики)

```sql
SELECT
    count()                                              AS total_views,
    uniq(user_id)                                        AS unique_users,
    round(countIf(duration < 10) / count() * 100, 1)     AS bounce_rate,
    round(avg(duration), 1)                              AS avg_duration
FROM tutorial.page_views
WHERE event_date >= $__fromTime AND event_date <= $__toTime
```

## Мониторинг ClickHouse

### Системные таблицы

```sql
-- Текущие запросы
SELECT query_id, user, query, elapsed, read_rows, memory_usage
FROM system.processes;

-- Размер таблиц
SELECT
    database,
    table,
    formatReadableSize(sum(bytes_on_disk))  AS size,
    sum(rows)                               AS total_rows,
    count()                                 AS parts_count
FROM system.parts
WHERE active
GROUP BY database, table
ORDER BY sum(bytes_on_disk) DESC;

-- Статус merges
SELECT
    database,
    table,
    round(progress * 100, 1) AS progress_pct,
    formatReadableSize(total_size_bytes_compressed) AS size,
    elapsed
FROM system.merges;

-- Метрики сервера
SELECT metric, value
FROM system.metrics
WHERE metric IN (
    'Query', 'Merge', 'MemoryTracking',
    'TCPConnection', 'HTTPConnection'
);

-- Ошибки
SELECT
    name,
    value,
    last_error_time,
    last_error_message
FROM system.errors
WHERE value > 0
ORDER BY last_error_time DESC;
```

### Асинхронные метрики (для Grafana)

```sql
SELECT metric, value
FROM system.asynchronous_metrics
WHERE metric IN (
    'MaxPartCountForPartition',
    'ReplicasMaxAbsoluteDelay',
    'Uptime',
    'FilesystemCacheBytes',
    'FilesystemCacheFiles'
);
```

> Состав `system.asynchronous_metrics` меняется от версии к версии, и отсутствующая метрика не даёт ошибки — запрос просто вернёт меньше строк. Смотри, что реально есть на твоей сборке: `SELECT metric FROM system.asynchronous_metrics ORDER BY metric`.

## Бэкапы

### Сначала — настройка диска для бэкапов

Без неё первый же `BACKUP` падает:

```
Code: 318. DB::Exception: The 'backups.allowed_disk' configuration parameter
is not set, cannot use 'Disk' backup engine. (INVALID_CONFIG_PARAMETER)
```

Создай рядом с `compose.yml` файл `config.d/backups.xml`:

```xml
<clickhouse>
    <storage_configuration>
        <disks>
            <backups>
                <type>local</type>
                <path>/var/lib/clickhouse/backups/</path>
            </backups>
        </disks>
    </storage_configuration>
    <backups>
        <allowed_disk>backups</allowed_disk>
        <allowed_path>/var/lib/clickhouse/backups/</allowed_path>
    </backups>
</clickhouse>
```

Подмонтируй его в контейнер — добавь в `compose.yml` в секцию `volumes` сервиса `clickhouse`:

```yaml
      - ./config.d/backups.xml:/etc/clickhouse-server/config.d/backups.xml
```

И перезапусти: `docker compose up -d`. Конфиги из `config.d/` подхватываются только при старте сервера.

### Встроенный механизм BACKUP/RESTORE

```sql
-- Бэкап таблицы на диск
BACKUP TABLE tutorial.page_views
TO Disk('backups', 'page_views_2026-04-05.zip');

-- Бэкап всей базы
BACKUP DATABASE tutorial
TO Disk('backups', 'tutorial_full_2026-04-05.zip');

-- Восстановление рядом, под другим именем — так проверяют бэкап, не трогая рабочую таблицу
RESTORE TABLE tutorial.page_views AS tutorial.page_views_restored
FROM Disk('backups', 'page_views_2026-04-05.zip');
```

Восстановить поверх существующей таблицы с данными не выйдет:

```
Code: 608. DB::Exception: Cannot restore the table tutorial.page_views because it already
contains some data. You can set structure_only=true or allow_non_empty_tables=true
to overcome that in the way you want. (CANNOT_RESTORE_TABLE)
```

Это защита от случайного затирания. Если действительно нужно долить данные поверх — `RESTORE TABLE ... SETTINGS allow_non_empty_tables=true`, но учти, что строки не заменятся, а добавятся к имеющимся.

Успешный `BACKUP` возвращает одну строку: `<uuid>  BACKUP_CREATED`.

### Бэкап через clickhouse-client

```bash
# Экспорт в файл (альтернативный подход)
docker exec clickhouse clickhouse-client \
    --user default --password clickhouse \
    --query="SELECT * FROM tutorial.page_views FORMAT Native" > backup.native

# Импорт из файла
docker exec -i clickhouse clickhouse-client \
    --user default --password clickhouse \
    --query="INSERT INTO tutorial.page_views FORMAT Native" < backup.native
```

> `INSERT` не заменяет данные, а добавляет: импорт в непустую `page_views` удвоит её (1 000 000 → 2 000 000 строк), и дальше все агрегаты урока будут вдвое больше. Импортируй либо в пустую таблицу (`TRUNCATE TABLE tutorial.page_views` перед этим), либо в отдельную — `page_views_restored`.

## TTL — автоматическое удаление старых данных

```sql
-- Удалить данные старше 90 дней
CREATE TABLE tutorial.logs (
    event_date Date,
    event_time DateTime,
    message    String
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_date)
ORDER BY event_time
TTL event_date + INTERVAL 90 DAY;

-- Наполняем, иначе смотреть на работу TTL будет не на чем:
-- половина строк заведомо старше 90 дней, половина — свежая
INSERT INTO tutorial.logs
SELECT today() - number % 200, now() - (number % 200) * 86400, 'log line ' || toString(number)
FROM numbers(2000);

-- Партиции до срабатывания TTL: заполнены все ~7 месяцев
SELECT partition, sum(rows) FROM system.parts
WHERE table = 'logs' AND active GROUP BY partition ORDER BY partition;

-- TTL применяется при merge. Не ждать фонового — запустить принудительно:
OPTIMIZE TABLE tutorial.logs FINAL;

-- Теперь у партиций старше 90 дней sum(rows) = 0, у свежих — без изменений
SELECT partition, sum(rows) FROM system.parts
WHERE table = 'logs' AND active GROUP BY partition ORDER BY partition;

-- Перемещение старых данных на медленный диск
-- TTL event_date + INTERVAL 30 DAY TO DISK 'cold'

-- Добавить/изменить TTL на существующую таблицу
ALTER TABLE tutorial.logs
    MODIFY TTL event_date + INTERVAL 180 DAY;
```

> **Не вешай TTL на `page_views`.** Данные курса сгенерированы за `2026-01-01 .. 2026-03-31`, и любой TTL, отсчитываемый от `today()`, снесёт часть из них — молча и в фоне, за десяток секунд после `ALTER`. Проверить, что попадёт под нож, до выполнения: `SELECT count() FROM tutorial.page_views WHERE event_date < today() - 180`. Снять TTL обратно можно (`ALTER TABLE ... REMOVE TTL`), а удалённые строки — нет.

## Пользователи и права

Управление доступами из SQL по умолчанию выключено: у пользователя из `CLICKHOUSE_USER` нет права `ACCESS MANAGEMENT`, и первый же `CREATE USER` падает с `Code: 497. DB::Exception: default: Not enough privileges ... (ACCESS_DENIED)`. Включается переменной окружения в `compose.yml` (она уже там есть):

```yaml
environment:
  - CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1
```

Проверить свои права: `SHOW GRANTS FOR default`.

```sql
-- Создать пользователя
CREATE USER analyst IDENTIFIED BY 'strong_password';

-- Дать доступ на чтение
GRANT SELECT ON tutorial.* TO analyst;

-- Readonly пользователь для Grafana
CREATE USER grafana IDENTIFIED BY 'grafana_password';
GRANT SELECT ON tutorial.* TO grafana;

-- Создать роль
CREATE ROLE analytics_reader;
GRANT SELECT ON tutorial.* TO analytics_reader;
GRANT analytics_reader TO analyst;

-- Проверить права
SHOW GRANTS FOR analyst;
```

## Production чек-лист

### Настройки сервера

```xml
<!-- /etc/clickhouse-server/config.d/production.xml -->
<clickhouse>
    <!-- Ограничения памяти -->
    <max_server_memory_usage_to_ram_ratio>0.8</max_server_memory_usage_to_ram_ratio>

    <!-- Логирование медленных запросов -->
    <query_log>
        <database>system</database>
        <table>query_log</table>
    </query_log>
</clickhouse>
```

### Профили для пользователей

```xml
<!-- /etc/clickhouse-server/users.d/profiles.xml -->
<clickhouse>
    <profiles>
        <dashboard>
            <max_execution_time>30</max_execution_time>
            <max_memory_usage>5000000000</max_memory_usage>
            <max_rows_to_read>500000000</max_rows_to_read>
        </dashboard>
    </profiles>
</clickhouse>
```

## Типичная архитектура

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Spring Boot│     │  Spring Boot │     │   Grafana        │
│  App (OLTP) │     │  Analytics   │     │   Dashboards     │
│             │     │  Service     │     │                  │
└──────┬──────┘     └──────┬───────┘     └────────┬─────────┘
       │                   │                      │
       │                   │ JDBC                 │ ClickHouse
       │                   │                      │ plugin
       ▼                   ▼                      ▼
┌──────────────┐    ┌──────────────────────────────────────┐
│  PostgreSQL  │    │           ClickHouse                 │
│  (OLTP)      │    │  ┌──────────────────────────────┐   │
│  - users     │    │  │ raw_events (MergeTree)        │   │
│  - orders    │    │  │     │                         │   │
│  - products  │    │  │     ├─► MV → daily_stats      │   │
│              │    │  │     └─► MV → hourly_metrics   │   │
│              │    │  │                               │   │
│              │    │  │ Dictionary ← PostgreSQL users │   │
│              │    │  └──────────────────────────────┘   │
└──────────────┘    └──────────────────────────────────────┘
       │                          ▲
       │      CDC / Batch ETL     │
       └──────────────────────────┘
```

### Поток данных

1. **OLTP-приложение** записывает в PostgreSQL (пользователи, заказы)
2. **Analytics Service** собирает события и пишет батчами в ClickHouse
3. **CDC/ETL** синхронизирует справочники из PostgreSQL в ClickHouse (словари)
4. **Materialized Views** предагрегируют данные при вставке
5. **Grafana** читает из предагрегированных таблиц — быстрые дашборды
6. **TTL** автоматически удаляет старые сырые данные

## Практика

1. Добавить Grafana в `compose.yml`, запустить
2. Подключить ClickHouse как DataSource
3. Создать дашборд с 4 панелями: временной ряд, таблица, pie chart, stat
4. Создать таблицу `logs` с TTL и убедиться по `system.parts`, что старые партиции исчезают (на `page_views` TTL не вешать — снесёт данные курса)
5. Создать readonly-пользователя для Grafana
6. Проверить `system.query_log` — найти медленные запросы

## Итоги урока

- Grafana + ClickHouse — стандартная связка для аналитических дашбордов
- Используй `$__fromTime` / `$__toTime` для привязки к time picker
- `system.processes`, `system.parts`, `system.merges` — мониторинг
- BACKUP/RESTORE — встроенный механизм бэкапов
- TTL — автоматическое удаление/перемещение старых данных
- Создавай отдельных пользователей с минимальными правами
- PostgreSQL (OLTP) + ClickHouse (OLAP) — типичная production-архитектура
