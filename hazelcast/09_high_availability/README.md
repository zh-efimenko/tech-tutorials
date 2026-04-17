# Урок 9. Высокая доступность

## Зачем нужна высокая доступность

Hazelcast хранит данные в оперативной памяти. Если узел упал и данные не реплицированы — они потеряны навсегда. Высокая доступность (HA) обеспечивает сохранность данных и работоспособность кластера при частичных сбоях.

Три столпа HA в Hazelcast:
- **Бэкапы** — реплики данных на других узлах
- **Split-brain protection** — защита от расщепления кластера
- **Partition groups** — размещение реплик на разных физических хостах

## Бэкапы: sync vs async

Механика бэкапов подробно рассмотрена в уроке 4. Здесь — фокус на production-решениях.

### Дифференцированный подход

Разные карты требуют разного уровня защиты:

```yaml
map:
  # Критичные данные: потеря недопустима
  orders:
    backup-count: 2
    async-backup-count: 0

  # Важные, но восстановимые данные
  product-catalog:
    backup-count: 1
    async-backup-count: 1

  # Ephemeral данные: быстро восстанавливаются
  heartbeats:
    backup-count: 0
    async-backup-count: 2

  # Временные данные с TTL
  deferred-messages:
    backup-count: 2
    async-backup-count: 0
```

**Логика выбора:**

```
Потеря данных = потеря бизнес-операции?
     │
     ├── Да ──────► backup-count: 2, async: 0
     │               (строгая консистентность)
     │
     ├── Терпимо ──► backup-count: 1, async: 1
     │               (баланс скорости и надёжности)
     │
     └── Нет ──────► backup-count: 0, async: 2
                      (максимальная скорость записи)
```

## Split-Brain Protection (Кворум)

### Что такое split-brain

При сетевом разделении (network partition) кластер из 3 узлов может "разделиться" на две части: [2 узла] и [1 узел]. Без защиты **обе** стороны считают себя валидными и принимают записи. При воссоединении — конфликт данных.

```
Нормальная работа:          Split-brain:
┌─────┐ ┌─────┐ ┌─────┐   ┌─────┐ ┌─────┐   ┌─────┐
│  1  │─│  2  │─│  3  │   │  1  │─│  2  │   │  3  │
└─────┘ └─────┘ └─────┘   └─────┘ └─────┘   └─────┘
                            Продолжают        Тоже
                            работать          работает!
```

### Настройка кворума

```yaml
hazelcast:
  split-brain-protection:
    quorum:
      enabled: true
      minimum-cluster-size: 2

  map:
    orders:
      split-brain-protection-ref: quorum
    product-catalog:
      split-brain-protection-ref: quorum
```

С кворумом `minimum-cluster-size: 2`:
- Сторона с 2 узлами продолжает работать
- Одиночный узел **отказывает** в операциях — `SplitBrainProtectionException`

### Типы кворума

```yaml
split-brain-protection:
  quorum-read-write:
    enabled: true
    minimum-cluster-size: 2
    protect-on: READ_WRITE    # Блокировать и чтение, и запись

  quorum-write-only:
    enabled: true
    minimum-cluster-size: 2
    protect-on: WRITE         # Блокировать только запись, чтение разрешено
```

| Тип | Что блокирует | Когда использовать |
|-----|--------------|-------------------|
| `READ_WRITE` | Чтение и запись | Критичные данные — лучше отказать, чем дать устаревшие |
| `WRITE` | Только запись | Данные можно читать устаревшие, но нельзя записывать конфликтующие |

### Формула для minimum-cluster-size

Для предотвращения "двух мажоритарных сторон":

```
minimum-cluster-size = (общее количество узлов / 2) + 1
```

| Узлов в кластере | minimum-cluster-size |
|-------------------|---------------------|
| 3 | 2 |
| 5 | 3 |
| 7 | 4 |

> Для кластера из **чётного** числа узлов (2, 4, 6) кворум не гарантирует единственного "мажорити". Используй нечётное число узлов.

## Merge Policy

Когда кластер воссоединяется после split-brain, конфликтующие записи (одинаковый ключ, разные значения на разных сторонах) нужно как-то разрешить. Это делает **merge policy**.

```yaml
map:
  orders:
    merge-policy:
      class-name: LatestUpdateMergePolicy
      per-entry-stats-enabled: true
```

### Доступные политики

| Политика | Описание | Когда использовать |
|----------|----------|-------------------|
| `LatestUpdateMergePolicy` | Побеждает последнее обновление (по timestamp) | Универсальный выбор |
| `HigherHitsMergePolicy` | Побеждает чаще читаемая запись | Кэши, hot data |
| `PutIfAbsentMergePolicy` | Сохраняется существующая, мержится только новая | Append-only данные |
| `PassThroughMergePolicy` | Мержащая сторона всегда побеждает | Когда одна сторона "главнее" |
| `DiscardMergePolicy` | Мержащая сторона отбрасывается | Когда нужно сохранить текущее |

> `per-entry-stats-enabled: true` обязателен для `LatestUpdateMergePolicy` и `HigherHitsMergePolicy` — без него нет данных о timestamps и hit counts.

### Кастомная merge policy

