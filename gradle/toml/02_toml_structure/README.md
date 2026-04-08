# Урок 2. Структура libs.versions.toml

## Формат TOML

TOML (Tom's Obvious, Minimal Language) — формат конфигурации, похожий на INI, но со строгой спецификацией.

### Основные типы данных

```toml
# Комментарий (строчный)

# Строки
name = "Gradle"
description = 'Version Catalogs'   # одинарные кавычки тоже работают

# Числа
port = 8080
pi = 3.14

# Булевы
enabled = true
```

> В version catalogs используются только **строки** и **inline-таблицы**. Числа, булевы и даты не применяются.

### Таблицы (секции)

```toml
[versions]
spring-boot = "3.5.3"
jackson = "2.18.3"

[libraries]
spring-boot-starter = { module = "org.springframework.boot:spring-boot-starter", version.ref = "spring-boot" }
```

Секция в квадратных скобках (`[versions]`) — это таблица. Все пары ключ-значение до следующей секции принадлежат ей.

### Inline-таблицы

```toml
# Inline-таблица — всё в одной строке, в фигурных скобках
spring-boot-starter = { module = "org.springframework.boot:spring-boot-starter", version.ref = "spring-boot" }

# Эквивалентная запись через группу и имя
spring-boot-starter = { group = "org.springframework.boot", name = "spring-boot-starter", version.ref = "spring-boot" }
```

## Четыре секции

Файл `libs.versions.toml` содержит **четыре секции**. Все необязательные — используй только нужные.

```toml
[versions]       # 1. Переменные с номерами версий
[libraries]      # 2. Зависимости (group:artifact:version)
[bundles]        # 3. Группы зависимостей
[plugins]        # 4. Gradle-плагины
```

### Обзор секций

```toml
[versions]
spring-boot = "3.5.3"
jackson = "2.18.3"
lombok = "1.18.36"

[libraries]
spring-boot-starter-web = { module = "org.springframework.boot:spring-boot-starter-web", version.ref = "spring-boot" }
jackson-databind = { module = "com.fasterxml.jackson.core:jackson-databind", version.ref = "jackson" }
lombok = { module = "org.projectlombok:lombok", version.ref = "lombok" }

[bundles]
spring-web = ["spring-boot-starter-web"]

[plugins]
spring-boot = { id = "org.springframework.boot", version.ref = "spring-boot" }
```

### Как каждая секция используется в build.gradle

```groovy
plugins {
    alias(libs.plugins.spring.boot)                 // [plugins]
}

dependencies {
    implementation libs.spring.boot.starter.web     // [libraries]
    implementation libs.bundles.spring.web          // [bundles]
    compileOnly libs.lombok                         // [libraries]
}

// Доступ к строковому значению версии
println libs.versions.spring.boot.get()             // [versions] → "3.5.3"
```

## Расположение файла

### Стандартное (автоматическое)

```
my-project/
├── gradle/
│   └── libs.versions.toml    ← Gradle находит автоматически
├── build.gradle
└── settings.gradle
```

Gradle ищет `gradle/libs.versions.toml` по умолчанию и создаёт каталог с именем `libs`. Ничего настраивать не нужно.

### Кастомное расположение

Если файл в другом месте — указываешь путь в `settings.gradle`:

```groovy
// settings.gradle
dependencyResolutionManagement {
    versionCatalogs {
        libs {
            from(files("./build-config/gradle/libs.versions.toml"))
        }
    }
}
```

### Несколько каталогов

Можно создать несколько каталогов с разными именами:

```groovy
dependencyResolutionManagement {
    versionCatalogs {
        libs {
            from(files("gradle/libs.versions.toml"))
        }
        testLibs {
            from(files("gradle/test-libs.versions.toml"))
        }
    }
}
```

```groovy
dependencies {
    implementation libs.spring.boot.starter
    testImplementation testLibs.mockito.core
}
```

> На практике одного каталога `libs` достаточно.

## Как Gradle обрабатывает TOML

```
gradle/libs.versions.toml
        │
        ▼
Gradle парсит TOML на фазе Initialization
        │
        ▼
Генерирует класс с type-safe accessors
        │
        ▼
Доступен в build.gradle как объект `libs`
        │
        ├── libs.versions.spring.boot.get()    → String "3.5.3"
        ├── libs.spring.boot.starter.web       → Provider<MinimalExternalModuleDependency>
        ├── libs.plugins.spring.boot           → Provider<PluginDependency>
        └── libs.bundles.spring.web            → Provider<List<MinimalExternalModuleDependency>>
```

## Минимальные рабочие примеры

### Только плагины (если зависимости через BOM)

```toml
[versions]
spring-boot = "3.5.3"
flyway = "11.13.0"

[plugins]
spring-boot = { id = "org.springframework.boot", version.ref = "spring-boot" }
flyway = { id = "org.flywaydb.flyway", version.ref = "flyway" }
```

### Только библиотеки (если плагины без версий)

```toml
[versions]
jackson = "2.18.3"
lombok = "1.18.36"

[libraries]
jackson-databind = { module = "com.fasterxml.jackson.core:jackson-databind", version.ref = "jackson" }
lombok = { module = "org.projectlombok:lombok", version.ref = "lombok" }
```

### Полный каталог

```toml
[versions]
spring-boot = "3.5.3"
jackson = "2.18.3"
lombok = "1.18.36"
testcontainers = "1.20.6"

[libraries]
spring-boot-starter-web = { module = "org.springframework.boot:spring-boot-starter-web", version.ref = "spring-boot" }
spring-boot-starter-test = { module = "org.springframework.boot:spring-boot-starter-test", version.ref = "spring-boot" }
jackson-databind = { module = "com.fasterxml.jackson.core:jackson-databind", version.ref = "jackson" }
lombok = { module = "org.projectlombok:lombok", version.ref = "lombok" }
testcontainers-postgresql = { module = "org.testcontainers:postgresql", version.ref = "testcontainers" }
testcontainers-junit = { module = "org.testcontainers:junit-jupiter", version.ref = "testcontainers" }

[bundles]
testcontainers = ["testcontainers-postgresql", "testcontainers-junit"]

[plugins]
spring-boot = { id = "org.springframework.boot", version.ref = "spring-boot" }
```

## Практика

1. Создай `gradle/libs.versions.toml` с одной версией, одной библиотекой и одним плагином
2. Убери версию из `build.gradle` и замени на accessor (`libs.xxx`)
3. Запусти `./gradlew build` — убедись, что сборка работает
4. Попробуй автодополнение: набери `libs.` в IntelliJ и посмотри подсказки (после Gradle sync)

## Итоги урока

- TOML — простой формат: секции в `[]`, пары ключ-значение, inline-таблицы в `{}`
- Четыре секции: `[versions]`, `[libraries]`, `[bundles]`, `[plugins]` — все необязательные
- Стандартный путь: `gradle/libs.versions.toml` — Gradle подхватывает автоматически
- Кастомный путь — через `dependencyResolutionManagement.versionCatalogs` в `settings.gradle`
- Gradle генерирует type-safe accessors → объект `libs` доступен в build-скриптах
