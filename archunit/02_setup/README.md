# Урок 2. Подключение и базовая настройка

## Зависимости

ArchUnit поставляется отдельным модулем под каждую версию JUnit. Добавлять его нужно только в `testImplementation` — в production попасть не может.

Артефакт выбирается по версии JUnit, которую тянет твой `spring-boot-starter-test`:

| Spring Boot | JUnit в starter-test | Артефакт ArchUnit |
|---|---|---|
| 3.x (3.5.x — последняя) | JUnit Jupiter 5.x | `archunit-junit5` |
| 4.x (4.1.x — последняя) | JUnit Jupiter 6.x | `archunit-junit6` |

**Gradle:**

```groovy
dependencies {
    // Spring Boot 4.x → JUnit 6
    testImplementation 'com.tngtech.archunit:archunit-junit6:1.5.0'

    // Spring Boot 3.x → JUnit 5
    // testImplementation 'com.tngtech.archunit:archunit-junit5:1.5.0'
}
```

**Maven:**

```xml
<dependency>
    <groupId>com.tngtech.archunit</groupId>
    <!-- archunit-junit5 для Spring Boot 3.x -->
    <artifactId>archunit-junit6</artifactId>
    <version>1.5.0</version>
    <scope>test</scope>
</dependency>
```

> **Важно:** `archunit-junit6` (как и `archunit-junit5`) уже включает `archunit` и соответствующие `*-api` / `*-engine` модули. Не добавляй их отдельно — получишь конфликт версий.

Поддержка JUnit 6 появилась в ArchUnit 1.5.0. `archunit-junit5` собран против JUnit Platform 1.x: на Spring Boot 4 он тянет `junit-platform-engine:1.14.x`, который BOM Spring Boot поднимает до 6.0.x. Практически это пока работает (движок совместим), но версии в дереве зависимостей расходятся, и полагаться на это в новом проекте не стоит — бери `archunit-junit6`.

Код тестов при этом одинаковый: пакеты `com.tngtech.archunit.junit.*` и весь API совпадают, отличается только артефакт. Никакой дополнительной настройки runner-а не нужно — `TestEngine` подхватывается автоматически.

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
./gradlew test
```

> **Внимание:** обычный фильтр Gradle `--tests "*.ArchitectureTest"` на ArchUnit-тесты не действует — они выполняются собственным `TestEngine`, и Gradle-фильтр его не ограничивает: запустятся все `@ArchTest` во всех классах. Способы запустить подмножество правил — теги и `junit.testFilter` — в уроке 10.

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
import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ClassFileImporter;
import com.tngtech.archunit.core.importer.ImportOption;

JavaClasses classes = new ClassFileImporter()
        // Сначала опции — исключить тестовые классы и сторонние библиотеки
        .withImportOption(ImportOption.Predefined.DO_NOT_INCLUDE_TESTS)
        .withImportOption(ImportOption.Predefined.DO_NOT_INCLUDE_JARS)

        // И только потом импорт — по имени пакета (ищет в classpath)
        .importPackages("com.example");

        // Другие способы импорта вместо importPackages:
        // .importPath("build/classes/java/main")      — из директории
        // .importJar(new JarFile("lib/mylib.jar"))    — из jar-файла
```

> **Важно:** порядок вызовов не произвольный. `withImportOption` возвращает `ClassFileImporter`, а `importPackages` — уже `JavaClasses`. Поставишь опции после импорта — код не скомпилируется.

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

Если импортировано 0 классов, правило не проходит молча — оно падает с `failed to check any classes` (урок 3). Но диагностика по этому сообщению неочевидна: причина обычно не в правиле, а в неверном пакете или в несобранных классах. Печать `classes.size()` экономит время при первой настройке.

## Практика

1. Добавь `archunit-junit5` или `archunit-junit6` (по версии Spring Boot) в зависимости своего сервиса
2. Создай `ArchitectureTest` с `@AnalyzeClasses(packagesOf = Application.class)`
3. Напиши одно правило `@ArchTest` — например, что все классы в пакете `service` не зависят от `jakarta.servlet`
4. Добавь вывод количества загруженных классов и убедись, что число больше нуля
5. Сломай правило намеренно (добавь импорт в тестовый класс) и посмотри на сообщение об ошибке
6. Добавь `DO_NOT_INCLUDE_TESTS` и убедись, что тест больше не падает на тестовых классах

## Итоги урока

- Артефакт выбирается по версии JUnit: `archunit-junit5` для Spring Boot 3.x, `archunit-junit6` (с ArchUnit 1.5.0) для Spring Boot 4.x — добавляется только в `testImplementation`, дополнительный runner не нужен
- `@AnalyzeClasses` + `@ArchTest` — канонический стиль: классы кешируются, правила переиспользуются
- `packagesOf = Application.class` лучше, чем строка с пакетом — не ломается при переименовании
- `DO_NOT_INCLUDE_TESTS` обязателен, иначе правила применяются к тестовым классам
- Если `classes.size() == 0` — правила падают с `failed to check any classes`; чаще всего это неверный пакет в `@AnalyzeClasses`, а не нарушение архитектуры
- `ClassFileImporter` работает с байткодом — исходники не нужны, но классы должны быть скомпилированы
