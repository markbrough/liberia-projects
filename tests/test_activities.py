from flask import url_for
import pytest
import warnings
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import time
from conftest import LiveServerClass
import json

@pytest.mark.usefixtures('client_class')
class TestActivities:
    def test_nonauth_routes_work(self):
        routes = [
            (url_for('activities.dashboard'), 302),
            (url_for('activities.activities'), 302),
            (url_for('activities.activity_new'), 302),
        ]
        for route, status_code in routes:
            res = self.client.get(route)
            assert res.status_code == status_code


    def test_auth_routes_work_user(self, user):
        routes = [
            (url_for('activities.dashboard'), 200),
            (url_for('activities.activities'), 200),
            (url_for('activities.activity_new'), 302),
        ]
        for route, status_code in routes:
            res = self.client.get(route)
            assert res.status_code == status_code


    def test_auth_routes_work_admin(self, admin):
        routes = [
            (url_for('activities.dashboard'), 200),
            (url_for('activities.activities'), 200),
            (url_for('activities.activity_new'), 200),
        ]
        for route, status_code in routes:
            res = self.client.get(route)
            assert res.status_code == status_code


    def test_activities_api_works(self, admin, app):
        res = self.client.get(url_for('api.api_activities_country'))
        assert res.status_code == 200
        assert len(json.loads(res.data)["activities"]) == 10


    def test_filters_api_works(self, admin, app):
        res = self.client.get(url_for('api.api_activities_filters'))
        assert res.status_code == 200
        assert len(json.loads(res.data)["filters"]) == 9


@pytest.mark.usefixtures('client_class')
class TestActivitiesLoad(LiveServerClass):
    def test_activities_load_user(self, app, selenium, selenium_login_user):
        selenium.get(url_for('activities.activities', _external=True))
        try:
            WebDriverWait(selenium, 10).until(
                EC.presence_of_element_located((By.ID, 'activities_count'))
            )
        except TimeoutException as ex:
            # print messages
            print("----LOGS----")
            for entry in selenium.get_log('browser'):
                print(entry)
            print("----LOGS----")
            raise TimeoutException
        assert selenium.find_element(By.ID, "activities_count").text == "10 found"
        assert len(selenium.find_elements(By.CSS_SELECTOR, "table tbody tr")) == 10
        assert len(selenium.find_elements(By.CSS_SELECTOR, "table tbody tr td a span.fas.fa-edit")) == 0

    def test_activities_load(self, app, selenium, selenium_login):
        selenium.get(url_for('activities.activities', _external=True))
        WebDriverWait(selenium, 10).until(
            EC.presence_of_element_located((By.ID, 'activities_count'))
        )
        assert selenium.find_element(By.ID, "activities_count").text == "10 found"
        assert len(selenium.find_elements(By.CSS_SELECTOR, "table tbody tr")) == 10
        assert len(selenium.find_elements(By.CSS_SELECTOR, "table tbody tr td a span.fas.fa-edit")) == 10
