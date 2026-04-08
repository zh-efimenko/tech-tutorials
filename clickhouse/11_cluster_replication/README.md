# Урок 11. Кластер ClickHouse: репликация, миграции и интеграция со Spring Boot

## Зачем кластер

Standalone ClickHouse подходит для разработки, но в production нужна отказоустойчивость. Кластер обеспечивает:

- **Репликацию** — данные дублируются на нескольких нодах, потеря одной ноды не приводит к потере данных
- **Высокую доступность** — приложение продолжает работать при падении реплики
- **Консистентность миграций** — DDL-операции (`CREATE TABLE`, `ALTER`) применяются ко всем нодам одновременно

В этом уроке мы настроим кластер из 3 нод, научимся создавать реплицированные таблицы, настроим Flyway-миграции и интеграцию через Spring Boot + Gradle.

## Архитектура кластера

```
                    ┌─────────────────────────────────────────┐
                    │          tutorial_cluster                │
                    │                                         │
                    │   ┌───────────┐  ┌───────────┐  ┌───────────┐
                    │   │  Node 1   │  │  Node 2   │  │  Node 3   │
                    │   │           │  │           │  │           │
                    │   │ Replica   │  │ Replica   │  │ Replica   │
                    │   │ + Keeper  │  │ + Keeper  │  │ + Keeper  │
                    │   │           │  │           │  │           │
                    │   │ :8123 HTTP│  │ :8123 HTTP│  │ :8123 HTTP│
                    │   │ :9000 TCP │  │ :9000 TCP │  │ :9000 TCP │
                    │   │ :9181 Keep│  │ :9181 Keep│  │ :9181 Keep│
                    │   └───────────┘  └───────────┘  └───────────┘
                    │         │              │              │       │
                    │         └──────────────┼──────────────┘       │
                    │                        │                     │
                    │              ┌─────────────────┐             │
                    │              │ ClickHouse Keeper│             │
                    │              │  (Raft consensus)│             │
                    │              └─────────────────┘             │
                    └─────────────────────────────────────────────┘
                                         ▲
                                         │ JDBC
                                  ┌──────────────┐
                                  │  Spring Boot  │
                                  │  Application  │
                                  └──────────────┘
```

### Ключевые понятия

| Понятие | Описание |
|---------|----------|
| **Shard (шард)** | Логическая группа, хранящая подмножество данных. В нашем случае — один шард |
| **Replica (реплика)** | Нода внутри шарда, хранящая полную копию данных |
| **ClickHouse Keeper** | Координационный сервис (замена ZooKeeper), управляет репликацией через Raft-консенсус |
| **ON CLUSTER** | DDL-директива, применяющая операцию ко всем нодам кластера |
| **ReplicatedMergeTree** | Движок таблиц с автоматической репликацией данных между нодами |
| **Macros** | Переменные (`{shard}`, `{replica}`), подставляемые автоматически на каждой ноде |

### Один шард vs. несколько шардов

```
 Один шард, 3 реплики:                 Два шарда, по 2 реплики:
 ┌──────────────────────────┐           ┌─────────────┐ ┌─────────────┐
 │        Shard 01          │           │  Shard 01   │ │  Shard 02   │
 │  ┌────┐ ┌────┐ ┌────┐   │           │ ┌──┐ ┌──┐  │ │ ┌──┐ ┌──┐  │
 │  │ R1 │ │ R2 │ │ R3 │   │           │ │R1│ │R2│  │ │ │R1│ │R2│  │
 │  │100%│ │100%│ │100%│   │           │ │50│ │50│  │ │ │50│ │50│  │
 │  └────┘ └────┘ └────┘   │           │ └──┘ └──┘  │ │ └──┘ └──┘  │
 └──────────────────────────┘           └─────────────┘ └─────────────┘
 Каждая нода = полная копия            Данные разделены между шардами
 + Простота, отказоустойчивость         + Горизонтальное масштабирование
 - Не масштабирует объём данных         - Сложнее конфигурация
```

Для аналитических сервисов с умеренным объёмом (до десятков ТБ) один шард с 3 репликами — оптимальный выбор. Именно эту схему мы будем использовать.

## Конфигурация кластера (XML)

### remote_servers — определение кластера

Файл `clickhouse-cluster.xml` описывает топологию:

