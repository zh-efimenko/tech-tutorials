# Урок 9. Организация тестов

## Проблема: правила разбросаны по файлам

Когда правил становится больше 10-15, возникают типичные проблемы:
- Дублирование правил в разных тест-классах
- Одно правило изменили в одном месте, забыли в другом
- Непонятно, где искать правило для конкретной категории

Решение — структурировать архитектурные тесты так же аккуратно, как бизнес-логику.

## Общие настройки через мета-аннотацию

Настройки импорта не стоит повторять в каждом тест-классе. Выносить их нужно в собственную аннотацию, помеченную `@AnalyzeClasses`:

```java
// Своя аннотация со всеми настройками импорта
@Retention(RetentionPolicy.RUNTIME)
@AnalyzeClasses(
    packagesOf = Application.class,
    importOptions = ImportOption.DoNotIncludeTests.class
)
public @interface AnalyzeMainClasses {
}
```

```java
// Конкретный тест берёт настройки одной аннотацией
@AnalyzeMainClasses
class LayerArchitectureTest {

    @ArchTest
    static final ArchRule controllers_in_controller_package = ...;
}
```

> **Внимание:** через наследование от базового класса это не работает. `@AnalyzeClasses` не помечена `@Inherited`, и тест-класс, который рассчитывает получить её от абстрактного предка, движком просто не подхватывается — правила не запускаются, а сборка при этом зелёная. Самый опасный сценарий: набор правил есть, тесты «проходят», но не выполняется ни одно. В отчёте такого теста просто нет; единственный след — строчка в логе уровня WARN: `Class ... is not (meta-)annotated with @AnalyzeClasses and thus cannot run as a top level test`. Если в проекте нет других тестов, Gradle 9 дополнительно упадёт с `test task did not discover any tests`.

## Разделение по категориям

Один большой класс `ArchitectureTest` трудно читать. Разбивай по логическим группам:

```
src/test/java/com/example/architecture/
├── AnalyzeMainClasses.java          ← мета-аннотация с общими настройками
├── LayerRulesTest.java              ← правила слоёв
├── NamingRulesTest.java             ← именование
├── DependencyRulesTest.java         ← зависимости и циклы
├── SpringRulesTest.java             ← Spring-аннотации
└── rules/                           ← переиспользуемые правила
    ├── CommonRules.java
    └── SpringAnnotationRules.java
```

## Переиспользуемые правила (библиотека правил)

Если одно правило применяется в нескольких тест-классах — выноси в отдельный класс:

```java
// Общая библиотека правил — не тест-класс, нет @AnalyzeClasses
public final class CommonRules {

    private CommonRules() {}

    // Правило доступно для переиспользования
    public static final ArchRule NO_FIELD_INJECTION =
        noFields()
            .should().beAnnotatedWith(Autowired.class)
            .as("Use constructor injection instead of @Autowired field injection")
            .because("Field injection prevents testing without Spring context");

    public static final ArchRule NO_DEPRECATED_API =
        noClasses()
            .should().dependOnClassesThat()
            .areAnnotatedWith(Deprecated.class)
            .as("Do not use deprecated classes");

    public static final ArchRule NO_SYSTEM_OUT =
        noClasses()
            .should().accessField(System.class, "out")
            .as("Use SLF4J logger instead of System.out");
}
```

```java
// Использование в тест-классе
@AnalyzeMainClasses
class GeneralRulesTest {

    @ArchTest
    static final ArchRule no_field_injection = CommonRules.NO_FIELD_INJECTION;

    @ArchTest
    static final ArchRule no_deprecated = CommonRules.NO_DEPRECATED_API;
}
```

## Коллекции правил через ArchTests

Несколько правил можно объединить в `ArchTests` и подключить как единый набор:

```java
import com.tngtech.archunit.junit.ArchTests;

public final class SpringAnnotationRules {

    @ArchTest
    public static final ArchRule no_field_injection = ...;

    @ArchTest
    public static final ArchRule controllers_have_validated = ...;

    @ArchTest
    public static final ArchRule transactional_methods_must_be_public = ...;
}
```

```java
// Подключение коллекции правил в тест-класс
@AnalyzeMainClasses
class SpringRulesTest {

    @ArchTest
    static final ArchTests spring_rules = ArchTests.in(SpringAnnotationRules.class);
}
```

