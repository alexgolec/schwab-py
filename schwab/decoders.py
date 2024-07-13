from abc import ABC, abstractmethod


class StreamJsonDecoder(ABC):
    @abstractmethod
    def decode_json_string(self, raw):
        raise NotImplementedError()
