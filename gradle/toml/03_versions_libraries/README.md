# Урок 3. [versions] и [libraries]

## Секция [versions]

Секция `[versions]` объявляет переменные с номерами версий. Эти переменные используются в `[libraries]` и `[plugins]` через `version.ref`.

### Простые версии

```toml
[versions]
spring-boot = "3.5.3"
jackson = "2.18.3"
lombok = "1.18.36"
mapstruct = "1.6.4"
flyway = "11.13.0"
postgresql = "42.7.5"
```

### Именование версий

- Используй **kebab-case** (через дефис): `spring-boot`, `junit-jupiter`
- Дефисы превращаются в точки для accessor: `spring-boot` → `libs.versions.spring.boot`
- Называй по библиотеке/фреймворку, а не по артефакту

```toml
# Правильно — одна версия для группы библиотек
[versions]
jackson = "2.18.3"

# Неправильно — дублирование версии
[versions]
jackson-databind = "2.18.3"
jackson-annotations = "2.18.3"
jackson-core = "2.18.3"
```

### Rich versions (расширенные версии)

Помимо простой строки, версию можно объявить с ограничениями:

```toml
[versions]
# Простая (интерпретируется как require)
guava = "33.4.0-jre"

# Строгая — не допускает повышения транзитивными зависимостями
commons-lang = { strictly = "3.17.0" }

# Диапазон с предпочтением
jedis = { require = "[4.4.6,)", prefer = "5.0.1" }

# Строгий диапазон с предпочтением
my-lib = { strictly = "[1.0, 2.0[", prefer = "1.2" }

# Отклонение конкретных версий
okhttp = { require = "4.12.0", reject = ["4.11.0", "4.10.0"] }
```

| Модификатор | Описание |
|-------------|----------|
| `require` | Минимальная допустимая версия. Может быть повышена конфликт-резолюцией |
| `strictly` | Жёсткое ограничение. Любая другая версия — ошибка сборки |
| `prefer` | Предпочтительная версия (если нет конфликта) |
| `reject` | Запрещённые версии |

> Rich versions подробно рассмотрены в уроке 7. В большинстве случаев достаточно простых строковых версий.

## Секция [libraries]

Секция `[libraries]` объявляет зависимости — привязывает алиас к GAV-координатам (Group, Artifact, Version).

### Три формата записи

#### 1. module + version.ref (рекомендуемый)

```toml
[versions]
spring-boot = "3.5.3"

[libraries]
spring-boot-starter = { module = "org.springframework.boot:spring-boot-starter", version.ref = "spring-boot" }
spring-boot-starter-web = { module = "org.springframework.boot:spring-boot-starter-web", version.ref = "spring-boot" }
spring-boot-starter-test = { module = "org.springframework.boot:spring-boot-starter-test", version.ref = "spring-boot" }
```

`module` — краткая запись `group:artifact`. `version.ref` — ссылка на `[versions]`.

#### 2. group + name + version.ref

```toml
[libraries]
spring-boot-starter = { group = "org.springframework.boot", name = "spring-boot-starter", version.ref = "spring-boot" }
```

Эквивалентно `module`, но более явная запись.

#### 3. module + version (inline)

```toml
[libraries]
guava = { module = "com.google.guava:guava", version = "33.4.0-jre" }
```

Версия указана напрямую, без ссылки на `[versions]`. Используй для зависимостей с уникальной версией.

#### 4. Без версии

```toml
[libraries]
spring-boot-starter = { module = "org.springframework.boot:spring-boot-starter" }
```

Без версии — версия должна приходить из BOM/platform. Полезно когда используешь `platform()`.

### Именование библиотек

Правила именования (по рекомендациям Gradle):

**1. Первый сегмент — группа/проект**

```toml
[libraries]
# Правильно: первый сегмент = проект
jackson-databind = { module = "com.fasterxml.jackson.core:jackson-databind", version.ref = "jackson" }
jackson-annotations = { module = "com.fasterxml.jackson.core:jackson-annotations", version.ref = "jackson" }
commons-lang3 = { module = "org.apache.commons:commons-lang3", version.ref = "commons-lang" }

# Неправильно: слишком длинные имена с полным path
fasterxml-jackson-core-databind = { ... }
org-apache-commons-lang3 = { ... }
```

**2. Дефисы внутри артефакта → camelCase**

```toml
[libraries]
# Дефис в названии артефакта → camelCase
jackson-dataformatCsv = { module = "com.fasterxml.jackson.dataformat:jackson-dataformat-csv", version.ref = "jackson" }
networknt-jsonSchemaValidator = { module = "com.networknt:json-schema-validator", version.ref = "networknt" }
```

**3. Убирать неявный контекст**

```toml
[libraries]
# Убираем "java" и "sdk" — это Java-проект, это очевидно
aws-core = { module = "com.amazonaws:aws-java-sdk-core", version.ref = "aws" }
# Не: aws-javaSdkCore
```

**4. Плагин как библиотека — суффикс `-plugin`**

```toml
[libraries]
bmuschko-docker-plugin = { module = "com.bmuschko:gradle-docker-plugin", version.ref = "bmuschko-docker" }
```

### Полный пример секции [libraries]

