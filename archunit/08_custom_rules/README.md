# Урок 8. Кастомные правила

## Когда встроенных предикатов не хватает

Встроенный API покрывает большинство случаев, но иногда нужна проверка, которую стандартными средствами не выразить:

- "Все `@EventListener` методы должны возвращать `void`"
- "Классы с полем типа `Clock` должны принимать его через конструктор, а не создавать сами"
- "Методы сервисов, начинающиеся с `find`, должны иметь только `@Transactional(readOnly = true)`"

Для этого используются `DescribedPredicate` и `ArchCondition`.

## DescribedPredicate: кастомный фильтр (.that())

`DescribedPredicate<T>` — это предикат с описанием. Используется там, где стандартные `.that().xxx()` не хватает.

```java
import com.tngtech.archunit.base.DescribedPredicate;
import com.tngtech.archunit.core.domain.JavaClass;

// Предикат: класс имеет более одного конструктора
DescribedPredicate<JavaClass> hasMoreThanOneConstructor =
    new DescribedPredicate<JavaClass>("have more than one constructor") {
        @Override
        public boolean test(JavaClass javaClass) {
            return javaClass.getConstructors().size() > 1;
        }
    };

// Использование в правиле
@ArchTest
static final ArchRule service_classes_should_have_single_constructor =
    noClasses()
        .that().resideInAPackage("..service..")
        .and(hasMoreThanOneConstructor)
        .should().beAnnotatedWith(Service.class)
        .as("Service classes with multiple constructors are a smell — use @RequiredArgsConstructor");
```

### Предикат для JavaMethod

```java
import com.tngtech.archunit.core.domain.JavaMethod;

// Метод возвращает Optional
DescribedPredicate<JavaMethod> returnsOptional =
    new DescribedPredicate<JavaMethod>("return Optional") {
        @Override
        public boolean test(JavaMethod method) {
            return method.getRawReturnType().isAssignableTo(Optional.class);
        }
    };

// Optional-возвращаемые методы не должны принимать null
// (это пример, полная проверка потребовала бы анализа тела метода)
methods()
    .that(returnsOptional)
    .should().bePublic()
    .as("Methods returning Optional must be public");
```

### Комбинирование предикатов

```java
DescribedPredicate<JavaClass> isService =
    DescribedPredicate.describe("annotated with @Service",
        c -> c.isAnnotatedWith(Service.class));

DescribedPredicate<JavaClass> isAbstract =
    DescribedPredicate.describe("abstract",
        JavaClass::isAbstract);

// AND
DescribedPredicate<JavaClass> isAbstractService = isService.and(isAbstract);

// OR
DescribedPredicate<JavaClass> isServiceOrComponent =
    isService.or(DescribedPredicate.describe("annotated with @Component",
        c -> c.isAnnotatedWith(Component.class)));
```

## ArchCondition: кастомное условие (.should())

`ArchCondition<T>` описывает условие с конкретными нарушениями. Принимает объект и `ConditionEvents` — куда добавляет сообщения о нарушениях.

```java
import com.tngtech.archunit.lang.ArchCondition;
import com.tngtech.archunit.lang.ConditionEvents;
import com.tngtech.archunit.lang.SimpleConditionEvent;
import com.tngtech.archunit.core.domain.JavaClass;

// Условие: класс не имеет публичных полей
ArchCondition<JavaClass> haveNoPublicFields =
    new ArchCondition<JavaClass>("have no public fields") {
        @Override
        public void check(JavaClass javaClass, ConditionEvents events) {
            javaClass.getFields().stream()
                .filter(field -> field.getModifiers().contains(JavaModifier.PUBLIC))
                .forEach(field -> {
                    String message = String.format(
                        "Field '%s' in class '%s' is public",
                        field.getName(), javaClass.getName()
                    );
                    // satisfied=false означает нарушение
                    events.add(SimpleConditionEvent.violated(javaClass, message));
                });
        }
    };

@ArchTest
static final ArchRule services_have_no_public_fields =
    classes()
        .that().areAnnotatedWith(Service.class)
        .should(haveNoPublicFields)
        .as("Service classes must not have public fields");
```

## Проверка аннотаций с параметрами

