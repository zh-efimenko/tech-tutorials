# Урок 8. Тестирование с Docker Compose

## Проблема тестирования с инфраструктурой

Интеграционные тесты требуют реальные сервисы: базу данных, кеш, брокер сообщений. Есть три подхода:

| Подход | Плюсы | Минусы |
|--------|-------|--------|
| H2/встроенные БД | Быстро | Поведение отличается от production |
| Testcontainers | Полный контроль | Нужен отдельный код настройки |
| spring-boot-docker-compose | Один compose-файл для dev и тестов | Менее гибкий, чем Testcontainers |

`spring-boot-docker-compose` позволяет использовать тот же подход, что и при разработке — контейнеры поднимаются автоматически, подключения настраиваются без кода.

## Поведение по умолчанию: тесты пропускают Docker Compose

По умолчанию `spring.docker.compose.skip.in-tests` равен `true`. Это значит, что при запуске тестов Docker Compose интеграция **отключена**. Spring Boot предполагает, что для тестов ты используешь Testcontainers или мок-сервисы.

Чтобы включить Docker Compose в тестах, нужно явно установить:

```yaml
spring:
  docker:
    compose:
      skip:
        in-tests: false
```

## Отдельный compose-файл для тестов

Для тестов обычно нужен урезанный набор сервисов. Если приложение работает с PostgreSQL, Redis, Kafka и Hazelcast, то для unit/slice-тестов достаточно только PostgreSQL и Redis.

Создай `compose-test.yaml` в корне проекта:

```yaml
# compose-test.yaml
services:
  db:
    image: postgres:18.4
    container_name: test_postgres
    ports:
      - "5433:5432"
    environment:
      POSTGRES_DB: test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test

  redis:
    image: redis:8.10
    container_name: test_redis
    ports:
      - "6380:6379"
```

**Важно:** порты сдвинуты (`5433` вместо `5432`, `6380` вместо `6379`), чтобы тестовые контейнеры не конфликтовали с dev-окружением. Spring Boot прочитает реальные порты из `docker compose ps` и настроит подключения корректно.

## Тестовый профиль

Создай `application-test.yml` для настройки тестового окружения:

```yaml
# src/test/resources/application-test.yml
spring:
  docker:
    compose:
      skip:
        in-tests: false
      file: compose-test.yaml
      arguments:
        - "--project-name=myapp-test"
      stop:
        command: down
        arguments:
          - "--volumes"
```

Четыре ключевых настройки:
- `skip.in-tests: false` — включает Docker Compose в тестах
- `file: compose-test.yaml` — указывает на тестовый compose-файл
- `arguments: ["--project-name=myapp-test"]` — отдельное имя Docker Compose проекта для тестов
- `stop.command: down` + `--volumes` — каждый прогон начинается с пустой базы

Последний пункт не косметика. По умолчанию после тестов выполняется `docker compose stop`: контейнеры и их тома остаются, и данные предыдущего прогона видны следующему. Тест, который упал из-за чужой строки, продолжит падать даже после того, как ты исправишь его код. Если состояние всё-таки накопилось, чисти вручную:

```bash
docker compose -p myapp-test -f compose-test.yaml down -v
```

### Зачем отдельное имя проекта

Без него тесты молча работают с dev-базой. Имя Docker Compose проекта по умолчанию — это имя директории, а `compose.yaml` и `compose-test.yaml` лежат в одной. Значит для Compose это один и тот же проект, и запущенный dev-контейнер числится в нём сервисом `db`:

```bash
$ docker compose -f compose.yaml up -d          # подняли dev
$ docker compose -f compose-test.yaml ps
NAME         SERVICE   PORTS
my_postgres  db        0.0.0.0:5432->5432/tcp   # это dev-контейнер!
```

Дальше срабатывает дефолт `spring.docker.compose.start.skip: if-running`: Spring Boot видит запущенный сервис, печатает `There are already Docker Compose services running, skipping startup`, тестовые контейнеры не поднимает и настраивает `DataSource` на dev-базу:

```
DEBUG --- com.zaxxer.hikari.HikariConfig : jdbcUrl......jdbc:postgresql://127.0.0.1:5432/myapp
```

Тесты при этом зелёные — они просто пишут не туда. Аргумент `--project-name` попадает во все команды Compose, включая `ps`, поэтому тестовый набор становится отдельным проектом со своими контейнерами.

