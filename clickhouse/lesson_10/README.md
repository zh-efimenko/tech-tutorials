# Урок 10. Дашборды и Production

## Grafana + ClickHouse

Grafana — стандартный инструмент для дашбордов поверх ClickHouse.

### Добавляем Grafana в compose.yml

```yaml
# Добавить в services в compose.yml
  grafana:
    image: grafana/grafana:11.6.0
    container_name: grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
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
3. Выбрать **ClickHouse**
4. Server address: `clickhouse` (имя сервиса в Docker), порт: `9000`
5. Database: `tutorial`
6. Username: `default`, Password: `clickhouse`
7. Save & Test

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
    'MarkCacheBytes',
    'MarkCacheFiles'
);
```

## Бэкапы

### Встроенный механизм BACKUP/RESTORE

```sql
-- Бэкап таблицы на диск
BACKUP TABLE tutorial.page_views
TO Disk('backups', 'page_views_2026-04-05.zip');

-- Бэкап всей базы
BACKUP DATABASE tutorial
TO Disk('backups', 'tutorial_full_2026-04-05.zip');

-- Восстановление
RESTORE TABLE tutorial.page_views
FROM Disk('backups', 'page_views_2026-04-05.zip');
```

### Настройка диска для бэкапов

Добавить в конфигурацию ClickHouse (через volume в Docker):

```xml
<!-- /etc/clickhouse-server/config.d/backups.xml -->
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

### Бэкап через clickhouse-client

```bash
# Экспорт в файл (альтернативный подход)
docker exec clickhouse-local clickhouse-client \
    --user default --password clickhouse \
    --query="SELECT * FROM tutorial.page_views FORMAT Native" > backup.native

# Импорт из файла
docker exec -i clickhouse-local clickhouse-client \
    --user default --password clickhouse \
    --query="INSERT INTO tutorial.page_views FORMAT Native" < backup.native
```

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

-- Перемещение старых данных на медленный диск
-- TTL event_date + INTERVAL 30 DAY TO DISK 'cold'

-- Добавить/изменить TTL на существующую таблицу
ALTER TABLE tutorial.page_views
    MODIFY TTL event_date + INTERVAL 180 DAY;
```

## Пользователи и права

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
4. Настроить TTL на `page_views`
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