Стандартный `beAnnotatedWith` не проверяет параметры аннотации. Кастомное условие может:

```java
// Условие: метод имеет @Transactional(readOnly = true)
ArchCondition<JavaMethod> beReadOnlyTransactional =
    new ArchCondition<JavaMethod>("be annotated with @Transactional(readOnly = true)") {
        @Override
        public void check(JavaMethod method, ConditionEvents events) {
            boolean isReadOnly = method.getAnnotations().stream()
                .filter(a -> a.getType().isAssignableTo(Transactional.class))
                .anyMatch(a -> {
                    Object readOnly = a.get("readOnly").orElse(false);
                    return Boolean.TRUE.equals(readOnly);
                });

            if (!isReadOnly) {
                events.add(SimpleConditionEvent.violated(method,
                    String.format("Method '%s' in '%s' must be @Transactional(readOnly = true)",
                        method.getName(), method.getOwner().getName())));
            }
        }
    };

@ArchTest
static final ArchRule find_methods_should_be_read_only =
    methods()
        .that().haveNameStartingWith("find")
        .and().areAnnotatedWith(Transactional.class)
        .should(beReadOnlyTransactional)
        .as("Methods named 'find*' must use @Transactional(readOnly = true)");
```

## Составные условия

```java
import com.tngtech.archunit.lang.ArchCondition;

// AND — оба условия должны выполняться
ArchCondition<JavaClass> combined =
    haveNoPublicFields.and(someOtherCondition);

// OR — хотя бы одно
ArchCondition<JavaClass> either =
    haveNoPublicFields.or(someOtherCondition);
```

## Готовые предикаты из библиотеки

ArchUnit поставляет многие предикаты через статические фабричные методы. Не надо изобретать их с нуля:

```java
import static com.tngtech.archunit.core.domain.JavaClass.Predicates.*;
import static com.tngtech.archunit.core.domain.properties.CanBeAnnotated.Predicates.*;

// Класс является аннотацией
assignableTo(Annotation.class)

// Аннотирован конкретной аннотацией
annotatedWith(Service.class)

// Имя класса подходит под regex
nameMatching(".*Service")

// Класс находится в пакете
resideInAPackage("..service..")
```

## Пример: проверка конструктора Lombok

```java
// Все @Service должны использовать @RequiredArgsConstructor (Lombok)
// вместо явного конструктора с @Autowired параметрами
DescribedPredicate<JavaClass> hasExplicitConstructorWithParams =
    new DescribedPredicate<JavaClass>("have explicit constructor with parameters") {
        @Override
        public boolean test(JavaClass javaClass) {
            return javaClass.getConstructors().stream()
                .anyMatch(c -> !c.getRawParameterTypes().isEmpty()
                    && !c.isAnnotatedWith(Autowired.class));
        }
    };
```

## Практика

1. Напиши `DescribedPredicate`, который определяет классы с более чем 5 полями — примени его для поиска "God objects" в сервисном слое
2. Напиши `ArchCondition`, которое проверяет: все `@Scheduled`-методы возвращают `void`
3. Создай условие, которое проверяет: поля типа `Logger` объявлены как `private static final`
4. Используй `DescribedPredicate.describe()` (лямбда-форму) для простых предикатов без анонимного класса
5. Напиши правило с параметрами аннотации: `@Cacheable` должен иметь явно указанное `cacheNames`
6. Скомбинируй два `ArchCondition` через `.and()` — убедись, что сообщения об ошибках включают описания обоих условий

## Итоги урока

- `DescribedPredicate` заменяет `.that().xxx()` когда стандартных фильтров не хватает — используется в секции `.that(predicate)`
- `ArchCondition` заменяет `.should().xxx()` для сложных проверок — принимает объект и `ConditionEvents`, куда добавляет нарушения
- `SimpleConditionEvent.violated(object, message)` — добавляет нарушение; `satisfied(object, message)` — подтверждает соответствие
- Параметры аннотаций проверяются только через `ArchCondition` — стандартный `beAnnotatedWith` параметры игнорирует
- `DescribedPredicate.describe("description", lambda)` — краткая форма для простых предикатов без анонимного класса
- Кастомные условия комбинируются через `.and()` / `.or()`, описания обоих включаются в итоговое сообщение