```xml
<clickhouse>
    <remote_servers>
        <tutorial_cluster>  <!-- имя кластера, используется в ON CLUSTER -->
            <shard>
                <replica>
                    <host>clickhouse-node-1</host>
                    <port>9000</port>  <!-- native TCP-порт -->
                </replica>
                <replica>
                    <host>clickhouse-node-2</host>
                    <port>9000</port>
                </replica>
                <replica>
                    <host>clickhouse-node-3</host>
                    <port>9000</port>
                </replica>
            </shard>
        </tutorial_cluster>
    </remote_servers>
</clickhouse>
```

**Правила:**
- Имя кластера (`tutorial_cluster`) — произвольное, но должно совпадать с тем, что передаётся в `ON CLUSTER`
- Все реплики внутри одного `<shard>` хранят одинаковые данные
- Порт `9000` — native TCP, не путать с `8123` (HTTP)

### ClickHouse Keeper — координация

Keeper встроен в ClickHouse и заменяет внешний ZooKeeper. Он обеспечивает:
- Лидер-выборы при репликации
- Хранение метаданных о частях данных (parts)
- Координацию DDL-операций (`ON CLUSTER`)

```xml
<clickhouse>
    <keeper_server>
        <tcp_port>9181</tcp_port>
        <server_id from_env="KEEPER_SERVER_ID"/>  <!-- уникальный ID из env -->
        <log_storage_path>/var/lib/clickhouse/coordination/log</log_storage_path>
        <snapshot_storage_path>/var/lib/clickhouse/coordination/snapshots</snapshot_storage_path>
        <coordination_settings>
            <operation_timeout_ms>10000</operation_timeout_ms>
            <session_timeout_ms>30000</session_timeout_ms>
        </coordination_settings>
        <raft_configuration>
            <server>
                <id>1</id>
                <hostname>clickhouse-node-1</hostname>
                <port>9234</port>  <!-- Raft-порт для межнодовой коммуникации -->
            </server>
            <server>
                <id>2</id>
                <hostname>clickhouse-node-2</hostname>
                <port>9234</port>
            </server>
            <server>
                <id>3</id>
                <hostname>clickhouse-node-3</hostname>
                <port>9234</port>
            </server>
        </raft_configuration>
    </keeper_server>
</clickhouse>
```

**Важно:**
- `server_id` задаётся через переменную окружения `KEEPER_SERVER_ID` — уникален для каждой ноды (1, 2, 3)
- Raft требует нечётное число нод (3, 5, 7) для кворума
- Порт `9234` — внутренний порт Raft-протокола, не открывается наружу

### Подключение к Keeper (zookeeper-секция)

В том же `clickhouse-cluster.xml` указывается, куда подключаться за координацией:

```xml
<clickhouse>
    <zookeeper>
        <node>
            <host>clickhouse-node-1</host>
            <port>9181</port>
        </node>
        <node>
            <host>clickhouse-node-2</host>
            <port>9181</port>
        </node>
        <node>
            <host>clickhouse-node-3</host>
            <port>9181</port>
        </node>
    </zookeeper>

    <macros>
        <shard>01</shard>
        <replica from_env="CLICKHOUSE_REPLICA_NAME"/>
    </macros>
</clickhouse>
```

**Секция `<macros>`** определяет переменные, доступные в DDL:
- `{shard}` — номер шарда (одинаковый для всех нод при одном шарде)
- `{replica}` — имя реплики из env `CLICKHOUSE_REPLICA_NAME`, уникальное для каждой ноды

> Секция называется `zookeeper`, но ClickHouse Keeper полностью совместим с ZooKeeper-протоколом.

## Docker Compose: поднимаем кластер

