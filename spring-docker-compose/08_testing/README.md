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
    image: postgres:17.5
    container_name: test_postgres
    ports:
      - "5433:5432"
    environment:
      POSTGRES_DB: test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test

  redis:
    image: redis:7.4
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
```

Два ключевых свойства:
- `skip.in-tests: false` — включает Docker Compose в тестах
- `file: compose-test.yaml` — указывает на тестовый compose-файл

## Test Slices с Docker Compose

Spring Boot предоставляет **test slices** — аннотации, которые загружают только часть контекста приложения. С Docker Compose они работают так же, как с полным контекстом.

### @DataJdbcTest — тесты репозитория базы данных

```java
@DataJdbcTest
@ActiveProfiles("test")
@Import(JdbcConfig.class)
class DemoRepositoryTest {

    @Autowired
    private DemoRepository demoRepository;

    @Test
    void findAllTest() {
        // Подготовка
        var demo = new Demo("value1", "value2");
        demoRepository.save(demo);

        // Действие
        var result = demoRepository.findAll();

        // Проверка
        assertFalse(result.isEmpty());
        assertEquals("value1", result.getFirst().demo1());
    }
}
```

`@DataJdbcTest` загружает только JDBC-слой: репозитории, `JdbcTemplate`, `DataSource`. Docker Compose поднимает PostgreSQL из `compose-test.yaml`, Spring Boot настраивает `DataSource` автоматически.

**Внимание:** `@DataJdbcTest` не включает `@Configuration`-классы. Если у тебя есть `JdbcConfig` с `@EnableJdbcAuditing`, его нужно подключить через `@Import(JdbcConfig.class)`.

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
@SpringBootTest
@ActiveProfiles("test")
class DemoServiceTest {

    @Autowired
    private DemoService demoService;

    @Test
    void addAndFindTest() {
        // Действие
        demoService.add(new Demo("test1", "test2"));
        var result = demoService.findAll();

        // Проверка
        assertFalse(result.isEmpty());
    }
}
```

`@SpringBootTest` загружает полный контекст. Все сервисы из `compose-test.yaml` будут подняты.

## Жизненный цикл контейнеров в тестах

При запуске тестов Docker Compose работает так:

1. Первый тестовый класс запускает Spring-контекст
2. Spring Boot поднимает контейнеры из `compose-test.yaml`
3. Контекст кешируется между тестовыми классами с одинаковой конфигурацией
4. Контейнеры живут, пока жив контекст
5. После завершения всех тестов контекст закрывается и контейнеры останавливаются

**Важно:** если разные тестовые классы используют один и тот же профиль и конфигурацию, Spring Boot переиспользует контекст (и контейнеры). Это значительно ускоряет выполнение набора тестов.

```
┌─────────────────────────────────────────────┐
│                Gradle test                  │
│                                             │
│  DemoRepositoryTest        ─┐               │
│  DemoCacheRepositoryTest   ─┼─ Контекст 1   │
│  DemoServiceTest           ─┘  (один набор  │
│                                контейнеров) │
│                                             │
│  AnotherProfileTest        ── Контекст 2    │
│                               (другой набор │
│                                контейнеров) │
└─────────────────────────────────────────────┘
```

## Изоляция данных между тестами

Docker Compose не очищает данные между тестами автоматически. Если один тест записал данные в PostgreSQL, следующий тест их увидит. Стратегии изоляции:

### Flyway clean (рекомендуется для тестов)

```yaml
# application-test.yml
spring:
  flyway:
    clean-disabled: false
    clean-on-validation-error: true
```

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
2. Создай `application-test.yml` с `skip.in-tests: false` и `file: compose-test.yaml`
3. Напиши тест `@DataJdbcTest` с `@ActiveProfiles("test")` — сохрани и прочитай запись из PostgreSQL
4. Напиши тест `@DataRedisTest` с `@ActiveProfiles("test")` — сохрани и прочитай запись из Redis
5. Запусти оба теста командой `./gradlew test` — убедись, что контейнеры поднимаются один раз для обоих
6. Проверь, что dev-контейнеры (порты 5432, 6379) не затронуты тестовыми контейнерами (порты 5433, 6380)
7. Добавь `@Transactional` к JDBC-тесту и убедись, что данные не сохраняются между методами
8. Запусти `docker ps` во время выполнения тестов — убедись, что видны тестовые контейнеры

## Итоги урока

- По умолчанию Docker Compose отключён в тестах — нужно явно установить `skip.in-tests: false`
- Отдельный `compose-test.yaml` содержит минимальный набор сервисов и сдвинутые порты, чтобы не конфликтовать с dev-окружением
- Test slices (`@DataJdbcTest`, `@DataRedisTest`) работают с Docker Compose — контейнеры поднимаются автоматически
- Spring Boot кеширует контекст между тестовыми классами с одинаковой конфигурацией — контейнеры не перезапускаются
- `@DataJdbcTest` автоматически откатывает транзакции — данные изолированы между тестами
- `@Import` нужен для подключения `@Configuration`-классов, которые test slice не загружает автоматически
- Для тестов с полным контекстом используй `@SpringBootTest` — Docker Compose поднимет все сервисы из тестового compose-файла
