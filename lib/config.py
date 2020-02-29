import json
import logging
from configparser import ConfigParser, ExtendedInterpolation
from lib.utils import get_file_path, Singleton


class Config(Singleton, ConfigParser):
    logger = logging.getLogger(__name__)

    def __init__(self):
        super().__init__(
            converters={'struct': self.struct_converter},
            interpolation=ExtendedInterpolation(),
        )

        # Don't lowercase keys.
        self.optionxform = str
        # Read config file
        self.read(get_file_path('etc', 'config.ini'))

    @staticmethod
    def struct_converter(value):
        try:
            decoded_value = json.loads(value)
        except json.JSONDecodeError as e:
            Config.logger.error(f'Could not decode value "{value}": {e}')
            decoded_value = None
        return decoded_value