```yaml
services:
  clickhouse-node-1:
    image: clickhouse/clickhouse-server:25.8.8.26
    hostname: clickhouse-node-1
    environment:
      CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT: 1
      CLICKHOUSE_DB: tutorial
      CLICKHOUSE_USER: default
      CLICKHOUSE_PASSWORD: clickhouse
      CLICKHOUSE_REPLICA_NAME: clickhouse-node-1   # уникальное имя реплики
      KEEPER_SERVER_ID: 1                           # уникальный ID в Raft
    volumes:
      - ./etc/docker/clickhouse/clickhouse-cluster.xml:/etc/clickhouse-server/config.d/cluster.xml
      - ./etc/docker/clickhouse/clickhouse-keeper.xml:/etc/clickhouse-server/config.d/keeper.xml
    ports:
      - "8123:8123"    # HTTP-интерфейс наружу
    healthcheck:
      test: ["CMD-SHELL", "clickhouse-client --query 'SELECT 1'"]
      interval: 5s
      timeout: 3s
      retries: 10

  clickhouse-node-2:
    image: clickhouse/clickhouse-server:25.8.8.26
    hostname: clickhouse-node-2
    environment:
      CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT: 1
      CLICKHOUSE_DB: tutorial
      CLICKHOUSE_USER: default
      CLICKHOUSE_PASSWORD: clickhouse
      CLICKHOUSE_REPLICA_NAME: clickhouse-node-2
      KEEPER_SERVER_ID: 2
    volumes:
      - ./etc/docker/clickhouse/clickhouse-cluster.xml:/etc/clickhouse-server/config.d/cluster.xml
      - ./etc/docker/clickhouse/clickhouse-keeper.xml:/etc/clickhouse-server/config.d/keeper.xml
    ports:
      - "8124:8123"
    healthcheck:
      test: ["CMD-SHELL", "clickhouse-client --query 'SELECT 1'"]
      interval: 5s
      timeout: 3s
      retries: 10
    labels:
      org.springframework.boot.ignore: true  # Spring Boot DevTools не управляет этим контейнером

  clickhouse-node-3:
    image: clickhouse/clickhouse-server:25.8.8.26
    hostname: clickhouse-node-3
    environment:
      CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT: 1
      CLICKHOUSE_DB: tutorial
      CLICKHOUSE_USER: default
      CLICKHOUSE_PASSWORD: clickhouse
      CLICKHOUSE_REPLICA_NAME: clickhouse-node-3
      KEEPER_SERVER_ID: 3
    volumes:
      - ./etc/docker/clickhouse/clickhouse-cluster.xml:/etc/clickhouse-server/config.d/cluster.xml
      - ./etc/docker/clickhouse/clickhouse-keeper.xml:/etc/clickhouse-server/config.d/keeper.xml
    ports:
      - "8125:8123"
    healthcheck:
      test: ["CMD-SHELL", "clickhouse-client --query 'SELECT 1'"]
      interval: 5s
      timeout: 3s
      retries: 10
    labels:
      org.springframework.boot.ignore: true
```

**Нюансы:**
- Все ноды используют одни и те же XML-конфигурации, но различаются через env (`KEEPER_SERVER_ID`, `CLICKHOUSE_REPLICA_NAME`)
- Лейбл `org.springframework.boot.ignore: true` на 2-й и 3-й нодах предотвращает их управление через Spring Boot Docker Compose Support — приложение подключается только к первой ноде
- HTTP-порты маппятся на разные хостовые порты: `8123`, `8124`, `8125`

## Реплицированные таблицы

### ReplicatedReplacingMergeTree

В кластере вместо обычного `MergeTree` используются `Replicated*`-движки. Переведём знакомую таблицу `page_views` из предыдущих уроков на реплицированный движок:

```sql
CREATE TABLE tutorial.page_views ON CLUSTER tutorial_cluster
(
    event_date Date,
    event_time DateTime,
    user_id    UInt64,
    page_url   String,
    duration   UInt32,
    country    LowCardinality(String),
    device     LowCardinality(String),
    updated_at DateTime DEFAULT now()
) ENGINE = ReplicatedReplacingMergeTree(updated_at)
      PARTITION BY toYYYYMM(event_date)
      ORDER BY (user_id, event_time);
```

### Разбор ключевых элементов

| Элемент | Значение |
|---------|----------|
| `ON CLUSTER tutorial_cluster` | DDL выполняется на всех нодах кластера одновременно |
| `ReplicatedReplacingMergeTree(updated_at)` | Данные реплицируются + дедупликация по `updated_at` при merge |
| `PARTITION BY toYYYYMM(event_date)` | Партиционирование по месяцам — ускоряет запросы с фильтром по дате |
| `ORDER BY (user_id, event_time)` | Сортировочный ключ — определяет порядок хранения и первичный индекс |
| `LowCardinality(String)` | Оптимизация для строк с малым количеством уникальных значений (enum-подобные) |

### Сравнение с standalone-версией

В уроке 2 мы создавали `page_views` так:

```sql
-- Standalone (один сервер)
CREATE TABLE tutorial.page_views
(
    ...
) ENGINE = MergeTree()
      PARTITION BY toYYYYMM(event_date)
      ORDER BY (user_id, event_time);

-- Кластер (3 реплики)
CREATE TABLE tutorial.page_views ON CLUSTER tutorial_cluster
(
    ...
) ENGINE = ReplicatedReplacingMergeTree(updated_at)
      PARTITION BY toYYYYMM(event_date)
      ORDER BY (user_id, event_time);
```

