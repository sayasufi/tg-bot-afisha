from collections.abc import Callable

from connectors.base import BaseSourceConnector


class ConnectorRegistry:
    def __init__(self):
        self._factories: dict[str, Callable[[], BaseSourceConnector]] = {}

    def register(self, name: str, factory: Callable[[], BaseSourceConnector]) -> None:
        self._factories[name] = factory

    def get(self, name: str) -> BaseSourceConnector:
        if name not in self._factories:
            raise KeyError(f"connector {name} is not registered")
        return self._factories[name]()


registry = ConnectorRegistry()
