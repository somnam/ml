# Import {{{
import logging
import os
from os import path

import urllib3
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait
from urllib3.exceptions import MaxRetryError

from lib.config import Config
from lib.exceptions import BrowserUnavailable
from lib.utils import get_file_path

# }}}


class Browser:
    logger = logging.getLogger(__name__)

    def __init__(self):
        self.config = Config()
        self._browser = self._make_browser()

    def _make_browser(self):
        try:
            # Use remote driver if selenium grid is running.
            driver = self.remote_driver()
            options = self.remote_driver_options()
            urllib3.PoolManager().request('HEAD', options['command_executor'])
        except urllib3.exceptions.MaxRetryError as e:
            # Fallback to local driver instance when grid is not running.
            self.logger.warning(f'Unable to connect to hub: {e}.'
                                ' Using local driver instance.')
            driver = self.driver()
            options = self.driver_options()

        try:
            browser = driver(**options)
        except (MaxRetryError, TimeoutException) as e:
            raise BrowserUnavailable(e)

        return browser

    def remote_driver(self):
        return webdriver.Remote

    def remote_driver_options(self):
        # Get selenium grid url.
        hub_url = (self.config['selenium']['hub_url']
                   if ('selenium' in self.config and 'hub_url' in self.config['selenium'])
                   else 'http://localhost:4444/wd/hub')

        # Get driver options.
        options = self.driver_options()['options']

        return {
            'command_executor': hub_url,
            'options': options,
        }

    def driver(self):
        raise NotImplementedError

    def driver_options(self):
        raise NotImplementedError

    def __getattr__(self, attr):
        """Proxy calls to internal browser object."""
        return getattr(self._browser, attr)

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self._browser.quit()

    def wait_is_visible_by_id(self, locator, **kwargs):
        return self.wait_is_visible(locator, using=By.ID, **kwargs)

    def wait_is_visible_by_css(self, locator, **kwargs):
        return self.wait_is_visible(locator, using=By.CSS_SELECTOR, **kwargs)

    def wait_is_visible_by_xpath(self, locator, **kwargs):
        return self.wait_is_visible(locator, using=By.XPATH, **kwargs)

    def wait_is_visible(self, locator, using, timeout=5):
        try:
            WebDriverWait(self._browser, timeout).until(
                expected_conditions.visibility_of_element_located(
                    (using, locator)
                )
            )
            return True
        except (TimeoutException, NoSuchElementException):
            return False

    def wait_is_clickable_by_css(self, locator, **kwargs):
        return self.wait_is_clickable(locator, using=By.CSS_SELECTOR, **kwargs)

    def wait_is_clickable_by_xpath(self, locator, **kwargs):
        return self.wait_is_clickable(locator, using=By.XPATH, **kwargs)

    def wait_is_clickable(self, locator, using, timeout=3):
        try:
            element = self._browser.find_element(by=using, value=locator)

            self.wait_for_stillness_of(element, timeout)

            WebDriverWait(self._browser, timeout).until(
                expected_conditions.element_to_be_clickable(
                    (using, locator)
                )
            )
            return True
        except (TimeoutException, NoSuchElementException):
            return False

    def wait_is_not_visible_by_id(self, locator, **kwargs):
        return self.wait_is_not_visible(locator, using=By.ID)

    def wait_is_not_visible_by_css(self, locator, **kwargs):
        return self.wait_is_not_visible(locator, using=By.CSS_SELECTOR)

    def wait_is_not_visible(self, locator, using, timeout=5):
        try:
            WebDriverWait(self._browser, timeout).until_not(
                expected_conditions.visibility_of_element_located(
                    (using, locator)
                )
            )
            return True
        except TimeoutException:
            return False

    def wait_for_stillness_of(self, element, timeout=5):
        try:
            WebDriverWait(self._browser, timeout).until(
                expected_conditions.staleness_of(element)
            )
        except TimeoutException:
            pass

    def set_input_value_by_id(self, locator, value):
        return self.set_input_value(locator, value, using=By.ID)

    def set_input_value_by_css(self, locator, value):
        return self.set_input_value(locator, value, using=By.CSS_SELECTOR)

    def set_input_value(self, locator, value, using):
        if self.wait_is_visible(locator, using):
            field = self._browser.find_element(by=using, value=locator)
            field.send_keys(value)


class FirefoxBrowser(Browser):
    def driver(self):
        return webdriver.Firefox

    def driver_options(self):
        # Customize Firefox instance.
        options = webdriver.FirefoxOptions()
        # Run in headless mode.
        options.headless = self.config.getboolean('selenium', 'headless',
                                                  fallback=True)

        # Set headless mode width / height.
        if options.headless:
            os.environ['MOZ_HEADLESS_WIDTH'] = '1920'
            os.environ['MOZ_HEADLESS_HEIGHT'] = '1080'

        # Set Firefox binary location
        binary_location = path.join(path.expanduser('~'),
                                    '.local', 'firefox', 'firefox')
        if path.exists(binary_location):
            options.binary_location = binary_location

        # Create custom profile.
        options.profile = webdriver.FirefoxProfile()
        # Disable browser auto-updates.
        for preference in ('app.update.auto', 'app.update.enabled', 'app.update.silent'):
            options.profile.set_preference(preference, False)

        return {
            'executable_path': path.join(path.expanduser('~'),
                                         '.local', 'bin', 'geckodriver'),
            'service_log_path': get_file_path('var/log/geckodriver.log'),
            'options': options,
        }
