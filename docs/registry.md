# Registry и подключение Tool

Registry хранит экземпляры Tool и конфигурацию профилей. Dispatcher получает из него пары `(tool, params)` и вызывает инструменты через общий контракт. Registry не выполняет проверки, не меняет Job и не обращается к сети.

## Интерфейс

```python
from core.registry import Registry

registry = Registry()
registry.register(tool)  # tool.name: str, tool.execute(call)
registry.register_profile("example", [(tool.name, {"option": "value"})])
selected_tool = registry.get(tool.name)
configured_tools = registry.get_tools_for_profile("example")
```

- `Registry()` создаёт отдельный пустой реестр.
- `register(tool)` сохраняет экземпляр по его `name`. Имя должно быть непустой строкой, а `execute` — вызываемым методом.
- `get(name)` возвращает тот же экземпляр. Имена сравниваются точно, с учётом регистра.
- `register_profile(name, entries)` задаёт непустую упорядоченную последовательность кортежей `(имя Tool, параметры)`. Параметры — словарь или другое отображение со строковыми ключами. Все Tool должны быть зарегистрированы заранее.
- `get_tools_for_profile(profile_name)` возвращает `list[tuple[Tool, dict[str, object]]]` в порядке профиля. Экземпляры Tool сохраняются, а список и словари параметров копируются, включая вложенные списки и словари.
- Повторное имя профиля и повтор одного Tool внутри профиля отклоняются. При ошибке проверки или копирования ни одна часть профиля не сохраняется.
- Неизвестное имя вызывает `UnknownOperationError`: `code = "unknown_operation"`, `operation = name`, `details = {"operation": name}`. Неизвестная операция не превращается в результат проверки репозитория.
- Повторная регистрация имени вызывает `DuplicateToolError` с `code = "duplicate_tool"`; исходный экземпляр сохраняется. Это ошибка настройки приложения.

Неизвестный профиль также вызывает `UnknownOperationError` с `code = "unknown_operation"`; в `operation` и `details.operation` находится имя профиля. `get(name)` ищет только Tool, а `get_tools_for_profile(name)` — только профиль.

Общий тип `Tool` определён участником блока 4 в `core/tool_contract.py` (PR №27). Registry использует его только для аннотаций: собственные тесты с подставными Tool запускаются до объединения остальных блоков. Registry проверяет наличие имени и вызываемого `execute`; содержание параметров проверяет сам Tool, как указано в [контракте Tool](tool-contract.md).

## Граница с Dispatcher и профилями

Регистрация выполняется при сборке приложения. Dispatcher получает уже заполненный Registry и запрашивает пары Tool и параметров по имени профиля. Для новой проверки достаточно зарегистрировать её экземпляр и добавить конфигурацию; менять Dispatcher не требуется.

Профиль `basic` задан в `core/profiles.py`:

```python
registry.register_profile(
    "basic",
    [
        ("required_files", {"required_paths": ["README.md", "CONTRIBUTING.md"]}),
        (
            "readme_sections",
            {
                "readme_path": "README.md",
                "required_sections": ["Описание проекта", "Запуск", "Тестирование"],
            },
        ),
    ],
)
```

Функция `register_basic_profile(registry)` выполняет эту настройку после регистрации `RequiredFilesTool` и `ReadmeSectionsTool`. Имена файлов и заголовков находятся в конфигурации, а не в Dispatcher. Алгоритм вызова использует один подготовленный `RepositorySnapshot`:

```python
from core.tool_contract import ToolCall

for tool, params in registry.get_tools_for_profile(profile_name):
    result = tool.execute(ToolCall(snapshot=snapshot, params=params))
    # Обработка результата и состояния Job относится к Dispatcher.
```

`execute(snapshot, **params)` этим интерфейсом не вводится: общий контракт остаётся `execute(call) -> ToolResult | ToolError`. После каждого вызова Dispatcher обрабатывает `ToolResult`, `ToolError` или непредвиденное исключение согласно своему контракту.

Изменение конфигурации, переданной в `register_profile`, или параметров, полученных из `get_tools_for_profile`, не влияет на следующие запросы профиля. Один и тот же Tool может входить в разные профили с разными параметрами. Реестр не регистрирует инструменты и не запускает проверки автоматически при импорте модулей.

## Проверка

```shell
python -m pytest -q
```

`tests/test_registry.py` проверяет регистрацию и поиск, неизвестные Tool и профили, порядок исполнителей, ошибки конфигурации, изоляцию реестров и защиту вложенных параметров от изменений. `tests/test_profiles.py` проверяет состав `basic` и соответствие названий параметров контракту p2.
