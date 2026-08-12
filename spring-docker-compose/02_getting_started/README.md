# Урок 2. Подключение и первый запуск

## Проект, на котором будем работать

Весь курс идёт на одном Gradle-проекте. Если готового нет, собери каркас:

```bash
# вариант 1: Spring Initializr (нужен spring CLI)
spring init --build gradle --java-version 25 --boot-version 4.1.0 \
  --dependencies web,data-jdbc,postgresql my-project

# вариант 2: вручную
mkdir my-project && cd my-project
gradle init --type basic --dsl groovy --project-name my-project
mkdir -p src/main/java/com/example src/main/resources
```

**Про идентификаторы зависимостей:** у Initializr нет id `webmvc` — с ним команда упадёт (`Unknown dependency 'webmvc'`). Пишется `web`, а для Spring Boot 4.1 Initializr сам подставит в `build.gradle` новый артефакт `spring-boot-starter-webmvc`.

**Порядок важен:** `gradle init` отказывается работать в непустой директории (`Aborting build initialization due to existing files in the project directory`), поэтому исходники создаём после него. Wrapper (`gradlew`), `settings.gradle` и `gradle.properties` задача `init` кладёт сама.

Минимум, который должен быть в проекте помимо `build.gradle`:

```groovy
// settings.gradle
rootProject.name = 'my-project'
```

```java
// src/main/java/com/example/Main.java
package com.example;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class Main {

    public static void main(String[] args) {
        SpringApplication.run(Main.class, args);
    }
}
```

Дальше во всех уроках предполагается, что `./gradlew` и класс с `@SpringBootApplication` уже на месте.

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
    id 'org.springframework.boot' version '4.1.0'  // создаёт testAndDevelopmentOnly
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
    image: postgres:18.4
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
    id 'org.springframework.boot' version '4.1.0'
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
    def bom = platform(org.springframework.boot.gradle.plugin.SpringBootPlugin.BOM_COORDINATES)
    implementation bom
    testAndDevelopmentOnly bom   // без этой строки bootJar не соберётся

    implementation 'org.springframework.boot:spring-boot-starter-webmvc'
    implementation 'org.springframework.boot:spring-boot-starter-data-jdbc'
    runtimeOnly 'org.postgresql:postgresql'

    testAndDevelopmentOnly 'org.springframework.boot:spring-boot-docker-compose'

    testImplementation 'org.springframework.boot:spring-boot-starter-test'
}

tasks.named('test') {
    useJUnitPlatform()
}
```

**Внимание:** BOM нужно подключить к каждой конфигурации, которая не наследует `implementation`. `testAndDevelopmentOnly` — как раз такая: если объявить платформу только в `implementation`, версия `spring-boot-docker-compose` останется неизвестной. `bootRun` при этом отработает, а сборка упадёт — в выводе будет причина:

```
> Could not resolve all files for configuration ':testAndDevelopmentOnly'.
   > Could not find org.springframework.boot:spring-boot-docker-compose:.
```

Заголовок ошибки зависит от того, включён ли configuration cache (а `gradle init` включает его в `gradle.properties`): без него это `Execution failed for task ':bootJar'`, с ним — `Configuration cache state could not be cached`. Смотри на вложенную причину, она одна и та же.

**Про Spring Boot 4:** в четвёртой версии стартеры разбиты на модули, поэтому имена изменились. Вместо `spring-boot-starter-web` теперь `spring-boot-starter-webmvc` (старое имя работает, но помечено deprecated). Сама зависимость `spring-boot-docker-compose` и все свойства `spring.docker.compose.*` остались прежними — переход с 3.x на 4.x эту интеграцию не ломает.

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
INFO  --- [main] .s.b.d.c.l.DockerComposeLifecycleManager : Using Docker Compose file /home/user/my-project/compose.yaml
```

Spring Boot:
1. Нашёл `compose.yaml` в рабочей директории
2. Выполнил `docker compose up`
3. Дождался готовности контейнеров
4. Прочитал информацию о сервисах (образ, порты, переменные окружения)
5. Автоматически настроил `spring.datasource.url`, `spring.datasource.username`, `spring.datasource.password`

Хост в URL берётся не из compose-файла, а из активного docker context — на локальной машине это `127.0.0.1`.

## Проверка автоконфигурации

Чтобы убедиться, что параметры подключения взялись из compose-файла, включи логи пула соединений:

```yaml
# application.yml
logging:
  level:
    com.zaxxer.hikari.HikariConfig: DEBUG
```

В логах при старте пула будет виден реальный JDBC URL:

```
DEBUG --- com.zaxxer.hikari.HikariConfig : jdbcUrl.....................jdbc:postgresql://127.0.0.1:5432/myapp
```

Никакого `spring.datasource.url` в application.yml указывать не нужно — Spring Boot извлёк всё из compose-файла.

## Что происходит при остановке

При завершении приложения (Ctrl+C или graceful shutdown) Spring Boot по умолчанию выполняет `docker compose stop`. Контейнеры останавливаются, но не удаляются — при следующем запуске они поднимутся с тем же состоянием данных. Команду остановки можно поменять на `down` — это тема следующего урока.

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
2. Добавь `compose.yaml` с PostgreSQL (образ `postgres:18.4`)
3. Запусти `./gradlew bootRun` и убедись, что контейнер поднялся автоматически
4. Проверь, что в `docker ps` виден контейнер с PostgreSQL
5. Останови приложение и проверь через `docker ps -a`, что контейнер остановлен (но не удалён)
6. Переименуй `compose.yaml` в `infra.yaml` и попробуй запустить — приложение не стартует вовсе: `java.lang.IllegalStateException: No Docker Compose file found in directory '<путь к проекту>/.'` и `BUILD FAILED`
7. Добавь в `application.yml` свойство `spring.docker.compose.file: infra.yaml` и запусти снова — теперь Spring Boot должен найти файл

## Итоги урока

- Зависимость подключается через `testAndDevelopmentOnly` в Gradle — это гарантирует, что она не попадёт в production JAR
- Spring Boot автоматически находит compose-файл в корне проекта по стандартным именам (`compose.yaml`, `docker-compose.yaml`)
- При `bootRun` Spring Boot выполняет `docker compose up`, при остановке — `docker compose stop`
- Подключения к сервисам (DataSource, Redis и т.д.) настраиваются автоматически на основе образов и переменных окружения из compose-файла
- Путь к нестандартному compose-файлу указывается через `spring.docker.compose.file`
- TRACE-логирование пакета `org.springframework.boot.docker.compose` показывает, какой файл найден и какие команды Docker выполняются
