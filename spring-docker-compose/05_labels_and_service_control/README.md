# Урок 5. Лейблы и управление сервисами

## Зачем нужны лейблы

Docker Compose позволяет добавлять произвольные метаданные к сервисам через `labels`. Spring Boot использует лейблы с префиксом `org.springframework.boot.*` для управления тем, как обрабатываются сервисы из compose-файла.

Лейблы решают задачи:
- Исключить сервис из автоконфигурации
- Переопределить параметры подключения
- Указать Spring Boot, как интерпретировать нестандартный образ

## org.springframework.boot.ignore

Самый часто используемый лейбл. Говорит Spring Boot полностью игнорировать сервис:

```yaml
services:
  hz_2:
    image: hazelcast/hazelcast:5.7
    ports:
      - "5702:5701"
    labels:
      org.springframework.boot.ignore: true
```

### Когда использовать

**Вспомогательные UI-сервисы.** Management Center, pgAdmin, RedisInsight — это инструменты для разработчика, Spring Boot не должен к ним подключаться:

```yaml
services:
  hazelcast-management:
    image: hazelcast/management-center:5.11.0
    ports:
      - "5700:8080"
    labels:
      org.springframework.boot.ignore: true

  pgadmin:
    image: dpage/pgadmin4:9.17
    ports:
      - "5050:80"
    environment:
      PGADMIN_DEFAULT_EMAIL: dev@example.com
      PGADMIN_DEFAULT_PASSWORD: dev
    labels:
      org.springframework.boot.ignore: true
```

**Внимание:** без `PGADMIN_DEFAULT_EMAIL` и `PGADMIN_DEFAULT_PASSWORD` контейнер pgAdmin падает на старте (`You need to define the PGADMIN_DEFAULT_EMAIL and PGADMIN_DEFAULT_PASSWORD ... environment variables.`). Приложение при этом не доходит до readiness-проверки, а падает раньше — на самой команде запуска: `ProcessExitException: 'docker compose ... up --no-color --detach --wait' failed with exit code 1`.

**Дублирующие ноды кластера.** Если в compose-файле два экземпляра Hazelcast для кластера, Spring Boot попытается подключиться к обоим. Помечаем вторую ноду как ignore — приложение подключается только к первой, а кластер формируется между нодами внутри Docker-сети:

```yaml
services:
  hz_1:
    image: hazelcast/hazelcast:5.7
    ports:
      - "5701:5701"
    environment:
      HZ_CLUSTERNAME: demo
      HZ_NETWORK_PUBLICADDRESS: hz_1:5701
      HZ_NETWORK_JOIN_AUTO-DETECTION_ENABLED: false
      HZ_NETWORK_JOIN_TCP-IP_ENABLED: true
      HZ_NETWORK_JOIN_TCP-IP_MEMBERS: hz_1:5701,hz_2:5701

  hz_2:
    image: hazelcast/hazelcast:5.7
    ports:
      - "5702:5701"
    environment:
      HZ_CLUSTERNAME: demo
      HZ_NETWORK_PUBLICADDRESS: hz_2:5701
      HZ_NETWORK_JOIN_AUTO-DETECTION_ENABLED: false
      HZ_NETWORK_JOIN_TCP-IP_ENABLED: true
      HZ_NETWORK_JOIN_TCP-IP_MEMBERS: hz_1:5701,hz_2:5701
    labels:
      # Приложение подключается только к hz_1
      # hz_2 существует для формирования кластера
      org.springframework.boot.ignore: true
```

**Про переменные Hazelcast.** Набор из четырёх переменных — не единственный рабочий, но самый предсказуемый. Что делает каждая:

| Конфигурация | Что происходит |
|---|---|
| Только `HZ_CLUSTERNAME` (+ `..._TCP-IP_MEMBERS` или без него) | Ноды находят друг друга механизмом по умолчанию: `Using Multicast discovery`. В Docker-сети это работает, `hz-healthcheck` даёт `"clusterSize":2`. Список членов при этом принимается (`Detected external configuration entries ... hazelcast.network.join.tcp-ip.members=...`), но не используется |
| `..._AUTO-DETECTION_ENABLED: false` + `..._TCP-IP_ENABLED: true`, **без** `HZ_NETWORK_PUBLICADDRESS` | Discovery переключается (`Using TCP/IP discovery`), но обе ноды объявляют себя как `[127.0.0.1]:5701` и пытаются присоединиться сами к себе: `ERROR JoinMastershipClaimOp: Target is this node! -> [127.0.0.1]:5701`, `"clusterSize":1` на каждой |
| Все четыре переменные | `Using TCP/IP discovery`, `"clusterSize":2` |

