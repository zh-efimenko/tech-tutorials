# Урок 1. Введение в Hazelcast

## Зачем нужен In-Memory Data Grid

Представь типичную высоконагруженную систему: тысячи запросов в секунду, требования к латентности менее 1 мс, данные должны быть доступны даже при падении отдельных серверов. Классическая база данных (PostgreSQL, MySQL) здесь не справится — даже с пулом соединений и индексами время ответа измеряется миллисекундами, а при высокой нагрузке — десятками миллисекунд.

**In-Memory Data Grid (IMDG)** решает эту проблему: данные хранятся в оперативной памяти, распределены по кластеру серверов и реплицированы для отказоустойчивости. Доступ к данным — микросекунды вместо миллисекунд.

Hazelcast — одна из ведущих реализаций IMDG для JVM-экосистемы. Текущая актуальная версия — **Hazelcast Platform 5.6** (октябрь 2025).

## Что такое Hazelcast

Hazelcast — это распределённое хранилище данных в оперативной памяти с открытым исходным кодом. Ключевые характеристики:

- **Распределённость** — данные автоматически разделяются (партиционируются) между узлами кластера
- **Репликация** — каждая запись имеет настраиваемое количество копий на других узлах
- **Отказоустойчивость** — при падении узла его данные доступны с реплик, кластер автоматически перебалансируется
- **Масштабируемость** — добавление узлов увеличивает объём доступной памяти и пропускную способность
- **Java API** — нативная интеграция с Java, Spring Boot, Kubernetes

## Какие задачи решает Hazelcast

| Задача | Пример | Почему не БД |
|--------|--------|-------------|
| Кэширование горячих данных | Каталог товаров, профили пользователей | Частые чтения, допустима eventual consistency |
| Хранение ephemeral-данных | Сессии, heartbeat-ы, временные токены | Не нужно долговременное хранение |
| Распределённые блокировки | Координация между инстансами | `synchronized` работает только в одной JVM |
| Real-time аналитика | Счётчики, агрегации в реальном времени | Латентность БД неприемлема |
| Pub/Sub между инстансами | Инвалидация кэшей, broadcast-события | Не нужен отдельный message broker |

## Hazelcast vs альтернативы

| Характеристика | Hazelcast | Redis | Apache Ignite | Memcached |
|---------------|-----------|-------|---------------|-----------|
| Язык | Java (JVM-native) | C | Java | C |
| Встраивание в JVM | Да (embedded mode) | Нет | Да | Нет |
| Распределённые структуры данных | IMap, IQueue, ITopic, ISet, IList | Strings, Hashes, Lists, Sets | Cache, SQL Tables | Key-Value |
| SQL-запросы | Да (Hazelcast SQL) | Нет | Да (полноценный SQL) | Нет |
| Партиционирование | Автоматическое (271 партиция) | Ручное (Redis Cluster) | Автоматическое | Нет (клиентский шардинг) |
| Транзакции | Да | Lua-скрипты | Да (ACID) | Нет |
| Персистентность | Опциональная (MapStore) | RDB/AOF | Да (native persistence) | Нет |
| Spring Boot интеграция | Автоконфигурация из коробки | Через Spring Data Redis | Через Spring Data | Нет |

**Когда выбирать Hazelcast:**

- Проект на Java/Spring Boot — нативная интеграция без сериализации в строки
- Нужны распределённые структуры данных (не только key-value)
- Важна embedded-модель — Hazelcast работает в том же процессе, что и приложение
- Требуется server-side вычисление — EntryProcessor, агрегации выполняются рядом с данными

**Когда НЕ выбирать Hazelcast:**

- Нужна полноценная персистентная БД — Hazelcast в первую очередь in-memory
- Polyglot-стек (Python, Node.js, Go) — Redis имеет лучшую поддержку клиентов
- Простое кэширование без распределённых структур — Redis проще в эксплуатации

## Архитектура на высоком уровне

```
┌──────────────────────────────────────────────┐
│              Hazelcast Cluster                │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  Node 1  │  │  Node 2  │  │  Node 3  │   │
│  │          │  │          │  │          │   │
│  │ Part 0-90│  │Part 91-180│ │Part 181-270│  │
│  │ (owner)  │  │ (owner)  │  │ (owner)  │   │
│  │          │  │          │  │          │   │
│  │ Backups  │  │ Backups  │  │ Backups  │   │
│  │from 2,3  │  │from 1,3  │  │from 1,2  │   │
│  └──────────┘  └──────────┘  └──────────┘   │
│                                              │
└──────────────────────────────────────────────┘
         ▲              ▲              ▲
         │              │              │
    ┌────┴────┐   ┌────┴────┐   ┌────┴────┐
    │  App 1  │   │  App 2  │   │  App 3  │
    │(client) │   │(client) │   │(client) │
    └─────────┘   └─────────┘   └─────────┘
```

