# Урок 10. CI и production практики

## Запуск архитектурных тестов в CI

Архитектурные тесты — обычные JUnit-тесты. В CI они запускаются вместе с остальными:

```bash
./gradlew test
```

Фильтр Gradle `--tests` архитектурные тесты не отбирает: их запускает собственный `TestEngine` ArchUnit, и при любом `--tests` выполнятся все `@ArchTest` из всех классов. Отдельно запустить подмножество можно двумя способами: тегами (см. ниже) или через `archunit.properties`:

```properties
# Запустить только правила с такими именами полей/методов (через запятую)
junit.testFilter=no_field_injection,controllers_in_correct_package
```

В Gradle можно создать отдельную задачу для архитектурных тестов:

```groovy
// build.gradle
def architectureTest = tasks.register('architectureTest', Test) {
    description = 'Runs architecture tests'
    group = 'verification'

    testClassesDirs = sourceSets.test.output.classesDirs
    classpath = sourceSets.test.runtimeClasspath

    useJUnitPlatform {
        includeTags 'architecture'
    }

    shouldRunAfter tasks.named('test')
}

tasks.named('check') {
    dependsOn architectureTest
}
```

> **Важно:** в Gradle 9 конфигурационный кеш — предпочтительный режим (в новых проектах из `gradle init` включён сразу), и несовместимые с ним API постепенно удаляются. Регистрируй задачи через `tasks.register` и обращайся к ним через `tasks.named`, а не через прямые ссылки (`check.dependsOn architectureTest`). Своей задаче типа `Test` обязательно задай `testClassesDirs` и `classpath` — по умолчанию они пустые, и задача пройдёт зелёной, не запустив ни одного теста.

```java
// В тест-классе пометь тегом
import com.tngtech.archunit.junit.ArchTag;

@ArchTag("architecture")
@AnalyzeClasses(packagesOf = Application.class)
class ArchitectureTest { ... }
```

> **Важно:** тег ставится через `@ArchTag`, а не через `@Tag` из JUnit. Движок ArchUnit `@Tag` не читает: класс с `@Tag("architecture")` в задачу с `includeTags 'architecture'` не попадёт, задача отработает вхолостую и покажет `BUILD SUCCESSFUL`, не проверив ни одного правила. `@ArchTag` можно вешать и на класс, и на отдельное `@ArchTest`-поле.

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
@AnalyzeClasses(
    packagesOf = Application.class,
    importOptions = {ImportOption.DoNotIncludeJars.class, ImportOption.DoNotIncludeTests.class}
)
```

> **Важно:** `@AnalyzeClasses` принимает **классы** опций (`ImportOption.DoNotIncludeJars.class`), а константы `ImportOption.Predefined.DO_NOT_INCLUDE_JARS` — только для `ClassFileImporter.withImportOption(..)`. Перепутать их — ошибка компиляции.

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

По умолчанию стор создаётся в директории `archunit_store` в рабочей директории процесса (для Gradle — корень проекта), причём создание нового стора по умолчанию запрещено. Оба значения задаются в `archunit.properties`:

```properties
# src/test/resources/archunit.properties
freeze.store.default.path=src/test/resources/archunit-freeze
freeze.store.default.allowStoreCreation=true
freeze.store.default.allowStoreUpdate=true
```

Внутри стор выглядит так:

```
src/test/resources/archunit-freeze/
├── stored.rules                              ← индекс: описание правила → имя файла
├── c82fc865-379e-4587-860a-9cbd27859f7c      ← нарушения одного правила
└── ...
```

Имена файлов — UUID, а не имена правил; сопоставление хранится в `stored.rules`. Весь каталог нужно закоммитить в git — это часть кодовой базы.

### Обновление заморозок

Когда старое нарушение исправлено — оно само убирается из стора при следующем запуске, если `allowStoreUpdate=true`.

> **Внимание:** `allowStoreUpdate=false` запрещает не только «расползание» списка, но и первичную запись: первый же прогон нового замороженного правила упадёт с `StoreUpdateFailedException`. Порядок такой — заморозил правило и закоммитил стор с `allowStoreUpdate=true`, и только потом, при желании, выставил `false` для CI.

Полное переписывание стора («перезаморозить всё как есть») включается свойством `freeze.refreeze=true`. Оно требует `allowStoreUpdate=true` и передаётся как system property — а Gradle системные свойства в тестовую JVM сам не пробрасывает, это нужно прописать в задаче:

```groovy
tasks.named('test') {
    useJUnitPlatform()
    systemProperty 'archunit.freeze.refreeze', findProperty('refreeze') ?: 'false'
}
```

```bash
# Перезаморозить текущее состояние локально
./gradlew test -Prefreeze=true
```

## archunit.properties: глобальная настройка

Файл `src/test/resources/archunit.properties` настраивает поведение всей библиотеки:

```properties
# Путь для стора заморозок
freeze.store.default.path=src/test/resources/archunit-freeze

# Создавать стор, если его ещё нет (по умолчанию false)
freeze.store.default.allowStoreCreation=true

# Разрешить запись в стор (по умолчанию true; false запрещает и первичную запись)
freeze.store.default.allowStoreUpdate=true

