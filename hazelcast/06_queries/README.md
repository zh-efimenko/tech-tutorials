# Урок 6. Запросы: Predicates и индексы

## Проблема: поиск данных в распределённой карте

`IMap.get(key)` работает отлично, когда ты знаешь ключ. Но что если нужно найти все товары категории "электроника" или всех пользователей с определённым статусом?

Без специального механизма единственный вариант — загрузить **все** записи на клиент и отфильтровать локально. На карте с миллионом записей это неприемлемо.

Hazelcast решает эту задачу двумя инструментами: **Predicates API** (фильтрация на сервере) и **индексы** (ускорение фильтрации).

## Predicates API

Predicates позволяют фильтровать данные **на стороне сервера**. Клиент отправляет условие, сервер возвращает только подходящие записи.

```java
IMap<String, ProductValue> products = hazelcast.getMap("products");

// Найти все товары категории 42
Collection<ProductValue> result = products.values(
    Predicates.equal("categoryId", 42L)
);

// Найти товары нескольких категорий
Collection<ProductValue> result = products.values(
    Predicates.in("categoryId", 42L, 43L, 44L)
);
```

### Доступные предикаты

| Предикат | Описание | Пример |
|----------|----------|--------|
| `equal` | Точное совпадение | `Predicates.equal("status", "ACTIVE")` |
| `notEqual` | Не равно | `Predicates.notEqual("status", "DELETED")` |
| `greaterThan` | Больше | `Predicates.greaterThan("price", 1000)` |
| `lessThan` | Меньше | `Predicates.lessThan("price", 500)` |
| `between` | Диапазон | `Predicates.between("price", 100, 1000)` |
| `in` | Входит в набор | `Predicates.in("categoryId", 1L, 2L, 3L)` |
| `like` | SQL LIKE | `Predicates.like("name", "Ноутбук%")` |
| `ilike` | Case-insensitive LIKE | `Predicates.ilike("name", "%apple%")` |
| `regex` | Регулярное выражение | `Predicates.regex("name", "^iPhone.*")` |
| `instanceOf` | Проверка типа | `Predicates.instanceOf(PremiumProduct.class)` |

### Составные предикаты

```java
// AND
Predicate<String, ProductValue> activeExpensive = Predicates.and(
    Predicates.equal("status", "ACTIVE"),
    Predicates.greaterThan("price", 10000)
);

// OR
Predicate<String, ProductValue> highlighted = Predicates.or(
    Predicates.equal("featured", true),
    Predicates.greaterThan("rating", 4.5)
);

// NOT
Predicate<String, ProductValue> notDeleted = Predicates.not(
    Predicates.equal("status", "DELETED")
);

// Комбинация
Collection<ProductValue> result = products.values(
    Predicates.and(activeExpensive, notDeleted)
);
```

### Операции с предикатами

| Операция | Описание |
|----------|----------|
| `values(predicate)` | Вернуть значения, подходящие под условие |
| `keySet(predicate)` | Вернуть ключи |
| `entrySet(predicate)` | Вернуть пары ключ-значение |
| `removeAll(predicate)` | Удалить все записи по условию (server-side, без загрузки на клиент) |

```java
// Server-side удаление — данные не загружаются на клиент
products.removeAll(Predicates.equal("categoryId", 42L));
```

## Индексы

Без индекса `values(Predicates.equal("categoryId", 42))` сканирует **все** записи на **всех** партициях — это `O(n)` с сетевыми вызовами. С индексом — `O(1)` хэш-поиск на каждой партиции.

### Типы индексов

| Тип | Поддерживает | Когда использовать |
|-----|-------------|-------------------|
| `HASH` | `=`, `in` | Точное совпадение |
| `SORTED` | `=`, `<`, `>`, `between`, `in` | Диапазонные запросы |
| `BITMAP` | `=`, `in` | Кардинальность < 1000 (статусы, флаги) |

### Конфигурация индекса

**YAML (серверная конфигурация):**

```yaml
map:
  products:
    indexes:
      - type: HASH
        attributes: [ "categoryId" ]
      - type: SORTED
        attributes: [ "price" ]
      - type: BITMAP
        attributes: [ "status" ]
```

**Java Config:**

```java
MapConfig productsConfig = new MapConfig("products");
productsConfig.addIndexConfig(new IndexConfig(IndexType.HASH, "categoryId"));
productsConfig.addIndexConfig(new IndexConfig(IndexType.SORTED, "price"));
productsConfig.addIndexConfig(new IndexConfig(IndexType.BITMAP, "status"));
```

### Составные индексы

```yaml
map:
  products:
    indexes:
      - type: SORTED
        attributes: [ "categoryId", "price" ]  # Составной индекс
```

Составной индекс ускоряет запросы по `categoryId`, по `categoryId + price`, но **не** по `price` отдельно (как и в SQL-базах).

