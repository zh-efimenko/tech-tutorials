# Урок 3. Основы API

## Строительные блоки правила

Любое правило в ArchUnit строится из трёх частей:

```
[субъект] .that() [предикат] .should() [условие]
```

- **Субъект** — что проверяем: классы, методы, поля, конструкторы
- **Предикат** — фильтр: какие именно (в каком пакете, с какой аннотацией)
- **Условие** — что должно выполняться

```java
classes()                                    // субъект
    .that().resideInAPackage("..service..")  // предикат
    .should().notBePublic()                  // условие
```

## Субъекты

```java
import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.*;

classes()        // JavaClass
fields()         // JavaField
methods()        // JavaMethod
constructors()   // JavaConstructor
codeUnits()      // JavaCodeUnit (method + constructor)
members()        // JavaMember (field + method + constructor)
```

Для инвертированных правил (запрет):

```java
noClasses()      // то же, но .should() читается как "не должны"
noFields()
noMethods()
```

Разница между `classes().should().notX()` и `noClasses().should().X()` — только читабельность. Результат одинаковый.

## Предикаты: .that()

Предикаты фильтруют субъекты перед проверкой условия.

### По пакету

```java
// Точный пакет
.that().resideInAPackage("com.example.service")

// Любой подпакет (двойная точка = wildcard)
.that().resideInAPackage("..service..")

// Несколько пакетов
.that().resideInAnyPackage("..service..", "..usecase..")
```

Синтаксис `..service..`:
- `..` в начале — любой префикс пакета
- `service` — точное совпадение сегмента
- `..` в конце — любой вложенный пакет

### По аннотации

```java
.that().areAnnotatedWith(Service.class)
.that().areNotAnnotatedWith(Deprecated.class)

// Мета-аннотации (аннотация на аннотации)
.that().areMetaAnnotatedWith(Transactional.class)
```

### По имени класса

```java
.that().haveSimpleNameEndingWith("Service")
.that().haveSimpleNameStartingWith("Abstract")
.that().haveNameMatching(".*Repository")   // regex
.that().haveSimpleNameContaining("Dto")
```

### По иерархии

```java
.that().areAssignableTo(BaseEntity.class)
.that().areAssignableFrom(CrudRepository.class)
.that().implement(Serializable.class)
.that().extend(AbstractService.class)
```

### По видимости

```java
.that().arePublic()
.that().arePrivate()
.that().areProtected()
.that().arePackagePrivate()
```

### Комбинирование предикатов

```java
import static com.tngtech.archunit.core.domain.properties.CanBeAnnotated.Predicates.*;
import static com.tngtech.archunit.lang.conditions.ArchConditions.*;

// AND — через цепочку .and()
.that().resideInAPackage("..service..")
    .and().areAnnotatedWith(Service.class)

// OR — через .or()
.that().resideInAPackage("..service..")
    .or().resideInAPackage("..usecase..")
```

## Условия: .should()

### Зависимости

```java
.should().dependOnClassesThat().resideInAPackage("..domain..")
.should().notDependOnClassesThat().resideInAPackage("..infrastructure..")
.should().onlyDependOnClassesThat().resideInAnyPackage("..domain..", "java..")
```

### Аннотации

```java
.should().beAnnotatedWith(Transactional.class)
.should().notBeAnnotatedWith(SuppressWarnings.class)
```

### Доступ к классу

```java
.should().onlyBeAccessed().byClassesThat().resideInAPackage("..service..")
.should().notBeAccessed().byClassesThat().resideInAPackage("..controller..")
```

### Видимость

```java
.should().bePublic()
.should().bePrivate()
.should().notBePublic()
```

### Реализация / наследование

```java
.should().implement(Serializable.class)
.should().beAssignableTo(BaseEntity.class)
```

## JavaClasses и JavaClass

`JavaClasses` — это коллекция, которую возвращает `ClassFileImporter`. Каждый элемент — `JavaClass`.

