"""Application errors carry no HTTP or database dependency."""


class JobNotFoundError(LookupError):
    pass


class IdempotencyConflictError(ValueError):
    def __init__(self, fields: tuple[str, ...] = ("Idempotency-Key",)):
        self.fields = fields
        super().__init__("Idempotency key conflicts with an existing request")


class InvalidJobParametersError(ValueError):
    def __init__(self, fields: tuple[str, ...]):
        self.fields = fields
        super().__init__("Invalid job parameters")