Hazelcast разделяет все данные на **271 партицию** (по умолчанию). Каждая партиция имеет владельца (owner) и настраиваемое количество реплик (backups). Ключ определяет, в какую партицию попадёт запись: `partitionId = hash(key) % partitionCount`.

## Основные структуры данных

| Структура | Java-аналог | Описание |
|-----------|-------------|----------|
| `IMap<K, V>` | `ConcurrentMap` | Распределённая карта — основная структура |
| `IQueue<E>` | `BlockingQueue` | Распределённая очередь |
| `ITopic<E>` | — | Pub/Sub механизм |
| `ISet<E>` | `Set` | Распределённое множество |
| `IList<E>` | `List` | Распределённый список |
| `IAtomicLong` | `AtomicLong` | Распределённый атомарный счётчик (CP Subsystem) |
| `FencedLock` | `ReentrantLock` | Распределённая блокировка (CP Subsystem) |
| `Ringbuffer<E>` | — | Кольцевой буфер для reliable messaging |

> **IMap** — это 90% использования Hazelcast на практике. Остальные структуры данных рассматриваются в уроке 12.

## Быстрый старт

### Запуск сервера

```bash
docker run -d --name hazelcast \
  -p 5701:5701 \
  -e HZ_CLUSTERNAME=dev \
  hazelcast/hazelcast:5.6.0
```

### Подключение из Java

```java
import com.hazelcast.client.HazelcastClient;
import com.hazelcast.client.config.ClientConfig;
import com.hazelcast.core.HazelcastInstance;
import com.hazelcast.map.IMap;

public class QuickStart {
    public static void main(String[] args) {
        ClientConfig config = new ClientConfig();
        config.setClusterName("dev");

        HazelcastInstance client = HazelcastClient.newHazelcastClient(config);
        
        // Получить или создать распределённую карту
        IMap<String, String> map = client.getMap("my-map");
        
        // Операции как с обычной ConcurrentMap
        map.put("key-1", "value-1");
        String value = map.get("key-1");
        System.out.println(value); // value-1
        
        // Но данные доступны с любого клиента кластера!
        
        client.shutdown();
    }
}
```

### Зависимости (Gradle)

```groovy
dependencies {
    implementation 'com.hazelcast:hazelcast:5.6.0'
    // Для Spring Boot — автоконфигурация включена
    implementation 'com.hazelcast:hazelcast-spring:5.6.0'
}
```

## Версии и поддержка

Hazelcast выпускается в двух редакциях:

| Редакция | Что включает |
|----------|-------------|
| **Community Edition** | Открытый исходный код, IMap, Serialization, Predicates, Indexes, Split-Brain Protection, K8s Discovery |
| **Enterprise Edition** | Всё из Community + HD Memory, WAN Replication, Hot Restart, Security, Blue-Green Deployments, Vector Search |

> Для большинства задач Community Edition достаточно. Enterprise нужен для WAN-репликации между дата-центрами, off-heap памяти и hot restart.

Hazelcast Platform 5.6 (октябрь 2025) — текущая стабильная версия. Ключевые изменения:
- Улучшения CP Subsystem (snapshot chunking, производительность)
- Dynamic Diagnostic Logging (бета) — переключение диагностики без рестарта
- Оптимизации High-Density Memory (до 30% прирост throughput)
- Минимальная версия JDK: **17** (начиная с Hazelcast 5.5)

## Практика

1. Запусти Hazelcast-сервер через Docker (команда выше)
2. Проверь его состояние через REST API: `curl http://localhost:5701/hazelcast/health/node-state`
3. Создай Java-проект с зависимостью `com.hazelcast:hazelcast:5.6.0`
4. Напиши программу, которая подключается к кластеру, кладёт 100 записей в IMap и читает их обратно
5. Запусти второй экземпляр Hazelcast (`docker run` с другим именем и `--network host`) и убедись, что данные доступны с обоих узлов
6. Останови первый узел и проверь, что данные сохранились на втором

## Итоги урока

- Hazelcast — In-Memory Data Grid для JVM, хранящий данные в оперативной памяти распределённого кластера
- Данные автоматически партиционируются по 271 партиции и реплицируются между узлами
- Основная структура данных — `IMap<K, V>`, распределённая реализация `ConcurrentMap`
- Hazelcast решает задачи кэширования, распределённых блокировок, pub/sub и real-time аналитики
- По сравнению с Redis, Hazelcast нативнее интегрируется с Java и поддерживает embedded-режим
- Community Edition покрывает большинство задач, Enterprise нужен для WAN-репликации и off-heap памяти
- Актуальная версия — Hazelcast Platform 5.6, минимальная версия JDK — 17