```java
public class CustomMergePolicy implements SplitBrainMergePolicy<Object, SplitBrainMergeTypes.MapMergeTypes<Object, Object>, Object> {

    @Override
    public Object merge(SplitBrainMergeTypes.MapMergeTypes<Object, Object> mergingEntry,
                         SplitBrainMergeTypes.MapMergeTypes<Object, Object> existingEntry) {
        if (existingEntry == null) {
            return mergingEntry.getValue();
        }
        // Кастомная логика: например, сравнить версии
        long mergingVersion = ((VersionedValue) mergingEntry.getValue()).getVersion();
        long existingVersion = ((VersionedValue) existingEntry.getValue()).getVersion();
        return mergingVersion > existingVersion
            ? mergingEntry.getValue()
            : existingEntry.getValue();
    }
}
```

## Partition Groups

По умолчанию Hazelcast размещает primary и backup партиции случайно. Если два Pod-а работают на одной физической ноде Kubernetes и оба хранят primary + backup одной партиции — падение ноды = потеря данных.

**Partition groups** гарантируют, что primary и backup одной партиции находятся на **разных** группах.

```yaml
partition-group:
  enabled: true
  group-type: HOST_AWARE
```

### Типы partition groups

| Тип | Описание |
|-----|----------|
| `HOST_AWARE` | Primary и backup на разных физических хостах (IP-адресах) |
| `ZONE_AWARE` | На разных availability zones (облачные провайдеры) |
| `RACK_AWARE` | На разных стойках (физические дата-центры) |
| `CUSTOM` | Ручное распределение |

### HOST_AWARE в Kubernetes

```
Node K8s-1:                  Node K8s-2:
┌──────────┐ ┌──────────┐   ┌──────────┐ ┌──────────┐
│ HZ Pod 1 │ │ HZ Pod 2 │   │ HZ Pod 3 │ │ HZ Pod 4 │
│ Part.0   │ │ Part.1   │   │ Part.0   │ │ Part.1   │
│ (owner)  │ │ (owner)  │   │ (backup) │ │ (backup) │
└──────────┘ └──────────┘   └──────────┘ └──────────┘
```

> Primary партиции на Node K8s-1, backup-ы на Node K8s-2 (и наоборот). Падение одной ноды не приводит к потере данных.

## Kubernetes Discovery

В Kubernetes Hazelcast обнаруживает членов кластера через DNS-записи Headless Service.

### Серверная конфигурация

```yaml
hazelcast:
  network:
    join:
      multicast:
        enabled: false
      kubernetes:
        enabled: true
        service-dns: hazelcast.default.svc.cluster.local
```

### Kubernetes-манифесты

```yaml
# Headless Service для discovery
apiVersion: v1
kind: Service
metadata:
  name: hazelcast
spec:
  clusterIP: None   # Headless!
  selector:
    app: hazelcast
  ports:
    - port: 5701

---
# StatefulSet для серверов
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: hazelcast
spec:
  serviceName: hazelcast
  replicas: 3
  selector:
    matchLabels:
      app: hazelcast
  template:
    metadata:
      labels:
        app: hazelcast
    spec:
      containers:
        - name: hazelcast
          image: hazelcast/hazelcast:5.6.0
          ports:
            - containerPort: 5701
          env:
            - name: HZ_CLUSTERNAME
              value: my-cluster
```

> **Почему StatefulSet:** Стабильные DNS-имена (`hazelcast-0`, `hazelcast-1`) и упорядоченный rolling update. Deployment не гарантирует порядок рестарта.

## Graceful Shutdown

При остановке узла (rolling update, scale down) данные должны быть мигрированы, а не потеряны.

```yaml
hazelcast:
  properties:
    hazelcast.shutdownhook.policy: GRACEFUL
    hazelcast.graceful.shutdown.max.wait: 120  # Секунд
```

Процесс graceful shutdown:
1. Узел перестаёт принимать новые операции
2. Партиции мигрируют на оставшиеся узлы
3. После завершения миграции узел останавливается

> В Kubernetes настрой `terminationGracePeriodSeconds` >= `graceful.shutdown.max.wait`:
```yaml
spec:
  terminationGracePeriodSeconds: 150  # Больше, чем 120
```

## Практика

1. Создай кластер из 3 узлов с `backup-count: 1`, положи данные, убей один узел — убедись, что данные доступны
2. Настрой split-brain protection с `minimum-cluster-size: 2` — изолируй один узел (симуляция network partition) и проверь, что он отказывает в операциях
3. Настрой `LatestUpdateMergePolicy` — запиши разные значения для одного ключа на двух сторонах split-brain, воссоедини кластер, проверь какое значение осталось
4. Настрой `HOST_AWARE` partition group — запусти 4 узла на 2 хостах и проверь, что primary и backup на разных хостах
5. Проверь graceful shutdown: останови узел с `GRACEFUL` policy, убедись что данные мигрировали (в логах будет `Migration completed`)
6. Настрой Kubernetes discovery и запусти 3 Pod-а в StatefulSet

## Итоги урока

- Высокая доступность строится на бэкапах, split-brain protection и partition groups
- Дифференцируй backup-стратегии: критичные данные — sync, ephemeral — async
- Split-brain protection (кворум) предотвращает запись на "меньшую" сторону при расщеплении кластера
- Для нечётного числа узлов `minimum-cluster-size = (N/2) + 1`
- Merge policy определяет, как разрешать конфликты при воссоединении — `LatestUpdateMergePolicy` универсальный выбор
- `HOST_AWARE` partition groups гарантируют, что primary и backup на разных физических хостах
- Kubernetes discovery через Headless Service + StatefulSet — рекомендуемый подход для K8s
- Graceful shutdown мигрирует партиции перед остановкой узла — настрой `terminationGracePeriodSeconds` соответственно