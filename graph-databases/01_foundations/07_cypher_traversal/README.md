# Урок 7. Cypher: обходы и агрегации

## Зачем нужны обходы переменной длины

Всё, что было до сих пор — паттерны фиксированной длины: ровно один шаг, ровно два шага. Но настоящие графовые задачи формулируются иначе: «все подкатегории на любой глубине», «цепочка приглашений до самого первого пригласившего», «связан ли этот аккаунт с заблокированным хотя бы как-нибудь». Глубина заранее неизвестна, и именно здесь граф даёт то, чего нет в SQL без рекурсивных CTE.

## Подготовка данных

Примеры урока идут по иерархии категорий глубиной три уровня и по цепочке приглашений. В графе из урока 4 их ещё нет — создай перед чтением, иначе запросы вернут пустой результат.

```cypher
// Третий уровень иерархии: Эспрессо-кофеварки → Кофеварки → Кухня
MATCH (cof:Category {name: 'Кофеварки'})
MERGE (e:Category {name: 'Эспрессо-кофеварки'})
MERGE (e)-[:SUBCATEGORY_OF]->(cof);

// Цепочка приглашений от Анны вглубь
MATCH (a:User {email: 'anna@shop.io'})
MERGE (p:User {email: 'petr@shop.io'})  ON CREATE SET p.name = 'Пётр', p.registeredAt = date('2026-01-05')
MERGE (d:User {email: 'dima@shop.io'})  ON CREATE SET d.name = 'Дима',  d.registeredAt = date('2026-02-05')
MERGE (k:User {email: 'kira@shop.io'})  ON CREATE SET k.name = 'Кира',  k.registeredAt = date('2026-03-05')
MERGE (a)-[:REFERRED]->(p)
MERGE (p)-[:REFERRED]->(d)
MERGE (d)-[:REFERRED]->(k);
```

## Пути переменной длины

Синтаксис — звёздочка с диапазоном внутри квадратных скобок связи.

```cypher
// Ровно 2 шага
MATCH (c:Category {name: 'Эспрессо-кофеварки'})-[:SUBCATEGORY_OF*2]->(root:Category)
RETURN root.name;

// От 1 до 3 шагов
MATCH (c:Category {name: 'Эспрессо-кофеварки'})-[:SUBCATEGORY_OF*1..3]->(parent:Category)
RETURN parent.name;

// 1 и более шагов — вся цепочка вверх до корня
MATCH (c:Category {name: 'Эспрессо-кофеварки'})-[:SUBCATEGORY_OF*]->(parent:Category)
RETURN parent.name;

// 0 и более: сам узел тоже попадёт в результат
MATCH (c:Category {name: 'Кухня'})<-[:SUBCATEGORY_OF*0..]-(sub:Category)
RETURN sub.name;
```

| Запись | Значение |
|---|---|
| `*` | От 1 до бесконечности |
| `*2` | Ровно 2 |
| `*1..3` | От 1 до 3 |
| `*..3` | От 1 до 3 |
| `*2..` | От 2 до бесконечности |
| `*0..1` | Ноль или один — узел сам или его сосед |

> **Внимание**: `*` без верхней границы на плотном графе — самый быстрый способ повесить базу. Количество путей растёт экспоненциально: при среднем количестве связей 50 обход глубины 5 обходит порядка 300 миллионов путей. Верхнюю границу нужно ставить всегда, кроме случаев, когда граф заведомо дерево.

### Работа с найденным путём

Переменная перед звёздочкой даёт доступ к списку связей:

```cypher
// Цепочка приглашений и её длина
MATCH path = (u:User {email: 'anna@shop.io'})-[r:REFERRED*1..5]->(invited:User)
RETURN invited.name, length(path) AS depth
ORDER BY depth;
```

Направление здесь принципиально: связь создаётся как «пригласивший → приглашённый», поэтому вниз по дереву приглашений идёт стрелка `->`. Развернув её на `<-`, получишь цепочку тех, кто пригласил самого пользователя, — а для Анны, приглашённой никем, это пустой результат.

