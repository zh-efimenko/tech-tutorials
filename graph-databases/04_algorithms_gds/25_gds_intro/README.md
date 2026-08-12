# Урок 25. Введение в GDS

> **Важно**: выводы в уроке сняты на базовом датасете из урока 9 — отсюда `nodeCount: 30` в примере проекции и реальные почты в топе PageRank. Если генератор синтетических данных из урока 9 уже запускался, узлов в проекции будет около двадцати тысяч, а состав топа зависит от того, как легли случайные подписки: синтетические аккаунты образуют собственный плотный подграф и обычно вытесняют реальных пользователей. Для алгоритмов трека 4 синтетика полезна: на графе из тридцати узлов разница между алгоритмами не видна. Сверяй структуру результата, а не конкретные числа.

## Что делает библиотека

Cypher отвечает на вопросы о **конкретном** узле: что купила Анна, кто заходил с этого устройства, какие категории вложены в «Кухню». Всё это обходы от известной точки.

Graph Data Science отвечает на вопросы о **графе целиком**: кто здесь самый влиятельный, на какие сообщества распадаются пользователи, какие узлы похожи друг на друга. Такие вопросы требуют пройти весь граф, и Cypher для этого не приспособлен.

| Вопрос | Инструмент |
|---|---|
| Что купил конкретный пользователь | Cypher |
| Кратчайший путь между двумя узлами | Cypher `SHORTEST` или GDS |
| Кто самый влиятельный в сети подписок | GDS |
| На какие группы распадается граф | GDS |
| Какие пользователи похожи по покупкам | GDS |
| Взвешенный кратчайший путь, A* | GDS |

## Проекция графа

Алгоритмы не работают с базой напрямую. Сначала граф **проецируется** в память в компактном виде: только нужные метки, типы связей и свойства.

```
   База (диск)                       Проекция (память)
   ┌─────────────────────┐          ┌──────────────────┐
   │ User, Product,      │          │ только User      │
   │ Order, Review,      │  ────▶   │ только FOLLOWS   │
   │ Device, все связи   │          │ без свойств      │
   └─────────────────────┘          └──────────────────┘
        свойства, метки              массивы id и рёбер
```

Причина такой архитектуры — производительность. Алгоритм вроде PageRank делает десятки проходов по всем рёбрам; читать при этом с диска через транзакционный слой было бы на порядки медленнее.

Практические следствия:

- проекция — **снимок**, она не видит изменений в базе после создания;
- проекция живёт в heap и занимает память, пока её явно не удалить;
- перед серией алгоритмов граф проецируют один раз и переиспользуют.

## Cypher-проекция

Современный способ — функция-агрегатор `gds.graph.project()` внутри обычного запроса. Она гибкая: что нашёл `MATCH`, то и попало в проекцию.

```cypher
MATCH (u:User)-[r:FOLLOWS]->(v:User)
RETURN gds.graph.project('social', u, v) AS g;
```

```
╒═══════════════════════════════════════════════════════════════════╕
│g                                                                  │
╞═══════════════════════════════════════════════════════════════════╡
│{projectMillis: 1378, graphName: "social", nodeCount: 30,          │
│ relationshipCount: 77, ...}                                       │
└───────────────────────────────────────────────────────────────────┘
```

Проекция с весами и свойствами узлов:

```cypher
MATCH (u:User)-[:PLACED]->(o:Order)-[c:CONTAINS]->(p:Product)
RETURN gds.graph.project(
  'purchases',
  u,
  p,
  {
    sourceNodeLabels: ['User'],
    targetNodeLabels: ['Product'],
    relationshipType: 'BOUGHT',
    relationshipProperties: { weight: c.qty }
  }
) AS g;
```

Здесь проекция строится не по существующим связям, а по **вычисленному** отношению: пользователь связывается напрямую с товаром через два шага, а количество становится весом ребра. Это ключевая возможность Cypher-проекции — граф в памяти может отличаться от графа в базе.

### Неориентированные связи

Многие алгоритмы — community detection, similarity — предполагают ненаправленный граф. Направление снимается при проекции.

```cypher
MATCH (u:User)-[:FOLLOWS]->(v:User)
RETURN gds.graph.project('socialUndirected', u, v,
  {}, {undirectedRelationshipTypes: ['*']}) AS g;
```

Стрелка в `MATCH` при этом остаётся направленной. Ненаправленность обеспечивает опция `undirectedRelationshipTypes`, а шаблон `-[:FOLLOWS]-` вернул бы каждую связь дважды и задвоил бы рёбра в проекции.