Вывод: если включаешь TCP-IP явно, `HZ_NETWORK_PUBLICADDRESS` обязателен. Он же определяет, по какому адресу клиент из урока 6 будет искать вторую ноду.

**Сервисы, которые не должны блокировать старт.** Нераспознанный образ сам по себе ничего не ломает: ConnectionDetails для него просто не создаются, и предупреждения в логах нет. Но readiness-проверка на такой сервис распространяется — Spring Boot ждёт, пока откроются все его пробрасываемые порты, и падает по таймауту, если этого не происходит. Лейбл ignore исключает сервис из обработки целиком, вместе с проверкой готовности:

```yaml
services:
  custom-service:
    image: my-company/custom-tool:latest
    labels:
      org.springframework.boot.ignore: true
```

## org.springframework.boot.service-connection

Этот лейбл указывает Spring Boot, какой тип ConnectionDetails создать для сервиса. Полезно, когда используется нестандартный образ, который Spring Boot не распознаёт автоматически.

```yaml
services:
  my-postgres:
    image: myregistry.io/custom-postgres:18
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD: myapp
    labels:
      org.springframework.boot.service-connection: postgres
```

Без этого лейбла Spring Boot не знает, что `myregistry.io/custom-postgres:18` — это PostgreSQL. С лейблом он обработает сервис как стандартный PostgreSQL.

### Доступные значения service-connection

Значение лейбла — это **имя образа, которое ждёт фабрика**, а не произвольное имя технологии. Значения для Spring Boot 4.1:

| Значение | ConnectionDetails |
|----------|-------------------|
| `postgres` | JdbcConnectionDetails / R2dbcConnectionDetails |
| `mysql`, `mariadb`, `mssql/server` | JdbcConnectionDetails / R2dbcConnectionDetails |
| `clickhouse/clickhouse-server` | JdbcConnectionDetails / R2dbcConnectionDetails |
| `gvenzl/oracle-free`, `gvenzl/oracle-xe` | JdbcConnectionDetails / R2dbcConnectionDetails |
| `mongo` | MongoConnectionDetails |
| `redis` | DataRedisConnectionDetails |
| `rabbitmq` | RabbitConnectionDetails |
| `elasticsearch` | ElasticsearchConnectionDetails |
| `cassandra` | CassandraConnectionDetails |
| `neo4j` | Neo4jConnectionDetails |
| `hazelcast/hazelcast` | HazelcastConnectionDetails |
| `apachepulsar/pulsar` | PulsarConnectionDetails |
| `openzipkin/zipkin` | ZipkinConnectionDetails |

**Важно:** значения `kafka` в этом списке нет — Docker Compose интеграция Kafka не поддерживает (урок 4). Лейбл на Kafka-сервисе ничего не даст, bootstrap-servers указываются вручную.

## org.springframework.boot.readiness-check.tcp.disable

Отключает TCP-проверку готовности для сервиса. Spring Boot по умолчанию проверяет доступность порта перед тем, как считать сервис готовым. Если сервис не пробрасывает порты или проверка мешает:

```yaml
services:
  worker:
    image: my-worker:latest
    labels:
      org.springframework.boot.readiness-check.tcp.disable: true
```

## Комбинирование лейблов

Лейблы можно комбинировать. Например, нестандартный образ PostgreSQL с отключённой проверкой готовности:

```yaml
services:
  db:
    image: myregistry.io/postgres-with-extensions:18
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD: myapp
    labels:
      org.springframework.boot.service-connection: postgres
      org.springframework.boot.readiness-check.tcp.disable: true
```

## Пример из практики: полный compose с лейблами