Отличия:
1. Добавлен `ON CLUSTER tutorial_cluster` — таблица создаётся на всех нодах
2. `MergeTree` → `ReplicatedReplacingMergeTree` — данные реплицируются и дедуплицируются
3. Добавлена колонка `updated_at` — используется как версия для `Replacing`-логики

### Пути реплик в Keeper

`ReplicatedReplacingMergeTree` автоматически использует макросы `{shard}` и `{replica}` для формирования уникальных путей в Keeper:

```
/clickhouse/tables/{shard}/tutorial.page_views          -- путь к метаданным таблицы
/clickhouse/tables/{shard}/tutorial.page_views/{replica} -- путь к конкретной реплике
```

Благодаря `<macros>` в конфигурации, каждая нода подставляет свои значения, и конфликтов не возникает.

### Другие таблицы кластера

```sql
-- Таблица пользователей (справочник)
CREATE TABLE tutorial.users ON CLUSTER tutorial_cluster
(
    id         UInt64,
    name       String,
    email      String,
    country    LowCardinality(String),
    updated_at DateTime DEFAULT now()
) ENGINE = ReplicatedReplacingMergeTree(updated_at)
      ORDER BY id;

-- Таблица стран (справочник)
CREATE TABLE tutorial.countries ON CLUSTER tutorial_cluster
(
    code       String,
    name       String,
    region     LowCardinality(String),
    updated_at DateTime DEFAULT now()
) ENGINE = ReplicatedReplacingMergeTree(updated_at)
      ORDER BY code;
```

**Паттерн:** все таблицы используют `ReplicatedReplacingMergeTree` с колонкой `updated_at` — при merge ClickHouse оставляет строку с наибольшим значением `updated_at`, что обеспечивает идемпотентность обновлений.

## Миграции Flyway для кластера

### Проблема

Flyway по умолчанию не знает о кластере ClickHouse. Если запустить миграцию на одной ноде, остальные ноды не получат таблицу `flyway_schema_history`, и миграции будут несогласованными.

### Решение: flyway-database-clickhouse

Плагин `flyway-database-clickhouse` решает эту проблему:

1. Таблица `flyway_schema_history` создаётся как `ReplicatedMergeTree` и реплицируется на все ноды
2. DDL-операции в миграциях выполняются с `ON CLUSTER` через placeholder

### Настройка Flyway в gradle.properties

```properties
# Flyway подключение для CLI-миграций (gradle flywayMigrate)
flyway.url=jdbc:clickhouse://localhost:8123/tutorial?jdbc_ignore_unsupported_values=true
flyway.user=default
flyway.password=clickhouse
flyway.outOfOrder=true
flyway.validateOnMigrate=false

# Кластерные настройки
# Имя кластера для таблицы flyway_schema_history (реплицируется на все ноды)
flyway.clickhouse.clusterName=tutorial_cluster
# Placeholder для использования в SQL-миграциях
flyway.placeholders.clickhouse_cluster_name=tutorial_cluster
```

**Два разных параметра с одним значением:**
- `flyway.clickhouse.clusterName` — указывает плагину создать `flyway_schema_history` как реплицированную таблицу на кластере
- `flyway.placeholders.clickhouse_cluster_name` — placeholder `${clickhouse_cluster_name}`, подставляемый в SQL-миграции

### Настройка Flyway в application.yml

```yaml
spring:
  flyway:
    out-of-order: true
    validate-migration-naming: true
    placeholders:
      clickhouse_cluster_name: ${CLICKHOUSE_CLUSTER_NAME:tutorial_cluster}
```

Placeholder `${clickhouse_cluster_name}` используется в миграциях:

```sql
CREATE TABLE tutorial.page_views ON CLUSTER ${clickhouse_cluster_name}
(
    ...
) ENGINE = ReplicatedReplacingMergeTree(updated_at)
      ...
```

### FlywayConfig — программная настройка clusterName

Spring Boot не поддерживает `flyway.clickhouse.clusterName` напрямую. Нужен кастомный бин:

```java
@Configuration
public class FlywayConfig {

    @Bean
    FlywayConfigurationCustomizer clickHouseClusterCustomizer(
        @Value("${CLICKHOUSE_CLUSTER_NAME:tutorial_cluster}") String clusterName
    ) {
        return configuration -> configuration.configuration(Map.of(
            "flyway.clickhouse.clusterName", clusterName
        ));
    }
}
```

