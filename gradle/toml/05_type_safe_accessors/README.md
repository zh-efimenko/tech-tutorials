# Урок 5. Type-safe accessors и использование в build-скриптах

## Type-safe accessors

Gradle генерирует type-safe accessors из TOML-файла автоматически. Каждый алиас превращается в свойство объекта `libs`.

### Правила преобразования имён

| TOML-имя | Accessor | Правило |
|----------|----------|---------|
| `spring-boot` | `libs.spring.boot` | Дефис → точка (новый уровень) |
| `spring_boot` | `libs.spring.boot` | Подчёркивание → точка |
| `springBoot` | `libs.springBoot` | camelCase сохраняется |
| `spring-boot-starter-web` | `libs.spring.boot.starter.web` | Каждый дефис — уровень |
| `jackson-dataformatCsv` | `libs.jackson.dataformatCsv` | Дефис → точка, camelCase сохраняется |

### Полная карта accessors

```toml
[versions]
spring-boot = "3.5.3"

[libraries]
spring-boot-starter = { module = "...", version.ref = "spring-boot" }

[bundles]
spring-web = ["spring-boot-starter", "spring-boot-starter-web"]

[plugins]
spring-boot = { id = "org.springframework.boot", version.ref = "spring-boot" }
```

```groovy
// Versions — строковое значение версии
libs.versions.spring.boot.get()           // → "3.5.3"

// Libraries — провайдер зависимости
libs.spring.boot.starter                   // → Provider<MinimalExternalModuleDependency>

// Bundles — провайдер списка зависимостей
libs.bundles.spring.web                    // → Provider<List<MinimalExternalModuleDependency>>

// Plugins — провайдер плагина
libs.plugins.spring.boot                   // → Provider<PluginDependency>
```

## Использование в Groovy DSL

### Блок plugins

```groovy
plugins {
    id 'java'
    alias(libs.plugins.spring.boot)
    alias(libs.plugins.spotless)
    alias(libs.plugins.flyway)
}
```

**Важно**: `alias()` нельзя использовать внутри `if`, циклов или методов — только напрямую в `plugins {}`.

### Блок dependencies

```groovy
dependencies {
    // Библиотеки
    implementation libs.spring.boot.starter.web
    implementation libs.jackson.databind

    // compileOnly / annotationProcessor
    compileOnly libs.lombok
    annotationProcessor libs.lombok

    // runtimeOnly
    runtimeOnly libs.postgresql

    // Бандлы
    testImplementation libs.bundles.testing

    // Проектные зависимости — из каталога не берутся
    implementation project(":common-lib")
}
```

### Блок buildscript

В `buildscript` type-safe accessors доступны для версий:

```groovy
buildscript {
    dependencies {
        // .get() обязателен — возвращает String из Provider
        classpath "org.flywaydb:flyway-database-postgresql:${libs.versions.flyway.get()}"
    }
}
```

> `libs.versions.xxx` возвращает `Provider<String>`. Для получения строки нужен `.get()`.

### Переопределение версии из каталога

```groovy
dependencies {
    // Использовать библиотеку, но с другой версией
    implementation(libs.jackson.databind) {
        version {
            strictly "2.17.0"
        }
    }

    // Исключение транзитивных зависимостей
    implementation(libs.spring.boot.starter.web) {
        exclude group: "org.springframework.boot", module: "spring-boot-starter-tomcat"
    }
}
```

## Использование в Kotlin DSL

### Основные отличия

```kotlin
// Kotlin DSL — скобки обязательны
plugins {
    alias(libs.plugins.spring.boot)
}

dependencies {
    implementation(libs.spring.boot.starter.web)     // скобки
    compileOnly(libs.lombok)
    annotationProcessor(libs.lombok)
    testImplementation(libs.bundles.testing)
}
```

```kotlin
// Доступ к версии
val springBootVersion = libs.versions.spring.boot.get()

// В buildscript
buildscript {
    dependencies {
        classpath("org.flywaydb:flyway-database-postgresql:${libs.versions.flyway.get()}")
    }
}
```

## Конфликт имён: когда accessor совпадает

Если имя библиотеки совпадает с именем бандла или имена создают конфликт accessors:

```toml
[libraries]
spring-boot = { module = "org.springframework.boot:spring-boot", version.ref = "spring-boot" }
spring-boot-starter = { module = "org.springframework.boot:spring-boot-starter", version.ref = "spring-boot" }
```

