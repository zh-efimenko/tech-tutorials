# Урок 6. Шаринг каталога между проектами

## Проблема: несколько сервисов с общей конфигурацией

Представим проект с несколькими микросервисами. Каждому нужны:
- Одинаковые версии плагинов (Spring Boot, Flyway, Spotless, JaCoCo)
- Одинаковые настройки компилятора (Java 25, `-parameters`)
- Одинаковые правила checkstyle, PMD, spotless
- Одинаковые базовые зависимости (BOM, Lombok, тесты)

Без централизации: дублирование в каждом сервисе, рассинхронизация, drift.

## Решение: build-config как shared config

```
my-platform/
├── order-service/               ← микросервис 1
│   ├── settings.gradle
│   ├── build.gradle
│   └── build-config/            ← git submodule → общая конфигурация
│       ├── build.gradle
│       ├── settings.gradle
│       └── gradle/
│           ├── libs.versions.toml
│           ├── base.gradle
│           ├── checkstyle.gradle
│           ├── jacoco.gradle
│           ├── modules.gradle
│           └── spotless.gradle
├── payment-service/             ← микросервис 2
│   ├── settings.gradle
│   ├── build.gradle
│   └── build-config/            ← тот же git submodule
├── notification-service/        ← микросервис 3
│   └── build-config/            ← тот же git submodule
...
└── build-config/                ← master-копия submodule
```

`build-config/` — git submodule, один и тот же во всех сервисах. Обновление build-config → обновление всех сервисов.

## Git Submodule

### Что такое

Git submodule — ссылка на конкретный коммит другого репозитория. В файловой системе выглядит как обычная папка, но управляется отдельно.

### Как работает

```bash
# Добавление submodule
git submodule add https://github.com/mycompany/build-config.git build-config

# Клонирование проекта с submodule
git clone --recurse-submodules https://github.com/mycompany/order-service.git

# Обновление submodule до последней версии
cd build-config
git pull origin master
cd ..
git add build-config
git commit -m "Update build-config submodule"
```

### Файлы submodule

```
order-service/
├── .gitmodules              ← конфигурация submodule
├── build-config             ← ссылка на коммит в репозитории build-config
```

`.gitmodules`:
```ini
[submodule "build-config"]
    path = build-config
    url = https://github.com/mycompany/build-config.git
```

## Composite Build: includeBuild

### settings.gradle модуля

```groovy
// order-service/settings.gradle
dependencyResolutionManagement {
    versionCatalogs {
        libs {
            from(files("./build-config/gradle/libs.versions.toml"))
        }
    }
}

rootProject.name = "order-service"

includeBuild("build-config")
```

### Что делает каждая строка

**1. `dependencyResolutionManagement.versionCatalogs.libs`**

Загружает TOML-файл из build-config и создаёт каталог `libs`. Теперь в `build.gradle` доступны:
- `libs.plugins.spring.boot`
- `libs.versions.spring.boot.get()`

**2. `rootProject.name = "order-service"`**

Имя корневого проекта. Влияет на имя артефакта и задачи.

**3. `includeBuild("build-config")`**

Подключает build-config как composite build. Gradle обнаруживает его `build.gradle` и `settings.gradle`, но не смешивает задачи — build-config остаётся изолированным проектом.

### Зачем includeBuild, если TOML уже подключен через from(files())?

`from(files())` загружает **только TOML-файл**. `includeBuild()` подключает **весь Gradle-проект** build-config, что позволяет:
- Использовать его артефакты как source dependency (без публикации)
- Ссылаться на build-config как на проект в зависимостях
- Gradle корректно разрешает зависимости между builds

## Структура build-config

### build.gradle (build-config)

```groovy
// Минимальный — build-config сам по себе не собирает приложение
plugins {
    id 'java-platform'
}
```

### settings.gradle (build-config)

```groovy
rootProject.name = "build-config"
```

### Файлы конфигурации в gradle/

Каждый `.gradle` файл — отдельная область ответственности:

| Файл | Назначение |
|------|-----------|
| `libs.versions.toml` | Версии плагинов (version catalog) |
| `base.gradle` | Общие настройки: Java 25, repositories, BOM, Lombok, тесты |
| `modules.gradle` | Настройки модулей: MapStruct, commons, AOP, параллельные тесты |
| `checkstyle.gradle` | Checkstyle + PMD с исключением сгенерированного кода |
| `spotless.gradle` | Форматирование Java-кода (import order, unused imports) |
| `jacoco.gradle` | Покрытие кода с исключениями (domain, model, DTO) |

### Как подключаются script-плагины

```groovy
// order-service/build.gradle
plugins {
    alias(libs.plugins.spring.boot)            // из TOML
    alias(libs.plugins.jacocolog)
    alias(libs.plugins.flyway)
    alias(libs.plugins.spotless)
    alias(libs.plugins.jib)
}

// Script-плагины из build-config
apply from: "$rootDir/build-config/gradle/base.gradle"
apply from: "$rootDir/build-config/gradle/checkstyle.gradle"
apply from: "$rootDir/build-config/gradle/jacoco.gradle"
apply from: "$rootDir/build-config/gradle/modules.gradle"
```

