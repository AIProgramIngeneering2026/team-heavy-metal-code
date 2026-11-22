class InvalidStateTransition(ValueError):
    """Переход Job запрещён диаграммой состояний."""

    http_status = 409


class OperationNotSupported(ValueError):
    """Операция не поддерживается в первой версии."""

    code = "OPERATION_NOT_SUPPORTED"