## Схема базы для тестов

Контейнер PostgreSQL поднимается пустым: Docker Compose создаёт базу, но не таблицы. Без DDL первый же тест репозитория падает:

```
org.springframework.jdbc.BadSqlGrammarException: ...
Caused by: org.postgresql.util.PSQLException: ERROR: relation "demo" does not exist
```

Самый короткий способ для курса — положить схему рядом с тестами и включить инициализацию:

```sql
-- src/test/resources/schema.sql
CREATE TABLE IF NOT EXISTS demo (
    id    SERIAL PRIMARY KEY,
    demo1 VARCHAR(255),
    demo2 VARCHAR(255)
);
```

Свойство добавляется в тот же файл — не копируй второй корень `spring:`, а дописывай ветку в существующий. Итоговый `application-test.yml` целиком:

```yaml
# src/test/resources/application-test.yml
spring:
  docker:
    compose:
      skip:
        in-tests: false
      file: compose-test.yaml
      arguments:
        - "--project-name=myapp-test"
      stop:
        command: down
        arguments:
          - "--volumes"
  sql:
    init:
      mode: always
```

В реальном проекте эту роль обычно берёт на себя Flyway или Liquibase — тогда `schema.sql` не нужен, миграции накатываются на контейнер при старте контекста.

## Test Slices с Docker Compose

Spring Boot предоставляет **test slices** — аннотации, которые загружают только часть контекста приложения. С Docker Compose они работают так же, как с полным контекстом.

### @DataJdbcTest — тесты репозитория базы данных

Сущность и репозиторий, на которых работают примеры ниже:

```java
// @Id — именно из org.springframework.data.annotation, не из jakarta.persistence
import org.springframework.data.annotation.Id;
import org.springframework.data.relational.core.mapping.Table;

@Table("demo")
public record Demo(@Id Long id, String demo1, String demo2) { }

// import org.springframework.data.repository.CrudRepository;
public interface DemoRepository extends CrudRepository<Demo, Long> { }
```

```java
@DataJdbcTest
@ActiveProfiles("test")
class DemoRepositoryTest {

    @Autowired
    private DemoRepository demoRepository;

    @Test
    void findAllTest() {
        // Подготовка — id генерирует база, поэтому в конструкторе null
        demoRepository.save(new Demo(null, "value1", "value2"));

        // Действие
        var result = demoRepository.findAll();

        // Проверка
        assertTrue(result.iterator().hasNext());
        assertEquals("value1", result.iterator().next().demo1());
    }
}
```

`@DataJdbcTest` загружает только JDBC-слой: репозитории, `JdbcTemplate`, `DataSource`. Docker Compose поднимает PostgreSQL из `compose-test.yaml`, Spring Boot настраивает `DataSource` автоматически.

**Подводный камень.** Как только на classpath оказываются два модуля Spring Data (а в этом курсе так и есть — JDBC и Redis), включается строгая привязка репозиториев к модулю. Репозиторий без размеченной сущности не достаётся никому:

```
Finished Spring Data repository scanning in 12 ms. Found 0 JDBC repository interfaces.
...
NoSuchBeanDefinitionException: No qualifying bean of type 'com.example.DemoRepository' available
```

Лечится аннотацией на сущности: `@Table` для JDBC (см. `Demo` выше) и `@RedisHash` для Redis:

```java
// @Id снова из org.springframework.data.annotation — та же ловушка, что и у Demo
import java.time.Instant;
import org.springframework.data.annotation.Id;
import org.springframework.data.redis.core.RedisHash;
import org.springframework.data.repository.CrudRepository;

@RedisHash("demo_cache")
public record DemoCache(@Id Long id, String demo1, String demo2, Instant createdAt) { }

public interface DemoCacheRepository extends CrudRepository<DemoCache, Long> { }
```

С одним только `spring-boot-starter-data-jdbc` аннотация не обязательна — поэтому проблема и вылезает именно в связке из урока 6. Симметрично: без `@RedisHash` не найдётся `DemoCacheRepository`.

**Внимание:** `@DataJdbcTest` не включает `@Configuration`-классы. Если в проекте есть собственная конфигурация JDBC-слоя (например, с `@EnableJdbcAuditing`), её подключают явно: `@Import(JdbcConfig.class)`. В примере выше такого класса нет, поэтому и импорта нет.

### @DataRedisTest — тесты Redis-репозитория

