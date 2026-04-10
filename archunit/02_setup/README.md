# Урок 2. Подключение и базовая настройка

## Зависимости

ArchUnit поставляется с модулем для JUnit 5. Добавлять его нужно только в `testImplementation` — в production попасть не может.

**Gradle:**

```groovy
dependencies {
    testImplementation 'com.tngtech.archunit:archunit-junit5:1.3.0'
}
```

**Maven:**

```xml
<dependency>
    <groupId>com.tngtech.archunit</groupId>
    <artifactId>archunit-junit5</artifactId>
    <version>1.3.0</version>
    <scope>test</scope>
</dependency>
```

> **Важно:** `archunit-junit5` уже включает `archunit` и `archunit-junit5-api`. Не добавляй их отдельно — получишь конфликт версий.

Spring Boot 3.x использует JUnit 5 по умолчанию через `spring-boot-starter-test`. ArchUnit с ним совместим напрямую, никакой дополнительной настройки runner-а не нужно.

## Первый тест

```java
import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ClassFileImporter;
import com.tngtech.archunit.lang.ArchRule;
import org.junit.jupiter.api.Test;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

class ArchitectureTest {

    // Загружаем все классы из указанного пакета
    JavaClasses importedClasses = new ClassFileImporter()
            .importPackages("com.example");

    @Test
    void controllers_should_not_depend_on_repositories() {
        ArchRule rule = noClasses()
                .that().resideInAPackage("..controller..")
                .should().dependOnClassesThat()
                .resideInAPackage("..repository..");

        rule.check(importedClasses);
    }
}
```

Запуск:

```bash
./gradlew test --tests "*.ArchitectureTest"
```

## Два способа объявлять тесты

ArchUnit поддерживает два стиля — выбери один и придерживайся его в проекте.

### Стиль 1: @ArchTest (рекомендуется)

```java
import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

@AnalyzeClasses(packages = "com.example")
class ArchitectureTest {

    @ArchTest
    static final ArchRule controllers_should_not_depend_on_repositories =
            noClasses()
                    .that().resideInAPackage("..controller..")
                    .should().dependOnClassesThat()
                    .resideInAPackage("..repository..");
}
```

**Плюсы:** классы загружаются один раз для всего теста (кеш), правило — `static final` поле, удобно переиспользовать.

### Стиль 2: Ручной @Test

```java
@Test
void rule_name() {
    ArchRule rule = noClasses()...;
    rule.check(importedClasses);
}
```

**Плюсы:** проще для динамических тестов (параметризованные). Минус — классы загружаются заново для каждого метода, если `importedClasses` объявлен как поле экземпляра.

> **Рекомендация:** используй `@ArchTest` + `@AnalyzeClasses` — это канонический способ. Классы кешируются автоматически.

## Настройка ClassFileImporter

Когда нужен ручной контроль над импортом (стиль 2 или базовый класс):

```java
JavaClasses classes = new ClassFileImporter()
        // Импортировать по имени пакета (ищет в classpath)
        .importPackages("com.example")

        // Импортировать из пути к директории
        // .importPath("build/classes/java/main")

        // Импортировать из jar-файла
        // .importJar(new JarFile("lib/mylib.jar"))

        // Исключить тестовые классы и сторонние библиотеки
        .withImportOption(ImportOption.Predefined.DO_NOT_INCLUDE_TESTS)
        .withImportOption(ImportOption.Predefined.DO_NOT_INCLUDE_JARS);
```

### Стандартные ImportOption

| Опция | Что исключает |
|-------|--------------|
| `DO_NOT_INCLUDE_TESTS` | Классы из `test/` директорий |
| `DO_NOT_INCLUDE_JARS` | Все `.jar` файлы из classpath |
| `DO_NOT_INCLUDE_ARCHIVES` | `.jar` и `.zip` |

> **Важно:** без `DO_NOT_INCLUDE_TESTS` правило применяется и к тестовым классам. Обычно это нежелательно — тесты часто нарушают архитектурные границы намеренно.

## Настройка через @AnalyzeClasses

```java
@AnalyzeClasses(
    // По пакету
    packages = "com.example",

    // По классу — берёт пакет этого класса
    // packagesOf = Application.class,

    // Исключить тестовые классы
    importOptions = {ImportOption.DoNotIncludeTests.class}
)
class ArchitectureTest {
    // ...
}
```

`packagesOf = Application.class` — удобный способ: переименовал пакет в `Application` — тест автоматически следует. Не нужно обновлять строку с именем пакета.

## Проверка настройки: сколько классов загружено

```java
@Test
void print_loaded_classes_count() {
    JavaClasses classes = new ClassFileImporter()
            .withImportOption(ImportOption.Predefined.DO_NOT_INCLUDE_TESTS)
            .importPackages("com.example");

    System.out.println("Loaded " + classes.size() + " classes");
    // Если 0 — неправильный пакет или классы не скомпилированы
}
```

Если тест загружает 0 классов, правила не проверяются и не падают — это ложноположительный результат. Всегда проверяй, что классы действительно загружены.

## Практика

1. Добавь `archunit-junit5` в зависимости своего сервиса
2. Создай `ArchitectureTest` с `@AnalyzeClasses(packagesOf = Application.class)`
3. Напиши одно правило `@ArchTest` — например, что все классы в пакете `service` не зависят от `javax.servlet`
4. Добавь вывод количества загруженных классов и убедись, что число больше нуля
5. Сломай правило намеренно (добавь импорт в тестовый класс) и посмотри на сообщение об ошибке
6. Добавь `DO_NOT_INCLUDE_TESTS` и убедись, что тест больше не падает на тестовых классах

## Итоги урока

- Зависимость `archunit-junit5` добавляется только в `testImplementation`, дополнительный runner для JUnit 5 не нужен
- `@AnalyzeClasses` + `@ArchTest` — канонический стиль: классы кешируются, правила переиспользуются
- `packagesOf = Application.class` лучше, чем строка с пакетом — не ломается при переименовании
- `DO_NOT_INCLUDE_TESTS` обязателен, иначе правила применяются к тестовым классам
- Если `classes.size() == 0` — правила молча не проверяются, это опасная ситуация
- `ClassFileImporter` работает с байткодом — исходники не нужны, но классы должны быть скомпилированы