**Почему это важно:** без этой настройки `flyway_schema_history` будет обычной таблицей на одной ноде. Если приложение переключится на другую реплику (failover), Flyway не увидит историю миграций и попытается их выполнить повторно.

### Именование миграций

```
V20260401_1__page_views_table.sql
V20260401_2__users_table.sql
V20260401_3__countries_table.sql
```

Паттерн: `V{YYYYMMDD}_{порядковый_номер}__{описание}.sql`
- `out-of-order: true` — позволяет накладывать миграции не строго по порядку (удобно при параллельной разработке)
- `validate-migration-naming: true` — строго проверяет формат имени файла

## Настройка Gradle (build.gradle)

### Buildscript — зависимость для плагина Flyway

```groovy
buildscript {
    dependencies {
        // Flyway-плагин не содержит ClickHouse-драйвер —
        // нужно добавить его в classpath самого плагина
        classpath "org.flywaydb:flyway-database-clickhouse:$flyway_database_clickhouse_version"
    }
}
```

**Почему `buildscript`?** Gradle-плагин `flyway` запускается в compile-time, а не в runtime приложения. Ему нужен свой собственный classpath с ClickHouse-драйвером.

### Dependencies — зависимости приложения

```groovy
dependencies {
    // Spring Boot JDBC (JdbcTemplate, DataSource auto-configuration)
    implementation "org.springframework.boot:spring-boot-starter-jdbc"

    // ClickHouse JDBC Driver
    implementation("com.clickhouse:clickhouse-jdbc:$clickhouse_jdbc_version") {
        // lz4 конфликтует с версией внутри spring-kafka —
        // исключаем, чтобы использовать версию из Kafka
        exclude group: "at.yawk.lz4", module: "lz4-java"
    }

    // Flyway Core (миграции при старте приложения)
    implementation "org.flywaydb:flyway-core"
    // ClickHouse-адаптер для Flyway (только runtime — не нужен при компиляции)
    runtimeOnly "org.flywaydb:flyway-database-clickhouse:$flyway_database_clickhouse_version"
}
```

### Версии в gradle.properties

```properties
flyway_database_clickhouse_version=10.24.0
clickhouse_jdbc_version=0.9.8
```

**Нюанс с lz4:** библиотека `lz4-java` поставляется и с ClickHouse JDBC, и со Spring Kafka. Разные версии конфликтуют — исключаем из ClickHouse-драйвера, чтобы использовать совместимую версию из Kafka.

## Конфигурация Spring Boot DataSource

### application.yml

```yaml
spring:
  datasource:
    driver-class-name: com.clickhouse.jdbc.ClickHouseDriver
    url: jdbc:clickhouse://${CLICKHOUSE_DB_HOST}:${CLICKHOUSE_DB_PORT}/${CLICKHOUSE_DB_NAME}
    username: ${CLICKHOUSE_DB_USER}
    password: ${CLICKHOUSE_DB_PASS}
```

### application-local.yml (для разработки)

```yaml
spring:
  datasource:
    driver-class-name: com.clickhouse.jdbc.ClickHouseDriver
    url: jdbc:clickhouse://localhost:8123/tutorial
    username: default
    password: clickhouse
  docker:
    compose:
      enabled: true
      lifecycle-management: start_only
```

**Паттерн подключения к кластеру:**
- Приложение подключается к **одной** ноде кластера (не ко всем сразу)
- В production балансировка между нодами делается через LoadBalancer или DNS
- В dev — подключаемся к первой ноде (`localhost:8123`)
- `lifecycle-management: start_only` — Spring Boot запускает Docker Compose, но не останавливает при shutdown

### JDBC URL параметры

| Параметр | Описание |
|----------|----------|
| `jdbc:clickhouse://host:port/db` | Стандартный формат подключения |
| `?jdbc_ignore_unsupported_values=true` | Игнорирует неподдерживаемые JDBC-операции (полезно для Flyway) |
| `?socket_timeout=300000` | Таймаут сокета в мс (для долгих запросов) |
| `?compress=true` | Сжатие трафика между клиентом и сервером |

## Проверка здоровья кластера

### Системные запросы

```sql
-- Проверить, что кластер виден
SELECT * FROM system.clusters WHERE cluster = 'tutorial_cluster';

-- Статус реплик (выполнить на каждой ноде)
SELECT
    database,
    table,
    replica_name,
    is_leader,
    total_replicas,
    active_replicas,
    queue_size,
    inserts_in_queue,
    merges_in_queue
FROM system.replicas
WHERE database = 'tutorial'
FORMAT Vertical;

-- Задержка репликации
SELECT
    database,
    table,
    replica_name,
    absolute_delay
FROM system.replicas
WHERE database = 'tutorial' AND absolute_delay > 0;

-- Статус ClickHouse Keeper
SELECT * FROM system.zookeeper WHERE path = '/clickhouse';
```