```java
@DataRedisTest
@ActiveProfiles("test")
class DemoCacheRepositoryTest {

    @Autowired
    private DemoCacheRepository demoCacheRepository;

    @Test
    void getByIdTest() {
        // Подготовка
        var cache = new DemoCache(1L, "value1", "value2", Instant.now());
        demoCacheRepository.save(cache);

        // Действие
        var result = demoCacheRepository.findById(1L);

        // Проверка
        assertTrue(result.isPresent());
        assertEquals("value1", result.get().demo1());
    }
}
```

`@DataRedisTest` загружает только Redis-слой: `RedisTemplate`, Redis-репозитории, `RedisConnectionFactory`. Docker Compose поднимает Redis из `compose-test.yaml`.

### @SpringBootTest — полный контекст

```java
import java.util.List;
import java.util.stream.StreamSupport;
import org.springframework.stereotype.Service;

@Service
public class DemoService {

    private final DemoRepository repository;

    public DemoService(DemoRepository repository) {
        this.repository = repository;
    }

    public void add(Demo demo) {
        repository.save(demo);
    }

    public List<Demo> findAll() {
        return StreamSupport.stream(repository.findAll().spliterator(), false).toList();
    }
}
```

```java
@SpringBootTest
@ActiveProfiles("test")
@Transactional   // без него тест оставит запись в базе и сломает соседние
class DemoServiceTest {

    @Autowired
    private DemoService demoService;

    @Test
    void addAndFindTest() {
        // Действие
        demoService.add(new Demo(null, "test1", "test2"));
        var result = demoService.findAll();

        // Проверка
        assertFalse(result.isEmpty());
    }
}
```

**Внимание, два подводных камня `@SpringBootTest`.**

*Первый — общая база.* В отличие от `@DataJdbcTest`, `@SpringBootTest` сам транзакцию не откатывает. Без `@Transactional` запись `test1` остаётся в базе, и `DemoRepositoryTest.findAllTest` начинает падать, потому что первой строкой из `findAll()` оказывается чужая:

```
org.opentest4j.AssertionFailedError: expected: <value1> but was: <test1>
```

Порядок выполнения тестовых классов при этом не гарантирован — ошибка выглядит плавающей. Кроме `@Transactional` помогает `deleteAll()` в `@BeforeEach` и ассерты, не завязанные на первый элемент.

Важная деталь: `@Transactional` спасает только от новых записей. Строка, попавшая в базу до того, как ты добавил аннотацию, никуда не денется — тестовые контейнеры переживают прогон. Если набор остался красным, сначала удали тестовое окружение (`docker compose -p myapp-test -f compose-test.yaml down -v`) или настрой `stop.command: down --volumes`, как показано выше.

*Второй — контекст поднимается целиком.* Все `@Configuration`-классы приложения тоже. Если по уроку 6 в проекте есть `HazelcastConfig` с бином `IMap`, а в `compose-test.yaml` Hazelcast нет, тест не запустится:

```
UnsatisfiedDependencyException: Error creating bean with name 'demoMessages'
Caused by: NoSuchBeanDefinitionException: No qualifying bean of type 'com.hazelcast.core.HazelcastInstance' available
```

Правило простое: `compose-test.yaml` должен содержать всё, что нужно полному контексту. Либо добавь в него Hazelcast, либо ограничь конфигурацию профилем (`@Profile("!test")` на `HazelcastConfig` — работает, потому что тест помечен `@ActiveProfiles("test")`), либо не используй `@SpringBootTest` там, где хватает слайса.

Не всякая нехватка сервиса роняет контекст. Бин `NewTopic` из практики урока 6 соберётся и без брокера: контекст поднимется, тест будет зелёным, но `KafkaAdmin` сначала выберет свой таймаут (`ERROR KafkaAdmin : Could not configure topics`, `TimeoutException`), и один тестовый класс вместо секунд пойдёт минуту. Если `./gradlew test` внезапно стал долгим — ищи в логе клиента, который стучится в отсутствующий сервис.

## Жизненный цикл контейнеров в тестах

При запуске тестов Docker Compose работает так:

1. Первый тестовый класс запускает Spring-контекст
2. Spring Boot поднимает контейнеры из `compose-test.yaml`
3. Контекст кешируется между тестовыми классами с одинаковой конфигурацией
4. Контейнеры живут, пока жив контекст
5. После завершения всех тестов контекст закрывается и контейнеры останавливаются

