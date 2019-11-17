import json
import logging
from configparser import ConfigParser
from lib.common import get_file_path


class Config:
    logger = logging.getLogger(__name__)

    def __init__(self):
        self.config = ConfigParser(
            converters={'struct': self.struct_converter},
        )
        # Don't lowercase keys.
        self.config.optionxform = str
        # Read config file
        self.config.read(get_file_path('etc', 'config.ini'))

    @staticmethod
    def struct_converter(value):
        try:
            decoded_value = json.loads(value)
        except json.JSONDecodeError as e:
            Config.logger.error(f'Could not decode value "{value}": {e}')
            decoded_value = None
        return decoded_value

    def __getitem__(self, section):
        return self.config[section] if section in self.config else None
