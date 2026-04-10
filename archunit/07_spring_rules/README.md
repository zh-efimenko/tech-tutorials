# Урок 7. Spring-специфичные правила

## Зачем проверять Spring-аннотации

Spring Boot строится на конвенциях: `@Service` значит бизнес-логика, `@Repository` — доступ к данным, `@Transactional` — работа в транзакции. Эти конвенции не проверяются компилятором — только ревью.

ArchUnit позволяет автоматически проверить, что аннотации используются правильно: нет `@Transactional` на контроллерах, нет `@Autowired` на полях, все `@RestController` защищены валидацией.

## Правила для контроллеров

```java
// Все @RestController должны быть в пакете controller
@ArchTest
static final ArchRule rest_controllers_in_controller_package =
    classes()
        .that().areAnnotatedWith(RestController.class)
        .should().resideInAPackage("..controller..")
        .as("@RestController classes must reside in the controller package");

// Контроллеры не должны быть аннотированы @Transactional
// — транзакции управляются в сервисном слое
@ArchTest
static final ArchRule controllers_should_not_be_transactional =
    noClasses()
        .that().areAnnotatedWith(RestController.class)
        .should().beAnnotatedWith(Transactional.class)
        .as("Controllers must not be @Transactional — move transactions to service layer");

// Контроллеры должны иметь @Validated для автоматической валидации входных данных
@ArchTest
static final ArchRule controllers_should_have_validated =
    classes()
        .that().areAnnotatedWith(RestController.class)
        .should().beAnnotatedWith(Validated.class)
        .as("@RestController must be annotated with @Validated for input validation");
```

## Правила для сервисов

```java
// Все классы в пакете service должны иметь @Service
@ArchTest
static final ArchRule service_classes_should_be_annotated =
    classes()
        .that().resideInAPackage("..service..")
        .and().areTopLevelClasses()
        .and().areNotInterfaces()
        .and().areNotAnnotatedWith(Deprecated.class)
        .should().beAnnotatedWith(Service.class)
        .as("All classes in the service package must be annotated with @Service");

// @Service не должен зависеть от web-слоя
@ArchTest
static final ArchRule services_should_not_depend_on_web =
    noClasses()
        .that().areAnnotatedWith(Service.class)
        .should().dependOnClassesThat()
        .resideInAnyPackage(
            "org.springframework.web..",
            "jakarta.servlet.."
        )
        .as("Services must not depend on web layer — they should be reusable");
```

## Правила для @Transactional

```java
// @Transactional только на публичных методах (Spring proxy не перехватывает приватные)
@ArchTest
static final ArchRule transactional_methods_must_be_public =
    methods()
        .that().areAnnotatedWith(Transactional.class)
        .should().bePublic()
        .as("@Transactional has no effect on non-public methods with proxy-based AOP");

// @Transactional не на @Repository — транзакции управляются в service
@ArchTest
static final ArchRule repositories_should_not_be_transactional =
    noClasses()
        .that().areAnnotatedWith(Repository.class)
        .should().beAnnotatedWith(Transactional.class)
        .as("@Repository classes should not be @Transactional — let services control transactions");
```

> **Важно:** Spring AOP по умолчанию работает через прокси. `@Transactional` на приватном или package-private методе не имеет эффекта — Spring просто не видит вызов. Это правило ловит именно такой тихий баг.

## Внедрение зависимостей

Field injection (`@Autowired` на поле) считается антипаттерном: класс нельзя создать в тесте без Spring-контекста.

```java
// Запрет @Autowired на полях — использовать constructor injection
@ArchTest
static final ArchRule no_field_injection =
    noFields()
        .should().beAnnotatedWith(Autowired.class)
        .as("Use constructor injection instead of @Autowired field injection")
        .because("Field injection prevents creating the class without a Spring context in tests");

// @Autowired не нужен на конструкторе, если он один (Spring 4.3+)
// Но если хочешь его запретить для чистоты:
@ArchTest
static final ArchRule no_autowired_on_constructors =
    noConstructors()
        .should().beAnnotatedWith(Autowired.class)
        .as("@Autowired on constructors is redundant in Spring Boot — omit it");
```

