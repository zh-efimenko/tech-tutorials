# Урок 7. Rich versions, платформы и BOM

## Конфликт версий: почему нужно управление

В реальном проекте десятки зависимостей тянут за собой сотни транзитивных. Ситуация:

```
Ваш проект
├── spring-boot-starter-web    → требует jackson-databind 2.18.3
├── some-library               → требует jackson-databind 2.17.0
└── another-library            → требует jackson-databind 2.16.1
```

Какую версию `jackson-databind` выбрать? Gradle должен **разрешить конфликт**.

### Стратегия Gradle по умолчанию

Gradle выбирает **наивысшую** версию из запрошенных. В примере выше: `2.18.3`.

Это работает в большинстве случаев (библиотеки обратно совместимы). Но иногда нужен явный контроль.

## Rich Versions в TOML

### Модификаторы версий

```toml
[versions]
# Простая версия (интерпретируется как require)
guava = "33.4.0-jre"

# strictly — жёсткое ограничение
commons-lang = { strictly = "3.17.0" }

# require — минимальная версия (может быть повышена)
jedis-min = { require = "4.4.6" }

# prefer — предпочтительная (используется при отсутствии конфликта)
jedis = { require = "[4.4.6,)", prefer = "5.0.1" }

# strictly + prefer — жёсткий диапазон с предпочтением
my-lib = { strictly = "[1.0, 2.0[", prefer = "1.2" }

# reject — запрещённые версии
okhttp = { require = "4.12.0", reject = ["4.11.0", "4.10.0"] }
```

### Иерархия жёсткости (от слабой к сильной)

```
prefer     →  "Хотелось бы эту версию, но не настаиваю"
require    →  "Минимум эта версия, но конфликт-резолюция может повысить"
strictly   →  "Только эта версия/диапазон. Нарушение — ошибка сборки"
reject     →  "Эти версии запрещены. Если выбрана — ошибка сборки"
```

### require (по умолчанию)

```toml
[versions]
guava = "33.4.0-jre"
# Эквивалентно:
# guava = { require = "33.4.0-jre" }
```

Простая строка — это `require`. Gradle может выбрать более высокую версию, если транзитивная зависимость требует её.

```
Ваш проект: require guava 33.4.0-jre
Библиотека X: require guava 33.5.0-jre
→ Результат: guava 33.5.0-jre (повышена)
```

### strictly — жёсткое ограничение

```toml
[versions]
guava = { strictly = "33.4.0-jre" }
```

`strictly` не допускает повышения. Если транзитивная зависимость требует другую версию — ошибка:

```
Ваш проект: strictly guava 33.4.0-jre
Библиотека X: require guava 33.5.0-jre
→ Результат: ОШИБКА — конфликт, strictly запрещает 33.5.0-jre
```

**Когда использовать**: когда точно знаешь, что другая версия сломает проект (breaking changes, баги в конкретной версии).

### strictly с диапазоном

```toml
[versions]
# Разрешены версии от 1.0 (включительно) до 2.0 (не включительно)
my-lib = { strictly = "[1.0, 2.0[" }

# С предпочтением конкретной версии
my-lib = { strictly = "[1.0, 2.0[", prefer = "1.5" }
```

Синтаксис диапазонов:

| Запись | Значение |
|--------|----------|
| `[1.0, 2.0]` | 1.0 <= version <= 2.0 |
| `[1.0, 2.0[` | 1.0 <= version < 2.0 |
| `]1.0, 2.0]` | 1.0 < version <= 2.0 |
| `]1.0, 2.0[` | 1.0 < version < 2.0 |
| `[1.0,)` | version >= 1.0 (без верхней границы) |

### reject — запрет конкретных версий

```toml
[versions]
# Запретить версии с известными багами
jackson = { require = "2.18.3", reject = ["2.18.0", "2.18.1"] }
```

Если конфликт-резолюция выберет запрещённую версию — ошибка сборки.

### Использование rich versions в [libraries]

Rich versions можно указать и в `[libraries]`:

```toml
[libraries]
commons-lang3 = { group = "org.apache.commons", name = "commons-lang3", version = { strictly = "[3.8, 4.0[", prefer = "3.17.0" } }
```

