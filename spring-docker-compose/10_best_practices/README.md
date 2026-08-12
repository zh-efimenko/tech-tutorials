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
PROJECT_NAME=myapp
DB_PORT=5432
REDIS_PORT=6379
```

В шаблоне должны быть ровно те переменные, которые compose-файл действительно подставляет (`${PROJECT_NAME:-myapp}`, `${DB_PORT:-5432}` — см. урок 9). Переменная, которой нет в compose-файле, только вводит в заблуждение: студент правит `.env`, а ничего не меняется.

## Именование контейнеров

Всегда задавай `container_name` — это помогает при отладке через `docker ps` и `docker logs`:

```yaml
services:
  db:
    image: postgres:18.4
    container_name: ${PROJECT_NAME:-myapp}_postgres
```

Используй префикс проекта, чтобы контейнеры разных проектов не конфликтовали.

## Healthcheck для всех критичных сервисов

Spring Boot ждёт готовности сервисов перед подключением. Без healthcheck он проверяет только доступность TCP-порта, что недостаточно для сервисов с долгой инициализацией.

```yaml
services:
  db:
    image: postgres:18.4
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U demo"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:8.10
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  kafka:
    image: apache/kafka:4.3.1
    healthcheck:
      test: ["CMD-SHELL", "/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list"]
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
    image: postgres:18.4
```

Обновляй версии осознанно, проверяя changelog. Свежий пример: в `postgres:18` том переехал с `/var/lib/postgresql/data` на `/var/lib/postgresql`, а `PGDATA` стал версионным (`/var/lib/postgresql/18/docker`). Compose-файл со старым путём монтирования после апгрейда мажорной версии молча получит пустую базу.

## CI/CD

В CI-окружении Docker Compose интеграция может мешать. Есть два подхода:

### Подход 1: Отключить интеграцию, использовать CI-сервисы

Если CI (GitHub Actions, GitLab CI) предоставляет PostgreSQL и Redis как services:

```yaml
# GitHub Actions
services:
  postgres:
    image: postgres:18.4
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
  - uses: actions/checkout@v7
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
java.lang.IllegalStateException: No Docker Compose file found in directory '/path/to/project/.'
```

**Причина:** compose-файл не в рабочей директории или называется нестандартно.

**Решение:** укажи путь явно:
```yaml
spring:
  docker:
    compose:
      file: path/to/compose.yaml
```

### Ошибка: подключение не настроилось

```
Failed to configure a DataSource: 'url' attribute is not specified and no embedded datasource could be configured
```

**Причина:** Spring Boot не распознал образ, ConnectionDetails не созданы. Отдельного сообщения про нераспознанный сервис в логах не будет — падает уже автоконфигурация DataSource.

**Решение:** добавь лейбл `org.springframework.boot.service-connection`:
```yaml
services:
  my-custom-db:
    image: myregistry.io/custom-postgres:18
    labels:
      org.springframework.boot.service-connection: postgres
```

### Ошибка: таймаут ожидания готовности

```
org.springframework.boot.docker.compose.lifecycle.ReadinessTimeoutException:
Readiness timeout of PT2M reached while waiting for services [my_worker]
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
4. Создай `application-test.yml` с `skip.in-tests: false`, `file: compose-test.yaml`, отдельным именем Compose-проекта (`arguments: ["--project-name=myapp-test"]`) и `stop.command: down` с `--volumes` — без имени проекта тесты уйдут в dev-базу, без `--volumes` потащат за собой данные прошлого прогона (урок 8)
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
6. Собери `./gradlew bootJar` и запусти JAR напрямую. Приложение упадёт с `Failed to configure a DataSource: 'url' attribute is not specified and no embedded datasource could be configured` — это и есть доказательство: контейнеры никто не поднял, ConnectionDetails никто не создал, интеграции в артефакте нет. Проверь это и напрямую: `unzip -l build/libs/*.jar | grep docker-compose` не найдёт ни одной записи

## Итоги урока

- `testAndDevelopmentOnly` гарантирует отсутствие зависимости в production JAR — не нужна отдельная конфигурация для production
- `compose.override.yaml` и `.env` не коммитятся — это локальные настройки разработчика
- Healthcheck нужен каждому критичному сервису — TCP-проверка порта недостаточна для сервисов с долгой инициализацией
- Версии образов фиксируются — `latest` приводит к невоспроизводимым сборкам
- В CI есть два подхода: отключить интеграцию (CI предоставляет сервисы) или использовать Docker Compose на раннере
- Типичные ошибки связаны с занятыми портами, нераспознанными образами и неправильным расположением compose-файла
- Чек-лист из 10 пунктов покрывает настройку Docker Compose интеграции для нового проекта