Все поля с `@ArchTest` из `SpringAnnotationRules` будут запущены как отдельные тесты. Поля **без** `@ArchTest` игнорируются молча: `ArchTests.in(CommonRules.class)` для класса-библиотеки из предыдущего раздела не запустит ни одного правила и не выдаст ошибки. Либо помечай поля `@ArchTest`, либо подключай правила по одному, как в `GeneralRulesTest`.

> **Внимание:** старое имя `ArchRules.in(..)` устарело — используй `ArchTests.in(..)`. Поведение одинаковое, но `ArchRules` остаётся в API только ради обратной совместимости.

## Разделение по модулям в многомодульном проекте

В многомодульном Gradle-проекте архитектурные тесты стоит размещать там, где есть доступ к классам всех модулей.

```
project/
├── bet-service/
│   └── src/test/java/
│       └── architecture/
│           └── BetServiceArchTest.java     ← правила только для bet-service
├── user-service/
│   └── src/test/java/
│       └── architecture/
│           └── UserServiceArchTest.java
└── common-arch-rules/                       ← общий модуль с правилами
    └── src/main/java/
        └── rules/
            ├── CommonRules.java
            └── SpringAnnotationRules.java
```

```groovy
// bet-service/build.gradle
dependencies {
    testImplementation project(':common-arch-rules')
    testImplementation 'com.tngtech.archunit:archunit-junit6:1.5.0'
}
```

## Параметризованные правила

Когда несколько сервисов имеют одну структуру — параметризуй правило:

```java
public static ArchRule layeredArchitectureRule(String basePackage) {
    return Architectures.layeredArchitecture()
        .consideringAllDependencies()
        .layer("Controller").definedBy(basePackage + ".controller..")
        .layer("Service").definedBy(basePackage + ".service..")
        .layer("Repository").definedBy(basePackage + ".repository..")
        .whereLayer("Controller").mayNotBeAccessedByAnyLayer()
        .whereLayer("Service").mayOnlyBeAccessedByLayers("Controller")
        .whereLayer("Repository").mayOnlyBeAccessedByLayers("Service");
}
```

```java
@AnalyzeClasses(packages = "com.example.bet", importOptions = ImportOption.DoNotIncludeTests.class)
class BetServiceArchTest {

    @ArchTest
    static final ArchRule layers = CommonRules.layeredArchitectureRule("com.example.bet");
}
```

## Именование тест-методов и полей

Хорошие имена — документация сами по себе:

```java
// Плохо — непонятно без чтения тела
static final ArchRule rule1 = ...;
static final ArchRule controllers_rule = ...;

// Хорошо — имя = утверждение
static final ArchRule controllers_should_not_access_repositories_directly = ...;
static final ArchRule transactional_annotation_must_be_on_public_methods = ...;
static final ArchRule domain_classes_must_not_depend_on_spring = ...;
```

Имя поля `@ArchTest` становится именем теста в отчёте JUnit.

## Практика

1. Создай мета-аннотацию `@AnalyzeMainClasses` с `@AnalyzeClasses(packagesOf = Application.class)` и повесь её на все существующие тест-классы
2. Разбей правила на классы: `LayerRulesTest`, `NamingRulesTest`, `SpringRulesTest`
3. Выдели `CommonRules` с 3-5 правилами, которые переиспользуются в нескольких тест-классах
4. Попробуй `ArchTests.in(CommonRules.class)` — сначала без `@ArchTest` на полях `CommonRules` (убедись, что не запускается ничего и ошибки нет), потом с `@ArchTest`
5. Переименуй все поля в snake_case с именем-утверждением — посмотри, как изменился JUnit-отчёт
6. Если проект многомодульный — вынеси общие правила в отдельный Gradle-модуль

## Итоги урока

- `@AnalyzeClasses` не наследуется от базового класса — общие настройки выносятся в собственную мета-аннотацию, иначе тесты молча не запускаются
- Разделение по файлам (слои, именование, зависимости, Spring) упрощает навигацию и поиск нужного правила
- Статические поля `public static final ArchRule` в отдельных классах — переиспользуемая библиотека правил
- `ArchTests.in(Class)` подключает все `@ArchTest`-поля из другого класса как единый набор правил (старое имя `ArchRules` устарело)
- Имя поля `@ArchTest` становится именем теста в JUnit-отчёте — используй snake_case с читабельным утверждением
- Параметризованные правила через статические методы позволяют описать один шаблон для нескольких сервисов