## Платформы (Platforms) и BOM

### Что такое BOM

BOM (Bill of Materials) — специальный POM-файл, который содержит только `<dependencyManagement>`. Он **не добавляет зависимости**, а только **управляет их версиями**.

```xml
<!-- spring-boot-dependencies BOM (упрощённо) -->
<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>com.fasterxml.jackson.core</groupId>
            <artifactId>jackson-databind</artifactId>
            <version>2.18.3</version>
        </dependency>
        <dependency>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
            <version>42.7.5</version>
        </dependency>
        <!-- ... сотни зависимостей ... -->
    </dependencies>
</dependencyManagement>
```

### platform() в Gradle

```groovy
dependencies {
    // Импортирует BOM — управляет версиями
    implementation platform("org.springframework.boot:spring-boot-dependencies:3.5.3")

    // Теперь версии не нужны — BOM их определяет
    implementation "org.springframework.boot:spring-boot-starter-web"     // версия из BOM
    implementation "com.fasterxml.jackson.core:jackson-databind"          // версия из BOM
    runtimeOnly "org.postgresql:postgresql"                               // версия из BOM
}
```

`platform()`:
- Импортирует BOM как **рекомендацию**
- Версии из BOM можно переопределить
- Транзитивные зависимости могут повысить версию

### enforcedPlatform() — жёсткий BOM

```groovy
dependencies {
    // Форсирует версии — даже транзитивные зависимости не могут повысить
    implementation enforcedPlatform("org.springframework.boot:spring-boot-dependencies:3.5.3")

    implementation "org.springframework.boot:spring-boot-starter-web"
    implementation "com.fasterxml.jackson.core:jackson-databind"  // строго 2.18.3, даже если кто-то тянет 2.19.0
}
```

`enforcedPlatform()`:
- Версии из BOM — **жёсткие** (эквивалент `strictly`)
- Транзитивные зависимости **не могут** повысить версию
- Используй осторожно — может сломать библиотеки, которые требуют более новую версию

### platform vs enforcedPlatform

| | `platform()` | `enforcedPlatform()` |
|---|---|---|
| Тип ограничения | `require` (рекомендация) | `strictly` (жёсткое) |
| Повышение транзитивными | Допускается | Запрещено |
| Риск поломки | Низкий | Средний |
| Типичное использование | Spring Boot BOM | Корпоративный BOM с фиксированными версиями |

## Паттерн: кастомный BOM (app-dependencies)

В крупных проектах часто создают кастомный BOM, который объединяет несколько BOM-ов и добавляет внутренние зависимости:

```groovy
// base.gradle
dependencies {
    implementation platform("com.mycompany:app-dependencies:$app_bom_version")
    compileOnly platform("com.mycompany:app-dependencies:$app_bom_version")
    runtimeOnly platform("com.mycompany:app-dependencies:$app_bom_version")
    annotationProcessor platform("com.mycompany:app-dependencies:$app_bom_version")
    testAnnotationProcessor platform("com.mycompany:app-dependencies:$app_bom_version")
    developmentOnly platform("com.mycompany:app-dependencies:$app_bom_version")
}
```

Зачем `platform()` для каждой конфигурации:
- `implementation platform(...)` — управляет версиями implementation-зависимостей
- `compileOnly platform(...)` — управляет версиями compileOnly-зависимостей
- И так далее

Без этого зависимости в `compileOnly`, `annotationProcessor` и других конфигурациях не увидят версии из BOM.

### Создание собственного BOM

```groovy
// app-dependencies/build.gradle
plugins {
    id 'java-platform'
    id 'maven-publish'
}

javaPlatform {
    allowDependencies()  // разрешает импорт других BOM
}

dependencies {
    // Импорт Spring Boot BOM
    api platform("org.springframework.boot:spring-boot-dependencies:3.5.3")

    // Импорт других BOM
    api platform("org.testcontainers:testcontainers-bom:1.20.6")

    // Управление версиями конкретных библиотек
    constraints {
        api "org.mapstruct:mapstruct:1.6.4"
        api "org.mapstruct:mapstruct-processor:1.6.4"
        api "org.instancio:instancio-junit:5.3.1"
    }
}

publishing {
    publications {
        bom(MavenPublication) {
            from components.javaPlatform
        }
    }
}
```