Именованный путь `path = (...)` — отдельный тип данных со своими функциями:

| Функция | Возвращает |
|---|---|
| `length(path)` | Количество связей в пути |
| `nodes(path)` | Список узлов |
| `relationships(path)` | Список связей |

```cypher
MATCH path = (a:Category {name: 'Эспрессо-кофеварки'})-[:SUBCATEGORY_OF*]->(:Category {name: 'Кухня'})
RETURN [n IN nodes(path) | n.name] AS chain, length(path) AS steps;
```

```
╒══════════════════════════════════════════════════════╤═══════╕
│chain                                                 │steps  │
╞══════════════════════════════════════════════════════╪═══════╡
│["Эспрессо-кофеварки", "Кофеварки", "Кухня"]          │2      │
└──────────────────────────────────────────────────────┴───────┘
```

## Кратчайший путь

Перебирать все пути ради самого короткого — дорого. Для этого есть отдельные функции с собственным алгоритмом обхода.

```cypher
// Один кратчайший путь между двумя пользователями по любым связям
MATCH (a:User {email: 'anna@shop.io'}), (b:User {email: 'petr@shop.io'})
MATCH path = shortestPath((a)-[*..6]-(b))
RETURN [n IN nodes(path) | coalesce(n.name, n.title, n.id)] AS chain, length(path) AS distance;

// Все кратчайшие пути одинаковой минимальной длины
MATCH (a:User {email: 'anna@shop.io'}), (b:User {email: 'petr@shop.io'})
MATCH path = allShortestPaths((a)-[*..6]-(b))
RETURN length(path) AS distance, count(*) AS pathCount;
```

Типовое применение — антифрод: «насколько близко подозрительный аккаунт к уже заблокированному».

> **Важно**: `shortestPath` считает длину в количестве связей, все рёбра равнозначны. Если у связей есть вес — стоимость, расстояние, время — нужен Dijkstra из библиотеки GDS, урок 29.

## WITH: конвейер запроса

`WITH` разделяет запрос на этапы: всё, что слева, вычисляется и передаётся дальше. Роль та же, что у подзапроса в SQL, но пишется линейно.

```cypher
// Пользователи, потратившие больше 5000, и их последний заказ
MATCH (u:User)-[:PLACED]->(o:Order)
WITH u, sum(o.total) AS revenue, max(o.id) AS lastOrderId
WHERE revenue > 5000
RETURN u.name, revenue, lastOrderId
ORDER BY revenue DESC;
```

Три вещи, которые умеет только `WITH`:

**1. Фильтрация по агрегату.** Аналог `HAVING` в SQL — отдельного ключевого слова в Cypher нет, фильтр после `WITH` и есть `HAVING`.

```cypher
MATCH (p:Product)<-[:CONTAINS]-(o:Order)
WITH p, count(o) AS orders
WHERE orders >= 3
RETURN p.title, orders;
```

**2. Ограничение перед следующим шагом.** Позволяет сначала отобрать топ, а потом идти по связям только от него.

```cypher
// Топ-3 товара по продажам и их категории.
// Без WITH ... LIMIT обход категорий шёл бы для всех товаров
MATCH (p:Product)<-[:CONTAINS]-(o:Order)
WITH p, count(o) AS sales
ORDER BY sales DESC LIMIT 3
MATCH (p)-[:IN_CATEGORY]->(c:Category)
RETURN p.title, sales, c.name;
```

**3. Дедупликация в середине запроса.**

```cypher
MATCH (u:User)-[:PLACED]->(:Order)-[:CONTAINS]->(p:Product)
WITH DISTINCT p
MATCH (p)-[:IN_CATEGORY]->(c:Category)
RETURN c.name, count(p) AS soldProducts;
```

> **Внимание**: `WITH` обрывает область видимости. Переменная, не перечисленная в `WITH`, дальше недоступна — это самая частая ошибка новичка. Если после `WITH u, revenue` понадобился `o`, его придётся искать заново.

## collect и UNWIND

