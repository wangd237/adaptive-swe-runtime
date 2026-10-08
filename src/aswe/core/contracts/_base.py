from typing import Any, Self

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Immutable contract data; even copy(update=...) must preserve validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False) -> Self:
        """Pydantic normally skips validation in copy(update=...); never do so here."""
        if not update:
            return super().model_copy(deep=deep)
        data = self.model_dump(mode="python")
        data.update(update)
        return type(self).model_validate(data)
