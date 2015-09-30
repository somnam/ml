#!/usr/bin/python2 -tt
# -*- coding: utf-8 -*-
# Import {{{
import os
import time
import shutil
from selenium import webdriver
from selenium.webdriver.support.ui import Select
# }}}

def browser_start():
    print(u'Starting browser.')

    # Load webdriver.
    browser = webdriver.Firefox()
    # Some of sites elements are loaded via ajax - wait for them.
    browser.implicitly_wait(2)
    return browser

def browser_stop(browser):
    print('Stopping browser.')
    browser.quit()
    return

def browser_timeout(browser):
    print('Restarting browser.')

    # Kill current browser instance.
    taskkill = None
    if browser.binary and browser.binary.process:
        print(u'Killing firefox process "%s".' % browser.binary.process.pid)
        taskkill = 'kill -9 %s' % browser.binary.process.pid
    else:
        print(u'Killing firefox process.')
        taskkill = 'pkill -9 firefox'
    os.system(taskkill)

    # Remove temp folder.
    if browser.profile and browser.profile.tempfolder:
        print(u'Removing temporary profile.')
        time.sleep(0.1)
        shutil.rmtree(browser.profile.tempfolder)

    # Remove object.
    browser = None
    return

def browser_select_by_id_and_value(browser, select_id, select_value):
    select = Select(browser.find_element_by_id(select_id))
    select.select_by_value(select_value)
    return select

def browser_click(browser, elem):
    webdriver.ActionChains(browser).move_to_element(elem) \
                                   .click(elem) \
                                   .perform()
    return


