# Import {{{
import urllib3
from lib.config import Config
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import Select, WebDriverWait
# }}}


class BrowserUnavailable(Exception):
    pass


class BrowserWrapper:  # {{{
    @property
    def browser(self):
        raise NotImplementedError()

    def find_by_css(self, selector):
        return self.browser.find_element_by_css_selector(selector)

    def find_all_by_css(self, selector):
        return self.browser.find_elements_by_css_selector(selector)

    def wait_is_visible_by_css(self, locator):
        return self.wait_is_visible(locator, By.CSS_SELECTOR)

    def wait_is_visible(self, locator, using=By.ID, timeout=5):
        try:
            WebDriverWait(self.browser, timeout).until(
                expected_conditions.visibility_of_element_located(
                    (using, locator)
                )
            )
            return True
        except (TimeoutException, NoSuchElementException):
            return False

    def wait_is_not_visible(self, locator, using=By.ID, timeout=5):
        try:
            WebDriverWait(self.browser, timeout).until_not(
                expected_conditions.visibility_of_element_located(
                    (using, locator)
                )
            )
            return True
        except TimeoutException:
            return False

    def set_input_value(self, locator, value, using=By.ID):
        if self.wait_is_visible(locator, using):
            field = self.browser.find_element(by=using, value=locator)
            field.send_keys(value)

    def select_by_id_and_value(self, select_id, select_value):
        select = None
        if (self.wait_is_visible(select_id)):
            select = Select(self.browser.find_element_by_id(select_id))
            option_xpath = '//select[@id="{0}"]/option[@value="{1}"]'.format(
                select_id, select_value
            )
            if (self.wait_is_visible(option_xpath, By.XPATH)):
                select.select_by_value(select_value)
        return select
# }}}


class FirefoxBrowserWrapper(BrowserWrapper):  # {{{
    @property
    def options(self):
        if not hasattr(self, '_options'):
            # Customize Firefox instance.
            options = webdriver.FirefoxOptions()
            # Run in headless mode.
            options.headless = True
            # Create custom profile.
            options.profile = webdriver.FirefoxProfile()
            # Disable browser auto-updates.
            for preference in ('app.update.auto', 'app.update.enabled', 'app.update.silent'):
                options.profile.set_preference(preference, False)
            self._options = options
        return self._options

    @property
    def browser(self):
        if not hasattr(self, '_browser'):
            # Start remote Firefox webdriver instance.
            config = Config()
            hub_url = (config['selenium']['hub_url']
                       if ('selenium' in config and 'hub_url' in config['selenium'])
                       else 'http://localhost:4444/wd/hub')
            try:
                self._browser = webdriver.Remote(
                    command_executor=hub_url,
                    options=self.options,
                )
            except urllib3.exceptions.MaxRetryError as e:
                raise BrowserUnavailable(e)
        return self._browser
# }}}
