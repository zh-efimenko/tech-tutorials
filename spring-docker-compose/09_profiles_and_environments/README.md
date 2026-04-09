# Урок 9. Профили и окружения

## Docker Compose Profiles

Docker Compose поддерживает собственные профили — механизм, позволяющий запускать подмножество сервисов. Spring Boot интегрируется с ними через свойство `spring.docker.compose.profiles.active`.

### Определение профилей в compose-файле

```yaml
services:
  db:
    image: postgres:17.5
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: demo
      POSTGRES_USER: demo
      POSTGRES_PASSWORD: demo

  redis:
    image: redis:7.4
    ports:
      - "6379:6379"

  kafka:
    image: confluentinc/cp-kafka:7.2.1
    ports:
      - "9092:9092"
    profiles:
      - messaging
    depends_on:
      - zookeeper

  zookeeper:
    image: confluentinc/cp-zookeeper:7.2.1
    ports:
      - "2181:2181"
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
    profiles:
      - messaging

  hz_1:
    image: hazelcast/hazelcast:5.6-jdk21
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

Spring Boot выполнит `docker compose --profile messaging --profile cache up`. Kafka, Zookeeper и Hazelcast запустятся вместе с PostgreSQL и Redis.

### Активация через переменную окружения

```bash
SPRING_DOCKER_COMPOSE_PROFILES_ACTIVE=messaging ./gradlew bootRun
```

Запустятся только PostgreSQL, Redis, Kafka и Zookeeper (без Hazelcast).

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

Docker Compose поддерживает слияние нескольких файлов. Spring Boot позволяет указать несколько файлов:

```yaml
spring:
  docker:
    compose:
      file: compose.yaml
```

Но для работы с несколькими файлами через override лучше использовать стандартный механизм Docker Compose — файл `compose.override.yaml`, который автоматически мержится с `compose.yaml`:

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
    image: postgres:17.5
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
    ports:
      - "5433:5432"    # другой порт, если 5432 занят
    volumes:
      - pgdata:/var/lib/postgresql/data  # сохранять данные

volumes:
  pgdata:
```

Docker Compose автоматически объединит оба файла. Spring Boot увидит результат слияния.

**Важно:** добавь `compose.override.yaml` в `.gitignore` — это файл для локальных настроек конкретного разработчика.

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
    image: postgres:${POSTGRES_VERSION:-17.5}
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
POSTGRES_VERSION=16.8
DB_PORT=5433
DB_NAME=myapp
```

Spring Boot читает compose-файл после подстановки переменных, поэтому ConnectionDetails будут содержать реальные значения.

## Практика

1. Добавь `profiles: [messaging]` к Kafka и Zookeeper в compose.yaml. Запусти без указания профиля — убедись, что Kafka не запускается
2. Добавь `spring.docker.compose.profiles.active: messaging` в application.yml — теперь Kafka должна подняться
3. Создай `application-dev.yml` с `lifecycle-management: start_only` и `application-minimal.yml` без Docker Compose профилей. Переключайся между ними
4. Создай `compose.override.yaml`, который меняет порт PostgreSQL на 5433. Добавь его в `.gitignore`
5. Добавь подстановку переменных в compose.yaml для имени базы и пользователя. Создай `.env` файл с кастомными значениями
6. Активируй Docker Compose профиль через переменную окружения `SPRING_DOCKER_COMPOSE_PROFILES_ACTIVE` без изменения application.yml

## Итоги урока

- Docker Compose профили позволяют запускать подмножество сервисов — активируются через `spring.docker.compose.profiles.active`
- Сервисы без `profiles` запускаются всегда, с `profiles` — только при явной активации
- Spring-профили (`application-{profile}.yml`) управляют compose-настройками для разных сценариев: dev, test, minimal
- `compose.override.yaml` автоматически мержится с `compose.yaml` — используй для локальных настроек разработчика
- Переменные окружения в compose-файле (`${VAR:-default}`) позволяют параметризовать конфигурацию через `.env`
- Комбинация Spring-профилей и Docker Compose профилей даёт гибкое управление инфраструктурой для любого сценария
