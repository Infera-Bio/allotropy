from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import uuid


class IdGenerator(ABC):
    @abstractmethod
    def generate_id(self) -> str:
        raise NotImplementedError


class _RandomUuidGenerator(IdGenerator):
    def generate_id(self) -> str:
        return str(uuid.uuid4())


class ContentDerivedIdGenerator(IdGenerator):
    """The n-th identifier is a UUID derived from the SHA-256 of the file and n, so one
    file always converts to the same identifiers and two files never share one."""

    def __init__(self, sha256: bytes) -> None:
        self._namespace = uuid.UUID(bytes=sha256[:16])
        self._count = 0

    def generate_id(self) -> str:
        self._count += 1
        return str(uuid.uuid5(self._namespace, str(self._count)))


_ID_GENERATOR = _RandomUuidGenerator()
# The generator of the conversion running in this context, if it asked for one.
_CURRENT_ID_GENERATOR: ContextVar[IdGenerator | None] = ContextVar(
    "allotropy_id_generator", default=None
)


@contextmanager
def content_derived_ids(sha256: bytes) -> Iterator[None]:
    """Mint content-derived identifiers, instead of random ones, inside this block."""
    token = _CURRENT_ID_GENERATOR.set(ContentDerivedIdGenerator(sha256))
    try:
        yield
    finally:
        _CURRENT_ID_GENERATOR.reset(token)


class _IdGeneratorFactory:
    def get_id_generator(self) -> IdGenerator:
        return _CURRENT_ID_GENERATOR.get() or _ID_GENERATOR


__ID_GENERATOR_FACTORY = _IdGeneratorFactory()


def random_uuid_str() -> str:
    return __ID_GENERATOR_FACTORY.get_id_generator().generate_id()
