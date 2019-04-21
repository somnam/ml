# Import {{{
from lib.common import get_file_path, remove_file
from xvfbwrapper import Xvfb
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import Select, WebDriverWait
# }}}


class BrowserWrapper:  # {{{
    def __init__(self):
        super().__init__()
        self._browser = None

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
        if (self.wait_is_visible(locator, using)):
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
    log_path = get_file_path('var/log/geckodriver.log')

    @property
    def browser(self):
        if not self._browser:
            # Remove old log file.
            remove_file(self.log_path)

            # Create custom Firefox profile.
            profile = webdriver.FirefoxProfile()
            # Disable browser auto-updates.
            for preference in ('app.update.auto', 'app.update.enabled', 'app.update.silent'):
                profile.set_preference(preference, False)

            # Start Firefox webdriver instance.
            self._browser = webdriver.Firefox(
                firefox_profile=profile,
                executable_path=get_file_path('bin/geckodriver'),
                log_path=self.log_path,
            )
        return self._browser
# }}}


class XvfbDisplay:  # {{{
    dimensions = {'width': 1024, 'height': 1024}

    def __init__(self):
        super().__init__()
        self._display = None

    @property
    def display(self):
        if not self._display:
            self._display = Xvfb(**self.dimensions)
        return self._display
# }}}