## Version Catalog vs Platform/BOM

| Аспект | Version Catalog (TOML) | Platform/BOM |
|--------|----------------------|-------------|
| Что хранит | Алиасы + версии | Только версии (constraints) |
| Влияние на сборку | Нет (только рекомендация) | Да (влияет на resolution) |
| Автодополнение IDE | Да (type-safe accessors) | Нет |
| Транзитивное влияние | Нет | Да (BOM влияет на транзитивные) |
| Бандлы | Да | Нет |
| Обязательность | Нет (можно не использовать) | Да (если подключен, влияет на все) |

### Когда что использовать

**Version Catalog** — для:
- Централизации алиасов и версий
- Автодополнения в IDE
- Группировки зависимостей (бандлы)

**Platform/BOM** — для:
- Управления версиями транзитивных зависимостей
- Обеспечения совместимости версий в runtime
- Корпоративных стандартов версий

**Вместе** — catalog даёт удобство (алиасы, автодополнение), BOM даёт безопасность (совместимые версии в runtime):

```toml
[libraries]
# Библиотека без версии — версия придёт из BOM
spring-boot-starter-web = { module = "org.springframework.boot:spring-boot-starter-web" }
```

```groovy
dependencies {
    implementation platform("org.springframework.boot:spring-boot-dependencies:3.5.3")
    implementation libs.spring.boot.starter.web  // версия из BOM
}
```

## Диагностика конфликтов версий

### dependencyInsight

```bash
# Узнать, какая версия jackson-databind используется и почему
./gradlew dependencyInsight --configuration runtimeClasspath --dependency jackson-databind
```

Вывод:

```
com.fasterxml.jackson.core:jackson-databind:2.18.3
   variant "runtime" [
      ...
   ]
   Selection reasons:
      - By constraint : platform com.mycompany:app-dependencies:1.0.4
      - By conflict resolution : between versions 2.18.3 and 2.17.0

com.fasterxml.jackson.core:jackson-databind:2.17.0 -> 2.18.3
\--- some-library:1.0.0
     \--- compileClasspath
```

### Полное дерево зависимостей

```bash
# Все зависимости
./gradlew dependencies --configuration runtimeClasspath

# В файл (для анализа)
./gradlew dependencies --configuration runtimeClasspath > deps.txt
```

### Принудительное разрешение конфликта

```groovy
configurations.all {
    resolutionStrategy {
        // Форсировать конкретную версию
        force "com.fasterxml.jackson.core:jackson-databind:2.18.3"

        // Запретить версию
        componentSelection {
            all { selection ->
                if (selection.candidate.module == "log4j-core" && selection.candidate.version == "2.14.0") {
                    selection.reject("CVE-2021-44228")
                }
            }
        }

        // Ошибка при конфликте (не выбирать автоматически)
        failOnVersionConflict()
    }
}
```

## Практика

1. Добавь rich version в TOML и проверь, что strictly блокирует повышение:

```toml
[versions]
guava = { strictly = "33.4.0-jre" }
```

2. Подключи Spring Boot BOM как platform и убери версии из зависимостей:

```groovy
dependencies {
    implementation platform("org.springframework.boot:spring-boot-dependencies:3.5.3")
    implementation "org.springframework.boot:spring-boot-starter-web"  // без версии
}
```

3. Запусти `dependencyInsight` для нескольких зависимостей — изучи, как Gradle разрешает конфликты

## Итоги урока

- Rich versions (`strictly`, `require`, `prefer`, `reject`) дают точный контроль над версиями
- `strictly` — жёсткое ограничение, не допускает повышения транзитивными зависимостями
- `platform()` — импорт BOM как рекомендации, `enforcedPlatform()` — как жёсткого ограничения
- Version Catalog и BOM дополняют друг друга: catalog — удобство, BOM — безопасность
- В крупных проектах: TOML управляет плагинами, кастомный BOM — версиями зависимостей
- `dependencyInsight` — основной инструмент диагностики конфликтов версий
