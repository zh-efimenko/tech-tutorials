# Урок 5. Compact Serialization и Java Records

## Зачем нужна сериализация в Hazelcast

Hazelcast хранит данные в `BINARY` формате — объекты Java преобразуются в массив байтов для хранения, репликации и передачи по сети. Выбор механизма сериализации напрямую влияет на:

- **Производительность** — время сериализации/десериализации
- **Потребление памяти** — размер сериализованных данных
- **Совместимость** — возможность менять структуру объектов без потери данных
- **Возможность запросов** — partial deserialization для индексов и Predicates

## Механизмы сериализации Hazelcast

| Механизм | Скорость | Schema evolution | Запросы без десериализации | Рекомендация |
|----------|---------|-----------------|--------------------------|-------------|
| `java.io.Serializable` | Медленная | Нет | Нет | Не использовать |
| `java.io.Externalizable` | Средняя | Ручная | Нет | Legacy |
| `IdentifiedDataSerializable` | Быстрая | Нет | Нет | Для внутренних структур |
| `Portable` | Средняя | Да | Да | Устаревший, заменён на Compact |
| **`Compact`** | **Быстрая** | **Да** | **Да** | **Рекомендуемый (5.2+)** |

## Compact Serialization

**Compact Serialization** — рекомендуемый механизм начиная с Hazelcast 5.2. Ключевые преимущества:

- **Schema evolution** — можно добавлять и удалять поля без нарушения совместимости
- **Partial deserialization** — чтение отдельных полей без полной десериализации (критично для индексов и Predicates)
- **Без reflection** — быстрее чем `java.io.Serializable`
- **Кросс-языковой** — работает с .NET, Python, Go клиентами
- **Zero-config для Java Records** — автоматическая сериализация без написания кода

## Java Records + Compact Serialization

Начиная с Hazelcast 5.1, Java Records поддерживаются в zero-config режиме. Достаточно определить record и зарегистрировать его — сериализатор будет создан автоматически.

### Определение DTO

```java
public record ProductValue(
    long categoryId,            // Примитив — сериализуется эффективнее обёртки
    String name,
    String status,
    PriceValue price,           // Вложенный record — рекурсивная сериализация
    @Nullable String description  // Nullable-поле: не занимает место если null
) {
    // Вложенные записи
    public record PriceValue(long amount, String currency) {}
}
```

**Ключевые моменты:**

- **Примитивные типы** (`long`, `int`, `double`) сериализуются эффективнее обёрток (`Long`, `Integer`)
- **Вложенные Records** — Compact Serialization рекурсивно обрабатывает вложенные record-ы
- **`@Nullable` поля** — если значение null, поле не занимает место в сериализованном виде
- **Нет наследования** — record-ы финальны, что идеально для сериализации

### Регистрация

Регистрация нужна и на клиенте, и на сервере.

**Java Config (Spring Boot):**

```java
@Bean
HazelcastConfigCustomizer compactSerializationCustomizer() {
    return config -> {
        config.getSerializationConfig()
            .getCompactSerializationConfig()
            .addClass(ProductValue.class)
            .addClass(ProductValue.PriceValue.class)
            .addClass(OrderValue.class);
    };
}
```

**YAML (серверная конфигурация):**

```yaml
hazelcast:
  serialization:
    compact-serialization:
      classes:
        - com.example.cache.dto.ProductValue
        - com.example.cache.dto.ProductValue$PriceValue
        - com.example.cache.dto.OrderValue
```

> **Важно:** Если DTO используется и в клиенте, и на сервере — регистрация нужна в обоих местах. Иначе сервер не сможет десериализовать данные для индексов и Predicates.

## Кастомный Compact Serializer

Для обычных классов (не records) или когда нужен контроль над форматом, можно написать свой сериализатор:

```java
public class OrderSerializer implements CompactSerializer<Order> {

    @Override
    public Order read(CompactReader reader) {
        long id = reader.readInt64("id");
        String status = reader.readString("status");
        long createdAt = reader.readInt64("createdAt");
        // Поля читаются по имени — порядок не важен
        return new Order(id, status, Instant.ofEpochMilli(createdAt));
    }

    @Override
    public void write(CompactWriter writer, Order order) {
        writer.writeInt64("id", order.getId());
        writer.writeString("status", order.getStatus());
        writer.writeInt64("createdAt", order.getCreatedAt().toEpochMilli());
    }

    @Override
    public String getTypeName() {
        return "Order";
    }

    @Override
    public Class<Order> getCompactClass() {
        return Order.class;
    }
}
```

Регистрация кастомного сериализатора:

```java
config.getSerializationConfig()
    .getCompactSerializationConfig()
    .addSerializer(new OrderSerializer());
```

> **Когда нужен кастомный сериализатор:** конвертация типов (Instant → long), оптимизация полей, обратная совместимость с non-record классами.

## Schema Evolution

Compact Serialization поддерживает эволюцию схемы — можно менять структуру DTO без потери данных.

### Добавление поля

```java
// Версия 1
public record ProductValue(long categoryId, String name) {}

// Версия 2 — добавлено поле description
public record ProductValue(long categoryId, String name, @Nullable String description) {}
```

