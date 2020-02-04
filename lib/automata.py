# Import {{{
import logging
import urllib3
from os import path
from lib.config import Config
from lib.utils import get_file_path
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import Select, WebDriverWait
# }}}


class BrowserUnavailable(Exception):
    pass


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
        except urllib3.exceptions.MaxRetryError as e:
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

    def wait_is_visible_by_id(self, locator):
        return self.wait_is_visible(locator, using=By.ID)

    def wait_is_visible_by_css_selector(self, locator):
        return self.wait_is_visible(locator, using=By.CSS_SELECTOR)

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

    def wait_is_not_visible_by_id(self, locator):
        return self.wait_is_not_visible(locator, using=By.ID)

    def wait_is_not_visible_by_css_selector(self, locator):
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

    def set_input_value_by_id(self, locator, value):
        return self.set_input_value(locator, value, using=By.ID)

    def set_input_value_by_css_selector(self, locator, value):
        return self.set_input_value(locator, value, using=By.CSS_SELECTOR)

    def set_input_value(self, locator, value, using):
        if self.wait_is_visible(locator, using):
            field = self._browser.find_element(by=using, value=locator)
            field.send_keys(value)

    def set_select_option_by_id(self, select_id, option):
        select = None
        if self.wait_is_visible_by_id(select_id):
            option_css_selector = f'select[id="{select_id}"] > option[value="{option}"]'
            if self.wait_is_visible_by_css_selector(option_css_selector):
                select = Select(self._browser.find_element_by_id(select_id))
                select.select_by_value(option)
        return select


class FirefoxBrowser(Browser):
    def driver(self):
        return webdriver.Firefox

    def driver_options(self):
        # Customize Firefox instance.
        options = webdriver.FirefoxOptions()
        # Run in headless mode.
        options.headless = (self.config['selenium'].getboolean('headless')
                            if ('selenium' in self.config
                                and 'headless' in self.config['selenium'])
                            else True)
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