```yaml
services:
  # Основная база — Spring Boot подключается автоматически
  db:
    image: postgres:18.4
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD: myapp

  # Кеш — Spring Boot подключается автоматически
  redis:
    image: redis:8.10
    ports:
      - "6379:6379"

  # Кастомный образ Elasticsearch — указываем тип подключения явно
  search:
    image: myregistry.io/elastic-with-plugins:9.2.0
    ports:
      - "9200:9200"
    labels:
      org.springframework.boot.service-connection: elasticsearch

  # Hazelcast нода 1 — Spring Boot подключается
  hz_1:
    image: hazelcast/hazelcast:5.7
    ports:
      - "5701:5701"
    environment:
      HZ_CLUSTERNAME: demo
      HZ_NETWORK_PUBLICADDRESS: hz_1:5701
      HZ_NETWORK_JOIN_AUTO-DETECTION_ENABLED: false
      HZ_NETWORK_JOIN_TCP-IP_ENABLED: true
      HZ_NETWORK_JOIN_TCP-IP_MEMBERS: hz_1:5701,hz_2:5701

  # Hazelcast нода 2 — только для кластера, Spring Boot игнорирует
  hz_2:
    image: hazelcast/hazelcast:5.7
    ports:
      - "5702:5701"
    environment:
      HZ_CLUSTERNAME: demo
      HZ_NETWORK_PUBLICADDRESS: hz_2:5701
      HZ_NETWORK_JOIN_AUTO-DETECTION_ENABLED: false
      HZ_NETWORK_JOIN_TCP-IP_ENABLED: true
      HZ_NETWORK_JOIN_TCP-IP_MEMBERS: hz_1:5701,hz_2:5701
    labels:
      org.springframework.boot.ignore: true

  # UI-инструменты — Spring Boot игнорирует
  pgadmin:
    image: dpage/pgadmin4:9.17
    ports:
      - "5050:80"
    environment:
      PGADMIN_DEFAULT_EMAIL: dev@example.com
      PGADMIN_DEFAULT_PASSWORD: dev
    labels:
      org.springframework.boot.ignore: true

  hazelcast-management:
    image: hazelcast/management-center:5.11.0
    ports:
      - "5700:8080"
    labels:
      org.springframework.boot.ignore: true
```

## Практика

1. Добавь pgAdmin в compose.yaml без лейбла ignore (обязательно с `PGADMIN_DEFAULT_EMAIL` и `PGADMIN_DEFAULT_PASSWORD`, иначе контейнер умрёт на старте). Включи `logging.level.org.springframework.boot.docker.compose: TRACE` и найди в логе `Checking readiness of service 'pgadmin'` → `Service 'pgadmin' is ready`. Строки `Container ... Waiting/Healthy` для этой проверки не показатель — их печатает `up --wait` для любого сервиса
2. Добавь лейбл `org.springframework.boot.ignore: true` к pgAdmin — строки `Checking readiness of service 'pgadmin'` исчезнут: сервис больше не участвует в readiness-проверке Spring Boot
3. Создай второй PostgreSQL-сервис в compose (для аналитики). Пометь его лейблом ignore, чтобы Spring Boot подключался только к основной базе
4. Замени образ PostgreSQL на нестандартный (например, `pgvector/pgvector:pg18` — образ на базе PostgreSQL, но с другим именем). Убедись, что Spring Boot не распознаёт его и приложение падает без DataSource. Добавь лейбл `service-connection: postgres` — подключение должно заработать
5. Добавь два экземпляра Hazelcast (со всеми четырьмя переменными из примера выше), пометь второй как ignore. Проверь через Management Center на http://localhost:5700 или через `docker compose exec hz_1 hz-healthcheck` (по имени сервиса — `container_name` в примерах урока не задан), что кластер сформирован из двух нод. Само подключение приложения к hz_1 проверить пока нечем — стартер `spring-boot-starter-hazelcast` подключается в уроке 6, там к этому и вернёмся
6. Поставь `spring.docker.compose.readiness.timeout: 10s` и добавь сервис, который не открывает пробрасываемый порт — сначала получи таймаут, затем сними его лейблом ignore

## Итоги урока

- Лейблы с префиксом `org.springframework.boot.*` управляют поведением Docker Compose интеграции для каждого сервиса
- `org.springframework.boot.ignore: true` полностью исключает сервис из обработки Spring Boot — необходим для UI-инструментов, дублирующих нод кластеров и нераспознаваемых образов
- `org.springframework.boot.service-connection` указывает тип подключения для нестандартных образов — Spring Boot обработает сервис как стандартную технологию
- `org.springframework.boot.readiness-check.tcp.disable` отключает TCP-проверку готовности для сервисов без пробрасываемых портов
- Лейблы комбинируются — можно одновременно указать тип подключения и отключить readiness check
- Нераспознанный образ не вызывает предупреждений — он просто остаётся без ConnectionDetails, но продолжает участвовать в readiness-проверке
