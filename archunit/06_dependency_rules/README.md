# Урок 6. Правила зависимостей

## Виды зависимостей, которые видит ArchUnit

ArchUnit фиксирует зависимость между двумя классами, если один из них:
- объявляет поле типа другого
- использует другой как параметр или возвращаемый тип метода
- вызывает метод или конструктор другого
- наследует или реализует другой
- использует другой как тип в аннотации

Это позволяет проверять не только явные импорты, но и косвенные зависимости через дженерики (`List<BetEntity>`) и аннотации (`@ConditionalOnBean(BetRepository.class)`).

## Запрет конкретных зависимостей

```java
// Нельзя использовать Lombok в domain-классах
@ArchTest
static final ArchRule domain_should_not_use_lombok =
    noClasses()
        .that().resideInAPackage("..domain..")
        .should().dependOnClassesThat()
        .resideInAPackage("lombok..")
        .as("Domain classes must not depend on Lombok")
        .because("Domain must be a pure Java model without framework dependencies");

// Нельзя использовать jakarta.persistence в сервисах
@ArchTest
static final ArchRule services_should_not_use_jpa_directly =
    noClasses()
        .that().resideInAPackage("..service..")
        .should().dependOnClassesThat()
        .resideInAPackage("jakarta.persistence..")
        .as("Services must not use JPA annotations directly — use repositories");
```

## Запрет конкретных классов

Когда нужно запретить не пакет, а конкретный класс:

```java
// Запрет использования System.out напрямую
@ArchTest
static final ArchRule no_system_out_println =
    noClasses()
        .should().callMethod(System.class, "out")
        .as("Use a logger instead of System.out");

// Запрет использования устаревшего класса
@ArchTest
static final ArchRule no_legacy_http_client =
    noClasses()
        .should().dependOnClassesThat().haveFullyQualifiedName("java.net.HttpURLConnection")
        .as("Use WebClient or RestClient instead of HttpURLConnection");
```

## Ограничение исходящих зависимостей

`onlyDependOnClassesThat` — самое строгое правило: класс может зависеть ТОЛЬКО от перечисленных пакетов.

```java
// Domain-классы зависят только от JDK и самих себя
@ArchTest
static final ArchRule domain_has_no_external_dependencies =
    classes()
        .that().resideInAPackage("..domain..")
        .should().onlyDependOnClassesThat()
        .resideInAnyPackage(
            "..domain..",    // сам себя
            "java..",        // JDK
            "jakarta..",     // Jakarta API (только интерфейсы, не реализации)
            "org.slf4j.."    // логирование — допустимо
        )
        .as("Domain classes must be framework-agnostic");
```

> **Внимание:** `onlyDependOnClassesThat` очень строгий. Если пропустить хотя бы один легитимный пакет (например, `kotlin..` в Kotlin-проекте), правило начнёт падать ложно. Начни с `noClasses().should().dependOnClassesThat()` — он мягче.

## Запрет конкретных импортов через имя класса

```java
// Запрет использования Apache Commons Lang (замени на Guava или JDK)
@ArchTest
static final ArchRule no_apache_commons_lang =
    noClasses()
        .should().dependOnClassesThat()
        .haveNameMatching("org\\.apache\\.commons\\.lang.*")
        .as("Use JDK or Guava instead of Apache Commons Lang");

// Запрет ObjectMapper в слое domain
@ArchTest
static final ArchRule domain_should_not_use_jackson =
    noClasses()
        .that().resideInAPackage("..domain..")
        .should().dependOnClassesThat()
        .haveNameMatching("com\\.fasterxml\\.jackson.*");
```

## Циклические зависимости между пакетами

Циклы убивают возможность изолированной компиляции и тестирования модулей. ArchUnit умеет их находить:

```java
import com.tngtech.archunit.library.dependencies.SlicesRuleDefinition;

// Нет циклов между пакетами первого уровня
@ArchTest
static final ArchRule no_cycles_between_packages =
    SlicesRuleDefinition.slices()
        .matching("com.example.(*)..")  // группируем по первому сегменту
        .should().beFreeOfCycles()
        .as("No cyclic dependencies between top-level packages");
```

`matching("com.example.(*)..")` — `(*)` захватывает первый сегмент пакета и группирует классы по нему. Получается "срез" (slice): один срез = один пакет первого уровня.

```
com.example.service    → срез "service"
com.example.repository → срез "repository"
com.example.domain     → срез "domain"
```

Если `service` зависит от `repository`, а `repository` зависит от `service` — это цикл, тест упадёт.

### Более детальные срезы

```java
// Группировать по двум уровням пакета
SlicesRuleDefinition.slices()
    .matching("com.example.(*).(*)..")
    .should().beFreeOfCycles()
```

### Игнорировать определённые срезы

```java
SlicesRuleDefinition.slices()
    .matching("com.example.(*)..")
    .that(not(nameMatching("test")))  // исключить срез "test"
    .should().beFreeOfCycles()
```

## Зависимости через поля vs через методы

ArchUnit различает виды зависимостей:

```java
// Только через поля (например, @Autowired поля)
noClasses()
    .that().resideInAPackage("..controller..")
    .should().haveAFieldOfType(resideInPackage("..repository.."))

// Через вызовы методов (обращение к статическим методам утилит)
noClasses()
    .should().callMethodWhere(target().getDeclaringClass().resideInPackage("..internal.."))
```

Для большинства правил `dependOnClassesThat` достаточен — он покрывает все виды зависимостей. Конкретные виды нужны для точечных правил.

## Практика

1. Напиши правило: классы в `..domain..` не зависят от `org.springframework..`
2. Создай правило против `System.out.println` — используй `callMethod`
3. Проверь наличие циклов между пакетами своего сервиса через `beFreeOfCycles()`
4. Напиши правило `onlyDependOnClassesThat` для domain-классов — начни с минимального набора пакетов и добавляй, пока тест не позеленеет
5. Запрети использование `java.util.Date` и `java.sql.Date` (замена: `java.time.*`):

```java
noClasses().should().dependOnClassesThat()
    .haveFullyQualifiedName("java.util.Date")
    .orShould().dependOnClassesThat()
    .haveFullyQualifiedName("java.sql.Date")
    .as("Use java.time types instead of legacy Date");
```

6. Найди реальный цикл зависимостей в проекте (если есть) — зафиксируй его и создай правило

## Итоги урока

- ArchUnit видит все виды зависимостей: поля, параметры, возвращаемые типы, вызовы методов, аннотации, наследование
- `noClasses().should().dependOnClassesThat()` — запрет конкретного пакета или класса, мягкое правило
- `onlyDependOnClassesThat()` — белый список зависимостей, строгое правило; пропуск одного легитимного пакета вызовет ложные падения
- `beFreeOfCycles()` находит циклы между срезами (slices) — группировка задаётся через `matching()`
- `(*)` в паттерне срезов — захватывает один сегмент пакета для группировки
- Запрет устаревших API (`java.util.Date`, `HttpURLConnection`) — простой способ принудительно перейти на современные альтернативы
