"""BF20 G1 remote OAuth authentication must not be impersonable via CLI claims."""
import contextlib
import sqlite3
import sys
import types
import inspect

import pytest

from mac_control.legacy_handlers import watcher_ops
from mac_control.watcher_runtime import multi_project_watcher as core
from mac_control.watcher_runtime import watcher_browser_dispatch as dispatch
from mac_control.watcher_runtime import watcher_http_adapter as adapter

class FakeMCP:
    def __init__(self): self.tools={}
    def tool(self,**_kwargs):
        def register(function):
            self.tools[function.__name__]=function
            return function
        return register

def test_browser_origin_authenticated_inside_mcp_not_claimed_in_subprocess(monkeypatch):
    """Auth subject verified in-process, and not handed over a spoofable CLI payload."""
    mcp=FakeMCP()
    watcher_ops.register(mcp)
    token=types.ModuleType('mac_control.account_profile')
    token.authenticated_profile=lambda: {'id':'verified-owner-123'}
    monkeypatch.setitem(sys.modules,'mac_control.account_profile',token)

    def forbidden(*_a,**_k):
        raise AssertionError('Browser handoff must not trust a caller-supplied CLI subject')
    monkeypatch.setattr(watcher_ops,'_cli_payload',forbidden)

    history=[]
    class IsolatedDB:
        def close(self): pass
    monkeypatch.setattr(core,'connect',lambda: IsolatedDB())
    monkeypatch.setattr(dispatch,'register_owned_project',
        lambda db,p,u,o: history.append(('register',p,u,o)) or {'project_id':p})
    monkeypatch.setattr(dispatch,'prepare_owner_dispatch',
        lambda db,p,t,u,prompt,key,owner,api:
            history.append(('dispatch',p,t,u,owner)) or {'state':'prepared'})
    monkeypatch.setattr(adapter,'setup',lambda db: None)
    result=mcp.tools['watcher_register_browser_project'](
        'pilot01','https://chatgpt.com/c/11111111-1111-4111-8111-111111111111')
    assert result['project_id']=='pilot01'
    queued=mcp.tools['watcher_dispatch_browser_task'](
        'pilot01','worker-a','https://chatgpt.com/c/22222222-2222-4222-8222-222222222222',
        'Perform an isolated benign smoke test for this browser task.',
        'bf20-origin-test-01')
    assert queued['state']=='prepared'
    assert history==[
        ('register','pilot01','https://chatgpt.com/c/11111111-1111-4111-8111-111111111111','verified-owner-123'),
        ('dispatch','pilot01','worker-a','https://chatgpt.com/c/22222222-2222-4222-8222-222222222222','verified-owner-123')
    ]

def test_bf20_runtime_module_is_in_installer_release_manifest():
    """The public source archive must actually install the BF20 runtime module."""
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    manifest=(root/'scripts/install_manifest.txt').read_text(encoding='utf-8').splitlines()
    assert 'src/mac_control/watcher_runtime/watcher_browser_dispatch.py' in manifest


def test_internal_cli_cannot_claim_to_be_remote_owner():
    """No untrusted CLI verbs that authorize by passing an arbitrary owner_subject."""
    code=inspect.getsource(core.main)
    assert "sub.add_parser('prepare-browser')" not in code
    assert "sub.add_parser('register-owned-project')" not in code


def test_dev_static_inventory_includes_owner_authenticated_browser_tools():
    """Dev preview remains in sync with the audited frozen source registry."""
    from mac_control.legacy_adapter import _EXPECTED
    from mac_control.dev_enabled_operations import (
        READ_ONLY_PREVIEW_OPERATIONS, LOCAL_MUTATION_OPERATIONS,
        LOCAL_COMPAT_READ_OPERATIONS, LOCAL_GUI_READ_OPERATIONS,
        LOCAL_TERMINAL_READ_OPERATIONS, LOCAL_BRIDGE_READ_OPERATIONS,
    )
    actual = (READ_ONLY_PREVIEW_OPERATIONS | LOCAL_MUTATION_OPERATIONS |
              LOCAL_COMPAT_READ_OPERATIONS | LOCAL_GUI_READ_OPERATIONS |
              LOCAL_TERMINAL_READ_OPERATIONS | LOCAL_BRIDGE_READ_OPERATIONS)
    assert actual == _EXPECTED
    assert len(actual) == 108
    assert {'watcher_register_browser_project', 'watcher_dispatch_browser_task'} <= LOCAL_MUTATION_OPERATIONS


def test_marker_lookup_only_has_extended_http_timeout(monkeypatch):
    """A slow read-only ChatGPT search must not relax normal gateway request limits."""
    import io
    timeouts = []

    def fake_open(request, timeout):
        timeouts.append((request.get_method(), request.full_url, timeout))
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(adapter._HTTP, 'open', fake_open)
    monkeypatch.setattr(adapter, 'api_key', lambda: None)
    assert adapter.api('POST', '/v1/chats/resolve-marker', {'marker':'WATCHER-CHAT-'+'a'*32})['ok']
    assert adapter.api('GET', '/v1/system/status')['ok']
    assert timeouts[0][2] == 180
    assert timeouts[1][2] == 30
    assert timeouts[0][0] == 'POST' and timeouts[1][0] == 'GET'


def test_marker_lookup_mcp_waits_longer_than_gateway_search(monkeypatch):
    """The CLI wrapper must outlive the specialized HTTP timeout."""
    mcp = FakeMCP()
    watcher_ops.register(mcp)
    calls = []

    def fake_cli(command, payload, timeout=45):
        calls.append((command, payload, timeout))
        return {'evidence_verified':True}

    monkeypatch.setattr(watcher_ops, '_cli_payload', fake_cli)
    marker='WATCHER-CHAT-'+'b'*32
    assert mcp.tools['watcher_resolve_current_chat'](marker)['evidence_verified']
    assert calls == [('resolve-chat', {'evidence_text':marker}, 210)]
    assert inspect.signature(watcher_ops._cli).parameters['timeout'].default == 45
    assert inspect.signature(watcher_ops._cli_payload).parameters['timeout'].default == 45
