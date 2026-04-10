# Урок 4. Правила для слоёв

## Проблема зависимостей между слоями

Классический Spring Boot сервис имеет слои: контроллер вызывает сервис, сервис вызывает репозиторий. Это однонаправленная зависимость. Как только кто-то решает вызвать репозиторий из контроллера напрямую — слои теряют смысл.

Писать отдельное правило для каждой пары слоёв (`controller → service`, `controller → repository`, `service → controller`) — утомительно. ArchUnit предоставляет готовый API для описания слоёв как единой конфигурации.

## Layered Architecture API

```java
import com.tngtech.archunit.library.Architectures;

@ArchTest
static final ArchRule layered_architecture =
    Architectures.layeredArchitecture()
        .consideringAllDependencies()

        // Объявляем слои: имя → пакеты
        .layer("Controller").definedBy("..controller..")
        .layer("Service").definedBy("..service..")
        .layer("Repository").definedBy("..repository..")
        .layer("Domain").definedBy("..domain..")

        // Описываем, кто может обращаться к каждому слою
        .whereLayer("Controller").mayNotBeAccessedByAnyLayer()
        .whereLayer("Service").mayOnlyBeAccessedByLayers("Controller")
        .whereLayer("Repository").mayOnlyBeAccessedByLayers("Service")
        .whereLayer("Domain").mayOnlyBeAccessedByLayers("Controller", "Service", "Repository");
```

`consideringAllDependencies()` — проверяет все зависимости между слоями, включая транзитивные через поля и методы.

### Как читать правило

```
Controller  →  Service  →  Repository
    ↓              ↓
  Domain  ←——————————————— (доступен всем)
```

- Контроллер обращается к сервису — разрешено
- Контроллер обращается к репозиторию напрямую — нарушение
- Сервис обращается к контроллеру — нарушение

## Несколько пакетов в одном слое

Иногда один логический слой разбит на несколько пакетов:

```java
.layer("Service").definedBy("..service..", "..usecase..", "..application..")
```

Или через класс как якорь пакета:

```java
.layer("Controller").definedBy(
    "com.example.controller..",
    "com.example.api.."
)
```

## Разрешение конкретных исключений

Бывают легитимные случаи, когда правило слишком строгое:

```java
.whereLayer("Repository").mayOnlyBeAccessedByLayers("Service")
.ignoreDependency(BetService.class, BetCacheRepository.class)
```

`.ignoreDependency(from, to)` — исключает конкретную пару из проверки. Используй осторожно: каждое исключение — это долг.

## Onion / Hexagonal Architecture

Для onion-архитектуры (domain в центре, не зависит ни от чего):

```java
@ArchTest
static final ArchRule onion_architecture =
    Architectures.onionArchitecture()
        .domainModels("..domain.model..")
        .domainServices("..domain.service..")
        .applicationServices("..application..")
        .adapter("web", "..adapter.web..")
        .adapter("persistence", "..adapter.persistence..")
        .adapter("messaging", "..adapter.messaging..");
```

Onion API проверяет:
- `domainModels` не зависят ни от чего внутри проекта
- `domainServices` зависят только от `domainModels`
- `applicationServices` зависят от domain
- `adapter` зависят от `applicationServices` и `domain`, но не друг от друга

## Ручные правила для конкретной структуры

Когда пакеты не соответствуют стандартным паттернам — пишем правила вручную:

```java
// Только сервис может использовать репозиторий
@ArchTest
static final ArchRule only_services_access_repositories =
    classes()
        .that().resideInAPackage("..repository..")
        .should().onlyBeAccessed().byAnyPackage(
            "..service..",
            "..repository.."  // репозитории могут зависеть друг от друга
        )
        .as("Repositories may only be used by services")
        .allowEmptyShould(false);

// Контроллеры не знают о репозиториях
@ArchTest
static final ArchRule controllers_do_not_use_repositories =
    noClasses()
        .that().resideInAPackage("..controller..")
        .should().dependOnClassesThat()
        .resideInAPackage("..repository..")
        .as("Controllers must not directly access repositories");
```

## Проверка доступности vs проверка зависимостей

Два разных способа описать одно правило — важно понимать разницу:

```java
// "От кого зависит" — смотрим на исходящие зависимости класса
noClasses()
    .that().resideInAPackage("..controller..")
    .should().dependOnClassesThat().resideInAPackage("..repository..")

// "Кто обращается" — смотрим на входящие зависимости (обратная сторона)
classes()
    .that().resideInAPackage("..repository..")
    .should().onlyBeAccessed().byClassesThat().resideInAPackage("..service..")
```

Первое — "контроллеры не зависят от репозиториев". Второе — "репозитории используются только сервисами". Они проверяют одно и то же, но с разных сторон. Layered Architecture API проверяет оба направления автоматически.

## Пример

```java
@AnalyzeClasses(
    packages = "com.example",
    importOptions = ImportOption.DoNotIncludeTests.class
)
class LayerArchitectureTest {

    @ArchTest
    static final ArchRule layer_dependencies =
        Architectures.layeredArchitecture()
            .consideringAllDependencies()
            .layer("API").definedBy("..controller..", "..api..")
            .layer("Application").definedBy("..service..", "..usecase..")
            .layer("Domain").definedBy("..domain..")
            .layer("Infrastructure").definedBy("..repository..", "..client..", "..config..")
            .whereLayer("API").mayNotBeAccessedByAnyLayer()
            .whereLayer("Application").mayOnlyBeAccessedByLayers("API")
            .whereLayer("Domain").mayOnlyBeAccessedByLayers("API", "Application", "Infrastructure")
            .whereLayer("Infrastructure").mayOnlyBeAccessedByLayers("Application");
}
```

## Практика

1. Опиши структуру слоёв одного из сервисов проекта и создай `layeredArchitecture()` правило
2. Намеренно нарушь правило (добавь зависимость от репозитория в контроллер) — посмотри на сообщение об ошибке
3. Попробуй `onionArchitecture()` — если структура пакетов не совпадает, адаптируй пакеты под неё или используй ручные правила
4. Напиши правило через `onlyBeAccessed()` — чем отличается сообщение об ошибке от `noClasses().should().dependOn...()`?
5. Добавь `.ignoreDependency()` для одного легитимного исключения — но напиши комментарий, почему это исключение существует
6. Добавь `.as()` и `.because()` к layered architecture правилу — посмотри, как они влияют на вывод

## Итоги урока

- `Architectures.layeredArchitecture()` — готовый API для описания слоёв без написания отдельных правил для каждой пары
- Слой объявляется через `.layer("Name").definedBy("..package..")` — можно указать несколько пакетов
- `whereLayer("X").mayOnlyBeAccessedByLayers("Y")` задаёт допустимые зависимости между слоями
- `consideringAllDependencies()` проверяет все зависимости, включая через поля и параметры методов
- `onionArchitecture()` — готовый шаблон для onion/hexagonal: domain ни от чего не зависит
- `.ignoreDependency(From, To)` исключает конкретную пару — каждое исключение нужно обосновывать
- Разница между `dependOnClassesThat` и `onlyBeAccessed().byClassesThat` — направление проверки (исходящие vs входящие зависимости)