> **Важно**: Louvain, Leiden и Node Similarity на направленном графе дают другие, часто бессмысленные результаты. Если алгоритм требует ненаправленности, документация об этом говорит явно, и игнорировать это нельзя.

## Каталог графов

Проекции живут в каталоге и переиспользуются между запросами.

```cypher
// Что сейчас в памяти
CALL gds.graph.list()
YIELD graphName, nodeCount, relationshipCount, memoryUsage, creationTime
RETURN graphName, nodeCount, relationshipCount, memoryUsage;

// Существует ли проекция
RETURN gds.graph.exists('social') AS exists;

// Освободить память
CALL gds.graph.drop('social') YIELD graphName RETURN graphName;

// Не падать, если проекции нет
CALL gds.graph.drop('social', false) YIELD graphName RETURN graphName;
```

> **Внимание**: проекция занимает heap и не удаляется сама. Забытые проекции — типичная причина `OutOfMemory` на сервере с GDS. Правило: создал проекцию, отработал, удалил. В приложении это оформляется как `try/finally`.

## Четыре режима выполнения

У каждого алгоритма один и тот же набор суффиксов.

| Режим | Что делает | Когда |
|---|---|---|
| `.stream` | Возвращает результат строками, ничего не пишет | Разведка, разовые отчёты |
| `.stats` | Возвращает только сводную статистику | Оценка перед запуском |
| `.mutate` | Пишет результат в проекцию в памяти | Конвейер из нескольких алгоритмов |
| `.write` | Пишет результат обратно в базу свойством узла | Результат нужен приложению |

```cypher
// stream: посмотреть глазами
CALL gds.pageRank.stream('social')
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).email AS email, round(score * 1000) / 1000 AS score
ORDER BY score DESC LIMIT 5;
```

```
╒═════════════════╤═══════╕
│email            │score  │
╞═════════════════╪═══════╡
│"oleg@shop.io"   │2.105  │
│"mult1@shop.io"  │2.059  │
│"sergey@shop.io" │1.932  │
│"elena@shop.io"  │1.469  │
│"mult3@shop.io"  │1.36   │
└─────────────────┴───────┘
```

```cypher
// write: сохранить в граф, чтобы приложение читало обычным Cypher
CALL gds.pageRank.write('social', {writeProperty: 'influence'})
YIELD nodePropertiesWritten, ranIterations
RETURN nodePropertiesWritten, ranIterations;

MATCH (u:User) WHERE u.influence IS NOT NULL
RETURN u.email, u.influence ORDER BY u.influence DESC LIMIT 5;
```

```cypher
// mutate: результат остаётся в проекции и подаётся на вход следующему алгоритму
CALL gds.pageRank.mutate('social', {mutateProperty: 'pr'})
YIELD nodePropertiesWritten;

CALL gds.louvain.stream('social', {relationshipWeightProperty: null})
YIELD nodeId, communityId
RETURN communityId, count(*) AS members ORDER BY members DESC;
```

`gds.util.asNode(nodeId)` превращает внутренний идентификатор проекции обратно в узел базы. Без него результат — просто числа.

## Оценка памяти

У каждого алгоритма есть `.estimate`, который считает потребление памяти, не запуская вычисление.

```cypher
CALL gds.pageRank.stream.estimate('social', {})
YIELD requiredMemory, nodeCount, relationshipCount
RETURN requiredMemory, nodeCount, relationshipCount;
```

То же для проекции — но здесь это процедура, а не функция, поэтому вызывается через `CALL`:

```cypher
CALL gds.graph.project.estimate('*', '*', {nodeCount: 20000, relationshipCount: 160000})
YIELD requiredMemory
RETURN requiredMemory;
```

На графе из десятков миллионов рёбер это обязательный шаг: узнать заранее, что алгоритму нужно 40 ГБ, дешевле, чем уронить сервер.

## Ограничения Community

| Возможность | Community | Enterprise |
|---|---|---|
| Все алгоритмы | Да | Да |
| Параллельность | До 4 потоков | Без ограничения |
| Сжатие проекции в памяти | Нет | Да |
| Model catalog для ML-пайплайнов | Ограниченно | Полностью |

В конфигурации проекции выше видно `readConcurrency: 4` — это и есть предел Community. На учебном графе разницы нет, на графе из сотен миллионов рёбер она принципиальна.

## Типовой конвейер

