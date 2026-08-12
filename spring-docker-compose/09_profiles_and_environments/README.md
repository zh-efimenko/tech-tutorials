# Урок 9. Профили и окружения

## Docker Compose Profiles

Docker Compose поддерживает собственные профили — механизм, позволяющий запускать подмножество сервисов. Spring Boot интегрируется с ними через свойство `spring.docker.compose.profiles.active`.

### Определение профилей в compose-файле

```yaml
services:
  db:
    image: postgres:18.4
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: demo
      POSTGRES_USER: demo
      POSTGRES_PASSWORD: demo

  redis:
    image: redis:8.10
    ports:
      - "6379:6379"

  kafka:
    image: apache/kafka:4.3.1
    ports:
      - "9092:9092"
    profiles:
      - messaging
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://:29092,CONTROLLER://:29093,PLAINTEXT_HOST://:9092
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:29093
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1

  hz_1:
    image: hazelcast/hazelcast:5.7
    ports:
      - "5701:5701"
    profiles:
      - cache
    environment:
      HZ_CLUSTERNAME: demo
```

Сервисы без `profiles` запускаются всегда. Сервисы с `profiles` запускаются только при активации соответствующего профиля.

### Активация профилей через Spring Boot

```yaml
# application.yml
spring:
  docker:
    compose:
      profiles:
        active: messaging, cache
```

Spring Boot выполнит `docker compose --profile messaging --profile cache up`. Kafka и Hazelcast запустятся вместе с PostgreSQL и Redis.

### Активация через переменную окружения

```bash
SPRING_DOCKER_COMPOSE_PROFILES_ACTIVE=messaging ./gradlew bootRun
```

Запустятся только PostgreSQL, Redis и Kafka (без Hazelcast).

## Spring-профили для compose-конфигурации

Spring-профили (`@ActiveProfiles`, `spring.profiles.active`) управляют, какой `application-{profile}.yml` загружается. Это позволяет хранить разные compose-настройки для разных сценариев.

### Структура файлов

```
src/main/resources/
├── application.yml               # общие настройки
├── application-dev.yml           # для локальной разработки
└── application-minimal.yml       # минимальный набор сервисов

src/test/resources/
└── application-test.yml          # для тестов
```

### application.yml — общие настройки

```yaml
spring:
  docker:
    compose:
      lifecycle-management: start_and_stop
```

### application-dev.yml — разработка

```yaml
spring:
  docker:
    compose:
      lifecycle-management: start_only
      profiles:
        active: messaging, cache
      readiness:
        wait: only-if-started
```

Полный стек, контейнеры не останавливаются между запусками.

### application-minimal.yml — только база и кеш

```yaml
spring:
  docker:
    compose:
      lifecycle-management: start_and_stop
      # Без профилей — запустятся только PostgreSQL и Redis
```

### application-test.yml — тесты

```yaml
spring:
  docker:
    compose:
      skip:
        in-tests: false
      file: compose-test.yaml
```

### Запуск с разными профилями

```bash
# Полный стек для разработки
./gradlew bootRun --args='--spring.profiles.active=dev'

# Минимальный стек для быстрой работы
./gradlew bootRun --args='--spring.profiles.active=minimal'

# Тесты (профиль задаётся в @ActiveProfiles)
./gradlew test
```

## Несколько compose-файлов

Docker Compose поддерживает слияние нескольких файлов. Свойство `spring.docker.compose.file` принимает список — файлы мержатся в указанном порядке:

```yaml
spring:
  docker:
    compose:
      file:
        - compose.yaml
        - compose-monitoring.yaml
```

Именно так и подключаются локальные переопределения. Штатный механизм Docker Compose — файл `compose.override.yaml`, который сам подхватывается командой `docker compose up`, — со Spring Boot **не работает**: интеграция всегда передаёт найденный файл явно (`docker compose --file compose.yaml …`), а явный `--file` отключает автоподхват override. Поэтому override-файл нужно перечислить руками:

```
project/
├── compose.yaml              # базовые сервисы
├── compose.override.yaml     # локальные переопределения (не коммитится)
└── compose-test.yaml         # для тестов
```

### compose.yaml — базовый

