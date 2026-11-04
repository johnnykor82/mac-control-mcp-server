"""BF21: GitHub verification is never on the hot path for a valid cache entry."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest

from mac_control.remote_auth import CachedAllowedGitHubVerifier


class GitHubCachedVerifierTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=self.root/'remote_auth.json'
        self.config.write_text(json.dumps({'github_allowed_ids':['12345678'],
            'jwt_signing_key':'a-test-only-signing-key-'+'X'*60}))
        self.config.chmod(0o600)
        self.now=1_800_000_000.
        self.mode='valid'
        self.calls=[]
        async def upstream(token):
            self.calls.append((token,self.now))
            if self.mode=='valid':
                return {'state':'valid','subject':'12345678','scopes':['read:user']}
            if self.mode=='invalid':return {'state':'invalid','reason':'401'}
            if self.mode=='other':return {'state':'valid','subject':'99999999','scopes':['read:user']}
            return {'state':'transient','reason':self.mode}
        self.upstream=upstream
        self.verifier=self.make_verifier()
    async def asyncTearDown(self):
        await self.verifier.aclose()
    def make_verifier(self,**kwargs):
        return CachedAllowedGitHubVerifier(
            allowed_ids={'12345678'}, signing_secret='a-test-only-signing-key-'+'X'*60,
            config_path=self.config, cache_path=self.root/'github-oauth-cache.enc',
            fetcher=self.upstream, clock=lambda:self.now, **kwargs)
    async def test_cold_must_verify_then_multiple_requests_use_zero_http(self):
        value=await self.verifier.verify_token('test-only-token')
        self.assertEqual(value.subject,'12345678')
        self.assertEqual(len(self.calls),1)
        self.mode='timeout'
        for i in range(12):
            self.assertEqual((await self.verifier.verify_token('test-only-token')).subject,'12345678')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.verifier.metrics()['cache_hit'],12)
    async def test_hourly_background_success_renews_expiry(self):
        await self.verifier.verify_token('test-only-token')
        self.now+=3601
        refreshed=await self.verifier.refresh_due()
        self.assertEqual(refreshed,1)
        self.assertEqual(len(self.calls),2)
        self.now+=86399
        self.assertIsNotNone(await self.verifier.verify_token('test-only-token'))
    async def test_timeout_does_not_extend_old_verification(self):
        await self.verifier.verify_token('test-only-token')
        self.now+=3601
        self.mode='timeout'
        await self.verifier.refresh_due()
        self.now+=86400-3601-1
        self.assertIsNotNone(await self.verifier.verify_token('test-only-token'))
        self.now+=2
        self.assertIsNone(await self.verifier.verify_token('test-only-token'))
    async def test_explicit_invalid_revokes_immediately(self):
        await self.verifier.verify_token('test-only-token')
        self.now+=3601
        self.mode='invalid'
        await self.verifier.refresh_due()
        self.assertIsNone(await self.verifier.verify_token('test-only-token'))
    async def test_unknown_token_never_accepted_offline(self):
        self.mode='timeout'
        self.assertIsNone(await self.verifier.verify_token('unverified-token'))
    async def test_other_user_not_cached(self):
        self.mode='other'
        self.assertIsNone(await self.verifier.verify_token('other-token'))
        self.mode='timeout'
        self.assertIsNone(await self.verifier.verify_token('other-token'))
    async def test_temporary_errors_do_not_revoke(self):
        await self.verifier.verify_token('test-only-token')
        for mode in ('429','503','403','timeout'):
            self.now+=3601
            self.mode=mode
            await self.verifier.refresh_due()
            self.assertIsNotNone(await self.verifier.verify_token('test-only-token'))
    async def test_restart_uses_encrypted_snapshot_without_new_http(self):
        await self.verifier.verify_token('test-only-token')
        data=(self.root/'github-oauth-cache.enc').read_bytes()
        self.assertNotIn(b'test-only-token',data)
        self.assertNotIn(b'12345678',data)
        self.assertEqual((self.root/'github-oauth-cache.enc').stat().st_mode & 0o077,0)
        await self.verifier.aclose()
        self.verifier=self.make_verifier()
        self.mode='timeout'
        self.assertEqual((await self.verifier.verify_token('test-only-token')).subject,'12345678')
        self.assertEqual(len(self.calls),1)
    async def test_clock_rollback_rejects_stale_data(self):
        await self.verifier.verify_token('test-only-token')
        self.now-=60
        self.mode='timeout'
        self.assertIsNone(await self.verifier.verify_token('test-only-token'))
    async def test_tampered_snapshot_requires_fresh_validation(self):
        await self.verifier.verify_token('test-only-token')
        await self.verifier.aclose()
        (self.root/'github-oauth-cache.enc').write_bytes(b'not an encrypted record')
        self.verifier=self.make_verifier()
        self.mode='timeout'
        self.assertIsNone(await self.verifier.verify_token('test-only-token'))
    async def test_config_edit_invalidates_current_confirmation(self):
        await self.verifier.verify_token('test-only-token')
        data=json.loads(self.config.read_text())
        data['github_allowed_ids']=['99999999']
        self.config.write_text(json.dumps(data))
        self.config.chmod(0o600)
        self.mode='timeout'
        self.assertIsNone(await self.verifier.verify_token('test-only-token'))
    async def test_parallel_first_use_is_single_flight(self):
        results=await asyncio.gather(*(self.verifier.verify_token('test-only-token')
                                       for _ in range(16)))
        self.assertTrue(all(x and x.subject=='12345678' for x in results))
        self.assertEqual(len(self.calls),1)
    async def test_two_tokens_isolated_in_cache(self):
        self.assertIsNotNone(await self.verifier.verify_token('token-A'))
        self.assertIsNotNone(await self.verifier.verify_token('token-B'))
        self.assertEqual(len(self.calls),2)
        self.mode='timeout'
        self.assertIsNotNone(await self.verifier.verify_token('token-A'))
        self.assertIsNotNone(await self.verifier.verify_token('token-B'))
        self.assertEqual(len(self.calls),2)
    async def test_signing_key_change_cannot_reuse_snapshot(self):
        await self.verifier.verify_token('test-only-token')
        await self.verifier.aclose()
        self.verifier=CachedAllowedGitHubVerifier(
            allowed_ids={'12345678'},signing_secret='DIFFERENT-key-'+'Y'*65,
            config_path=self.config,cache_path=self.root/'github-oauth-cache.enc',
            fetcher=self.upstream,clock=lambda:self.now)
        self.mode='timeout'
        self.assertIsNone(await self.verifier.verify_token('test-only-token'))
        self.assertEqual(self.verifier.metrics()['storage_unavailable'],1)
    async def test_world_readable_cache_is_not_trusted(self):
        await self.verifier.verify_token('test-only-token')
        await self.verifier.aclose()
        (self.root/'github-oauth-cache.enc').chmod(0o644)
        self.verifier=self.make_verifier()
        self.mode='timeout'
        self.assertIsNone(await self.verifier.verify_token('test-only-token'))
    async def test_upstream_http_401_vs_403_vs_valid_identity(self):
        from unittest.mock import patch
        import httpx2
        original=httpx2.AsyncClient
        for status,expected in ((401,'invalid'),(403,'transient'),(429,'transient'),
                                (503,'transient'),(200,'valid')):
            def respond(req):
                if req.url.path=='/user':
                    if status!=200:return httpx2.Response(status)
                    return httpx2.Response(200,json={'id':12345678})
                return httpx2.Response(200,headers={'x-oauth-scopes':'read:user'})
            transport=httpx2.MockTransport(respond)
            with patch('mac_control.github_oauth_cache.httpx2.AsyncClient',
                       side_effect=lambda **opts:original(transport=transport,**opts)):
                result=await self.verifier._github_probe('test-only-token')
            self.assertEqual(result['state'],expected)
    async def test_background_worker_survives_network_error_until_revoked(self):
        await self.verifier.verify_token('test-only-token')
        self.assertIsNotNone(self.verifier._worker)
        self.now+=3601
        self.mode='timeout'
        await self.verifier.refresh_due()
        self.assertFalse(self.verifier._worker.done())
        self.mode='valid'
        self.now+=3601
        await self.verifier.refresh_due()
        self.assertEqual(self.verifier.metrics()['background_success'],1)
        self.now+=3601
        self.mode='invalid'
        await self.verifier.refresh_due()
        self.assertIsNone(await self.verifier.verify_token('test-only-token'))