```cypher
// 1. Проекция
MATCH (u:User)-[:FOLLOWS]->(v:User)
RETURN gds.graph.project('social', u, v, {}, {undirectedRelationshipTypes: ['*']}) AS g;

// 2. Оценка памяти
CALL gds.louvain.stats.estimate('social', {}) YIELD requiredMemory RETURN requiredMemory;

// 3. Пробный запуск: сводка без записи
CALL gds.louvain.stats('social') YIELD communityCount, modularity
RETURN communityCount, modularity;

// 4. Запись результата в граф
CALL gds.louvain.write('social', {writeProperty: 'community'})
YIELD communityCount, nodePropertiesWritten
RETURN communityCount, nodePropertiesWritten;

// 5. Освобождение памяти
CALL gds.graph.drop('social') YIELD graphName RETURN graphName;

// 6. Использование результата обычным Cypher
MATCH (u:User)
RETURN u.community, count(*) AS members, collect(u.email)[0..3] AS sample
ORDER BY members DESC;
```

Шаг 6 — суть подхода: GDS считает, результат ложится в граф свойством, дальше с ним работает обычное приложение через Spring Data Neo4j.

## Вызов из приложения

```java
@Service
public class GraphAnalyticsService {

    private final Neo4jClient client;

    public GraphAnalyticsService(Neo4jClient client) {
        this.client = client;
    }

    public void refreshInfluence() {
        client.query("CALL gds.graph.drop('social', false)").run();
        client.query("""
                     MATCH (u:User)-[:FOLLOWS]->(v:User)
                     RETURN gds.graph.project('social', u, v) AS g
                     """).run();
        try {
            client.query("CALL gds.pageRank.write('social', {writeProperty: 'influence'})").run();
        } finally {
            client.query("CALL gds.graph.drop('social', false)").run();
        }
    }
}
```

> **Важно**: запросы GDS не выполняются внутри `@Transactional`. Проекция и запись результата управляют своими транзакциями, а сами вычисления идут вне транзакционного контекста. Это та же ситуация, что с `CALL {} IN TRANSACTIONS` в уроке 21.

Пересчёт алгоритмов — фоновая задача по расписанию, а не операция в обработке HTTP-запроса: PageRank на большом графе занимает минуты.

## Практика

1. Убедись, что плагин установлен: `RETURN gds.version()`.
2. Построй Cypher-проекцию `social` по связям `FOLLOWS` и посмотри `nodeCount` и `relationshipCount` в ответе.
3. Выведи список проекций через `gds.graph.list` вместе с `memoryUsage`.
4. Запусти PageRank в режиме `.stream` и выведи топ-5 пользователей с почтами через `gds.util.asNode`.
5. Запусти тот же PageRank в режиме `.write` и прочитай результат обычным Cypher.
6. Построй вторую проекцию `purchases`, где пользователь связан напрямую с товаром, а весом служит количество из связи `CONTAINS`.
7. Построй ненаправленную проекцию `FOLLOWS` и сравни результат Louvain на ней и на направленной версии.
8. Оцени память для Louvain через `.estimate` до запуска.
9. Найди в конфигурации проекции значение `readConcurrency` и объясни, откуда взялась четвёрка.
10. Удали все проекции и проверь через `gds.graph.list`, что каталог пуст.

## Итоги урока

- Cypher отвечает на вопросы о конкретном узле, GDS — о графе целиком: влияние, сообщества, похожесть.
- Алгоритмы работают не с базой, а с проекцией в памяти: только нужные метки, типы связей и свойства.
- Проекция — снимок: изменения в базе после её создания в неё не попадают.
- Cypher-проекция через функцию `gds.graph.project()` позволяет строить в памяти граф, которого нет в базе, — например, связывать пользователя с товаром напрямую через два шага.
- Многие алгоритмы требуют ненаправленного графа; направление снимается опцией `undirectedRelationshipTypes` при проекции.
- Проекции живут в каталоге, занимают heap и не удаляются сами — забытые проекции являются типичной причиной `OutOfMemory`.
- У каждого алгоритма четыре режима: `.stream` для разведки, `.stats` для сводки, `.mutate` для конвейера, `.write` для записи результата в граф.
- `gds.util.asNode(nodeId)` переводит внутренний идентификатор проекции обратно в узел базы.
- `.estimate` считает требуемую память без запуска алгоритма — обязательный шаг на больших графах.
- Community ограничивает параллельность четырьмя потоками; сам набор алгоритмов не урезан.
- Запросы GDS не выполняются внутри `@Transactional`, а пересчёт выносится в фоновую задачу по расписанию.
