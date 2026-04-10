# Урок 5. Правила именования

## Зачем автоматизировать конвенции

Соглашения по именованию — первое, что новый разработчик нарушит случайно. Назвал класс `BetManager` вместо `BetService`, положил его в пакет `service` — и IDE не подсказывает, что это нарушение. ArchUnit превращает конвенцию в тест.

## Именование классов по пакету

Самый частый паттерн: классы в определённом пакете должны иметь определённый суффикс.

```java
// Все классы в пакете service должны оканчиваться на Service
@ArchTest
static final ArchRule services_should_be_named_service =
    classes()
        .that().resideInAPackage("..service..")
        .should().haveSimpleNameEndingWith("Service")
        .as("All classes in service package must end with 'Service'")
        .allowEmptyShould(false);

// Все классы в пакете repository должны оканчиваться на Repository
@ArchTest
static final ArchRule repositories_should_be_named_repository =
    classes()
        .that().resideInAPackage("..repository..")
        .should().haveSimpleNameEndingWith("Repository")
        .allowEmptyShould(false);

// Все классы в пакете controller должны оканчиваться на Controller
@ArchTest
static final ArchRule controllers_should_be_named_controller =
    classes()
        .that().resideInAPackage("..controller..")
        .should().haveSimpleNameEndingWith("Controller")
        .allowEmptyShould(false);
```

## Именование по аннотации

Обратное направление: если класс имеет аннотацию, он должен называться определённым образом.

```java
// Если класс аннотирован @Service, его имя должно оканчиваться на Service
@ArchTest
static final ArchRule annotated_with_service_should_be_named_service =
    classes()
        .that().areAnnotatedWith(Service.class)
        .should().haveSimpleNameEndingWith("Service")
        .as("Classes annotated with @Service must end with 'Service'");

// Если аннотирован @RestController — оканчиваться на Controller
@ArchTest
static final ArchRule annotated_with_rest_controller_should_be_named_controller =
    classes()
        .that().areAnnotatedWith(RestController.class)
        .should().haveSimpleNameEndingWith("Controller");

// Если аннотирован @Repository — оканчиваться на Repository
@ArchTest
static final ArchRule annotated_with_repository_should_be_named_repository =
    classes()
        .that().areAnnotatedWith(Repository.class)
        .should().haveSimpleNameEndingWith("Repository");
```

## Именование и размещение в пакете

Связываем имя и расположение: если назвал `BetService` — положи в правильный пакет.

```java
// Классы с суффиксом Service должны находиться в пакете service
@ArchTest
static final ArchRule service_classes_should_reside_in_service_package =
    classes()
        .that().haveSimpleNameEndingWith("Service")
        .should().resideInAPackage("..service..")
        .as("Classes named *Service must live in the service package");

// Классы с суффиксом Controller должны быть в пакете controller
@ArchTest
static final ArchRule controller_classes_should_reside_in_controller_package =
    classes()
        .that().haveSimpleNameEndingWith("Controller")
        .should().resideInAPackage("..controller..");
```

## Именование интерфейсов

```java
// Интерфейсы не должны начинаться с I (антипаттерн IUserService)
@ArchTest
static final ArchRule interfaces_should_not_start_with_I =
    classes()
        .that().areInterfaces()
        .should().haveSimpleNameNotStartingWith("I")
        .as("Interface names must not start with 'I' prefix");

// Все интерфейсы в пакете port должны оканчиваться на Port
@ArchTest
static final ArchRule port_interfaces_should_end_with_port =
    classes()
        .that().resideInAPackage("..port..")
        .and().areInterfaces()
        .should().haveSimpleNameEndingWith("Port");
```

## Regex-паттерны в именовании

Для более сложных конвенций — регулярные выражения:

```java
// Имя должно соответствовать паттерну: начинаться с заглавной буквы
@ArchTest
static final ArchRule classes_should_start_with_uppercase =
    classes()
        .that().areTopLevelClasses()
        .should().haveNameMatching(".*\\.[A-Z].*")
        .as("Top-level class names must start with uppercase");

// DTO классы должны соответствовать паттерну *Request или *Response или *Dto
@ArchTest
static final ArchRule dto_classes_naming =
    classes()
        .that().resideInAPackage("..dto..")
        .should().haveSimpleNameEndingWith("Request")
            .orShould().haveSimpleNameEndingWith("Response")
            .orShould().haveSimpleNameEndingWith("Dto")
        .as("Classes in dto package must end with Request, Response, or Dto");
```

## Именование методов

```java
// Методы @Scheduled должны быть void и называться по схеме schedule* или process*
@ArchTest
static final ArchRule scheduled_methods_naming =
    methods()
        .that().areAnnotatedWith(Scheduled.class)
        .should().haveRawReturnType(void.class)
        .as("@Scheduled methods must return void");
```

> **Важно:** ArchUnit проверяет метаданные метода через байткод, но не сигнатуру по регексу напрямую. Для именования методов нужны кастомные условия (урок 8).

## Именование пакетов

ArchUnit не проверяет имена пакетов напрямую, но через слои можно убедиться, что пакеты с определёнными именами существуют и используются правильно.

Имена пакетов проверяются косвенно: если правило `allowEmptyShould(false)` и предикат `resideInAPackage("..controller..")` падает с "no classes found" — значит пакета с таким именем нет.

## Таблица методов именования

| Метод | Что проверяет |
|-------|--------------|
| `haveSimpleNameEndingWith("X")` | Простое имя класса (без пакета) оканчивается на X |
| `haveSimpleNameStartingWith("X")` | Простое имя начинается с X |
| `haveSimpleNameContaining("X")` | Простое имя содержит X |
| `haveSimpleNameNotEndingWith("X")` | Простое имя НЕ оканчивается на X |
| `haveNameMatching("regex")` | Полное имя (с пакетом) соответствует regex |
| `haveSimpleNameMatching("regex")` | Простое имя соответствует regex |

## Практика

1. Напиши правило: все классы с аннотацией `@Component` должны находиться в пакете `infrastructure` или `config`
2. Создай правило: классы с именем `*Dto` не должны иметь методов (только поля — record или POJO)
3. Напиши двусторонние правила: классы в `..repository..` называются `*Repository`, и классы `*Repository` живут в `..repository..`
4. Добавь правило против антипаттерна: классы с суффиксом `Manager`, `Helper`, `Util` должны находиться в пакете `util` — если у тебя есть такой пакет
5. Напиши правило: все абстрактные классы должны начинаться с `Abstract`
6. Проверь: интерфейсы в проекте не начинаются с `I` (антипаттерн из Java 2000-х)

## Итоги урока

- Именование по пакету (`classes in ..service.. should end with Service`) — самое частое правило, защищает от случайных имён
- Двусторонние правила (имя ↔ пакет) дают полную гарантию: ни неправильного имени, ни неправильного размещения
- `haveSimpleNameEndingWith` работает с простым именем класса, `haveNameMatching` — с полным именем включая пакет
- `orShould()` позволяет описать несколько допустимых вариантов именования для одной категории классов
- `allowEmptyShould(false)` критичен для правил именования — иначе переименование пакета делает правило невидимым
- Антипаттерны именования (IUserService, BetManager, OrderHelper) можно запретить через `haveSimpleNameNotStartingWith` / `haveSimpleNameNotEndingWith`
