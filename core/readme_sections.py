
import re

from core.tool_contract import (
    CheckResult,
    ToolCall,
    ToolError,
    ToolResult,
)


def _extract_headings(text: str) -> set[str]:
    """Извлекает заголовки Markdown, исключая блоки кода."""
    headings = set()
    fence_char = None
    fence_size = 0
    previous = None

    for line in text.splitlines():
        # Пропускаем содержимое ограждённых блоков кода.
        if fence_char is not None:
            closing = (
                r" {0,3}"
                + re.escape(fence_char)
                + "{" + str(fence_size) + r",}[ \t]*"
            )
            if re.fullmatch(closing, line):
                fence_char = None
            previous = None
            continue

        opening = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", line)
        if opening:
            marker = opening.group(1)
            if marker[0] != "`" or "`" not in opening.group(2):
                fence_char = marker[0]
                fence_size = len(marker)
                previous = None
                continue

        # Четыре пробела обозначают блок кода.
        if not line.strip() or line.startswith(("    ", "\t")):
            previous = None
            continue

        # Заголовки вида ## Название.
        match = re.match(r" {0,3}#{1,6}(?:[ \t]+|$)(.*)$", line)
        if match:
            title = re.sub(
                r"[ \t]+#+[ \t]*$", "", match.group(1)
            ).strip()
            if title:
                headings.add(title)
            previous = None
            continue

        # Заголовки вида Название с подчёркиванием === или ---.
        if previous and re.fullmatch(
            r" {0,3}(?:=+|-+)[ \t]*", line
        ):
            headings.add(previous)
            previous = None
            continue

        # Списки и цитаты не считаются заголовками.
        if re.match(
            r" {0,3}(?:>|[-+*][ \t]+|\d+[.)][ \t]+)",
            line,
        ):
            previous = None
        else:
            previous = line.strip()

    return headings


class ReadmeSectionsTool:
    name = "readme_sections"

    def execute(self, call: ToolCall) -> ToolResult | ToolError:
        params = call.params
        readme_path = params.get("readme_path")
        required_sections = params.get("required_sections")

        # Проверяем путь README.
        if (
            not isinstance(readme_path, str)
            or not readme_path
            or readme_path != readme_path.strip()
            or readme_path.startswith("/")
            or "\\" in readme_path
            or any(
                part in ("", ".", "..")
                for part in readme_path.split("/")
            )
        ):
            return ToolError(
                code="invalid_tool_parameters",
                message="Некорректный путь README.",
                details={"field": "params.readme_path"},
            )

        # Проверяем список обязательных разделов.
        if (
            not isinstance(required_sections, list)
            or not required_sections
        ):
            return ToolError(
                code="invalid_tool_parameters",
                message="Список разделов должен быть непустым.",
                details={"field": "params.required_sections"},
            )

        sections = []
        seen = set()

        for index, section in enumerate(required_sections):
            if not isinstance(section, str) or not section.strip():
                return ToolError(
                    code="invalid_tool_parameters",
                    message="Некорректное название раздела.",
                    details={
                        "field": f"params.required_sections[{index}]"
                    },
                )

            normalized = section.strip()

            if normalized in seen:
                return ToolError(
                    code="invalid_tool_parameters",
                    message="Повторяющийся раздел.",
                    details={
                        "field": f"params.required_sections[{index}]"
                    },
                )

            seen.add(normalized)
            sections.append(normalized)

        # Проверяем наличие README в снимке.
        file_exists = readme_path in call.snapshot.paths

        if file_exists:
            if readme_path not in call.snapshot.text_files:
                return ToolError(
                    code="snapshot_incomplete",
                    message="Не получено содержимое существующего README.",
                    details={"path": readme_path},
                )

            content = call.snapshot.text_files[readme_path]
            if not isinstance(content, str):
                return ToolError(
                    code="snapshot_incomplete",
                    message="Некорректное содержимое README.",
                    details={"path": readme_path},
                )

            headings = _extract_headings(content)
        else:
            headings = set()

        # Формируем результат для каждого раздела.
        results = []

        for section in sections:
            found = section in headings

            if not file_exists:
                details = (
                    f"Раздел «{section}» не найден: "
                    f"файл {readme_path} отсутствует."
                )
            elif found:
                details = f"Раздел «{section}» найден."
            else:
                details = f"Обязательный раздел «{section}» отсутствует."

            results.append(
                CheckResult(
                    check_name=f"section:{readme_path}:{section}",
                    status=found,
                    details=details,
                )
            )

        return ToolResult(
            tool=self.name,
            results=results,
        )