```yaml
services:
  db:
    image: postgres:18.4
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: demo
      POSTGRES_USER: demo
      POSTGRES_PASSWORD: demo
```

### compose.override.yaml — локальные настройки

```yaml
services:
  db:
    ports: !override
      - "5433:5432"    # другой порт, если 5432 занят
    volumes:
      - pgdata:/var/lib/postgresql        # сохранять данные (в postgres:18+ том смонтирован сюда)

volumes:
  pgdata:
```

**Про `!override`:** без этого тега список портов не заменяется, а **дополняется** — записи считаются разными, если отличается опубликованный порт. В результате Compose опубликует оба маппинга, `5432:5432` и `5433:5432`, и занятый порт 5432 никуда не денется. Проверить результат слияния до запуска можно так:

```bash
docker compose -f compose.yaml -f compose.override.yaml config
```

Для `volumes` и `environment` тег не нужен: тома дополняются, переменные переопределяются по ключу.

Чтобы Spring Boot увидел слияние, оба файла указываются в свойстве:

```yaml
spring:
  docker:
    compose:
      file:
        - compose.yaml
        - compose.override.yaml
```

**Важно:** добавь `compose.override.yaml` в `.gitignore` — это файл для локальных настроек конкретного разработчика. И помни, что при запуске `docker compose up` руками, без Spring Boot, override подхватится сам — поведение отличается.

## Условный запуск через Spring-профили

Можно полностью менять compose-файл в зависимости от Spring-профиля:

```yaml
# application-full.yml
spring:
  docker:
    compose:
      file: compose.yaml
      profiles:
        active: messaging, cache

# application-light.yml
spring:
  docker:
    compose:
      file: compose-light.yaml
```

```bash
# Полный стек
./gradlew bootRun --args='--spring.profiles.active=full'

# Легковесный стек
./gradlew bootRun --args='--spring.profiles.active=light'
```

## Переменные окружения в compose-файле

Docker Compose поддерживает подстановку переменных окружения:

```yaml
services:
  db:
    image: postgres:${POSTGRES_VERSION:-18.4}
    ports:
      - "${DB_PORT:-5432}:5432"
    environment:
      POSTGRES_DB: ${DB_NAME:-demo}
      POSTGRES_USER: ${DB_USER:-demo}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-demo}
```

Переменные берутся из файла `.env` в корне проекта или из окружения:

```bash
# .env
POSTGRES_VERSION=17.5
DB_PORT=5433
DB_NAME=myapp
```

Spring Boot читает compose-файл после подстановки переменных, поэтому ConnectionDetails будут содержать реальные значения.

## Практика

1. Добавь `profiles: [messaging]` к Kafka в compose.yaml. Запусти без указания профиля — убедись, что Kafka не запускается
2. Добавь `spring.docker.compose.profiles.active: messaging` в application.yml — теперь Kafka должна подняться
3. Создай `application-dev.yml` с `lifecycle-management: start_only` и `application-minimal.yml` без Docker Compose профилей. Переключайся между ними
4. Создай `compose.override.yaml`, который меняет порт PostgreSQL на 5433 (не забудь `!override`), перечисли оба файла в `spring.docker.compose.file` и проверь итог через `docker compose ... config`. Добавь override в `.gitignore`
5. Добавь подстановку переменных в compose.yaml для имени базы и пользователя. Создай `.env` файл с кастомными значениями
6. Активируй Docker Compose профиль через переменную окружения `SPRING_DOCKER_COMPOSE_PROFILES_ACTIVE` без изменения application.yml

## Итоги урока

- Docker Compose профили позволяют запускать подмножество сервисов — активируются через `spring.docker.compose.profiles.active`
- Сервисы без `profiles` запускаются всегда, с `profiles` — только при явной активации
- Spring-профили (`application-{profile}.yml`) управляют compose-настройками для разных сценариев: dev, test, minimal
- `compose.override.yaml` со Spring Boot автоматически не подхватывается: интеграция передаёт файлы через `--file`, поэтому override перечисляется явно в `spring.docker.compose.file`
- Переменные окружения в compose-файле (`${VAR:-default}`) позволяют параметризовать конфигурацию через `.env`
- Комбинация Spring-профилей и Docker Compose профилей даёт гибкое управление инфраструктурой для любого сценария
