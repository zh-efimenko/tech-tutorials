# Программа обучения: Gradle Version Catalogs (TOML)

## Цель

Освоить механизм Version Catalogs — централизованное управление зависимостями и плагинами через TOML-файл: от создания каталога до шаринга между микросервисами.

## Требования

- Java 17+, Gradle 9.x; примеры прогонялись на Gradle 9.5.0 и Java 25; version catalogs стабильны с Gradle 7.4.1
- Примеры используют Spring Boot 4.1.0 — Jackson там уже 3.x (группа `tools.jackson`)
- Базовые знания Gradle (build.gradle, dependencies, plugins)
- Терминал (bash/zsh)

---

## Уроки

| #  | Тема | Папка | Описание |
|----|------|-------|----------|
| 1  | Зачем нужны Version Catalogs | `01_why_version_catalogs/` | Проблемы управления версиями, старые подходы, что даёт TOML |
| 2  | Структура libs.versions.toml | `02_toml_structure/` | Формат TOML, четыре секции, расположение файла, подключение |
| 3  | [versions] и [libraries] | `03_versions_libraries/` | Объявление версий, version.ref, форматы записи библиотек |
| 4  | [plugins] и [bundles] | `04_plugins_bundles/` | alias(), группировка зависимостей, ограничения |
| 5  | Type-safe accessors | `05_type_safe_accessors/` | Правила именования, Groovy/Kotlin DSL, отладка |
| 6  | Шаринг каталога между проектами | `06_sharing_catalog/` | Composite builds, git submodules, published catalogs |
| 7  | Rich versions и платформы (BOM) | `07_rich_versions_bom/` | strictly, prefer, require, reject, platform(), enforcedPlatform |
| 8  | Миграция и best practices | `08_migration_best_practices/` | Пошаговая миграция, anti-patterns, Renovate/Dependabot |

---

## Рекомендуемый порядок

Уроки выстроены последовательно. Уроки 1-2 — введение, 3-5 — ядро Version Catalogs, 6-8 — продвинутые сценарии и практика.
