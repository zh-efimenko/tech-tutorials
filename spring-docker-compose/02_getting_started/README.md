# Урок 2. Подключение и первый запуск

## Добавление зависимости

Зависимость `spring-boot-docker-compose` подключается через конфигурацию Gradle — `testAndDevelopmentOnly`. Это означает, что она попадает в classpath только при локальном запуске (`bootRun`) и в тестах, но не в итоговый JAR.

```groovy
// build.gradle
dependencies {
    testAndDevelopmentOnly 'org.springframework.boot:spring-boot-docker-compose'
}
```

**Внимание:** не используй `implementation` или `runtimeOnly` — зависимость не должна попадать в production-артефакт.

### Что такое testAndDevelopmentOnly

`testAndDevelopmentOnly` — это **не стандартная конфигурация Gradle**. Её создаёт **Spring Boot Gradle Plugin** при своём применении. Без плагина этой конфигурации нет, и Gradle выдаст ошибку при попытке её использовать.

Поэтому обязательное условие — наличие плагина в `plugins {}`:

```groovy
plugins {
    id 'java'
    id 'org.springframework.boot' version '3.5.3'  // создаёт testAndDevelopmentOnly
}
```

Если по какой-то причине плагин не применён (нестандартная сборка), конфигурацию нужно создать вручную:

```groovy
// Только если Spring Boot Plugin НЕ применён
configurations {
    testAndDevelopmentOnly
    testImplementation.extendsFrom(testAndDevelopmentOnly)
    developmentOnly.extendsFrom(testAndDevelopmentOnly)
}
```

В обычном проекте этого делать не нужно — плагин всё создаёт автоматически.

Сравнение конфигураций, которые создаёт Spring Boot Plugin:

| Конфигурация | bootRun | test | bootJar |
|-------------|---------|------|---------|
| `implementation` | да | да | да |
| `testImplementation` | нет | да | нет |
| `developmentOnly` | да | нет | нет |
| `testAndDevelopmentOnly` | да | да | нет |

`testAndDevelopmentOnly` — идеальный выбор, потому что зависимость нужна и при `bootRun`, и в тестах, но не в production JAR.

## Создание compose-файла

Spring Boot ищет compose-файл в корне проекта. Поддерживаются имена:

- `compose.yaml` (рекомендуемое)
- `compose.yml`
- `docker-compose.yaml`
- `docker-compose.yml`

Создадим минимальный compose-файл с PostgreSQL:

```yaml
# compose.yaml — в корне проекта, рядом с build.gradle
services:
  db:
    image: postgres:17.5
    container_name: my_postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD: myapp
```

**Важно:** порт должен быть пробросом (host:container). Spring Boot читает маппинг портов из `docker compose ps`, чтобы определить, на каком порту доступен сервис.

## Минимальный build.gradle

```groovy
plugins {
    id 'java'
    id 'org.springframework.boot' version '3.5.3'
}

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(25)
    }
}

repositories {
    mavenCentral()
}

dependencies {
    implementation platform(org.springframework.boot.gradle.plugin.SpringBootPlugin.BOM_COORDINATES)

    implementation 'org.springframework.boot:spring-boot-starter-web'
    implementation 'org.springframework.boot:spring-boot-starter-data-jdbc'
    runtimeOnly 'org.postgresql:postgresql'

    testAndDevelopmentOnly 'org.springframework.boot:spring-boot-docker-compose'

    testImplementation 'org.springframework.boot:spring-boot-starter-test'
}

tasks.named('test') {
    useJUnitPlatform()
}
```

## Первый запуск

Запусти приложение:

```bash
./gradlew bootRun
```

В логах появятся строки, показывающие работу Docker Compose интеграции:

```
  .   ____          _            __ _ _
 /\\ / ___'_ __ _ _(_)_ __  __ _ \ \ \ \
...
INFO  --- [main] .s.b.d.c.l.DockerComposeLifecycleManager : Using Docker Compose file 'compose.yaml'
INFO  --- [main] .s.b.d.c.l.DockerComposeLifecycleManager : Docker Compose has been started
```

Spring Boot:
1. Нашёл `compose.yaml` в корне проекта
2. Выполнил `docker compose up`
3. Дождался готовности контейнеров
4. Прочитал информацию о сервисах (образ, порты, переменные окружения)
5. Автоматически настроил `spring.datasource.url`, `spring.datasource.username`, `spring.datasource.password`

## Проверка автоконфигурации

Чтобы убедиться, что properties настроены автоматически, добавь в `application.yml` вывод автосконфигурированных значений:

```yaml
# application.yml
logging:
  level:
    org.springframework.boot.docker.compose: DEBUG
```

В DEBUG-логах ты увидишь, какие connection details были созданы:

```
DEBUG --- JdbcConnectionDetails: Providing JDBC URL: jdbc:postgresql://localhost:5432/myapp
```

Никакого `spring.datasource.url` в application.yml указывать не нужно — Spring Boot извлёк всё из compose-файла.

## Что происходит при остановке

При завершении приложения (Ctrl+C или graceful shutdown) Spring Boot выполняет `docker compose down`:

```
INFO  --- [main] .s.b.d.c.l.DockerComposeLifecycleManager : Docker Compose has been stopped
```

Контейнеры останавливаются и удаляются. Поведение при остановке настраивается — это тема следующего урока.

## Структура проекта

```
my-project/
├── build.gradle
├── compose.yaml                    <-- Docker Compose файл
├── settings.gradle
└── src/
    └── main/
        ├── java/
        │   └── com/example/
        │       └── Main.java
        └── resources/
            └── application.yml     <-- Минимальная конфигурация
```

Spring Boot ищет compose-файл относительно рабочей директории. При запуске через `./gradlew bootRun` рабочая директория — корень проекта, поэтому compose-файл должен лежать рядом с `build.gradle`.

## Практика

1. Создай новый Spring Boot проект с зависимостью `spring-boot-docker-compose`
2. Добавь `compose.yaml` с PostgreSQL (образ `postgres:17.5`)
3. Запусти `./gradlew bootRun` и убедись, что контейнер поднялся автоматически
4. Проверь, что в `docker ps` виден контейнер с PostgreSQL
5. Останови приложение и проверь, что контейнер удалён
6. Переименуй `compose.yaml` в `infra.yaml` и попробуй запустить — убедись, что Spring Boot не находит файл
7. Добавь в `application.yml` свойство `spring.docker.compose.file: infra.yaml` и запусти снова — теперь Spring Boot должен найти файл

## Итоги урока

- Зависимость подключается через `testAndDevelopmentOnly` в Gradle — это гарантирует, что она не попадёт в production JAR
- Spring Boot автоматически находит compose-файл в корне проекта по стандартным именам (`compose.yaml`, `docker-compose.yaml`)
- При `bootRun` Spring Boot выполняет `docker compose up`, при остановке — `docker compose down`
- Подключения к сервисам (DataSource, Redis и т.д.) настраиваются автоматически на основе образов и переменных окружения из compose-файла
- Путь к нестандартному compose-файлу указывается через `spring.docker.compose.file`
- DEBUG-логирование пакета `org.springframework.boot.docker.compose` помогает понять, какие connection details были созданы
