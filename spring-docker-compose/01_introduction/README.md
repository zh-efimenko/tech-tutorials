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

1. **Автоматический запуск и остановка контейнеров** — Spring Boot сам вызывает `docker compose up` при старте приложения и `docker compose down` при остановке
2. **Автоконфигурация подключений** — Spring Boot читает compose-файл, определяет образы сервисов и автоматически настраивает `spring.datasource.url`, `spring.data.redis.host` и другие properties

```
┌──────────────────────────────────────────────────┐
│                  Spring Boot App                 │
│                                                  │
│  1. Находит compose.yaml в корне проекта         │
│  2. Выполняет docker compose up                  │
│  3. Читает образы и порты из compose-файла       │
│  4. Настраивает DataSource, Redis, Kafka и т.д.  │
│  5. Запускает ApplicationContext                  │
│  6. При остановке: docker compose down           │
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

Spring Boot автоматически распознаёт образы и настраивает подключения для популярных технологий:

| Технология | Образы | Что настраивается |
|------------|--------|-------------------|
| PostgreSQL | `postgres`, `bitnami/postgresql` | `spring.datasource.*` |
| MySQL | `mysql`, `bitnami/mysql` | `spring.datasource.*` |
| MongoDB | `mongo`, `bitnami/mongodb` | `spring.data.mongodb.*` |
| Redis | `redis`, `bitnami/redis` | `spring.data.redis.*` |
| Kafka | `confluentinc/cp-kafka`, `bitnami/kafka` | `spring.kafka.*` |
| RabbitMQ | `rabbitmq` | `spring.rabbitmq.*` |
| Hazelcast | `hazelcast/hazelcast` | `HazelcastConnectionDetails` |
| Elasticsearch | `elasticsearch`, `bitnami/elasticsearch` | `spring.elasticsearch.*` |
| Zipkin | `openzipkin/zipkin` | `management.zipkin.*` |

Полный список поддерживаемых образов расширяется с каждой версией Spring Boot.

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
2. Убедись, что команда `docker compose version` возвращает версию v2.x
3. Создай минимальный Spring Boot проект с `compose.yaml` (PostgreSQL) и запусти `./gradlew bootRun`
4. Открой Docker Desktop или выполни `docker ps` — убедись, что контейнеры запущены автоматически
5. Останови приложение (Ctrl+C) и снова проверь `docker ps` — контейнеры должны остановиться
6. Попробуй запустить приложение без Docker (останови Docker Desktop) — изучи сообщение об ошибке

## Итоги урока

- `spring-boot-docker-compose` автоматизирует запуск и остановку Docker Compose при старте/остановке Spring Boot приложения
- Зависимость избавляет от ручного управления контейнерами и дублирования конфигурации подключений
- Spring Boot автоматически распознаёт образы популярных технологий (PostgreSQL, Redis, Kafka и другие) и настраивает properties
- Зависимость предназначена только для разработки и тестов — в production она не используется
- Для работы требуется Docker Compose v2, установленный на машине разработчика
- Подход упрощает онбординг: новому разработчику достаточно выполнить `./gradlew bootRun`