`libs.spring.boot` — это библиотека `spring-boot` или промежуточный уровень для `spring-boot-starter`?

Gradle решает это так:
- `libs.spring.boot` — обращение к библиотеке `spring-boot`
- `libs.spring.boot.starter` — обращение к библиотеке `spring-boot-starter`

Но если конфликт неразрешим, Gradle выдаёт ошибку при генерации. Избегай ситуаций, когда одно имя является префиксом другого без дочерних элементов.

## Автодополнение в IDE

### IntelliJ IDEA

IntelliJ поддерживает автодополнение для version catalogs:

1. Начинаешь вводить `libs.`
2. IDE показывает доступные библиотеки, бандлы, плагины, версии
3. Ctrl+Click на accessor переходит к определению в TOML

### Требования

- IntelliJ IDEA 2023.1+ (для Groovy DSL)
- Kotlin DSL — автодополнение работает лучше (полная поддержка типов)
- Проект должен быть синхронизирован (Gradle sync)

### Навигация

```
libs.spring.boot.starter.web
│    │                    │
│    └── Ctrl+Click ──────┴── переход к TOML-файлу
│
└── Ctrl+Click → LibrariesForLibs.java (сгенерированный класс)
```

## Паттерн: version catalog + script-плагины

Часто используется комбинация version catalog и script-плагинов:

```
settings.gradle
├── libs from build-config/gradle/libs.versions.toml  ← version catalog
│
build.gradle
├── plugins { alias(libs.plugins.xxx) }               ← плагины из каталога
├── apply from: "build-config/gradle/base.gradle"      ← конфигурация из скрипта
├── apply from: "build-config/gradle/checkstyle.gradle" ← конфигурация из скрипта
├── apply from: "build-config/gradle/modules.gradle"    ← конфигурация из скрипта
```

**Version catalog** управляет *версиями* плагинов и зависимостей.
**Script-плагины** управляют *конфигурацией* (что включить, как настроить).

### Доступ к каталогу из script-плагина

```groovy
// build-config/gradle/openApi.gradle
buildscript {
    dependencies {
        // libs доступен в script-плагинах, если они подключены через apply from:
        classpath "org.openapitools:openapi-generator-gradle-plugin:${libs.versions.open.api.generator.plugin.get()}"
    }
}
```

## Отладка

### Проверить, что каталог загружен

```bash
# Показать все доступные зависимости из каталога
./gradlew dependencies --configuration compileClasspath

# Вывести значение конкретной версии
./gradlew properties | grep -i "libs"
```

### Типичные ошибки

**1. `libs` не найден**
```
Could not find method alias() for arguments [...]
```
Проверь, что TOML-файл указан в `settings.gradle` через `dependencyResolutionManagement.versionCatalogs`.

**2. Accessor не генерируется**
```
Unresolved reference: spring
```
Проверь имя в TOML. Если есть опечатка — accessor не создастся. Выполни Gradle sync в IDE.

**3. alias() вне plugins {}**
```
The alias() method can only be called inside the plugins block
```
`alias()` работает только в `plugins {}`. Для script-плагинов используй `apply plugin:`.

**4. version.ref ссылается на несуществующую версию**
```
Version reference 'xxx' doesn't exist
```
Проверь, что версия объявлена в `[versions]` и имя совпадает точно.

## Практика

1. Создай TOML-файл с несколькими библиотеками, плагинами и бандлом
2. Подключи его в `settings.gradle`
3. Используй accessors в `build.gradle`
4. Проверь автодополнение в IDE (после Gradle sync)
5. Попробуй обратиться к `libs.versions.xxx.get()` в `buildscript`

## Итоги урока

- Type-safe accessors генерируются автоматически из имён в TOML
- Дефисы и подчёркивания → точки, camelCase сохраняется
- `libs.xxx` — библиотека, `libs.plugins.xxx` — плагин, `libs.bundles.xxx` — бандл
- `libs.versions.xxx.get()` — строковое значение версии (для buildscript)
- `alias()` работает только в `plugins {}`, нельзя использовать с `apply`
- IntelliJ поддерживает автодополнение и навигацию для version catalogs
- Версию из каталога можно переопределить через `version { strictly "..." }`
