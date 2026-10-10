from enum import IntEnum


class IdentityLevel(IntEnum):
    """How sure we are who the caller is (design §4). Issued by auth, never by a model."""

    UNKNOWN = 0
    LIKELY = 1
    VERIFIED = 2
    STRONGLY_VERIFIED = 3

    @classmethod
    def parse(cls, value: "str | int | IdentityLevel") -> "IdentityLevel":
        if isinstance(value, IdentityLevel):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[value.strip().upper()]

    @property
    def label(self) -> str:
        return self.name.lower()