## Правила для репозиториев

```java
// Репозитории должны быть интерфейсами (JPA-стиль)
@ArchTest
static final ArchRule repositories_should_be_interfaces =
    classes()
        .that().resideInAPackage("..repository..")
        .and().haveSimpleNameEndingWith("Repository")
        .should().beInterfaces()
        .as("Repository classes must be interfaces (extend JpaRepository or CrudRepository)");

// Репозитории должны расширять Spring Data интерфейсы
@ArchTest
static final ArchRule repositories_should_extend_spring_data =
    classes()
        .that().areAnnotatedWith(Repository.class)
        .should().beAssignableTo(
            org.springframework.data.repository.Repository.class
        )
        .as("@Repository classes must extend a Spring Data repository interface");
```

## Правила для конфигураций

```java
// @Configuration должна быть в пакете config
@ArchTest
static final ArchRule configurations_in_config_package =
    classes()
        .that().areAnnotatedWith(Configuration.class)
        .should().resideInAPackage("..config..")
        .as("@Configuration classes must reside in the config package");

// @Bean-методы должны быть в @Configuration классах (не в @Service или @Component)
@ArchTest
static final ArchRule bean_methods_only_in_configurations =
    methods()
        .that().areAnnotatedWith(Bean.class)
        .should().beDeclaredInClassesThat()
        .areAnnotatedWith(Configuration.class)
        .as("@Bean methods must only be declared in @Configuration classes");
```

## Правила для @Component и компонентного скана

```java
// Ни один из "business" пакетов не должен содержать @Component напрямую
// — только @Service, @Repository, @Controller — более специфичные стереотипы
@ArchTest
static final ArchRule no_plain_component_in_business_layer =
    noClasses()
        .that().resideInAnyPackage("..service..", "..domain..")
        .should().beAnnotatedWith(Component.class)
        .as("Use @Service instead of generic @Component in service and domain packages");
```

## Мета-аннотации

Spring использует мета-аннотации: `@Service` аннотирована `@Component`. ArchUnit умеет проверять мета-аннотации:

```java
// Все Spring-бины (через мета-аннотацию @Component)
classes()
    .that().areMetaAnnotatedWith(Component.class)
    .should().resideInAnyPackage("..service..", "..repository..", "..controller..", "..config..")
    .as("All Spring beans must reside in known packages")
```

`areMetaAnnotatedWith` — проверяет не только прямую аннотацию, но и транзитивно через аннотации. `@Service` → `@Component`, поэтому класс с `@Service` попадёт в выборку.

## Практика

1. Найди в проекте все `@Autowired` поля и напиши правило, которое их запрещает
2. Проверь, что `@Transactional` нет на контроллерах в твоём сервисе
3. Напиши правило: все `@EventListener`-методы должны быть `void`
4. Создай правило: `@Async`-методы не должны находиться в `@Repository` классах
5. Проверь, что у всех `@RestController` есть `@RequestMapping` или аналог (через `areAnnotatedWith` с мета-аннотациями)
6. Напиши правило: классы с `@SpringBootApplication` должны быть ровно в корневом пакете (не в подпакете)

## Итоги урока

- `@Transactional` на приватных методах не работает в proxy-based AOP — ArchUnit может поймать этот тихий баг
- Запрет field injection (`@Autowired` на полях) делает классы тестируемыми без Spring-контекста
- `@Bean` только в `@Configuration` — предотвращает скрытое создание бинов в неожиданных местах
- `areMetaAnnotatedWith(Component.class)` находит все Spring-бины через любую стереотип-аннотацию
- `@Transactional` не должен быть на `@Repository` — управление транзакциями принадлежит сервисному слою
- Правила для Spring помогают поймать ошибки, которые компилятор не видит, а Spring молча игнорирует
