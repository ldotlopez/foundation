class CacheMissError(Exception):
    pass


class MissingKeyError(CacheMissError):
    def __init__(self, key: str) -> None:
        super().__init__(f"Key not found: {key!r}")
        self.key = key


class ExpiredKeyError(CacheMissError):
    def __init__(self, key: str) -> None:
        super().__init__(f"Key expired: {key!r}")
        self.key = key
