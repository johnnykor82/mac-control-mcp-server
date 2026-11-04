"""BF21: bounded offline GitHub verification, with owner-private encrypted state.

The OAuthProxy still issues/validates its own JWTs. This verifier only caches
*previously* authenticated upstream GitHub account identity; it never issues
an OAuth credential or extends the client-side JWT lifetime.
"""
from __future__ import annotations

import asyncio
import collections
from cryptography.fernet import Fernet, InvalidToken
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Awaitable, Callable

import httpx2
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from fastmcp.server.auth.providers.github import GitHubTokenVerifier


class CachedAllowedGitHubVerifier(GitHubTokenVerifier):
    """Positive trust expires 24h after LAST successful online verification.

    HTTP requests for a known fresh token never contact GitHub. An owned,
    cancellable background worker refreshes each active token hourly.
    No bearer credential is stored in the added on-disk cache.
    """
    def __init__(self, *, allowed_ids: set[str], signing_secret: str,
                 config_path: Path, cache_path: Path,
                 fetcher: Callable[[str], Awaitable[dict]] | None = None,
                 clock: Callable[[], float] | None = None,
                 interval: int = 3600, ttl: int = 86400):
        super().__init__(required_scopes=["read:user"])
        if not allowed_ids or not all(str(i).isdecimal() for i in allowed_ids):
            raise ValueError("An explicit GitHub numeric allowlist is required")
        if len(signing_secret) < 32:
            raise ValueError("Persistent cache requires owner signing key")
        self._allowed=frozenset(str(i) for i in allowed_ids)
        self._secret=signing_secret.encode()
        self._config=Path(config_path)
        self._cache_file=Path(cache_path)
        self._config_state=self._secure_config_state()
        self._fetcher=fetcher or self._github_probe
        self._clock=clock or time.time
        self._interval=interval
        self._ttl=ttl
        self._fernet=Fernet(derive_jwt_key(high_entropy_material=signing_secret,
                               salt="maccontrol-github-oauth-cache-v1"))
        self._records: dict[str, dict] = {}
        self._active: dict[str, str] = {}  # bearer only in server RAM
        self._attempts: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._worker: asyncio.Task | None = None
        self._counts=collections.Counter()
        self._revoked: set[str] = set()
        self._load()

    def _secure_config_state(self):
        s=self._config.lstat()
        if (not stat.S_ISREG(s.st_mode) or s.st_mode & 0o077
                or s.st_uid != os.getuid()):
            raise PermissionError("OAuth configuration must be owner-only")
        return (s.st_ino,s.st_mtime_ns,s.st_size)

    def _config_ok(self):
        try:
            return self._secure_config_state()==self._config_state
        except (OSError,PermissionError):
            return False

    def _fingerprint(self, token: str) -> str:
        identity=";".join(sorted(self._allowed)).encode()
        return hmac.new(self._secret,b"maccontrol-bf21-v1\0"+identity+b"\0"+
                        token.encode(),hashlib.sha256).hexdigest()

    def _load(self):
        p=self._cache_file
        try:
            s=p.lstat()
        except FileNotFoundError:
            return
        try:
            if (not stat.S_ISREG(s.st_mode) or s.st_mode & 0o077
                    or s.st_uid!=os.getuid()):
                raise ValueError("Unsafe verifier snapshot")
            raw=json.loads(self._fernet.decrypt(p.read_bytes()))
            if raw.get('version')!=1:raise ValueError('Unsupported version')
            entries=raw.get('records')
            if not isinstance(entries,dict) or len(entries)>500:
                raise ValueError('Invalid record set')
            for key,item in entries.items():
                if (isinstance(key,str) and len(key)==64
                    and isinstance(item,dict) and
                    str(item.get('subject')) in self._allowed
                    and 'read:user' in item.get('scopes',[]) and
                    isinstance(item.get('verified'),(int,float))):
                    self._records[key]=item
        except (ValueError,TypeError,KeyError,OSError,InvalidToken):
            self._counts['storage_unavailable']+=1
            self._records={}

    def _save(self):
        p=self._cache_file
        payload=json.dumps({'version':1,'records':self._records},
                           sort_keys=True,separators=(',',':')).encode()
        encoded=self._fernet.encrypt(payload)
        fd=None;tmp=None
        try:
            p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            # Never follow an attacker-supplied symlink or overwrite loose permissions.
            if p.is_symlink():raise PermissionError('Symlink verifier cache')
            fd,tmp=tempfile.mkstemp(prefix='.github-verify-',dir=p.parent)
            os.fchmod(fd,0o600)
            with os.fdopen(fd,'wb') as out:
                fd=None;out.write(encoded);out.flush();os.fsync(out.fileno())
            os.replace(tmp,p);tmp=None
        except OSError:
            self._counts['storage_unavailable']+=1
        finally:
            if fd is not None:os.close(fd)
            if tmp is not None:
                try:os.unlink(tmp)
                except FileNotFoundError:pass

    def metrics(self):
        return dict(self._counts)

    def _fresh(self,item,now):
        t=item.get('verified',float('inf'))
        return isinstance(t,(int,float)) and t<=now and 0<=now-t<self._ttl

    @staticmethod
    def _access(token,item):
        sub=str(item['subject'])
        return AccessToken(token=token,client_id=sub,scopes=item['scopes'],
                           expires_at=None,subject=sub,claims={'sub':sub})

    async def _github_probe(self,token: str) -> dict:
        """One upstream validation, errors classified without logging secrets."""
        headers={'Authorization':f'Bearer {token}',
                 'Accept':'application/vnd.github.v3+json',
                 'User-Agent':'MacControl-GitHub-OAuth'}
        try:
            async with httpx2.AsyncClient(timeout=10) as client:
                user=await client.get('https://api.github.com/user',headers=headers)
                if user.status_code==401:
                    return {'state':'invalid','reason':'401'}
                if user.status_code!=200:
                    return {'state':'transient','reason':str(user.status_code)}
                payload=user.json()
                subject=payload.get('id')
                if not isinstance(subject,int) or subject<=0:
                    return {'state':'transient','reason':'unexpected_json'}
                scopes=await client.get('https://api.github.com/user/repos',
                                        headers=headers)
                if scopes.status_code==401:
                    return {'state':'invalid','reason':'401'}
                if scopes.status_code!=200:
                    return {'state':'transient','reason':str(scopes.status_code)}
                granted=[v.strip() for v in
                         scopes.headers.get('x-oauth-scopes','').split(',') if v.strip()]
                if not granted:granted=['user']  # Match original verifier.
                return {'state':'valid','subject':str(subject),'scopes':granted}
        except (httpx2.RequestError,ValueError,TypeError):
            return {'state':'transient','reason':'network_error'}

    async def _check_online(self,key: str,token: str,*,background: bool):
        try:
            result=await self._fetcher(token)
        except Exception:
            result={'state':'transient','reason':'network_error'}
        now=self._clock()
        state=result.get('state') if isinstance(result,dict) else None
        if state=='valid':
            subject=str(result.get('subject',''))
            scopes=result.get('scopes')
            if (subject not in self._allowed or not isinstance(scopes,list)
                    or 'read:user' not in scopes):
                state='invalid';result={'reason':'scope_or_subject'}
            else:
                record={'subject':subject,'scopes':sorted(set(scopes)),
                        'verified':now}
                self._records[key]=record
                self._active[key]=token
                self._attempts[key]=now
                self._counts['background_success' if background else 'online_success']+=1
                self._save()
                return self._access(token,record)
        if state=='invalid':
            self._counts['explicit_invalid']+=1
            self._records.pop(key,None)
            self._active.pop(key,None)
            self._attempts.pop(key,None)
            self._revoked.add(key)
            self._save()
        else:
            reason=result.get('reason','unknown') if isinstance(result,dict) else 'unknown'
            self._counts['rate_limited' if reason in ('403','429','503') else 'timeout']+=1
            self._attempts[key]=now
        return None

    def _ensure_worker(self):
        if self._worker is None or self._worker.done():
            self._worker=asyncio.create_task(self._work_loop(),
                                            name='maccontrol-github-oauth-refresh')

    async def _work_loop(self):
        try:
            while True:
                await asyncio.sleep(60)
                await self.refresh_due()
        except asyncio.CancelledError:
            raise

    async def refresh_due(self):
        """Run due validations without blocking any concurrent cached request."""
        if not self._config_ok():
            self._counts['config_changed']+=1
            return 0
        changed=0
        for key,token in tuple(self._active.items()):
            now=self._clock()
            rec=self._records.get(key)
            if rec is None:continue
            if now<rec['verified']:
                self._records.pop(key,None)
                self._active.pop(key,None)
                self._counts['clock_rollback']+=1
                continue
            if now-self._attempts.get(key,rec['verified'])<self._interval:
                continue
            lock=self._locks.setdefault(key,asyncio.Lock())
            async with lock:
                if key not in self._active:continue
                now=self._clock()
                if now-self._attempts.get(key,rec['verified'])<self._interval:
                    continue
                self._attempts[key]=now
                await self._check_online(key,token,background=True)
                changed+=1
        return changed

    async def verify_token(self,token: str):
        if not isinstance(token,str) or not token or not self._config_ok():
            self._counts['config_changed']+=1
            return None
        key=self._fingerprint(token)
        if key in self._revoked:
            return None
        now=self._clock()
        item=self._records.get(key)
        if item and self._fresh(item,now):
            self._counts['cache_hit']+=1
            self._active[key]=token
            self._attempts.setdefault(key,item['verified'])
            self._ensure_worker()
            return self._access(token,item)
        if item:
            self._counts['stale_rejected']+=1
        else:self._counts['cache_miss']+=1
        lock=self._locks.setdefault(key,asyncio.Lock())
        async with lock:
            now=self._clock()
            item=self._records.get(key)
            if item and self._fresh(item,now):
                self._active[key]=token
                self._ensure_worker()
                return self._access(token,item)
            result=await self._check_online(key,token,background=False)
            if result is not None:self._ensure_worker()
            return result

    async def aclose(self):
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            try:await self._worker
            except asyncio.CancelledError:pass
        self._worker=None
