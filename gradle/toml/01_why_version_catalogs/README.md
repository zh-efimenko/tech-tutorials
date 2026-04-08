# Урок 1. Зачем нужны Version Catalogs

## Проблема: как управляли версиями раньше

### Строки в build.gradle

Самый примитивный подход — версии прямо в зависимостях:

```groovy
// order-service/build.gradle
dependencies {
    implementation "org.springframework.boot:spring-boot-starter-web:3.5.3"
    implementation "com.fasterxml.jackson.core:jackson-databind:2.18.3"
}

// payment-service/build.gradle
dependencies {
    implementation "org.springframework.boot:spring-boot-starter-web:3.5.3"
    implementation "com.fasterxml.jackson.core:jackson-databind:2.18.3"  // а вдруг тут 2.19.0?
}
```

Проблемы:
- **Дублирование** — одна версия в каждом модуле/сервисе
- **Рассинхронизация** — забыли обновить в одном месте
- **Нет автодополнения** — IDE не подсказывает
- **String-based** — опечатка видна только при сборке

### gradle.properties

```properties
# gradle.properties
spring_boot_version=3.5.3
jackson_version=2.18.3
```

```groovy
dependencies {
    implementation "org.springframework.boot:spring-boot-starter-web:$spring_boot_version"
    implementation "com.fasterxml.jackson.core:jackson-databind:$jackson_version"
}
```

Лучше: версия в одном месте. Но:
- Нет type-safe доступа
- Нет автодополнения для зависимостей
- Нет группировки (бандлов)
- Нет управления плагинами

### ext-блок

```groovy
ext {
    versions = [
        springBoot: "3.5.3",
        jackson: "2.18.3"
    ]
    deps = [
        springBootWeb: "org.springframework.boot:spring-boot-starter-web:${versions.springBoot}",
        jackson: "com.fasterxml.jackson.core:jackson-databind:${versions.jackson}"
    ]
}

dependencies {
    implementation deps.springBootWeb
}
```

Ещё лучше: структура, переменные. Но:
- Нет стандарта — каждый проект делает по-своему
- Не работает с `plugins {}` блоком
- Плохая поддержка в IDE
- Нет Dependabot/Renovate

### buildSrc/Dependencies.kt

```kotlin
object Versions {
    const val springBoot = "3.5.3"
}
object Deps {
    const val springBootWeb = "org.springframework.boot:spring-boot-starter-web:${Versions.springBoot}"
}
```

Ближе всего к идеалу: type-safe, автодополнение. Но:
- Любое изменение версии **перекомпилирует** весь buildSrc → замедляет сборку
- Плагины всё ещё не управляются
- Кастомный формат, нет стандарта

## Решение: Version Catalogs

**Version Catalog** (Gradle 7.0+, стабильный с 7.4.1) — стандартный механизм для централизованного управления зависимостями и плагинами через TOML-файл.

```
gradle/libs.versions.toml     ← один файл
        │
        ▼
  build.gradle
  libs.spring.boot.starter    ← type-safe
  libs.plugins.spring.boot    ← плагины тоже
  libs.bundles.testing         ← группы
```

### Что даёт

| Возможность | gradle.properties | ext {} | buildSrc | **TOML Catalog** |
|---|---|---|---|---|
| Версии в одном месте | Да | Да | Да | **Да** |
| Type-safe accessors | Нет | Нет | Да | **Да** |
| Автодополнение в IDE | Нет | Частично | Да | **Да** |
| Управление плагинами | Нет | Нет | Нет | **Да** |
| Бандлы (группировка) | Нет | Нет | Ручной | **Да** |
| Стандартный формат | Нет | Нет | Нет | **Да** |
| Dependabot/Renovate | Да | Нет | Нет | **Да** |
| Не замедляет сборку | Да | Да | Нет | **Да** |

### Как выглядит

**TOML-файл** (`gradle/libs.versions.toml`):

```toml
[versions]
spring-boot = "3.5.3"
jackson = "2.18.3"

[libraries]
spring-boot-starter-web = { module = "org.springframework.boot:spring-boot-starter-web", version.ref = "spring-boot" }
jackson-databind = { module = "com.fasterxml.jackson.core:jackson-databind", version.ref = "jackson" }

[plugins]
spring-boot = { id = "org.springframework.boot", version.ref = "spring-boot" }
```

**build.gradle**:

```groovy
plugins {
    alias(libs.plugins.spring.boot)        // вместо: id "..." version "..."
}

dependencies {
    implementation libs.spring.boot.starter.web   // вместо строки с GAV
    implementation libs.jackson.databind
}
```

Обновление версии Spring Boot → одно изменение в TOML → все модули подхватывают.

## Минимальные знания Gradle для курса

Если ты уже работаешь с Gradle — пропусти этот раздел.

### Ключевые файлы

| Файл | Роль |
|------|------|
| `build.gradle` | Плагины, зависимости, задачи |
| `settings.gradle` | Имя проекта, модули, **version catalogs** |
| `gradle.properties` | JVM-настройки, пользовательские свойства |
| `gradle/libs.versions.toml` | **Version catalog** (тема этого курса) |

### Блок dependencies (конфигурации)

```groovy
dependencies {
    implementation "..."        // компиляция + runtime
    compileOnly "..."           // только компиляция (Lombok)
    runtimeOnly "..."           // только runtime (JDBC-драйверы)
    annotationProcessor "..."   // процессоры аннотаций
    testImplementation "..."    // тесты
}
```

### Блок plugins

```groovy
plugins {
    id 'java'                                       // core-плагин (без версии)
    id 'org.springframework.boot' version '3.5.3'   // внешний плагин (с версией)
}
```

Именно этот `version '3.5.3'` мы хотим вынести в TOML.

## Практика

Открой `build.gradle` любого своего проекта и посчитай:
1. Сколько зависимостей с захардкоженными версиями?
2. Сколько плагинов с версиями?
3. Есть ли дублирование версий между модулями?

Если ответ больше 3 — version catalog сэкономит время.

## Итоги урока

- Старые подходы (gradle.properties, ext, buildSrc) решают часть проблем, но ни один не даёт всё сразу
- Version Catalog — стандартный формат TOML для управления версиями, зависимостями и плагинами
- Даёт: type-safe accessors, автодополнение, бандлы, управление плагинами, поддержку Dependabot
- Не замедляет сборку (в отличие от buildSrc)
- Файл: `gradle/libs.versions.toml` — Gradle подхватывает автоматически
