# Урок 1. Зачем нужен spring-boot-docker-compose

## Проблема ручного управления инфраструктурой

Типичный микросервис зависит от нескольких внешних систем: база данных, кеш, брокер сообщений. Чтобы запустить приложение локально, разработчик должен:

1. Открыть терминал
2. Выполнить `docker compose up -d`
3. Дождаться готовности всех сервисов
4. Запустить приложение
5. После работы не забыть выполнить `docker compose down`

Это рутина, которая отнимает время и порождает типичные ошибки: забыл поднять контейнеры, забыл остановить, порты заняты старыми контейнерами, properties в приложении не совпадают с compose-файлом.

## Что делает spring-boot-docker-compose

Начиная с Spring Boot 3.1, в экосистему добавлена зависимость `spring-boot-docker-compose`. Она решает две задачи:

1. **Автоматический запуск и остановка контейнеров** — Spring Boot сам вызывает `docker compose up` при старте приложения и `docker compose stop` при остановке
2. **Автоконфигурация подключений** — Spring Boot читает compose-файл, определяет образы сервисов и автоматически настраивает `spring.datasource.url`, `spring.data.redis.host` и другие properties

```
┌──────────────────────────────────────────────────┐
│                  Spring Boot App                 │
│                                                  │
│  1. Находит compose.yaml в корне проекта         │
│  2. Выполняет docker compose up                  │
│  3. Читает образы и порты из compose-файла       │
│  4. Настраивает DataSource, Redis, Hazelcast     │
│  5. Запускает ApplicationContext                 │
│  6. При остановке: docker compose stop           │
│                                                  │
└──────────────────────────────────────────────────┘
```

Разработчик просто запускает `./gradlew bootRun` — всё остальное происходит автоматически.

## До и после

### Без spring-boot-docker-compose

```yaml
# application.yml — все параметры вручную
spring:
  datasource:
    url: jdbc:postgresql://localhost:5432/mydb
    username: myuser
    password: mypass
  data:
    redis:
      host: localhost
      port: 6379
  kafka:
    bootstrap-servers: localhost:9092
```

Если порт в compose-файле изменился — нужно вручную обновить application.yml. Если забыл поднять контейнеры — приложение падает с непонятной ошибкой подключения.

### С spring-boot-docker-compose

```yaml
# application.yml — ничего лишнего
spring:
  docker:
    compose:
      lifecycle-management: start_and_stop
```

Spring Boot сам определяет хост, порт, credentials из compose-файла. Никакого дублирования конфигурации.

## Какие сервисы поддерживаются

Spring Boot распознаёт сервис по **имени образа** — список имён зашит в самой интеграции. Основные из них (Spring Boot 4.1):

| Технология | Имена образов | Что настраивается |
|------------|---------------|-------------------|
| PostgreSQL | `postgres` | `spring.datasource.*`, `spring.r2dbc.*` |
| MySQL / MariaDB | `mysql`, `mariadb` | `spring.datasource.*`, `spring.r2dbc.*` |
| MS SQL Server | `mssql/server` | `spring.datasource.*`, `spring.r2dbc.*` |
| Oracle | `gvenzl/oracle-free`, `gvenzl/oracle-xe` | `spring.datasource.*`, `spring.r2dbc.*` |
| ClickHouse | `clickhouse/clickhouse-server` | `spring.datasource.*`, `spring.r2dbc.*` |
| MongoDB | `mongo` | `spring.data.mongodb.*` |
| Redis | `redis`, `redis/redis-stack`, `redis/redis-stack-server` | `spring.data.redis.*` |
| RabbitMQ | `rabbitmq` | `spring.rabbitmq.*` |
| Hazelcast | `hazelcast/hazelcast` | `HazelcastConnectionDetails` |
| Elasticsearch | `elasticsearch`, `elasticsearch/elasticsearch` | `spring.elasticsearch.*` |
| Cassandra | `cassandra` | `spring.cassandra.*` |
| Neo4j | `neo4j` | `spring.neo4j.*` |
| Pulsar | `apachepulsar/pulsar` | `spring.pulsar.*` |
| ActiveMQ / Artemis | `apache/activemq`, `apache/activemq-artemis` | `spring.activemq.*`, `spring.artemis.*` |
| Zipkin | `openzipkin/zipkin` | `management.zipkin.*` |

**Важно:** **Kafka в этом списке нет**. Для Kafka connection details создаются только через Testcontainers, но не через Docker Compose. Брокер в compose-файле поднимется и Spring Boot дождётся его готовности, а `spring.kafka.bootstrap-servers` придётся указать в `application.yml` вручную. Это не изменилось ни в 3.x, ни в 4.x — подробности в уроке 4.

Образы с другими именами (`bitnami/postgresql`, собственные сборки) не распознаются автоматически — им нужен лейбл `org.springframework.boot.service-connection` (урок 5).

## Когда это полезно

- **Локальная разработка** — один `bootRun` поднимает всю инфраструктуру
- **Тестирование** — тесты автоматически получают нужные контейнеры (альтернатива Testcontainers)
- **Онбординг новых разработчиков** — не нужно объяснять, какие контейнеры запускать и с какими параметрами

## Когда это НЕ нужно

- **Production** — зависимость подключается только для разработки и тестов (`testAndDevelopmentOnly` в Gradle)
- **CI с предзапущенными сервисами** — если CI уже поднимает PostgreSQL через services, дублировать через compose не нужно
- **Проекты без Docker** — очевидно, требуется Docker на машине разработчика

## Практика

1. Установи Docker Desktop (или Docker Engine + Compose plugin), если ещё не установлен
2. Убедись, что команда `docker compose version` возвращает версию не ниже 2.2.0 (на актуальном Docker Desktop это уже `Docker Compose version v5.x`)
3. Создай минимальный Spring Boot проект с `compose.yaml` (PostgreSQL) и запусти `./gradlew bootRun`
4. Открой Docker Desktop или выполни `docker ps` — убедись, что контейнеры запущены автоматически
5. Останови приложение (Ctrl+C) и снова проверь `docker ps` — контейнеры должны остановиться
6. Попробуй запустить приложение без Docker (останови Docker Desktop) — изучи сообщение об ошибке

## Итоги урока

- `spring-boot-docker-compose` автоматизирует запуск и остановку Docker Compose при старте/остановке Spring Boot приложения
- Зависимость избавляет от ручного управления контейнерами и дублирования конфигурации подключений
- Spring Boot распознаёт сервис по имени образа (PostgreSQL, Redis, Hazelcast и другие) и настраивает properties; Kafka в этот список не входит
- Зависимость предназначена только для разработки и тестов — в production она не используется
- Для работы требуется Docker Compose v2, установленный на машине разработчика
- Подход упрощает онбординг: новому разработчику достаточно выполнить `./gradlew bootRun`
