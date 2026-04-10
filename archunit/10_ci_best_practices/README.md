# Урок 10. CI и production практики

## Запуск архитектурных тестов в CI

Архитектурные тесты — обычные JUnit-тесты. В CI они запускаются вместе с остальными:

```bash
./gradlew test
```

Отдельный запуск только архитектурных тестов:

```bash
./gradlew test --tests "*.architecture.*"
```

В Gradle можно создать отдельную задачу для архитектурных тестов:

```groovy
// build.gradle
tasks.register('architectureTest', Test) {
    description = 'Runs architecture tests'
    group = 'verification'

    useJUnitPlatform {
        includeTags 'architecture'
    }

    shouldRunAfter test
}

check.dependsOn architectureTest
```

```java
// В тест-классе пометь тегом
@Tag("architecture")
@AnalyzeClasses(packagesOf = Application.class)
class ArchitectureTest { ... }
```

## Производительность

ArchUnit загружает байткод — это занимает время. Для больших проектов (1000+ классов) первый запуск может занять несколько секунд.

### Кеширование классов

`@AnalyzeClasses` кеширует загруженные классы между тестами в пределах одной JVM-сессии. Все тест-классы с одинаковым `@AnalyzeClasses` разделяют кеш.

```java
// Эти два класса используют один кеш — классы загружаются один раз
@AnalyzeClasses(packagesOf = Application.class)
class LayerRulesTest { ... }

@AnalyzeClasses(packagesOf = Application.class)
class NamingRulesTest { ... }
```

> **Внимание:** если `@AnalyzeClasses` отличается хотя бы одним параметром — создаётся новый кеш. Используй одинаковые настройки во всех тест-классах.

### Ограничение области сканирования

Не нужно загружать весь classpath:

```java
// Плохо — загружает всё, включая библиотеки
new ClassFileImporter().importClasspath()

// Хорошо — только собственный код
@AnalyzeClasses(packagesOf = Application.class, importOptions = DO_NOT_INCLUDE_JARS)
```

## Freeze Violations: как справляться с legacy-нарушениями

Если правило добавляется в проект с уже существующими нарушениями — тест сразу упадёт. Исправить все нарушения сразу не всегда возможно.

**Freeze violations** — механизм "заморозки": ArchUnit запоминает текущие нарушения и считает тест успешным до тех пор, пока нарушений не стало больше. Новые нарушения — тест падает. Старые — допускаются до исправления.

```java
import com.tngtech.archunit.library.freeze.FreezingArchRule;

@ArchTest
static final ArchRule no_field_injection =
    FreezingArchRule.freeze(
        noFields()
            .should().beAnnotatedWith(Autowired.class)
            .as("Use constructor injection")
    );
```

При первом запуске ArchUnit сохраняет список текущих нарушений в файл. При последующих запусках сравнивает: новые нарушения — ошибка, старые — игнорируются.

### Хранение заморозок

По умолчанию заморозки хранятся в `build/` — не сохраняются между сборками. Для правильной работы нужно хранить в `src/test/resources`:

```java
// archunit.properties
archunit.freeze.store.default.path=src/test/resources/archunit-freeze
archunit.freeze.store.default.allowStoreCreation=true
archunit.freeze.store.default.allowStoreUpdate=false  // не обновлять автоматически в CI
```

```
src/test/resources/archunit-freeze/
├── no_field_injection             ← файл с замороженными нарушениями
├── controllers_in_correct_package
└── ...
```

Файлы заморозки нужно закоммитить в git — это часть кодовой базы.

### Обновление заморозок

Когда старое нарушение исправлено — оно само убирается из файла заморозки при следующем запуске (если `allowStoreUpdate=true`). В CI ставь `false`, чтобы разработчики обновляли вручную через флаг:

```bash
# Обновить список замороженных нарушений локально
ARCHUNIT_FREEZE_REFREEZE=true ./gradlew test
```

## archunit.properties: глобальная настройка

Файл `src/test/resources/archunit.properties` настраивает поведение всей библиотеки:

```properties
# Падать, если предикат не нашёл ни одного класса
archunit.allowEmptyShould=false

# Путь для файлов заморозки
archunit.freeze.store.default.path=src/test/resources/archunit-freeze

# Не обновлять заморозки автоматически (обновляй только через env-переменную)
archunit.freeze.store.default.allowStoreUpdate=false

# Создавать новые файлы заморозки если их нет
archunit.freeze.store.default.allowStoreCreation=true
```

