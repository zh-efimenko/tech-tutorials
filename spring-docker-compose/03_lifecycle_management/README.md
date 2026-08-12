# Урок 3. Управление жизненным циклом

## Режимы управления жизненным циклом

Spring Boot предоставляет три режима управления Docker Compose через свойство `spring.docker.compose.lifecycle-management`:

| Режим | При старте приложения | При остановке приложения |
|-------|----------------------|------------------------|
| `start_and_stop` | `docker compose up` | `docker compose stop` / `down` |
| `start_only` | `docker compose up` | ничего |
| `none` | ничего | ничего |

### start_and_stop (по умолчанию)

```yaml
spring:
  docker:
    compose:
      lifecycle-management: start_and_stop
```

Полный контроль: Spring Boot поднимает контейнеры при старте и останавливает при завершении. Это поведение по умолчанию.

### start_only

```yaml
spring:
  docker:
    compose:
      lifecycle-management: start_only
```

Spring Boot запускает контейнеры, но не останавливает их. Полезно, когда:
- Хочешь переключаться между запусками приложения без ожидания старта контейнеров
- Работаешь с несколькими приложениями, использующими одни и те же сервисы
- Контейнеры долго стартуют (Kafka, Elasticsearch)

### none

```yaml
spring:
  docker:
    compose:
      lifecycle-management: none
```

Spring Boot не управляет Docker Compose, но всё равно читает compose-файл для автоконфигурации подключений. Ты сам запускаешь `docker compose up -d` и останавливаешь контейнеры.

## Команда остановки

При `lifecycle-management: start_and_stop` Spring Boot по умолчанию выполняет `docker compose stop`. Это останавливает контейнеры, но не удаляет их и тома. Можно изменить на `down`:

```yaml
spring:
  docker:
    compose:
      stop:
        command: down
```

Разница между `stop` и `down`:

| Команда | Контейнеры | Сети | Тома |
|---------|-----------|------|------|
| `stop` | Останавливаются (можно перезапустить) | Сохраняются | Сохраняются |
| `down` | Удаляются | Удаляются | Сохраняются |

## Аргументы остановки

К команде остановки можно добавить аргументы. Свойство `stop.arguments` — это список, а самый частый аргумент — `--volumes` (он же `-v`) для удаления томов при `down`:

```yaml
spring:
  docker:
    compose:
      stop:
        command: down
        arguments:
          - "--volumes"
          - "--remove-orphans"
        timeout: 10s
```

Есть и общий список `spring.docker.compose.arguments` — эти аргументы подставляются во все команды (`up`, `stop`, `down`), а не только в остановку:

```yaml
spring:
  docker:
    compose:
      arguments:
        - "--project-name=myapp"
```

**Когда использовать `--volumes`:** если хочешь гарантированно чистое состояние при каждом запуске — удаляются и именованные тома, и анонимные.

**Когда НЕ использовать:** если данные в базе нужны между перезапусками (например, нагенерированные тестовые данные).

**Внимание:** «данные сохраняются, если не передать `--volumes`» — верно только для именованных томов. В compose-файле этого курса секции `volumes` нет, поэтому PostgreSQL пишет в **анонимный** том, привязанный к контейнеру. Проверено:

| Что выполнено | Данные |
|---|---|
| `stop` → `up` (дефолт) | сохраняются — контейнер тот же |
| `down` → `up` (без `--volumes`) | **теряются** — контейнер удалён, новый получает новый анонимный том (`ERROR: relation "t" does not exist`) |
| `down --volumes` → `up` | теряются |

Чтобы данные пережили `down`, том нужно объявить явно:

```yaml
services:
  db:
    image: postgres:18.4
    volumes:
      - pgdata:/var/lib/postgresql   # в postgres:18+ том смонтирован сюда

volumes:
  pgdata:
```

## Таймаут остановки

Свойство `spring.docker.compose.stop.timeout` задаёт время ожидания graceful shutdown контейнеров:

```yaml
spring:
  docker:
    compose:
      stop:
        timeout: 30s
```

По умолчанию Docker даёт контейнерам 10 секунд на завершение, после чего отправляет SIGKILL. Для тяжёлых сервисов (базы данных с большим WAL, Kafka с незакрытыми транзакциями) может потребоваться увеличить таймаут.

## Поведение при уже запущенных контейнерах

Если контейнеры уже запущены (например, ты запустил их вручную или предыдущий запуск использовал `start_only`), Spring Boot обнаружит это и не будет повторно выполнять `docker compose up`. Он просто прочитает информацию о запущенных сервисах и настроит подключения.

```
INFO  --- DockerComposeLifecycleManager : There are already Docker Compose services running, skipping startup
```

**Важно:** проверка грубая — старт пропускается, если запущен **хотя бы один** сервис из compose-файла, а не все. Если руками поднять только Kafka, а остальные сервисы оставить лежать, Spring Boot напечатает сообщение выше, ничего не поднимет, и приложение упадёт на автоконфигурации DataSource.