Пара взаимно обратных операций: `collect` сворачивает строки в список, `UNWIND` разворачивает список в строки.

```cypher
// Свернуть: одна строка на пользователя со списком товаров
MATCH (u:User)-[:PLACED]->(:Order)-[:CONTAINS]->(p:Product)
RETURN u.name, collect(DISTINCT p.title) AS products;

// Развернуть: строка на каждый элемент списка
UNWIND ['CM-100', 'GR-200', 'KT-300'] AS sku
MATCH (p:Product {sku: sku})
RETURN p.title, p.price;
```

`UNWIND` — основной способ передать в запрос пачку данных одним параметром. Именно так работает батчевая загрузка из приложения:

```cypher
// Значение параметра пишется одной строкой: cypher-shell не поддерживает
// перенос через обратный слэш и упадёт на нём с ошибкой разбора выражения
:param rows => [{sku: 'BL-400', title: 'Блендер Turbo', price: 3490.0}, {sku: 'TS-500', title: 'Тостер Crisp', price: 1290.0}]

UNWIND $rows AS row
MERGE (p:Product {sku: row.sku})
  ON CREATE SET p.title = row.title, p.price = row.price
RETURN count(*) AS processed;
```

Один запрос вместо сотни — разница по скорости на порядки. Этот приём используется и в уроке 9, и во всём Java-коде трека 3.

Комбинация обеих операций решает задачу «топ-N внутри группы»:

```cypher
// Три самых дорогих товара в каждой категории
MATCH (c:Category)<-[:IN_CATEGORY]-(p:Product)
WITH c, p ORDER BY p.price DESC
WITH c, collect(p)[0..3] AS topProducts
UNWIND topProducts AS p
RETURN c.name, p.title, p.price;
```

Разбор: сортировка перед `collect` сохраняется внутри списка, срез `[0..3]` берёт первые три, `UNWIND` возвращает их обратно строками.

## Функции списков

```cypher
// Проекция: преобразовать каждый элемент
MATCH (o:Order)-[c:CONTAINS]->(p:Product)
WITH o, collect(p.price * c.qty) AS lineTotals
RETURN o.id, lineTotals, reduce(acc = 0.0, x IN lineTotals | acc + x) AS computedTotal;

// Фильтрация внутри списка
MATCH (u:User)-[:PLACED]->(o:Order)
WITH u, collect(o) AS orders
RETURN u.name, [o IN orders WHERE o.total > 5000 | o.id] AS bigOrders;

// Предикаты по списку
MATCH (u:User)-[:PLACED]->(o:Order)
WITH u, collect(o.status) AS statuses
RETURN u.name,
       all(s IN statuses WHERE s = 'delivered')  AS allDelivered,
       any(s IN statuses WHERE s = 'cancelled')  AS hasCancelled,
       none(s IN statuses WHERE s = 'pending')   AS nothingPending;
```

| Функция | Назначение |
|---|---|
| `[x IN list \| expr]` | Проекция каждого элемента |
| `[x IN list WHERE cond]` | Фильтр |
| `[x IN list WHERE cond \| expr]` | Фильтр и проекция |
| `reduce(acc = init, x IN list \| expr)` | Свёртка в одно значение |
| `all`, `any`, `none`, `single` | Предикаты |
| `size(list)` | Длина |
| `head`, `last`, `tail` | Первый, последний, хвост |
| `list[0..3]` | Срез |
| `range(1, 10)` | Генерация списка чисел |

## Функции map

```cypher
// Собрать структуру в ответе — так формируют DTO для приложения
MATCH (u:User)-[:PLACED]->(o:Order)
RETURN u.name, collect({orderId: o.id, total: o.total, status: o.status}) AS orders;

// Все свойства узла как map
MATCH (p:Product {sku: 'CM-100'}) RETURN properties(p) AS props;

// Ключи и обращение по вычисляемому ключу
MATCH (p:Product {sku: 'CM-100'})
WITH properties(p) AS props
RETURN keys(props) AS fields, props['title'] AS title;
```

