import re
from core.tool_contract import (
    CheckResult,
    ToolCall,
    ToolError,
    ToolResult,
)


class RequiredFilesTool:
    name = "required_files"

    def execute(self, call: ToolCall) -> ToolResult | ToolError:
        params = call.params

        # Проверяем наличие списка обязательных файлов.
        required_paths = params.get("required_paths")

        if not isinstance(required_paths, list) or not required_paths:
            return ToolError(
                code="invalid_tool_parameters",
                message="required_paths должен быть непустым списком путей.",
                details={"field": "params.required_paths"},
            )

        # Проверяем каждый путь и отсутствие дубликатов.
        seen = set()

        for index, path in enumerate(required_paths):
            if (
                not isinstance(path, str)
                or not path
                or path.startswith("/")
                or re.match(r"^[A-Za-z]:", path)
                or "\\" in path
                or any(
                    part in ("", ".", "..")
                    for part in path.split("/")
                )
                or path in seen
            ):
                return ToolError(
                    code="invalid_tool_parameters",
                    message="Некорректный или повторяющийся путь файла.",
                    details={
                        "field": f"params.required_paths[{index}]"
                    },
                )

            seen.add(path)

        # Проверяем файлы в переданном снимке репозитория.
        available_paths = set(call.snapshot.paths)
        results = []

        for path in required_paths:
            exists = path in available_paths

            results.append(
                CheckResult(
                    check_name=f"file:{path}",
                    status=exists,
                    details=(
                        f"Файл {path} присутствует в репозитории."
                        if exists
                        else f"Обязательный файл {path} отсутствует."
                    ),
                )
            )

        return ToolResult(
            tool=self.name,
            results=results,
        )