# Разрешить правилам с пустым результатом .that() проходить (по умолчанию они падают)
# archRule.failOnEmptyShould=false
```

> **Внимание:** есть соблазн добавить сюда `resolveMissingDependenciesFromClassPath=false` ради скорости. Не делай этого вслепую: без дорезолвинга ArchUnit не видит суперклассы и мета-аннотации классов вне импортируемых пакетов, и правила вида `beAssignableTo(Repository.class)` или `areMetaAnnotatedWith(Component.class)` начинают выдавать ложные нарушения либо не находить классов вовсе.

> **Внимание:** ключи пишутся **без** префикса `archunit.` — префикс нужен только при передаче того же свойства как system property (`-Darchunit.freeze.refreeze=true`). Ключ с лишним префиксом молча игнорируется, и настройка не действует: именно так и выглядит «настроил, а ничего не изменилось».

`archRule.failOnEmptyShould` трогать не нужно: значение по умолчанию (`true`) — то, что нужно в проекте. Правило, чей `.that()` ничего не нашёл, падает, и переименование пакета не превращает набор правил в декорацию.

## Исключения для конкретных нарушений

Иногда нарушение легитимно и не должно попасть в freeze. Используй `.ignoreDependency()` или кастомный предикат:

```java
import static com.tngtech.archunit.base.DescribedPredicate.describe;
import static com.tngtech.archunit.base.DescribedPredicate.not;

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
import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.priority;

// Приоритет задаётся в начале правила, а не в конце
ArchRule rule = priority(Priority.HIGH)   // MEDIUM (default), HIGH, LOW
    .noClasses().that()...
    .as("Rule description");
```

Метода `withPriority(..)` на `ArchRule` нет — приоритет выбирается стартовой точкой `ArchRuleDefinition.priority(..)`, после которой идут `classes()` / `noClasses()` / `fields()` и так далее.

Приоритет влияет только на отображение в отчёте (`Architecture Violation [Priority: HIGH]`), не на то, падает тест или нет.

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
| Сборка зелёная, но не выполнилось ни одного правила | `@AnalyzeClasses` ждали по наследству от базового класса | Мета-аннотация с `@AnalyzeClasses` на каждом тест-классе (урок 9) |
| Задача с `includeTags` ничего не запускает | Тег поставлен через JUnit-овый `@Tag` | `@ArchTag("architecture")` |
| Настройка в `archunit.properties` не действует | Лишний префикс `archunit.` в ключе | Убрать префикс: `freeze.store.default.path`, `archRule.failOnEmptyShould` |
| Первая заморозка падает с `StoreUpdateFailedException` | `allowStoreUpdate=false` до создания стора | Создать стор с `true`, закоммитить, потом ставить `false` |
| Тест медленный (> 10 сек) | Сканируется весь classpath | `ImportOption.DoNotIncludeJars.class`, сузить пакеты в `@AnalyzeClasses` |
| Правила дублируются | Нет общей библиотеки правил | Вынеси в `CommonRules` и `ArchTests.in()` |
| `beAssignableTo` / `areMetaAnnotatedWith` дают ложные нарушения | Выключен `resolveMissingDependenciesFromClassPath` | Вернуть значение по умолчанию (`true`) |

## Стратегия внедрения в существующий проект

```
1. Добавить archunit-junit5 / archunit-junit6 в зависимости
2. Создать мета-аннотацию @AnalyzeMainClasses с @AnalyzeClasses
3. Написать 3-5 базовых правил (слои, запрет field injection, именование)
4. Запустить тесты — зафиксировать нарушения через FreezingArchRule
5. Закоммитить freeze-файлы
6. Настроить archunit.properties
7. Постепенно исправлять замороженные нарушения, убирая их из freeze-файлов
8. Добавлять новые правила по мере усиления контроля
```

## Практика

1. Настрой `archunit.properties` с путём для стора заморозок — и проверь, что он реально применился (стор создался там, где указано, а не в `archunit_store`)
2. Возьми одно реально нарушаемое правило из проекта и примени `FreezingArchRule.freeze()`
3. Проверь, что freeze-файл создан в правильном месте и закоммичен
4. Добавь Gradle-задачу `architectureTest` с тегом `@ArchTag("architecture")` — и убедись, что она действительно запускает правила, а не завершается вхолостую
5. Намеренно добавь новое нарушение — убедись, что тест падает, хотя старое нарушение заморожено
6. Исправь старое замороженное нарушение и запусти тест — убедись, что стор обновился (при `allowStoreUpdate=true`)

## Итоги урока

- Архитектурные тесты запускаются через `./gradlew test` — отдельный runner не нужен, но фильтр `--tests` на них не действует: подмножество отбирается через `@ArchTag` или `junit.testFilter`
- `@AnalyzeClasses` кеширует классы между тестами с одинаковыми настройками — используй одинаковые параметры везде
- `FreezingArchRule.freeze()` — способ внедрить правило в legacy-проект без немедленного исправления всех нарушений
- Стор заморозок (`stored.rules` + файлы с UUID-именами) хранится в `src/test/resources/archunit-freeze/` и коммитится в git
- Ключи в `archunit.properties` пишутся без префикса `archunit.` — с префиксом настройка молча игнорируется
- `allowStoreUpdate=false` в CI предотвращает автоматическое расширение списка замороженных нарушений, но стор должен быть создан заранее — иначе первый прогон падает
- Стратегия внедрения: написал правило → заморозил существующие нарушения → постепенно исправляешь
