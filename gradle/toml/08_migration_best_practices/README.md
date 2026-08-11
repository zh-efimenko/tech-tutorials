# Урок 8. Миграция, публикация и best practices

## Публикация Version Catalog

Когда каталог нужен не только в одном monorepo, а в нескольких независимых проектах — его можно опубликовать как Maven-артефакт.

### Создание проекта для каталога

```
version-catalog/
├── build.gradle
├── settings.gradle
└── gradle/
    └── libs.versions.toml
```

### settings.gradle

```groovy
rootProject.name = "my-version-catalog"
```

> Блок `dependencyResolutionManagement.versionCatalogs` здесь не нужен и вреден: файл лежит на дефолтном пути, Gradle импортирует его сам, а повторный `from` валит сборку с `you can only call the 'from' method a single time`. За публикацию отвечает блок `catalog {}` в `build.gradle`.

### build.gradle

```groovy
plugins {
    id 'version-catalog'    // генерирует каталог из TOML
    id 'maven-publish'      // публикует артефакт
}

group = "com.mycompany"
version = "1.0.0"

catalog {
    versionCatalog {
        from(files("gradle/libs.versions.toml"))
    }
}

publishing {
    publications {
        maven(MavenPublication) {
            from components.versionCatalog
        }
    }
    repositories {
        maven {
            url = "https://nexus.mycompany.com/repository/maven-releases/"
            credentials {
                username = System.getenv("NEXUS_USERNAME")
                password = System.getenv("NEXUS_PASSWORD")
            }
        }
    }
}
```

### Публикация

```bash
./gradlew publish
```

Gradle генерирует и загружает `libs.versions.toml` как артефакт в Maven-репозиторий.

### Использование опубликованного каталога

```groovy
// settings.gradle потребителя
dependencyResolutionManagement {
    versionCatalogs {
        libs {
            from("com.mycompany:my-version-catalog:1.0.0")
        }
    }
    repositories {
        maven {
            url = "https://nexus.mycompany.com/repository/maven-releases/"
        }
    }
}
```

Теперь в `build.gradle` доступны те же accessors: `libs.spring.boot.starter`, `libs.plugins.spring.boot` и т.д.

### Переопределение версий из опубликованного каталога

```groovy
dependencyResolutionManagement {
    versionCatalogs {
        libs {
            from("com.mycompany:my-version-catalog:1.0.0")

            // Переопределить версию
            version("spring-boot", "4.1.0")

            // Добавить библиотеку, которой нет в каталоге
            library("my-custom-lib", "com.mycompany:custom-lib:2.0.0")
        }
    }
}
```

## Сравнение подходов к шарингу

| Подход | Версионирование | Автономность проектов | Сложность |
|--------|----------------|----------------------|-----------|
| Git submodule (build-config) | Git коммиты | Низкая (привязан к submodule) | Низкая |
| Опубликованный каталог | Семантическое | Высокая | Средняя |
| from(files("../shared/...")) | Нет (всегда latest) | Низкая (monorepo) | Низкая |

## Миграция на Version Catalogs

### С gradle.properties

**До:**

```properties
# gradle.properties
spring_boot_version=4.1.0
jackson_version=3.2.1
```

```groovy
// build.gradle
dependencies {
    implementation "org.springframework.boot:spring-boot-starter-web:$spring_boot_version"
    implementation "tools.jackson.core:jackson-databind:$jackson_version"
}
```

**После:**

```toml
[versions]
spring-boot = "4.1.0"
jackson = "3.2.1"

[libraries]
spring-boot-starter-web = { module = "org.springframework.boot:spring-boot-starter-web", version.ref = "spring-boot" }
jackson-databind = { module = "tools.jackson.core:jackson-databind", version.ref = "jackson" }
```

```groovy
dependencies {
    implementation libs.spring.boot.starter.web
    implementation libs.jackson.databind
}
```

### С ext-блока

**До:**

```groovy
ext {
    springBootVersion = "4.1.0"
    deps = [
        springBootWeb: "org.springframework.boot:spring-boot-starter-web:${springBootVersion}",
        jackson: "tools.jackson.core:jackson-databind:3.2.1"
    ]
}

dependencies {
    implementation deps.springBootWeb
    implementation deps.jackson
}
```