```java
JavaClasses classes = new ClassFileImporter()
        .importPackages("com.example");

// Найти конкретный класс
JavaClass betService = classes.get(BetService.class);

// Посмотреть на зависимости
betService.getDirectDependenciesFromSelf()
        .forEach(dep -> System.out.println(dep.getTargetClass().getName()));

// Аннотации
betService.isAnnotatedWith(Service.class); // true/false

// Поля
betService.getFields().forEach(field -> {
    System.out.println(field.getName() + ": " + field.getRawType().getName());
});
```

`JavaClass` — основной объект для рефлексии в ArchUnit. Можно получить поля, методы, аннотации, суперкласс, интерфейсы, пакет.

## Описание правила: as и because

```java
ArchRule rule = noClasses()
        .that().resideInAPackage("..controller..")
        .should().dependOnClassesThat().resideInAPackage("..repository..")
        .as("Controllers must not access repositories directly")  // описание
        .because("Business logic belongs in the service layer");   // причина
```

`.as()` — переопределяет стандартное сообщение об ошибке.
`.because()` — добавляет пояснение в сообщение об ошибке.

Сообщение при нарушении выглядит так:

```
Architecture Violation [Priority: MEDIUM] - Rule 'Controllers must not access repositories
directly, because Business logic belongs in the service layer' was violated (1 times):
```

Приоритет задаётся не на правиле, а на его старте — через `ArchRuleDefinition.priority(..)` (урок 10).

## allowEmptyShould: защита от ложных успехов

Правило, чей `.that()` не нашёл ни одного класса, по умолчанию **падает**:

```java
// Если пакета "..controller.." не существует — тест красный, а не зелёный
noClasses()
    .that().resideInAPackage("..controller..")
    .should().dependOnClassesThat().resideInAPackage("..repository..");
```

```
Rule 'no classes that reside in a package '..controller..' should depend on classes that
reside in a package '..repository..'' failed to check any classes. This means either that
no classes have been passed to the rule at all, or that no classes passed to the rule
matched the `that()` clause.
```

Это защита от ситуации «переименовали пакет — правило молча перестало проверять что-либо».

Иногда пустой результат легитимен (правило написано впрок, модуль ещё не создан). Тогда разреши его точечно:

```java
.allowEmptyShould(true)
```

Или глобально, для всех правил, в `archunit.properties`:

```properties
# src/test/resources/archunit.properties
archRule.failOnEmptyShould=false
```

> **Внимание:** ключи в `archunit.properties` пишутся без префикса `archunit.`. Префикс нужен только когда то же свойство передаётся как system property: `-Darchunit.archRule.failOnEmptyShould=false`. Ключ с лишним префиксом не вызовет ошибки — он просто будет проигнорирован.

## Практика

1. Напиши правило с субъектом `fields()`, предикатом по аннотации `@Autowired` и условием `should().bePrivate()`
2. Создай правило `methods().that().haveNameMatching("get.*").should().bePublic()` — что оно проверяет?
3. Добавь к любому правилу `.as("...")` и `.because("...")` — посмотри, как изменится сообщение при нарушении
4. Попробуй `noClasses().that().resideInAPackage("..nonexistent..").should()...` — убедись, что тест падает с «failed to check any classes»; добавь `.allowEmptyShould(true)` и убедись, что стал зелёным
5. Используй `JavaClass` API напрямую: загрузи классы, получи `BetService`, выведи все его зависимости
6. Напиши правило с `or()` — классы в пакете `service` или `usecase` должны быть аннотированы `@Service`

## Итоги урока

- Правило строится по схеме: субъект → предикат (`.that()`) → условие (`.should()`)
- Субъектами могут быть классы, методы, поля, конструкторы — каждый тип имеет свои предикаты и условия
- `..package..` — wildcards в именах пакетов: `..` означает любое количество подпакетов
- Предикаты комбинируются через `.and()` / `.or()` для сложных фильтров
- `.as()` задаёт читабельное название правила, `.because()` объясняет причину в сообщении об ошибке
- Правило с пустым результатом `.that()` падает по умолчанию — переименование пакета не превратит правило в молчаливо зелёное; `allowEmptyShould(true)` нужен только там, где пустой результат легитимен