`archunit.allowEmptyShould=false` — самая важная настройка. Без неё правила с несуществующими пакетами молча проходят.

## Исключения для конкретных нарушений

Иногда нарушение легитимно и не должно попасть в freeze. Используй `.ignoreDependency()` или кастомный предикат:

```java
@ArchTest
static final ArchRule no_direct_repo_access =
    noClasses()
        .that().resideInAPackage("..controller..")
        .and(not(describe("except BetController for legacy reasons",
            c -> c.getSimpleName().equals("BetController"))))
        .should().dependOnClassesThat()
        .resideInAPackage("..repository..");
```

> **Совет:** добавляй комментарий к каждому исключению с тикетом задачи по рефакторингу. Без контекста через полгода никто не вспомнит, почему исключение существует.

## Приоритеты нарушений

```java
import com.tngtech.archunit.lang.Priority;

ArchRule rule = noClasses()...
    .as("Rule description")
    .withPriority(Priority.HIGH);  // MEDIUM (default), HIGH, LOW
```

Приоритет влияет только на отображение в отчёте, не на то, падает тест или нет.

## Интеграция с отчётами

ArchUnit совместим с JUnit Platform — его результаты автоматически попадают в стандартные JUnit-отчёты (Surefire, Gradle test report, Allure).

Для Allure добавь аннотации к тест-классам:

```java
@Epic("Architecture")
@Feature("Layer rules")
@AnalyzeClasses(packagesOf = Application.class)
class LayerRulesTest { ... }
```

## Типичные проблемы и решения

| Проблема | Причина | Решение |
|----------|---------|---------|
| Тест зелёный, но правило не работает | `allowEmptyShould=true`, пакет не найден | Установи `allowEmptyShould=false` глобально |
| Тест медленный (> 10 сек) | Сканируется весь classpath | Добавь `DO_NOT_INCLUDE_JARS` |
| Freeze-файлы постоянно обновляются в CI | `allowStoreUpdate=true` в CI | Поставь `false` для CI |
| Правила дублируются | Нет базового класса | Вынеси в `CommonRules` и `ArchRules.in()` |
| После рефакторинга пакетов тесты зелёные, но правила сломаны | Предикат `allowEmptyShould=true` | `allowEmptyShould=false` везде |

## Стратегия внедрения в существующий проект

```
1. Добавить archunit-junit5 в зависимости
2. Создать BaseArchitectureTest с @AnalyzeClasses
3. Написать 3-5 базовых правил (слои, запрет field injection, именование)
4. Запустить тесты — зафиксировать нарушения через FreezingArchRule
5. Закоммитить freeze-файлы
6. Настроить archunit.properties
7. Постепенно исправлять замороженные нарушения, убирая их из freeze-файлов
8. Добавлять новые правила по мере усиления контроля
```

## Практика

1. Настрой `archunit.properties` с `allowEmptyShould=false` и путём для freeze-файлов
2. Возьми одно реально нарушаемое правило из проекта и примени `FreezingArchRule.freeze()`
3. Проверь, что freeze-файл создан в правильном месте и закоммичен
4. Добавь Gradle-задачу `architectureTest` с тегом `@Tag("architecture")`
5. Намеренно добавь новое нарушение — убедись, что тест падает, хотя старое нарушение заморожено
6. Исправь старое замороженное нарушение и запусти тест — убедись, что freeze-файл обновился

## Итоги урока

- Архитектурные тесты запускаются через `./gradlew test` — отдельный runner не нужен
- `@AnalyzeClasses` кеширует классы между тестами с одинаковыми настройками — используй одинаковые параметры везде
- `FreezingArchRule.freeze()` — способ внедрить правило в legacy-проект без немедленного исправления всех нарушений
- Freeze-файлы хранятся в `src/test/resources/archunit-freeze/` и коммитятся в git
- `archunit.allowEmptyShould=false` в `archunit.properties` — критически важная настройка для всех проектов
- `allowStoreUpdate=false` в CI предотвращает автоматическое расширение списка замороженных нарушений
- Стратегия внедрения: написал правило → заморозил существующие нарушения → постепенно исправляешь