**Важно:** контекст переиспользуется только между классами с одинаковой конфигурацией. Разные слайсы — это разные конфигурации, поэтому `@DataJdbcTest`, `@DataRedisTest` и `@SpringBootTest` поднимают три разных контекста. Контейнеры при этом всё равно общие: первый контекст их поднял, а остальные видят запущенные сервисы и печатают `There are already Docker Compose services running, skipping startup`.

```
┌──────────────────────────────────────────────────────────┐
│                       Gradle test                        │
│                                                          │
│  DemoRepositoryTest       ── Контекст 1  ─┐              │
│  DemoCacheRepositoryTest  ── Контекст 2  ─┼─ один набор  │
│  DemoServiceTest          ── Контекст 3  ─┘  контейнеров │
│                                                          │
│  Классы с той же конфигурацией переиспользуют            │
│  уже созданный контекст, новый не поднимается            │
└──────────────────────────────────────────────────────────┘
```

## Изоляция данных между тестами

Docker Compose не очищает данные между тестами автоматически. Если один тест записал данные в PostgreSQL, следующий тест их увидит. Стратегии изоляции:

### Чистое окружение на каждый прогон

```yaml
# application-test.yml
spring:
  docker:
    compose:
      stop:
        command: down
        arguments:
          - "--volumes"
```

Самый надёжный вариант для этого курса: контейнеры и тома удаляются после прогона, следующий стартует с пустой базой.

### Flyway clean (если в проекте есть миграции)

```yaml
# application-test.yml
spring:
  flyway:
    clean-disabled: false
    clean-on-validation-error: true
```

**Внимание:** без Flyway на classpath эти свойства просто игнорируются. В проекте курса схему создаёт `schema.sql`, поэтому блок ничего не даст — он для проектов с миграциями.

### @Transactional (для @DataJdbcTest)

`@DataJdbcTest` по умолчанию оборачивает каждый тест в транзакцию и откатывает её после выполнения. Данные не сохраняются между тестами.

### Ручная очистка

```java
@BeforeEach
void setUp() {
    demoRepository.deleteAll();
}
```

## Настройка Gradle для тестов

Убедись, что `spring-boot-docker-compose` доступна в тестах. Конфигурация `testAndDevelopmentOnly` автоматически включает зависимость и в `bootRun`, и в `test`:

```groovy
dependencies {
    testAndDevelopmentOnly 'org.springframework.boot:spring-boot-docker-compose'
}
```

Если нужна зависимость только для тестов (не для `bootRun`):

```groovy
dependencies {
    testImplementation 'org.springframework.boot:spring-boot-docker-compose'
}
```

В Spring Boot 4 каждый test slice живёт в своём модуле, поэтому одного `spring-boot-starter-test` больше не хватает — нужен тестовый стартер той технологии, которую тестируешь:

```groovy
dependencies {
    testImplementation 'org.springframework.boot:spring-boot-starter-data-jdbc-test'   // @DataJdbcTest
    testImplementation 'org.springframework.boot:spring-boot-starter-data-redis-test'  // @DataRedisTest

    testAndDevelopmentOnly 'org.springframework.boot:spring-boot-docker-compose'
}
```

Тестовые стартеры тянут `spring-boot-starter-test` транзитивно — отдельно его подключать не нужно. Аннотации при этом переехали в новые пакеты: `org.springframework.boot.data.jdbc.test.autoconfigure.DataJdbcTest` и `org.springframework.boot.data.redis.test.autoconfigure.DataRedisTest`. Если импорты остались из 3.x (`org.springframework.boot.test.autoconfigure.data.*`), код просто не скомпилируется.

## Docker Compose vs Testcontainers

Оба подхода поднимают реальные контейнеры для тестов. Когда что использовать:

| Критерий | Docker Compose | Testcontainers |
|----------|---------------|----------------|
| Конфигурация | compose-файл (декларативно) | Java-код (программно) |
| Переиспользование с dev | Один compose для dev и тестов | Отдельная конфигурация |
| Гибкость | Декларативная — нельзя менять конфигурацию из кода теста | Полная — контейнер можно настроить прямо в тесте |
| Параллельные тесты | Один набор контейнеров на весь запуск — нет изоляции данных между параллельными тестами | Каждый тест-класс получает свой контейнер с чистым состоянием |
| Жизненный цикл | Контейнеры живут на весь ApplicationContext | Можно поднять контейнер на один тест или один класс |
| Зависимости | Только Docker Compose | Docker + Testcontainers SDK |