Проекция узла в структуру — способ вернуть приложению ровно нужные поля вместо узла целиком:

```cypher
MATCH (p:Product)
RETURN p {.sku, .title, .price} AS product;
```

Эта же запись напрямую отображается на DTO в Spring Data Neo4j, урок 19.

## Подзапросы CALL

`CALL {}` выполняет вложенный запрос для каждой входящей строки. Переменные из внешнего запроса передаются явным списком в скобках.

```cypher
// Для каждой категории — два самых дорогих товара
MATCH (c:Category)
CALL (c) {
  MATCH (c)<-[:IN_CATEGORY]-(p:Product)
  RETURN p ORDER BY p.price DESC LIMIT 2
}
RETURN c.name, collect(p.title) AS topProducts;
```

Без `CALL {}` ограничить выборку внутри группы не получится: `LIMIT` во внешнем запросе обрежет общий результат, а не по категории.

`UNION` объединяет результаты нескольких запросов с одинаковыми именами колонок:

```cypher
MATCH (u:User)-[:PLACED]->(:Order)-[:CONTAINS]->(p:Product)
RETURN p.title AS title, 'purchased' AS source
UNION
MATCH (u:User)-[:VIEWED]->(p:Product)
RETURN p.title AS title, 'viewed' AS source;
```

## Практика

> **Внимание**: задания 5 и 6 считают агрегаты по заказам, а в графе урока 4 их всего два. На таких данных фильтр «больше двух заказов» и топ-3 по продажам вернут пустой или вырожденный результат — это нормально. Осмысленные числа появятся после загрузки датасета в уроке 9; к этим заданиям стоит вернуться тогда.

1. Дострой иерархию категорий минимум на три уровня и выведи полную цепочку от самой глубокой подкатегории до корня одной строкой через `nodes(path)`.
2. Найди все подкатегории категории «Кухня» на любой глубине, включая её саму.
3. Создай цепочку из четырёх пользователей, связанных `REFERRED`, и найди для последнего всю цепочку пригласивших с указанием глубины.
4. Найди кратчайший путь между двумя пользователями по любым типам связей с ограничением глубины 6 и выведи цепочку имён и названий.
5. Выведи пользователей, у которых больше двух заказов, использовав фильтр по агрегату после `WITH`.
6. Возьми топ-3 товара по количеству продаж и только для них выведи категорию — обход категорий должен идти после `LIMIT`.
7. Загрузи пять новых товаров одним запросом через `UNWIND $rows` и `MERGE`.
8. Выведи для каждой категории два самых дорогих товара через `CALL (c) {}`.
9. Для каждого заказа посчитай сумму позиций через `reduce` и сравни с сохранённым полем `total`.
10. Верни список пользователей, где для каждого собрана структура `{orderId, total, status}` по всем его заказам.

## Итоги урока

- Синтаксис `*1..3` задаёт обход переменной глубины; верхнюю границу нужно ставить всегда, иначе количество путей растёт экспоненциально.
- Именованный путь `path = (...)` даёт функции `length`, `nodes` и `relationships` для работы с найденной цепочкой.
- `shortestPath` и `allShortestPaths` используют отдельный алгоритм и считают длину в рёбрах; для взвешенных путей нужен Dijkstra из GDS.
- `WITH` разбивает запрос на этапы и обрывает область видимости: не перечисленные переменные дальше недоступны.
- Фильтр после `WITH` заменяет `HAVING`, а `WITH ... ORDER BY ... LIMIT` перед следующим `MATCH` резко сокращает объём обхода.
- `collect` сворачивает строки в список, `UNWIND` разворачивает список в строки; их комбинация решает задачу «топ-N внутри группы».
- `UNWIND $rows` — основной способ батчевой загрузки: один запрос вместо сотни отдельных.
- `CALL (var) {}` выполняет подзапрос для каждой входящей строки и позволяет применять `LIMIT` внутри группы.
- Проекция `p {.sku, .title}` формирует структуру ответа и напрямую отображается на DTO в Spring Data Neo4j.
