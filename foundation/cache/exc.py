class CacheMissError(Exception):
    pass


class MissingKeyError(CacheMissError):
    def __init__(self, key: str) -> None:
        self.key = key


class ExpiredKeyError(CacheMissError):
    def __init__(self, key: str) -> None:
        self.key = key