### Ключевые метрики

| Метрика | Норма | Проблема |
|---------|-------|----------|
| `active_replicas` | = `total_replicas` | Есть недоступные реплики |
| `queue_size` | 0 | Накапливается очередь операций |
| `absolute_delay` | 0 | Реплика отстаёт от лидера |
| `is_leader` | Ровно 1 на таблицу | Нет лидера = нет записи |

## Типичные ошибки и решения

### 1. «Table already exists» при миграции

**Причина:** `ON CLUSTER` не использовался, таблица создана только на одной ноде.

**Решение:** всегда использовать `ON CLUSTER ${clickhouse_cluster_name}` в миграциях.

### 2. Flyway повторно запускает миграции после failover

**Причина:** `flyway_schema_history` не реплицирована.

**Решение:** настроить `flyway.clickhouse.clusterName` через `FlywayConfig` бин.

### 3. «Replica already exists» при создании таблицы

**Причина:** макрос `{replica}` возвращает одинаковое значение на разных нодах.

**Решение:** убедиться, что `CLICKHOUSE_REPLICA_NAME` уникален для каждой ноды в Docker Compose.

### 4. Конфликт версий lz4

**Причина:** `clickhouse-jdbc` и `spring-kafka` тянут разные версии lz4.

**Решение:** исключить lz4 из ClickHouse-зависимости:
```groovy
implementation("com.clickhouse:clickhouse-jdbc:$clickhouse_jdbc_version") {
    exclude group: "at.yawk.lz4", module: "lz4-java"
}
```

### 5. Данные видны на одной ноде, но не на другой

**Причина:** запись шла без `ON CLUSTER`, или реплика отстала.

**Решение:** проверить `system.replicas` на задержку, и использовать `SYSTEM SYNC REPLICA table_name` для принудительной синхронизации.

## Практика

1. Поднять кластер из 3 нод через `docker compose up -d`
2. Подключиться к каждой ноде и проверить кластер:
   ```bash
   docker exec -it clickhouse-node-1 clickhouse-client \
       --user default --password clickhouse \
       --query "SELECT * FROM system.clusters WHERE cluster = 'tutorial_cluster'"
   ```
3. Создать реплицированную таблицу `page_views`:
   ```sql
   CREATE TABLE tutorial.page_views ON CLUSTER tutorial_cluster
   (
       event_date Date,
       event_time DateTime,
       user_id    UInt64,
       page_url   String,
       duration   UInt32,
       country    LowCardinality(String),
       device     LowCardinality(String),
       updated_at DateTime DEFAULT now()
   ) ENGINE = ReplicatedReplacingMergeTree(updated_at)
         PARTITION BY toYYYYMM(event_date)
         ORDER BY (user_id, event_time);
   ```
4. Вставить данные на ноде 1, проверить появление на нодах 2 и 3
5. Остановить ноду 2, вставить данные, поднять ноду 2 — убедиться, что данные подтянулись
6. Написать Flyway-миграцию с placeholder `${clickhouse_cluster_name}` и запустить через `gradle flywayMigrate`
7. Настроить Spring Boot приложение с `FlywayConfig` и `application.yml` для кластера

## Итоги урока

- Кластер ClickHouse = `remote_servers` (топология) + `keeper_server` (координация) + `macros` (подстановки)
- `ON CLUSTER` — DDL применяется ко всем нодам; без него таблица создаётся только локально
- `ReplicatedReplacingMergeTree` — стандартный движок для кластерных таблиц с дедупликацией
- Flyway в кластере: `flyway.clickhouse.clusterName` реплицирует `flyway_schema_history`
- Placeholders (`${clickhouse_cluster_name}`) — единственный правильный способ передать имя кластера в миграции
- `FlywayConfigurationCustomizer` — обязательный бин для программной настройки clusterName в Spring Boot
- Gradle: ClickHouse-драйвер нужен и в `buildscript` (для плагина Flyway), и в `dependencies` (для приложения)
- Исключение `lz4-java` из `clickhouse-jdbc` — стандартная практика при совместном использовании с Kafka
- Приложение подключается к одной ноде, балансировка — на уровне инфраструктуры