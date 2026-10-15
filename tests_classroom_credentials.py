import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class SavedCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.st = types.SimpleNamespace(session_state={}, secrets={})
        kis = types.SimpleNamespace(KIS=object, BrokerError=RuntimeError)
        spec = importlib.util.spec_from_file_location('classroom_under_test',
            Path(__file__).parent / 'predash' / 'classroom.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'streamlit': self.st, 'predash.kis': kis}):
            spec.loader.exec_module(self.module)
        self.st.secrets.update(KIS_ENV='real', KIS_APP_KEY='saved-real',
            KIS_APP_SECRET='secret', KIS_CANO='00123456', KIS_ACNT_PRDT_CD='01')

    def test_new_session_restores_saved_profile_and_leading_zeroes(self):
        self.st.session_state.clear()
        settings = self.module.account_settings()
        self.assertEqual((settings['mode'], settings['key'], settings['cano'], settings['product']),
                         ('real', 'saved-real', '00123456', '01'))

    def test_session_override_is_a_whole_profile(self):
        self.st.session_state['classroom_credentials'] = {
            'mode': 'real', 'key': 'temporary', 'secret': '', 'cano': '', 'product': ''}
        settings = self.module.account_settings()
        self.assertEqual(settings['key'], 'temporary')
        self.assertEqual(settings['secret'], '')

    def test_demo_never_reuses_real_profile(self):
        self.assertEqual(self.module.account_settings('demo')['key'], '')
        self.st.secrets['KIS_DEMO_APP_KEY'] = 'demo'
        settings = self.module.account_settings('demo')
        self.assertEqual(settings['key'], 'demo')
        self.assertEqual(settings['secret'], '')

    def test_legacy_demo_profile_only_applies_to_demo(self):
        self.st.secrets['KIS_ENV'] = 'demo'
        self.assertEqual(self.module.account_settings('demo')['key'], 'saved-real')
        self.assertEqual(self.module.account_settings('real')['key'], '')

    def test_disconnect_suppresses_saved_profile_until_reenabled(self):
        self.st.session_state['classroom_saved_disabled'] = True
        self.assertEqual(self.module.account_settings()['key'], '')
        self.st.session_state.pop('classroom_saved_disabled')
        self.assertEqual(self.module.account_settings()['key'], 'saved-real')

    def test_no_secrets_file_still_allows_session_entry(self):
        class MissingSecrets:
            def get(self, *args):
                raise FileNotFoundError
        self.st.secrets = MissingSecrets()
        self.assertEqual(self.module.account_settings()['key'], '')
        self.st.session_state['classroom_credentials'] = {'mode': 'demo', 'key': 'session'}
        self.assertEqual(self.module.account_settings()['key'], 'session')


if __name__ == '__main__':
    unittest.main()
