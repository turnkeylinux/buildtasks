import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('ec2_refresh', str(ROOT / 'bt-ec2-refresh'))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class HeadlessPreseedTest(unittest.TestCase):
    def run_preseed(self, ec2=False, existing=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'inithooks.conf'
            defaults = root / 'defaults'
            defaults.write_text('INITHOOKS_CONF=' + str(config) + '\n')
            if existing is not None:
                config.write_text(existing)
            script = (ROOT / 'patches/headless/overlay/usr/lib/inithooks/firstboot.d/29preseed').read_text()
            script = script.replace('/etc/default/inithooks', str(defaults))
            script = script.replace('chmod +x /usr/lib/inithooks/firstboot.d/??turnkey-init-fence*', ':')
            if ec2:
                # The EC2 overlay applies this exact transformation after headless.
                self.assertIn("s/^export SEC_UPDATES=SKIP$/export SEC_UPDATES=FORCE/", (ROOT / 'patches/ec2/conf').read_text())
                script = script.replace('export SEC_UPDATES=SKIP', 'export SEC_UPDATES=FORCE')
            subprocess.run(['bash', '-c', script], env={'PATH': os.environ['PATH']}, check=True, capture_output=True)
            return config.read_text()

    def test_ec2_initializes_without_inherited_config_path(self):
        result = self.run_preseed(ec2=True)
        self.assertIn('export SEC_UPDATES=FORCE\n', result)
        self.assertIn('export AUTO_RUN=TRUE\n', result)

    def test_explicit_user_preseed_is_preserved(self):
        config = 'export SEC_UPDATES=SKIP\nexport APP_DOMAIN=example.org\n'
        self.assertEqual(self.run_preseed(ec2=True, existing=config), config)

    def test_other_headless_formats_keep_their_existing_choice(self):
        self.assertIn('export SEC_UPDATES=SKIP\n', self.run_preseed())


class PublicationTest(unittest.TestCase):
    def reconcile_candidate(self, visibility):
        refresh = module.Refresh.__new__(module.Refresh)
        refresh.catalog = Mock()
        refresh.batch = 'test-batch'
        refresh.catalog.describe_change_set.return_value = {'Status': 'SUCCEEDED'}
        refresh.catalog.start_change_set.return_value = {'ChangeSetId': 'retirement'}
        refresh.catalog.describe_entity.return_value = {
            'EntityIdentifier': 'product@2', 'DetailsDocument': {'Versions': [
                {'VersionTitle': '19.0', 'DeliveryOptions': [{'Id': 'old', 'Visibility': 'Public'}]},
                {'VersionTitle': '19.0.20261104', 'DeliveryOptions': [{'Id': 'new', 'Visibility': visibility}]},
            ]}}
        item = {'app': 'core', 'product_id': 'product', 'version': '19.0.20261104', 'change_set_id': 'addition'}
        with tempfile.TemporaryDirectory() as directory:
            refresh.state = Path(directory)
            refresh.reconcile(item)
        return refresh, item

    def test_old_delivery_stays_public_until_replacement_is_public(self):
        refresh, item = self.reconcile_candidate('Restricted')
        refresh.catalog.start_change_set.assert_not_called()
        self.assertFalse(item['new_delivery_public'])

    def test_only_superseded_delivery_is_retired(self):
        refresh, item = self.reconcile_candidate('Public')
        request = refresh.catalog.start_change_set.call_args.kwargs['ChangeSet'][0]
        self.assertEqual(request['ChangeType'], 'RestrictDeliveryOptions')
        self.assertEqual(request['DetailsDocument']['DeliveryOptionIds'], ['old'])
        self.assertEqual(item['retirement_status'], 'SUCCEEDED')

    def test_unverified_image_cannot_be_submitted(self):
        refresh = module.Refresh.__new__(module.Refresh)
        refresh.catalog = Mock()
        with self.assertRaisesRegex(ValueError, 'verified boot'):
            refresh.publish({'ami': 'ami-candidate'})
        refresh.catalog.start_change_set.assert_not_called()

    def test_new_instance_visibility_is_retryable(self):
        refresh = module.Refresh.__new__(module.Refresh)
        refresh.ec2 = Mock()
        refresh.ec2.describe_instances.side_effect = ClientError(
            {'Error': {'Code': 'InvalidInstanceID.NotFound', 'Message': 'not yet propagated'}}, 'DescribeInstances')
        self.assertEqual(refresh.instance('i-new')['State']['Name'], 'pending')

    def test_other_aws_errors_are_not_hidden(self):
        refresh = module.Refresh.__new__(module.Refresh)
        refresh.ec2 = Mock()
        refresh.ec2.describe_instances.side_effect = ClientError(
            {'Error': {'Code': 'UnauthorizedOperation', 'Message': 'denied'}}, 'DescribeInstances')
        with self.assertRaises(ClientError):
            refresh.instance('i-new')


class ClientTokenTest(unittest.TestCase):
    def test_existing_tokens_keep_their_idempotency_identity(self):
        for token in ['batch-core-r1', 'x' * 64]:
            self.assertEqual(module.ec2_client_token(token), token)

    def test_long_tokens_are_stable_and_distinguish_attempts(self):
        token = 'x' * 60 + '-test-lighttpd-php-fastcgi-r1-1'
        first = module.ec2_client_token(token)
        self.assertEqual(len(first), 64)
        self.assertEqual(first, module.ec2_client_token(token))
        self.assertNotEqual(first, module.ec2_client_token(token[:-1] + '2'))

    def test_long_appliance_name_sends_an_accepted_boot_request_token(self):
        refresh = module.Refresh.__new__(module.Refresh)
        refresh.batch = 'tkl-use1-refresh-benchmark-20261104'
        refresh.resources = dict(key_name='test-key', subnet='subnet-test', security_group='sg-test')
        refresh.ec2 = Mock()
        refresh.ec2.run_instances.side_effect = RuntimeError('request captured')
        with tempfile.TemporaryDirectory() as directory:
            refresh.state = Path(directory)
            with self.assertRaisesRegex(RuntimeError, 'request captured'):
                refresh.boot_test(dict(app='lighttpd-php-fastcgi', ami='ami-test'))
        self.assertLessEqual(len(refresh.ec2.run_instances.call_args.kwargs['ClientToken']), 64)


if __name__ == '__main__':
    unittest.main()
