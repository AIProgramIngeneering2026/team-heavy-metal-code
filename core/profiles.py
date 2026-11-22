"""Built-in profile configuration, independent of concrete Tool classes."""

from .registry import Registry


def register_basic_profile(registry: Registry) -> None:
    """Configure basic after both of its tools have been registered."""
    registry.register_profile(
        "basic",
        [
            (
                "required_files",
                {"required_paths": ["README.md", "CONTRIBUTING.md"]},
            ),
            (
                "readme_sections",
                {
                    "readme_path": "README.md",
                    "required_sections": [
                        "Описание проекта",
                        "Запуск",
                        "Тестирование",
                    ],
                },
            ),
        ],
    )
