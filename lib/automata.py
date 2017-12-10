#!/usr/bin/python2 -tt
# -*- coding: utf-8 -*-
# Import {{{
import os
import time
import shutil
from lib.common import get_file_path
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import (
    Select,
    WebDriverWait,
)
from selenium.webdriver.firefox.firefox_binary import FirefoxBinary
# }}}

def browser_start():
    print(u'Starting browser.')

    # Disable browser auto-updates.
    profile = webdriver.FirefoxProfile()
    profile.set_preference('app.update.auto', False)
    profile.set_preference('app.update.enabled', False)
    profile.set_preference('app.update.silent', False)

    # Load webdriver.
    binary  = FirefoxBinary(get_file_path('./firefox/firefox'))
    browser = webdriver.Firefox(
        firefox_profile=profile,
        firefox_binary=binary,
    )
    return browser

def browser_stop(browser):
    print('Stopping browser.')
    browser.quit()
    return

def select_by_id_and_value(browser, select_id, select_value):
    select = Select(browser.find_element_by_id(select_id))
    select.select_by_value(select_value)
    return select

def wait_is_visible(browser, locator, using=By.ID, timeout=5):
    try:
        WebDriverWait(browser, timeout).until(
            expected_conditions.visibility_of_element_located(
                (using, locator)
            )
        )
        return True
    except (TimeoutException, NoSuchElementException):
        return False

def wait_is_not_visible(browser, locator, using=By.ID, timeout=5):
    try:
        WebDriverWait(browser, timeout).until_not(
            expected_conditions.visibility_of_element_located(
                (using, locator)
            )
        )
        return True
    except TimeoutException:
        return False
