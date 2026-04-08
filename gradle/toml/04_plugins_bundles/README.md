# Урок 4. [plugins] и [bundles]

## Секция [plugins]

Секция `[plugins]` объявляет Gradle-плагины с их ID и версиями. Это позволяет управлять версиями плагинов централизованно.

### Формат записи

```toml
[versions]
spring-boot = "3.5.3"
spotless = "7.0.2"
flyway = "11.13.0"

[plugins]
# С ссылкой на [versions]
spring-boot = { id = "org.springframework.boot", version.ref = "spring-boot" }
spotless = { id = "com.diffplug.spotless", version.ref = "spotless" }
flyway = { id = "org.flywaydb.flyway", version.ref = "flyway" }

# С inline-версией
jib = { id = "com.google.cloud.tools.jib", version = "3.4.5" }
```

Каждый плагин содержит:
- `id` — идентификатор плагина (как в `plugins { id "..." }`)
- `version.ref` или `version` — версия

### Использование в build.gradle

```groovy
plugins {
    alias(libs.plugins.spring.boot)    // вместо: id 'org.springframework.boot' version '3.5.3'
    alias(libs.plugins.spotless)       // вместо: id 'com.diffplug.spotless' version '7.0.2'
    alias(libs.plugins.flyway)         // вместо: id 'org.flywaydb.flyway' version '11.13.0'
}
```

### Kotlin DSL

```kotlin
plugins {
    alias(libs.plugins.spring.boot)
    alias(libs.plugins.spotless)
    alias(libs.plugins.flyway)
}
```

> Синтаксис `alias()` одинаковый для Groovy и Kotlin DSL.

### Ограничение: alias() только в plugins {}

`alias()` работает **только** внутри блока `plugins {}`. Нельзя использовать в `apply`:

```groovy
// Правильно
plugins {
    alias(libs.plugins.spring.boot)
}

// Ошибка — alias не работает с apply
apply plugin: libs.plugins.spring.boot  // НЕЛЬЗЯ
```

Для script-плагинов (`.gradle` файлов) нужно использовать `apply plugin:` с ID, а версию получать из каталога:

```groovy
// В script-плагине (файл .gradle)
apply plugin: "org.barfuin.gradle.jacocolog"
// Версия уже зафиксирована в TOML и применена через alias() в корневом build.gradle
```

### Практический пример: каталог плагинов для микросервиса

```toml
[versions]
spring-boot = "3.5.3"
flyway = "11.13.0"
spotless = "7.0.2"
jib = "3.4.5"
jacocolog = "3.1.0"
open-api-generator = "7.11.0"

[plugins]
spring-boot = { id = "org.springframework.boot", version.ref = "spring-boot" }
flyway = { id = "org.flywaydb.flyway", version.ref = "flyway" }
spotless = { id = "com.diffplug.spotless", version.ref = "spotless" }
jib = { id = "com.google.cloud.tools.jib", version.ref = "jib" }
jacocolog = { id = "org.barfuin.gradle.jacocolog", version.ref = "jacocolog" }
open-api-generator = { id = "org.openapi.generator", version.ref = "open-api-generator" }
```

Использование в `build.gradle`:

```groovy
plugins {
    alias(libs.plugins.spring.boot)
    alias(libs.plugins.jacocolog)
    alias(libs.plugins.flyway)
    alias(libs.plugins.spotless)
    alias(libs.plugins.jib)
}
```

### Плагины без версии

Если плагин — core-плагин Gradle (java, java-library, application), его не нужно добавлять в каталог:

```groovy
plugins {
    id 'java'                                  // core-плагин, версия не нужна
    alias(libs.plugins.spring.boot.plugin)     // внешний плагин из каталога
}
```

### Доступ к версии плагина в buildscript

```groovy
buildscript {
    dependencies {
        // .get() возвращает строковое значение версии
        classpath "org.flywaydb:flyway-database-postgresql:${libs.versions.flyway.plugin.get()}"
        classpath "org.openapitools:openapi-generator-gradle-plugin:${libs.versions.open.api.generator.plugin.get()}"
    }
}
```

## Секция [bundles]

**Bundle** — именованная группа библиотек, которые обычно используются вместе. Одна строка в `build.gradle` вместо нескольких.

### Формат записи

```toml
[versions]
spring-boot = "3.5.3"
testcontainers = "1.20.6"

[libraries]
spring-boot-starter = { module = "org.springframework.boot:spring-boot-starter", version.ref = "spring-boot" }
spring-boot-starter-web = { module = "org.springframework.boot:spring-boot-starter-web", version.ref = "spring-boot" }
spring-boot-starter-jdbc = { module = "org.springframework.boot:spring-boot-starter-jdbc", version.ref = "spring-boot" }
spring-boot-starter-test = { module = "org.springframework.boot:spring-boot-starter-test", version.ref = "spring-boot" }
testcontainers-postgresql = { module = "org.testcontainers:postgresql", version.ref = "testcontainers" }
testcontainers-junit = { module = "org.testcontainers:junit-jupiter", version.ref = "testcontainers" }

[bundles]
# Бандл ссылается на алиасы из [libraries]
spring-web = ["spring-boot-starter", "spring-boot-starter-web", "spring-boot-starter-jdbc"]
testcontainers = ["testcontainers-postgresql", "testcontainers-junit"]
```

### Использование в build.gradle

```groovy
dependencies {
    // Одна строка вместо трёх
    implementation libs.bundles.spring.web

    // Эквивалентно:
    // implementation libs.spring.boot.starter
    // implementation libs.spring.boot.starter.web
    // implementation libs.spring.boot.starter.jdbc

    testImplementation libs.bundles.testcontainers
}
```

### Когда использовать бандлы