### Разделение ответственности

```
TOML (libs.versions.toml)
    │
    └── Управляет ВЕРСИЯМИ плагинов
        "Какую версию Spring Boot использовать?"
        "Какую версию Spotless использовать?"

Script-плагины (*.gradle)
    │
    └── Управляют КОНФИГУРАЦИЕЙ
        "Какие repositories подключить?"
        "Какие правила checkstyle применить?"
        "Какие зависимости общие для всех модулей?"
```

## Детальный разбор base.gradle

```groovy
allprojects {
    apply plugin: "java"
    group = "com.mycompany"

    repositories {
        mavenLocal()
        mavenCentral()
        maven {
            url = "https://nexus.mycompany.com/repository/maven-releases/"
            credentials {
                username = System.getenv("NEXUS_USERNAME")
                password = System.getenv("NEXUS_PASSWORD")
            }
        }
    }

    // Java 25
    tasks.withType(JavaCompile).configureEach {
        options.release = 25
    }

    // BOM + базовые зависимости
    ext {
        app_bom_version = "1.0.4"
    }

    dependencies {
        implementation platform("com.mycompany:app-dependencies:$app_bom_version")
        compileOnly "org.projectlombok:lombok"
        annotationProcessor "org.projectlombok:lombok"
        testImplementation "org.springframework.boot:spring-boot-starter-test"
    }

    test {
        useJUnitPlatform()
    }
}
```

Один файл — общая конфигурация для **всех** модулей **всех** сервисов.

## Обновление build-config

### Процесс обновления

```bash
# 1. Внести изменения в master-копию build-config
cd my-platform/build-config
# ... редактирование файлов ...
git add . && git commit -m "Update Spring Boot to 3.5.4"
git push

# 2. Обновить submodule в каждом сервисе
cd my-platform/order-service/build-config
git pull origin master
cd ..
git add build-config
git commit -m "Update build-config submodule"
git push

# Повторить для payment-service, notification-service, ...
```

### Автоматизация (скрипт)

```bash
#!/bin/bash
# update-build-config.sh
REPOS=("order-service" "payment-service" "notification-service" "analytics-service")

for repo in "${REPOS[@]}"; do
    echo "Updating $repo..."
    cd "$repo/build-config"
    git pull origin master
    cd ..
    git add build-config
    git commit -m "Update build-config submodule"
    git push
    cd ..
done
```

## Альтернативные подходы к шарингу каталога

### 1. Опубликованный каталог (Maven)

```groovy
// settings.gradle
dependencyResolutionManagement {
    versionCatalogs {
        libs {
            from("com.mycompany:version-catalog:1.0.0")
        }
    }
}
```

Каталог публикуется как Maven-артефакт. Подробнее в уроке 8.

### 2. Локальная ссылка на файл

```groovy
// settings.gradle
dependencyResolutionManagement {
    versionCatalogs {
        libs {
            from(files("../shared-config/gradle/libs.versions.toml"))
        }
    }
}
```

Файл в соседней директории (monorepo).

### 3. Convention Plugins (buildSrc / included build)

```groovy
// settings.gradle
includeBuild("build-logic")

// build-logic/src/main/groovy/my-conventions.gradle
plugins {
    id 'java'
    id 'org.springframework.boot'
}

dependencies {
    implementation platform("org.springframework.boot:spring-boot-dependencies:3.5.3")
}
```

Convention plugins — более "Gradle-native" подход. Script-плагины проще, но менее типобезопасны.

### Сравнение подходов

| Подход | Простота | Типобезопасность | Версионирование |
|--------|----------|-----------------|-----------------|
| Git submodule + script-плагины | Высокая | Низкая | Git commits |
| Опубликованный каталог (Maven) | Средняя | Высокая | Семантическое |
| Convention plugins | Средняя | Высокая | Git commits |
| Monorepo + from(files()) | Высокая | Низкая | Нет (всегда latest) |

## Практика

1. Создай структуру из двух сервисов с общим `build-config`:
   - `service-a/settings.gradle` → `from(files("./build-config/gradle/libs.versions.toml"))`
   - `service-b/settings.gradle` → тот же файл
2. Добавь `base.gradle` с общими зависимостями и настройками
3. Подключи через `apply from:` и убедись, что оба сервиса используют одинаковые версии
4. Измени версию в TOML — проверь, что оба сервиса подхватили изменение

## Итоги урока

- Composite build (`includeBuild`) подключает независимый Gradle-проект в текущую сборку
- Git submodule build-config — единая точка конфигурации для всех микросервисов
- TOML управляет версиями плагинов, script-плагины — конфигурацией (repositories, checkstyle, dependencies)
- `from(files())` загружает TOML, `includeBuild()` подключает весь Gradle-проект
- Обновление build-config = обновление submodule во всех сервисах
- Альтернативы: опубликованный каталог (Maven), convention plugins, monorepo