**После:** тот же TOML, что и выше.

### С buildSrc/Dependencies.kt

**До:**

```kotlin
// buildSrc/src/main/kotlin/Dependencies.kt
object Versions {
    const val springBoot = "4.1.0"
}
object Deps {
    const val springBootWeb = "org.springframework.boot:spring-boot-starter-web:${Versions.springBoot}"
}
```

**После:** TOML. Бонус: Gradle не перекомпилирует buildSrc при изменении версий.

### Пошаговый план миграции

1. **Создай `gradle/libs.versions.toml`** с пустыми секциями
2. **Перенеси плагины** из `plugins {}` в `[plugins]` → замени на `alias()`
3. **Перенеси версии** из `gradle.properties` / `ext {}` в `[versions]`
4. **Перенеси зависимости** в `[libraries]` → замени строки на accessors
5. **Сгруппируй** часто используемые зависимости в `[bundles]`
6. **Удали** старые переменные из `gradle.properties` / `ext {}`
7. **Проверь** сборку: `./gradlew clean build`

> Мигрировать можно **постепенно** — TOML и строковые зависимости сосуществуют.

## Best Practices

### 1. Один каталог для проекта

```groovy
// Правильно — settings.gradle пустой: gradle/libs.versions.toml подхватывается автоматически
rootProject.name = "order-service"

// Обычно не нужно — несколько каталогов усложняют
// testLibs, infraLibs, etc.
```

Явный `versionCatalogs { libs { from(files(...)) } }` нужен только когда файл лежит вне дефолтного пути (например, в submodule `build-config/`). Для дефолтного пути это ошибка сборки.

### 2. Версии — в [versions], не inline

```toml
# Правильно — версия объявлена один раз, переиспользуется
[versions]
jackson = "3.2.1"

[libraries]
jackson-databind = { module = "tools.jackson.core:jackson-databind", version.ref = "jackson" }
jackson-core = { module = "tools.jackson.core:jackson-core", version.ref = "jackson" }

# Неправильно — версия дублируется
[libraries]
jackson-databind = { module = "tools.jackson.core:jackson-databind", version = "3.2.1" }
jackson-core = { module = "tools.jackson.core:jackson-core", version = "3.2.1" }
```

Исключение: если зависимость уникальная и версия нигде не переиспользуется, inline допустим.

### 3. Kebab-case для имён

```toml
# Правильно
[libraries]
spring-boot-starter-web = { ... }
jackson-databind = { ... }
commons-lang3 = { ... }

# Неправильно
[libraries]
springBootStarterWeb = { ... }
jackson_databind = { ... }
COMMONS_LANG3 = { ... }
```

### 4. Не хранить не-зависимости

```toml
# Неправильно — TOML для зависимостей, не для конфигурации
[versions]
java-version = "25"                    # Это не зависимость
docker-image-tag = "latest"            # Это не зависимость
max-heap-size = "2g"                   # Это не зависимость
```

### 5. Группировать логически, не алфавитно

```toml
[versions]
# Spring Boot
spring-boot = "4.1.0"

# Serialization
jackson = "3.2.1"
protobuf = "4.35.1"

# Database
flyway = "13.2.0"
postgresql = "42.7.13"

# Testing
testcontainers = "2.0.5"
instancio = "5.6.0"
```

### 6. Комментарии для неочевидного

```toml
[versions]
# Используется в openApi.gradle для генерации кода
open-api-generator = "7.14.0"

# Версия должна совпадать с runtime-версией в Docker (см. compose.yml)
clickhouse-jdbc = "0.9.8"
```

### 7. Не дублировать BOM-версии в каталоге

Если используешь BOM (Spring Boot Dependencies), не нужно дублировать управляемые им версии:

