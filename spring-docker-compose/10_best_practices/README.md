# Урок 10. Best practices и production

## Главное правило: spring-boot-docker-compose — только для dev и test

Зависимость подключается через `testAndDevelopmentOnly`:

```groovy
testAndDevelopmentOnly 'org.springframework.boot:spring-boot-docker-compose'
```

Это означает:
- В `bootJar` / `bootWar` зависимости нет
- В production-артефакте Docker Compose интеграция отсутствует
- Properties `spring.docker.compose.*` в production игнорируются

Не нужно добавлять `spring.docker.compose.enabled: false` в production-профиль — зависимости просто нет в classpath.

## Структура compose-файлов

Рекомендуемая организация файлов:

```
project/
├── compose.yaml              # полный стек для разработки
├── compose-test.yaml         # урезанный стек для тестов
├── compose.override.yaml     # локальные переопределения (в .gitignore)
├── .env                      # переменные для compose (в .gitignore)
├── .env.example              # шаблон .env (коммитится)
├── .gitignore
├── build.gradle
└── src/
    ├── main/resources/
    │   ├── application.yml
    │   └── application-dev.yml
    └── test/resources/
        └── application-test.yml
```

### .gitignore

```
compose.override.yaml
.env
```

### .env.example

```bash
# Скопируй в .env и настрой под своё окружение
DB_PORT=5432
REDIS_PORT=6379
```

## Именование контейнеров

Всегда задавай `container_name` — это помогает при отладке через `docker ps` и `docker logs`:

```yaml
services:
  db:
    image: postgres:17.5
    container_name: ${PROJECT_NAME:-myapp}_postgres
```

Используй префикс проекта, чтобы контейнеры разных проектов не конфликтовали.

## Healthcheck для всех критичных сервисов

Spring Boot ждёт готовности сервисов перед подключением. Без healthcheck он проверяет только доступность TCP-порта, что недостаточно для сервисов с долгой инициализацией.

```yaml
services:
  db:
    image: postgres:17.5
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U demo"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7.4
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  kafka:
    image: confluentinc/cp-kafka:7.2.1
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "29092"]
      interval: 10s
      timeout: 5s
      retries: 10
```

## Версионирование образов

Всегда фиксируй версию образа. Никогда не используй `latest`:

```yaml
# Плохо — непредсказуемо
services:
  db:
    image: postgres:latest

# Хорошо — воспроизводимо
services:
  db:
    image: postgres:17.5
```

Обновляй версии осознанно, проверяя changelog.

## CI/CD

В CI-окружении Docker Compose интеграция может мешать. Есть два подхода:

### Подход 1: Отключить интеграцию, использовать CI-сервисы

Если CI (GitHub Actions, GitLab CI) предоставляет PostgreSQL и Redis как services:

```yaml
# GitHub Actions
services:
  postgres:
    image: postgres:17.5
    env:
      POSTGRES_DB: test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    ports:
      - 5432:5432
```

В application-ci.yml отключи Docker Compose:

```yaml
# application-ci.yml
spring:
  docker:
    compose:
      enabled: false
  datasource:
    url: jdbc:postgresql://localhost:5432/test
    username: test
    password: test
```

### Подход 2: Использовать Docker Compose в CI

Если CI поддерживает Docker-in-Docker или Docker socket:

```yaml
# GitHub Actions
steps:
  - uses: actions/checkout@v4
  - name: Run tests
    run: ./gradlew test
    # Docker Compose поднимется автоматически через spring-boot-docker-compose
```

Этот подход проще — не нужна отдельная конфигурация для CI. Но требует Docker на CI-раннере.

## Типичные ошибки и решения

### Ошибка: порт занят

```
Bind for 0.0.0.0:5432 failed: port is already allocated
```

**Причина:** предыдущие контейнеры не были остановлены (crash приложения, `start_only`).

**Решение:**
```bash
docker compose down
# или конкретный контейнер
docker rm -f demo_postgres
```