Поведением управляет свойство `spring.docker.compose.start.skip`: значение `if-running` (по умолчанию) пропускает запуск при уже поднятых сервисах, `never` — всегда выполняет команду запуска.

**Следствие:** если запуск был пропущен, Spring Boot не регистрирует и хук остановки — контейнеры не будут остановлены при завершении приложения, даже при `start_and_stop`.

## Readiness Check

Spring Boot не просто запускает контейнеры — он ждёт их готовности. Проверка готовности определяется по healthcheck в compose-файле:

```yaml
services:
  kafka:
    image: apache/kafka:4.3.1
    healthcheck:
      test: ["CMD-SHELL", "/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list"]
      interval: 10s
      timeout: 5s
      retries: 10
```

Проверок на самом деле две, и они не заменяют друг друга:

1. **Healthcheck** отрабатывает сам Docker Compose: Spring Boot запускает контейнеры командой `docker compose up --no-color --detach --wait`, а флаг `--wait` заставляет Compose дождаться статуса `healthy` для сервисов с healthcheck.
2. **TCP-проверка** выполняется Spring Boot **всегда**, независимо от наличия healthcheck: единственная реализация в `ServiceReadinessChecks` — `TcpConnectServiceReadinessCheck`, она пытается открыть каждый пробрасываемый порт сервиса. Отключается только лейблом `org.springframework.boot.readiness-check.tcp.disable` (урок 5) или `org.springframework.boot.ignore`.

**Важно:** для сервисов, которые долго стартуют (Kafka, Elasticsearch), всегда определяй healthcheck в compose-файле. Открытый порт ещё не означает готовность: TCP-проверка засчитает такой сервис готовым, и приложение начнёт работу с неинициализированным брокером.

## Пример полной конфигурации

```yaml
spring:
  docker:
    compose:
      lifecycle-management: start_and_stop
      stop:
        command: down
        arguments:
          - "--volumes"
        timeout: 15s
```

Эта конфигурация:
- Запускает контейнеры при старте приложения
- При остановке выполняет `docker compose down --volumes` (удаляет контейнеры, сети и тома)
- Даёт контейнерам 15 секунд на graceful shutdown

## Выбор стратегии для разных сценариев

| Сценарий | lifecycle-management | stop.command | stop.arguments |
|----------|---------------------|-------------|----------------|
| Быстрая разработка, данные не важны | `start_and_stop` | `down` | `--volumes` |
| Разработка, данные нужны между запусками | `start_only` | — | — |
| Несколько приложений, общие сервисы | `start_only` или `none` | — | — |
| Тесты (чистое состояние) | `start_and_stop` | `down` | `--volumes` |
| CI/CD с предзапущенными сервисами | `none` | — | — |

## Практика

1. Запусти приложение с `lifecycle-management: start_and_stop` и убедись, что контейнеры останавливаются после завершения
2. Измени на `start_only`, запусти и останови приложение — проверь, что контейнеры продолжают работать
3. Запусти приложение снова и убедись, что Spring Boot определяет уже запущенные контейнеры (сообщение "There are already Docker Compose services running, skipping startup")
4. Настрой `stop.command: down` с аргументом `--volumes` — проверь, что тома удаляются (данные в базе не сохраняются)
5. Создай в базе таблицу и проверь, что переживает перезапуск: при дефолтном `stop.command: stop` данные на месте, а при `stop.command: down` без `--volumes` — исчезают. Затем добавь именованный том `pgdata` и повтори `down` — теперь данные сохраняются
6. Запусти приложение без healthcheck и с healthcheck для PostgreSQL. Строки `Container my_postgres Waiting` → `Container my_postgres Healthy` `DockerCli` печатает на INFO в обоих случаях — это вывод `up --wait`, а не признак healthcheck. Разница видна в `docker ps`: без healthcheck статус `Up 3 seconds` без суффикса (Compose дождался только запуска контейнера), с healthcheck — `Up 5 seconds (healthy)`. Какие именно команды вызывает интеграция, показывает TRACE для `org.springframework.boot.docker.compose`

## Итоги урока

- `lifecycle-management` определяет, управляет ли Spring Boot контейнерами: `start_and_stop`, `start_only` или `none`
- Команда остановки настраивается через `stop.command` — `stop` сохраняет контейнеры, `down` удаляет их
- Аргумент `--volumes` в списке `stop.arguments` удаляет тома при `down` — полезно для тестов и чистого состояния
- Если контейнеры уже запущены, Spring Boot не перезапускает их — просто читает конфигурацию
- Healthcheck в compose-файле позволяет Spring Boot дождаться реальной готовности сервиса, а не только открытого порта
- Для тестов оптимален режим `start_and_stop` с `down --volumes` — каждый запуск начинается с чистого состояния
- Для разработки часто удобнее `start_only` — контейнеры живут между перезапусками приложения