```toml
# Неправильно — эти версии уже управляются Spring Boot BOM
[versions]
jackson = "3.2.1"
postgresql = "42.7.13"
logback = "1.5.34"

# Правильно — в каталоге только то, чем BOM НЕ управляет
[versions]
spring-boot = "4.1.0"          # сам BOM
mapstruct = "1.6.3"            # нет в Spring Boot BOM
instancio = "5.6.0"            # нет в Spring Boot BOM
```

## Anti-Patterns

### 1. Каталог как замена всего

```groovy
// Anti-pattern: каталог не заменяет конфигурацию
// Не пытайся впихнуть в TOML то, что должно быть в build.gradle:
// - repositories
// - compiler arguments
// - test configuration
// - task setup
```

### 2. Слишком мелкие бандлы

```toml
# Anti-pattern — бандл из одной зависимости бессмысленен
[bundles]
postgres = ["postgresql"]

# Anti-pattern — бандл из зависимостей с разными конфигурациями
[bundles]
lombok = ["lombok"]  # нужен compileOnly + annotationProcessor, бандл не поможет
```

### 3. Переусложнение rich versions

```toml
# Anti-pattern — не нужно strictly для каждой зависимости
[versions]
spring-boot = { strictly = "4.1.0" }
jackson = { strictly = "3.2.1" }
lombok = { strictly = "1.18.46" }

# Правильно — strictly только когда есть конкретная причина
[versions]
spring-boot = "4.1.0"
jackson = "3.2.1"
log4j = { strictly = "2.26.1" }  # strictly из-за CVE в старых версиях
```

## Инструменты

### Renovate / Dependabot

Оба инструмента поддерживают `libs.versions.toml` и автоматически создают PR при выходе новых версий.

Renovate `renovate.json`:
```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended"],
  "gradle": {
    "enabled": true
  }
}
```

### version-catalog-update-plugin

Плагин для автоматического обновления версий в TOML:

```groovy
// build.gradle (именно build, не settings — в settings-скрипте плагин не применяется)
plugins {
    id "nl.littlerobots.version-catalog-update" version "1.1.1"
}
```

```bash
# Обновить libs.versions.toml сразу
./gradlew versionCatalogUpdate

# Или в два шага: сначала собрать обновления в gradle/libs.versions.updates.toml,
# отредактировать его руками, оставив только нужное
./gradlew versionCatalogUpdate --interactive

# затем применить отобранное к libs.versions.toml
./gradlew versionCatalogApplyUpdates
```

> Пока `libs.versions.updates.toml` не применён, обычный `versionCatalogUpdate` падает: `... libs.versions.updates.toml exists, did you mean to run the versionCatalogApplyUpdates task to apply the updates?`

### gradle init

Новые проекты, созданные через `gradle init`, автоматически генерируют `libs.versions.toml`:

```bash
gradle init --type java-application --dsl groovy --java-version 25
```

## Чеклист: настройка version catalog для нового проекта

- [ ] Создать `gradle/libs.versions.toml`
- [ ] Определить `[versions]` для всех внешних зависимостей
- [ ] Определить `[libraries]` с `version.ref`
- [ ] Определить `[plugins]` для внешних Gradle-плагинов
- [ ] Сгруппировать часто используемые зависимости в `[bundles]`
- [ ] Заменить строковые зависимости в `build.gradle` на type-safe accessors
- [ ] Заменить `id "..." version "..."` на `alias(libs.plugins.xxx)`
- [ ] Проверить автодополнение в IDE
- [ ] Настроить Renovate/Dependabot для автоматических обновлений
- [ ] Убрать старые переменные из `gradle.properties` / `ext {}`

## Итоги урока

- Каталог можно опубликовать как Maven-артефакт через `version-catalog` + `maven-publish` плагины
- Опубликованный каталог подключается через `from("group:artifact:version")` в `settings.gradle`
- Миграция на TOML — постепенная: старые и новые подходы сосуществуют
- Best practices: один каталог, kebab-case, версии в `[versions]`, логическая группировка
- Anti-patterns: strictly для всего, бандлы из одной зависимости, не-зависимости в каталоге
- Renovate/Dependabot поддерживают автоматическое обновление `libs.versions.toml`
- Version catalog + BOM = удобство (алиасы, IDE) + безопасность (совместимые версии)
