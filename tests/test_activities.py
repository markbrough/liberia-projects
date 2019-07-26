from flask import url_for
import pytest
import warnings
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

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


    def test_auth_routes_work(self, user):
        routes = [
            (url_for('activities.dashboard'), 200),
            (url_for('activities.activities'), 200),
            (url_for('activities.activity_new'), 200),
        ]
        for route, status_code in routes:
            res = self.client.get(route)
            assert res.status_code == status_code


@pytest.mark.usefixtures('live_server')
@pytest.mark.usefixtures('client_class')
class TestActivitiesLoad():
    def test_activities_load(self, app, selenium, selenium_login):
        selenium.get(url_for('activities.activities', _external=True))
        WebDriverWait(selenium, 5).until(
            EC.presence_of_element_located((By.ID, 'projectsList'))
        )
        assert selenium.find_element(By.ID, "activities_count").text == "10 found"
        assert len(selenium.find_elements(By.XPATH, "//table/tbody/tr")) == 10