При чтении данных версии 1 поле `description` будет `null`. При чтении данных версии 2 клиентом версии 1 — поле `description` игнорируется.

### Удаление поля

```java
// Версия 2
public record ProductValue(long categoryId, String name, String description) {}

// Версия 3 — поле description удалено
public record ProductValue(long categoryId, String name) {}
```

Данные, записанные с полем `description`, по-прежнему можно прочитать — лишнее поле игнорируется.

### Правила schema evolution

| Действие | Поддержка | Примечание |
|----------|-----------|-----------|
| Добавить nullable-поле | Да | Старые записи вернут null/default |
| Удалить поле | Да | Поле игнорируется при чтении |
| Переименовать поле | Нет | Старое поле станет null, новое не прочитается |
| Изменить тип поля | Нет | Ошибка десериализации |

> **Практический совет:** При schema evolution делай новые поля `@Nullable` или используй примитивы с default-значениями. Это обеспечит обратную совместимость при rolling update.

## Маппинг Domain <-> HZ DTO

Хорошая практика — разделять доменную модель и DTO для Hazelcast. Доменные объекты не должны зависеть от механизма хранения.

### Ручной маппинг

```java
@Component
class ProductMapper {

    ProductValue toHZ(Product product) {
        return new ProductValue(
            product.getCategoryId(),
            product.getName(),
            product.getStatus().name(),
            new ProductValue.PriceValue(
                product.getPrice().amount(),
                product.getPrice().currency()
            ),
            product.getDescription()
        );
    }

    Product toDomain(String key, ProductValue value) {
        return new Product(
            key,
            value.categoryId(),
            value.name(),
            Status.valueOf(value.status()),
            new Price(value.price().amount(), value.price().currency()),
            value.description()
        );
    }
}
```

### MapStruct

Для сложных DTO MapStruct генерирует маппинг автоматически:

```java
@Mapper(componentModel = "spring")
public interface ProductMapper {
    ProductValue toHZ(Product product);
    Product toDomain(String key, ProductValue value);

    // Конвертация типов, не поддерживаемых Compact Serialization
    default long toEpochMilli(Instant instant) {
        return instant.toEpochMilli();
    }

    default Instant toInstant(long epochMilli) {
        return Instant.ofEpochMilli(epochMilli);
    }
}
```

> **Зачем маппинг Instant -> long:** Compact Serialization не поддерживает `java.time.Instant` напрямую. Время хранится как `long` (epoch milliseconds) и конвертируется при маппинге.

## Поддерживаемые типы в Compact Serialization

| Java-тип | Compact-тип | Метод |
|----------|------------|-------|
| `boolean` | Boolean | `readBoolean` / `writeBoolean` |
| `byte` / `short` / `int` | Int32 | `readInt32` / `writeInt32` |
| `long` | Int64 | `readInt64` / `writeInt64` |
| `float` | Float32 | `readFloat32` / `writeFloat32` |
| `double` | Float64 | `readFloat64` / `writeFloat64` |
| `String` | String | `readString` / `writeString` |
| `BigDecimal` | Decimal | `readDecimal` / `writeDecimal` |
| `LocalDate` | Date | `readDate` / `writeDate` |
| `LocalTime` | Time | `readTime` / `writeTime` |
| `LocalDateTime` | Timestamp | `readTimestamp` / `writeTimestamp` |
| `OffsetDateTime` | TimestampWithTimezone | `readTimestampWithTimezone` |
| Compact class | Compact | `readCompact` / `writeCompact` |
| `boolean[]`, `int[]`, ... | Array of X | `readArrayOfInt32` / ... |

> `Instant`, `Duration`, `Enum` не поддерживаются напрямую — их нужно конвертировать (в `long`, `String`).

## Практика

1. Создай Java Record с 5-6 полями (включая вложенный record) и зарегистрируй для Compact Serialization
2. Положи объект в IMap и прочитай его — убедись, что сериализация/десериализация работает
3. Добавь новое nullable-поле в record, прочитай старые данные — убедись, что schema evolution работает
4. Напиши кастомный `CompactSerializer` для класса с `Instant`-полем (конвертация в epoch millis)
5. Создай маппер (ручной или MapStruct) для конвертации Domain <-> HZ DTO
6. Сравни размер сериализованных данных: Compact vs `java.io.Serializable` (используй `SerializationService.toBytes`)

## Итоги урока

- Compact Serialization — рекомендуемый механизм сериализации в Hazelcast 5.2+
- Java Records поддерживаются в zero-config режиме: достаточно определить record и зарегистрировать класс
- Compact Serialization обеспечивает schema evolution: можно добавлять и удалять nullable-поля без нарушения совместимости
- Partial deserialization позволяет читать отдельные поля для индексов и Predicates без десериализации всего объекта
- Регистрация DTO нужна и на клиенте, и на сервере
- Доменная модель не должна зависеть от Hazelcast — используй отдельные HZ DTO с маппером
- `Instant`, `Enum`, `Duration` не поддерживаются напрямую — конвертируй в `long` или `String`
- При rolling update новые nullable-поля обеспечивают обратную совместимость