**Про порты:** динамические порты (`"5432"` вместо `"5432:5432"`) поддерживаются в обоих подходах — Spring Boot читает реальный маппинг через `docker compose ps`, поэтому конфликтов портов нет ни в том ни в другом случае.

Реальное ограничение Docker Compose в параллельных тестах — **изоляция данных**: все параллельно выполняющиеся тесты работают с одной базой данных. Один тест может испортить данные другому. С Testcontainers каждый тест-класс получает отдельный контейнер с чистым состоянием.

Docker Compose подходит, когда хочешь единый compose-файл для dev и тестов и тесты запускаются в одном потоке. Testcontainers лучше для параллельного запуска и сценариев, где нужна изоляция данных на уровне теста.

## Практика

1. Создай `compose-test.yaml` с PostgreSQL и Redis на сдвинутых портах
2. Создай `application-test.yml` с `skip.in-tests: false`, `file: compose-test.yaml`, `arguments: ["--project-name=myapp-test"]`, `stop.command: down` с `--volumes` и `spring.sql.init.mode: always`, а рядом — `schema.sql` с таблицей `demo`
3. Напиши тест `@DataJdbcTest` с `@ActiveProfiles("test")` — сохрани и прочитай запись из PostgreSQL
4. Напиши тест `@DataRedisTest` с `@ActiveProfiles("test")` — сохрани и прочитай запись из Redis
5. Запусти оба теста командой `./gradlew test` — убедись, что контейнеры поднимаются один раз для обоих
6. Подними dev-окружение (`docker compose up -d`) и прогони тесты ещё раз. С `--project-name=myapp-test` поднимутся отдельные тестовые контейнеры на портах 5433/6380; убери этот аргумент — и в логе появится `There are already Docker Compose services running, skipping startup`, а Hikari покажет dev-порт 5432. Верни аргумент обратно
7. Убедись, что грязное состояние действительно ломает тесты. С `stop.command: down --volumes` из пункта 2 симптом не поймать — база чистая на каждом прогоне. Поэтому временно поменяй в `application-test.yml` блок остановки на `stop.command: stop`, убери `@Transactional` с `@SpringBootTest` и прогони набор дважды подряд (`./gradlew test --rerun-tasks`): второй прогон падает с `AssertionFailedError: expected: <value1> but was: <test1>`. Затем верни `@Transactional`, выполни `docker compose -p myapp-test -f compose-test.yaml down -v` и верни `down --volumes` — набор снова зелёный при любом числе прогонов
8. Запусти `docker ps` во время выполнения тестов — убедись, что видны тестовые контейнеры

## Итоги урока

- По умолчанию Docker Compose отключён в тестах — нужно явно установить `skip.in-tests: false`
- Контейнер базы поднимается пустым: схему создаёт `schema.sql` с `spring.sql.init.mode: always` или миграции Flyway/Liquibase
- Отдельный `compose-test.yaml` содержит минимальный набор сервисов и сдвинутые порты, чтобы не конфликтовать с dev-окружением
- Одних сдвинутых портов мало: без `--project-name` тестовый и dev-файл считаются одним Docker Compose проектом, и при поднятом dev-окружении тесты молча идут в dev-базу
- `@SpringBootTest` поднимает все `@Configuration` приложения — в `compose-test.yaml` должны быть сервисы под каждый из них, иначе контекст не соберётся
- Test slices (`@DataJdbcTest`, `@DataRedisTest`) работают с Docker Compose — контейнеры поднимаются автоматически
- Spring Boot кеширует контекст между тестовыми классами с одинаковой конфигурацией — контейнеры не перезапускаются
- `@DataJdbcTest` автоматически откатывает транзакции — данные изолированы между тестами
- `@Import` нужен для подключения `@Configuration`-классов, которые test slice не загружает автоматически
- Для тестов с полным контекстом используй `@SpringBootTest` — Docker Compose поднимет все сервисы из тестового compose-файла
- В Spring Boot 4 каждому slice нужен свой тестовый стартер (`spring-boot-starter-data-jdbc-test`, `spring-boot-starter-data-redis-test`), а аннотации лежат в новых пакетах
