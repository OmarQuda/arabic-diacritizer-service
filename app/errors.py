class ServiceError(Exception):
    def __init__(self, status: int, error: str, **fields):
        self.status = status
        self.body = {"error": error, **fields}
        super().__init__(error)