### Выбор типа индекса

```
Какие запросы?
     │
     ├── Только = и in ──────────► HASH
     │                              (быстрее для точных совпадений)
     │
     ├── <, >, between ──────────► SORTED
     │                              (поддерживает все операции)
     │
     └── Мало уникальных значений ► BITMAP
           (статус: 3-5 значений)    (компактнее по памяти)
```

### Индексы и Compact Serialization

Индексы работают с полями Compact-объектов через **partial deserialization**. Hazelcast читает только индексируемое поле без десериализации всего объекта.

```
Полная десериализация (без Compact):
┌─────────────────────────────────┐
│ Весь объект: 500 байт           │ → Java Object → field access
└─────────────────────────────────┘

Partial deserialization (с Compact):
┌──────┐─────────────────────────┐
│field │ остальные 490 байт      │ → читаем только field
└──────┘─────────────────────────┘
```

> Это ключевое преимущество Compact Serialization — индексация работает значительно быстрее.

## Вложенные поля и ключи

### Запросы по вложенным полям

```java
// Запись: ProductValue(price=PriceValue(amount=999, currency="USD"))
// Обращение к вложенному полю через точку
products.values(Predicates.greaterThan("price.amount", 500L));
```

Индексы тоже поддерживают вложенные поля:

```yaml
indexes:
  - type: SORTED
    attributes: [ "price.amount" ]
```

### Запросы по ключу

```java
// Поиск по ключу карты
products.values(Predicates.equal("__key", "prod-42"));

// Полезно, если ключ — составной объект
products.values(Predicates.equal("__key.region", "EU"));
```

## SQL-запросы (альтернатива Predicates)

Hazelcast 5.x поддерживает SQL как альтернативу Predicates API:

```java
// Эквивалент Predicates.equal("categoryId", 42)
try (SqlResult result = hazelcast.getSql().execute(
    "SELECT * FROM products WHERE categoryId = ?", 42L
)) {
    for (SqlRow row : result) {
        String name = row.getObject("name");
        long price = row.getObject("price.amount");
    }
}
```

### Когда SQL, когда Predicates

| Критерий | Predicates | SQL |
|----------|-----------|-----|
| Простые запросы (=, in) | Быстрее (нет парсинга) | Работает |
| Сложные запросы (JOIN, ORDER BY) | Не поддерживает | Поддерживает |
| Агрегации (COUNT, AVG, SUM) | Через Aggregators API | `SELECT COUNT(*) FROM ...` |
| Type safety | Compile-time проверка | Строки |
| Код | Java API | SQL-строки |

> Для простых запросов (`equal`, `in`) Predicates API быстрее, так как не требует парсинга SQL. SQL имеет смысл для сложных запросов с JOIN, агрегациями и сортировкой.

## Проектирование ключа карты

Выбор ключа IMap — одно из важнейших решений при проектировании:

```java
// Вариант 1: простой ключ
IMap<Long, Order> orders; // Ключ = ID заказа

// Вариант 2: строковый ключ для Predicates
IMap<String, OrderItem> items; // Ключ = "order:42:item:1"
// Поле orderId в значении + индекс для поиска всех items заказа

// Вариант 3: составной ключ (объект)
public record OrderItemKey(long orderId, long itemId) {}
IMap<OrderItemKey, OrderItem> items;
```

> **Практическое правило:** Если часто ищешь записи по полю, отличному от ключа — вынеси это поле в значение и создай индекс. Это надёжнее, чем разбирать составной строковый ключ.

## Практика

1. Создай IMap с 10 000 записей, каждая с полями `categoryId`, `status`, `price`
2. Выполни `values(Predicates.equal("categoryId", 5))` без индекса — замерь время
3. Добавь HASH-индекс на `categoryId`, повтори запрос — сравни время
4. Создай SORTED-индекс на `price` и выполни `between`-запрос
5. Используй `removeAll(predicate)` для удаления всех записей с `status = "DELETED"`
6. Создай составной предикат (AND/OR) и убедись, что индексы используются
7. Выполни аналогичный запрос через SQL API и сравни результат с Predicates

## Итоги урока

- Predicates API фильтрует данные на стороне сервера, не загружая все записи на клиент
- Без индекса запрос по предикату сканирует все записи (O(n)), с индексом — O(1) для HASH
- HASH-индекс для `=` и `in`, SORTED для диапазонов, BITMAP для полей с малой кардинальностью
- Compact Serialization обеспечивает partial deserialization — индексы читают только нужные поля
- `removeAll(predicate)` удаляет записи на сервере без загрузки на клиент
- SQL-запросы — альтернатива Predicates для сложных запросов с JOIN и агрегациями
- Индексы настраиваются в серверной конфигурации (YAML или Java Config)
- Правильный выбор ключа и индексов — ключевой фактор производительности запросов