**Профилактика:** используй `lifecycle-management: start_and_stop` с `stop.command: down`.

### Ошибка: Spring Boot не находит compose-файл

```
No Docker Compose file found
```

**Причина:** compose-файл не в рабочей директории или называется нестандартно.

**Решение:** укажи путь явно:
```yaml
spring:
  docker:
    compose:
      file: path/to/compose.yaml
```

### Ошибка: ConnectionDetails не создаются

```
No ConnectionDetails found for service 'my-custom-db'
```

**Причина:** Spring Boot не распознаёт образ.

**Решение:** добавь лейбл `org.springframework.boot.service-connection`:
```yaml
services:
  my-custom-db:
    image: myregistry.io/custom-postgres:17
    labels:
      org.springframework.boot.service-connection: postgres
```

### Ошибка: таймаут ожидания готовности

```
Timed out waiting for container to be ready
```

**Причина:** сервис долго стартует, а readiness timeout слишком маленький.

**Решение:**
```yaml
spring:
  docker:
    compose:
      readiness:
        timeout: 3m
```

### Ошибка: тесты не поднимают контейнеры

**Причина:** `skip.in-tests` по умолчанию `true`.

**Решение:**
```yaml
# application-test.yml
spring:
  docker:
    compose:
      skip:
        in-tests: false
```

### Ошибка: конфликт между dev и test контейнерами

**Причина:** одинаковые порты в compose.yaml и compose-test.yaml.

**Решение:** используй разные порты и `container_name`:
```yaml
# compose-test.yaml
services:
  db:
    container_name: test_postgres
    ports:
      - "5433:5432"   # другой хост-порт
```

## Чек-лист для нового проекта

1. Добавь `spring-boot-docker-compose` через `testAndDevelopmentOnly`
2. Создай `compose.yaml` с полным стеком и healthcheck для каждого сервиса
3. Создай `compose-test.yaml` с минимальным набором сервисов и сдвинутыми портами
4. Создай `application-test.yml` с `skip.in-tests: false` и `file: compose-test.yaml`
5. Добавь `compose.override.yaml` и `.env` в `.gitignore`
6. Создай `.env.example` с шаблоном переменных
7. Пометь UI-сервисы и дублирующие ноды лейблом `org.springframework.boot.ignore: true`
8. Для нестандартных образов добавь лейбл `org.springframework.boot.service-connection`
9. Задай `container_name` для всех сервисов с префиксом проекта
10. Зафиксируй версии всех образов

## Практика

1. Проверь свой проект по чек-листу выше — исправь несоответствия
2. Создай `.env.example` для compose.yaml. Убедись, что `docker compose up` работает без `.env` (используются значения по умолчанию)
3. Добавь healthcheck для PostgreSQL и Redis. Включи DEBUG-логирование и убедись, что Spring Boot ждёт healthy-статуса
4. Смоделируй падение приложения (kill -9) при `lifecycle-management: start_only` — убедись, что при повторном запуске контейнеры переиспользуются
5. Настрой GitHub Actions workflow с `./gradlew test` — убедись, что тесты проходят в CI с Docker Compose
6. Попробуй собрать `./gradlew bootJar` и запустить JAR напрямую — убедись, что Docker Compose интеграция не активируется (зависимости нет в classpath)

## Итоги урока

- `testAndDevelopmentOnly` гарантирует отсутствие зависимости в production JAR — не нужна отдельная конфигурация для production
- `compose.override.yaml` и `.env` не коммитятся — это локальные настройки разработчика
- Healthcheck нужен каждому критичному сервису — TCP-проверка порта недостаточна для сервисов с долгой инициализацией
- Версии образов фиксируются — `latest` приводит к невоспроизводимым сборкам
- В CI есть два подхода: отключить интеграцию (CI предоставляет сервисы) или использовать Docker Compose на раннере
- Типичные ошибки связаны с занятыми портами, нераспознанными образами и неправильным расположением compose-файла
- Чек-лист из 10 пунктов покрывает настройку Docker Compose интеграции для нового проекта
