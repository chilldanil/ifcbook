# ifc_book_prototype — Статус и план развития

> Дата: 2026-05-13  
> Тесты: 116 passed, 5 skipped  
> Последний коммит: `c841414` — Legend: убран слот "Doors" когда doors_enabled=false

---

## Что это

Пайплайн: IFC-файл → PDF-книга с архитектурными чертежами.

```
sample.ifc  →  [pipeline]  →  book.pdf
                                ├── A-000  Cover Sheet
                                ├── A-001  Drawing Index
                                ├── A-101  Floor Plan Floor 2
                                ├── A-102  Floor Plan Floor 1
                                ├── A-201..204  Elevations (N/E/S/W)
                                ├── A-601  Opening Type Schedule
                                └── A-602  Element Type Schedule
```

Запуск:
```bash
python -m ifc_book_prototype samples/file.ifc --out out/demo
```

---

## Текущая архитектура

| Модуль | Роль |
|---|---|
| `pipeline.py` | Оркестратор: loader → geometry → render → PDF |
| `ifc_loader.py` | Парсинг IFC, нормализация модели |
| `geometry_backend.py` | Phase 3C: OCCT cut + serializer projection + hidden. Главный kernel |
| `geometry_projection.py` | Merge owned lines (projection + hidden) в итоговый linework |
| `geometry_occt.py` | OCCT BRep section (cut plane) |
| `elevation_backend.py` | Фасадные виды (N/E/S/W) через OCCT edges |
| `feature_anchors.py` | Семантические якоря: лестницы, комнаты, двери |
| `render_svg.py` | SVG-рендер каждого листа |
| `render_pdf.py` | Сборка SVG → PDF через ReportLab |
| `schedules.py` | Спецификации (Opening Type, Element Type) |
| `profiles/` | JSON-профили стиля (линии, масштаб, оверлеи) |

**Активный профиль:** `din_iso_arch_floor_plan_v3_phase3c_owned_projection_hidden.json`

---

## Что работает сейчас

### Планы этажей (Phase 3C)
- **OCCT BRep cut** — точное сечение стен/колонн/перекрытий по cut plane 1.1м
- **Owned projection** — собственная проекция элементов сверху
- **Owned hidden** — скрытые линии (пунктир)
- **Serializer fallback** — если owned ничего не дало, берём линии из IFC-сериализатора
- **Двери** — door arc + frame из сериализатора, фильтрация по GUID/storey (без кросс-утечек)
- **Окна** — projection линии

### Фасады
- OCCT edge projection для 4 направлений (N/E/S/W)
- Storey elevation lines
- Scale bar, dimensions

### Оверлеи
- **Лестницы** — стрелки UP/DOWN с лейблом
- **Комнаты** — лейбл из IFC LongName/Name (если есть IfcSpace)
- **Легенда** — условные обозначения на плане

### Спецификации
- Opening Type Schedule (двери, окна по типам)
- Element Type Schedule (все элементы)

### Инфраструктура
- Детерминированный output (стабильный hash)
- 116 тестов (unit + snapshot + regression)
- Benchmark suite
- Bundle replay (кэш геометрии)

---

## Что не работает / ограничения

| Проблема | Причина | Приоритет |
|---|---|---|
| Нет комнатных лейблов на простых IFC | Файл без IfcSpace — лейблить нечего | — |
| IfcFurnishingElement не рендерится | Не в included_classes, не обрабатывается | Средний |
| IfcCurtainWall не в cut_classes | Витраж как монолитный класс не режется | Средний |
| Floor 2 пустой на simple sample | В IFC стены привязаны только к Floor 1 | — (проблема файла) |
| Нет штриховки стен | Не реализовано | **Высокий** |
| Нет размерных цепочек | Не реализовано | Высокий |
| Нет маркеров разрезов на плане | Не реализовано | Средний |
| Snapshot hash хрупкий | Любое изменение рендера ломает тест | Технический долг |

---

## Следующие фичи — приоритет

### 1. Штриховка стен в разрезе (Wall Hatching)
**Что:** Стены в cut-сечении заполняются паттерном согласно материалу.  
**Зачем:** DIN/ISO стандарт. Без этого план выглядит незавершённым.  
**Реализация:**
- SVG `<pattern>` — diagonal lines для бетона, brick pattern для кладки
- Читаем `IfcMaterial` / `IfcMaterialLayerSetUsage` → маппинг на паттерн
- Closed cut paths (замкнутые контуры) заполняем fill
- Если материал неизвестен — generic crosshatch

**Файлы:** `render_svg.py` (pattern def + fill), `geometry_backend.py` (pass material info)

---

### 2. Мебель на плане (IfcFurnishingElement)
**Что:** Стулья, столы, сантехника — тонкими серыми линиями.  
**Зачем:** Планы с мебелью читаются как готовые архитектурные чертежи.  
**Реализация:**
- Добавить `IfcFurnishingElement` в `included_classes` профиля
- Рендерить как PROJECTED (тонкая линия, без пунктира)
- Отдельный цвет/weight: `furniture` класс

---

### 3. Маркеры разрезов на плане (Section Markers)
**Что:** Стрелки с подписью A-201 / A-202 на floor plan, показывающие откуда берётся фасад.  
**Зачем:** Связывает листы книги в единую систему чертежей.  
**Реализация:**
- Зная направление фасада и bbox модели → вычисляем линию сечения
- Рисуем: линия + стрелки + пузырь с номером листа
- Параметры в профиле: show_section_markers: true

---

### 4. Размерные цепочки (Dimension Chains)
**Что:** Размеры вдоль стен — общий габарит, ширина проёмов, привязки.  
**Зачем:** Архитектурный чертёж без размеров — не чертёж.  
**Реализация:**
- Из cut linework извлекаем горизонтальные/вертикальные wall endpoints
- Группируем в цепочки (cluster по Y-координате)
- SVG: линия с засечками + текст размера в мм

---

### 5. Ведомость помещений (Room Schedule)
**Что:** Таблица: Номер | Имя | Площадь | Этаж  
**Зачем:** Обязательный лист в любом комплекте.  
**Реализация:**
- Читаем IfcSpace + IfcQuantityArea (Qto_SpaceBaseQuantities)
- Лист A-501 (Room Schedule)
- Требует IFC с реальными IfcSpace

---

## Технический долг

- `test_typed_line_snapshots.py` — hash-based snapshot, хрупкий. Заменить на структурную проверку SVG
- `geometry_backend.py` — функция `_classify_group()` разрослась, нужен рефакторинг
- `feature_anchors.py` — `_extract_anchor_xy()` несколько fallback стратегий, задокументировать

---

## Тестовые IFC файлы

| Файл | Что в нём | Подходит для |
|---|---|---|
| `samples/2026_BIMprojects/sample.ifc` | 2 этажа, 3 стены, 9 окон, 1 дверь, 35 мебелей, IFC2X3, **нет IfcSpace** | Базовый smoke test |
| Большой Revit-файл (предыдущие сессии) | 11 этажей, 40 дверей, реальные комнаты | Интеграционный тест |

Для полноценного теста комнатных лейблов нужен IFC с `IfcSpace` + `LongName`.