```toml
[versions]
spring-boot = "3.5.3"
jackson = "2.18.3"
lombok = "1.18.36"
mapstruct = "1.6.4"
postgresql = "42.7.5"
testcontainers = "1.20.6"
instancio = "5.3.1"

[libraries]
# Spring Boot
spring-boot-starter = { module = "org.springframework.boot:spring-boot-starter", version.ref = "spring-boot" }
spring-boot-starter-web = { module = "org.springframework.boot:spring-boot-starter-web", version.ref = "spring-boot" }
spring-boot-starter-jdbc = { module = "org.springframework.boot:spring-boot-starter-jdbc", version.ref = "spring-boot" }
spring-boot-starter-test = { module = "org.springframework.boot:spring-boot-starter-test", version.ref = "spring-boot" }
spring-boot-docker-compose = { module = "org.springframework.boot:spring-boot-docker-compose", version.ref = "spring-boot" }

# Jackson
jackson-databind = { module = "com.fasterxml.jackson.core:jackson-databind", version.ref = "jackson" }
jackson-annotations = { module = "com.fasterxml.jackson.core:jackson-annotations", version.ref = "jackson" }

# Инструменты
lombok = { module = "org.projectlombok:lombok", version.ref = "lombok" }
mapstruct = { module = "org.mapstruct:mapstruct", version.ref = "mapstruct" }
mapstruct-processor = { module = "org.mapstruct:mapstruct-processor", version.ref = "mapstruct" }

# БД
postgresql = { module = "org.postgresql:postgresql", version.ref = "postgresql" }

# Тестирование
testcontainers-postgresql = { module = "org.testcontainers:postgresql", version.ref = "testcontainers" }
testcontainers-junit = { module = "org.testcontainers:junit-jupiter", version.ref = "testcontainers" }
instancio-junit = { module = "org.instancio:instancio-junit", version.ref = "instancio" }
```

## Использование в build.gradle

```groovy
dependencies {
    // Библиотека из каталога
    implementation libs.spring.boot.starter.web
    implementation libs.jackson.databind

    // Lombok
    compileOnly libs.lombok
    annotationProcessor libs.lombok

    // MapStruct
    implementation libs.mapstruct
    annotationProcessor libs.mapstruct.processor

    // БД
    runtimeOnly libs.postgresql

    // Тесты
    testImplementation libs.spring.boot.starter.test
    testImplementation libs.testcontainers.postgresql
    testImplementation libs.instancio.junit
}
```

### Kotlin DSL

```kotlin
dependencies {
    implementation(libs.spring.boot.starter.web)
    implementation(libs.jackson.databind)
    compileOnly(libs.lombok)
}
```

### Доступ к версии из каталога

```groovy
// Получить строковое значение версии
def springBootVersion = libs.versions.spring.boot.get()
println "Spring Boot: $springBootVersion"  // 3.5.3

// В buildscript classpath
buildscript {
    dependencies {
        classpath "org.flywaydb:flyway-database-postgresql:${libs.versions.flyway.get()}"
    }
}
```

## Как дефисы превращаются в accessors

Gradle преобразует имена из TOML в type-safe accessors по правилам:

| Символ в TOML | В accessor |
|---------------|------------|
| `-` (дефис) | `.` (точка — новый уровень) |
| `_` (подчёркивание) | `.` (точка — новый уровень) |
| camelCase | Сохраняется |

```toml
[libraries]
spring-boot-starter-web = { ... }     # → libs.spring.boot.starter.web
commons_lang3 = { ... }               # → libs.commons.lang3
jackson-dataformatCsv = { ... }       # → libs.jackson.dataformatCsv
```

> Дефис и подчёркивание обрабатываются одинаково. Gradle рекомендует использовать **дефисы** для единообразия.

## Практика

Создай `gradle/libs.versions.toml` для Spring Boot проекта:

```toml
[versions]
spring-boot = "3.5.3"
lombok = "1.18.36"
postgresql = "42.7.5"

[libraries]
spring-boot-starter-web = { module = "org.springframework.boot:spring-boot-starter-web", version.ref = "spring-boot" }
spring-boot-starter-jdbc = { module = "org.springframework.boot:spring-boot-starter-jdbc", version.ref = "spring-boot" }
spring-boot-starter-test = { module = "org.springframework.boot:spring-boot-starter-test", version.ref = "spring-boot" }
lombok = { module = "org.projectlombok:lombok", version.ref = "lombok" }
postgresql = { module = "org.postgresql:postgresql", version.ref = "postgresql" }
```

Используй в `build.gradle`:

```groovy
dependencies {
    implementation libs.spring.boot.starter.web
    implementation libs.spring.boot.starter.jdbc
    compileOnly libs.lombok
    annotationProcessor libs.lombok
    runtimeOnly libs.postgresql
    testImplementation libs.spring.boot.starter.test
}
```

## Итоги урока

- `[versions]` — переменные с номерами версий, используются через `version.ref`
- `[libraries]` — привязка алиасов к GAV-координатам зависимостей
- Три формата записи: `module + version.ref` (рекомендуемый), `group + name`, `module + version`
- Библиотеки без версии — для зависимостей, управляемых BOM
- Именование: kebab-case, первый сегмент — проект/группа, camelCase для внутренних дефисов
- Дефисы в TOML превращаются в точки в accessor: `spring-boot-starter` → `libs.spring.boot.starter`
- Rich versions (`strictly`, `require`, `prefer`, `reject`) — для продвинутого управления версиями