**Используй бандлы для:**
- Зависимостей, которые всегда идут вместе (`testcontainers-postgresql` + `junit-jupiter`)
- Группы библиотек одного фреймворка (`spring-boot-starter-*`)
- Часто повторяющихся наборов в нескольких модулях

**Не используй бандлы для:**
- Зависимостей, которые иногда используются по отдельности
- Одной-двух зависимостей (нет смысла в бандле)
- Зависимостей с разными конфигурациями (implementation + compileOnly)

### Ограничение: одна конфигурация

Бандл подключается целиком в одну конфигурацию:

```groovy
dependencies {
    // Все библиотеки из бандла идут в implementation
    implementation libs.bundles.spring.web

    // Нельзя часть в implementation, часть в compileOnly
}
```

Если зависимости требуют разных конфигураций (например, Lombok: `compileOnly` + `annotationProcessor`), бандл не подходит:

```groovy
dependencies {
    // Lombok — НЕ бандл, потому что нужны разные конфигурации
    compileOnly libs.lombok
    annotationProcessor libs.lombok
}
```

### Практический пример: полный TOML с бандлами

```toml
[versions]
spring-boot = "3.5.3"
jackson = "2.18.3"
lombok = "1.18.36"
mapstruct = "1.6.4"
testcontainers = "1.20.6"
instancio = "5.3.1"

[libraries]
# Spring Boot
spring-boot-starter = { module = "org.springframework.boot:spring-boot-starter", version.ref = "spring-boot" }
spring-boot-starter-web = { module = "org.springframework.boot:spring-boot-starter-web", version.ref = "spring-boot" }
spring-boot-starter-jdbc = { module = "org.springframework.boot:spring-boot-starter-jdbc", version.ref = "spring-boot" }
spring-boot-starter-aop = { module = "org.springframework.boot:spring-boot-starter-aop", version.ref = "spring-boot" }
spring-boot-starter-test = { module = "org.springframework.boot:spring-boot-starter-test", version.ref = "spring-boot" }
spring-boot-docker-compose = { module = "org.springframework.boot:spring-boot-docker-compose", version.ref = "spring-boot" }

# Jackson
jackson-databind = { module = "com.fasterxml.jackson.core:jackson-databind", version.ref = "jackson" }
jackson-annotations = { module = "com.fasterxml.jackson.core:jackson-annotations", version.ref = "jackson" }
jackson-datatype-jsr310 = { module = "com.fasterxml.jackson.datatype:jackson-datatype-jsr310", version.ref = "jackson" }

# Инструменты
lombok = { module = "org.projectlombok:lombok", version.ref = "lombok" }
mapstruct = { module = "org.mapstruct:mapstruct", version.ref = "mapstruct" }
mapstruct-processor = { module = "org.mapstruct:mapstruct-processor", version.ref = "mapstruct" }

# Тестирование
spring-boot-starter-test = { module = "org.springframework.boot:spring-boot-starter-test", version.ref = "spring-boot" }
testcontainers-postgresql = { module = "org.testcontainers:postgresql", version.ref = "testcontainers" }
testcontainers-junit = { module = "org.testcontainers:junit-jupiter", version.ref = "testcontainers" }
instancio-junit = { module = "org.instancio:instancio-junit", version.ref = "instancio" }

[bundles]
spring-web = ["spring-boot-starter", "spring-boot-starter-web", "spring-boot-starter-aop"]
jackson = ["jackson-databind", "jackson-annotations", "jackson-datatype-jsr310"]
testcontainers = ["testcontainers-postgresql", "testcontainers-junit"]
testing = ["spring-boot-starter-test", "testcontainers-postgresql", "testcontainers-junit", "instancio-junit"]

[plugins]
spring-boot = { id = "org.springframework.boot", version.ref = "spring-boot" }
```

Использование:

```groovy
plugins {
    id 'java'
    alias(libs.plugins.spring.boot)
}

dependencies {
    implementation libs.bundles.spring.web
    implementation libs.bundles.jackson
    implementation libs.spring.boot.starter.jdbc

    compileOnly libs.lombok
    annotationProcessor libs.lombok

    implementation libs.mapstruct
    annotationProcessor libs.mapstruct.processor

    developmentOnly libs.spring.boot.docker.compose

    testImplementation libs.bundles.testing
}
```

## Сравнение секций

| Секция | Содержит | Accessor | Использование |
|--------|----------|----------|---------------|
| `[versions]` | Номера версий | `libs.versions.xxx.get()` | Ссылки из [libraries] и [plugins], buildscript classpath |
| `[libraries]` | GAV-координаты | `libs.xxx` | `implementation`, `compileOnly`, `runtimeOnly`, ... |
| `[plugins]` | Plugin ID + версия | `libs.plugins.xxx` | `alias()` в блоке `plugins {}` |
| `[bundles]` | Группы библиотек | `libs.bundles.xxx` | `implementation`, `testImplementation`, ... |

## Практика

Создай TOML-файл для проекта с Spring Boot, PostgreSQL и тестами:

1. Объяви версии в `[versions]`
2. Добавь библиотеки в `[libraries]`
3. Создай бандлы в `[bundles]` для часто используемых групп
4. Добавь плагины в `[plugins]`
5. Используй каталог в `build.gradle` через type-safe accessors

## Итоги урока

- `[plugins]` — централизованное управление версиями Gradle-плагинов
- `alias(libs.plugins.xxx)` — подключение плагина из каталога в блоке `plugins {}`
- `libs.versions.xxx.get()` — доступ к строковому значению версии (для buildscript classpath)
- `[bundles]` — группировка библиотек, которые всегда используются вместе
- Бандл подключается целиком в одну конфигурацию — не подходит для зависимостей с разными конфигурациями
- Каталог может содержать только `[versions]` и `[plugins]`, если зависимости управляются через BOM
