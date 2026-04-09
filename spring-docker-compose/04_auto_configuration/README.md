# Урок 4. Автоконфигурация подключений

## Как Spring Boot определяет параметры подключения

Когда Spring Boot запускает Docker Compose, он выполняет `docker compose ps` и получает информацию о каждом сервисе: образ, маппинг портов, переменные окружения. На основе этих данных создаются **ConnectionDetails** — объекты, которые предоставляют параметры подключения другим автоконфигурациям Spring Boot.

```
┌─────────────────────────────────────────────────────────┐
│                    compose.yaml                         │
│                                                         │
│  services:                                              │
│    db:                                                  │
│      image: postgres:17.5        ──┐                    │
│      ports: "5432:5432"          ──┼── Spring Boot      │
│      environment:                ──┘   читает           │
│        POSTGRES_DB: myapp                               │
│        POSTGRES_USER: myapp                             │
│        POSTGRES_PASSWORD: myapp                         │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│              JdbcConnectionDetails                      │
│                                                         │
│  url:      jdbc:postgresql://localhost:5432/myapp        │
│  username: myapp                                        │
│  password: myapp                                        │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│                    DataSource                           │
│  (HikariCP с автоматическими параметрами)               │
└─────────────────────────────────────────────────────────┘
```

## ConnectionDetails и их приоритет

Spring Boot 3.1+ использует механизм **ConnectionDetails** — интерфейсы, предоставляющие параметры подключения. Docker Compose создаёт реализации этих интерфейсов автоматически.

**Важно:** ConnectionDetails от Docker Compose имеют приоритет выше, чем значения из `application.yml`. Если в compose-файле определён PostgreSQL на порту 5432, а в application.yml указан `spring.datasource.url` с портом 5433 — будет использован порт из compose.

| Источник | Приоритет |
|----------|-----------|
| ConnectionDetails (Docker Compose, Testcontainers, Service Bindings) | Высший |
| application.yml / application.properties | Низший |

Это означает, что при активной Docker Compose интеграции значения `spring.datasource.*` из application.yml **игнорируются**. Если тебе нужно переопределить автоконфигурацию — используй лейблы (урок 5) или отключи Docker Compose для конкретного запуска.

## Автоконфигурация PostgreSQL

Spring Boot распознаёт образы PostgreSQL и извлекает параметры из переменных окружения:

```yaml
services:
  db:
    image: postgres:17.5
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD: myapp
```

Из этого Spring Boot создаёт `JdbcConnectionDetails`:
- URL: `jdbc:postgresql://localhost:5432/myapp` (хост и порт из `docker compose ps`, база из `POSTGRES_DB`)
- Username: из `POSTGRES_USER`
- Password: из `POSTGRES_PASSWORD`

Если `POSTGRES_DB` не указан, используется значение `POSTGRES_USER` (поведение самого PostgreSQL).

## Автоконфигурация Redis

```yaml
services:
  redis:
    image: redis:7.4
    ports:
      - "6379:6379"
```

Spring Boot создаёт `RedisConnectionDetails`:
- Host: `localhost`
- Port: `6379`

Если Redis защищён паролем:

```yaml
services:
  redis:
    image: redis:7.4
    ports:
      - "6379:6379"
    command: redis-server --requirepass myredispass
    environment:
      REDIS_PASSWORD: myredispass
```

Spring Boot извлечёт пароль из переменной `REDIS_PASSWORD`.

## Автоконфигурация Kafka

```yaml
services:
  kafka:
    image: confluentinc/cp-kafka:7.2.1
    ports:
      - "9092:9092"
    environment:
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092
```

Spring Boot создаёт `KafkaConnectionDetails`:
- Bootstrap servers: `localhost:9092`

Spring Boot анализирует `KAFKA_ADVERTISED_LISTENERS` и выбирает listener, доступный с хоста (не из контейнерной сети).

## Динамические порты

Compose-файл может использовать динамические порты — когда Docker сам выбирает свободный порт на хосте:

```yaml
services:
  db:
    image: postgres:17.5
    ports:
      - "5432"  # хост-порт назначается динамически
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD: myapp
```

Spring Boot вызывает `docker compose ps`, получает реальный маппинг (например, `0.0.0.0:54321->5432/tcp`) и использует именно этот порт. Это полезно, если стандартный порт 5432 уже занят.

## Несколько сервисов одного типа

Если в compose-файле два PostgreSQL-сервиса, Spring Boot не сможет однозначно определить, какой из них использовать для `DataSource`. В этом случае один сервис нужно пометить лейблом `org.springframework.boot.ignore=true` (подробнее в уроке 5).

## Отладка автоконфигурации

Для диагностики проблем с автоконфигурацией:

```yaml
logging:
  level:
    org.springframework.boot.docker.compose: DEBUG
    org.springframework.boot.autoconfigure.service.connection: DEBUG
```

В логах ты увидишь:
- Какие сервисы обнаружены в compose-файле
- Какие ConnectionDetails созданы
- Какие properties были переопределены

Ещё один способ — Actuator endpoint `/actuator/info` с включённым Docker Compose Actuator:

```yaml
management:
  info:
    docker-compose:
      enabled: true
```

## Практика

1. Создай compose.yaml с PostgreSQL и Redis. Запусти приложение без `spring.datasource.*` и `spring.data.redis.*` в application.yml — убедись, что подключения работают
2. Добавь `spring.datasource.url: jdbc:postgresql://localhost:9999/wrong` в application.yml — проверь, что Spring Boot всё равно подключается к правильному порту из compose
3. Измени порт PostgreSQL на динамический (`"5432"` вместо `"5432:5432"`) — убедись, что приложение подключается к порту, назначенному Docker
4. Включи DEBUG-логирование для `org.springframework.boot.docker.compose` и изучи, какие ConnectionDetails создаются
5. Добавь Kafka в compose-файл и убедись, что `spring.kafka.bootstrap-servers` настраивается автоматически
6. Попробуй добавить два PostgreSQL-сервиса в compose и запусти приложение — изучи ошибку

## Итоги урока

- Spring Boot создаёт ConnectionDetails на основе образов, портов и переменных окружения из compose-файла
- ConnectionDetails имеют приоритет выше, чем значения из application.yml — это намеренное поведение, не баг
- Для PostgreSQL параметры извлекаются из `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- Динамические порты поддерживаются — Spring Boot получает реальный маппинг через `docker compose ps`
- Два сервиса одного типа вызывают конфликт — один нужно пометить лейблом ignore
- DEBUG-логирование пакета `org.springframework.boot.docker.compose` показывает все автосконфигурированные подключения
