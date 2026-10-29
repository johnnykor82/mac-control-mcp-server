"""Native macOS background Accessibility backend, Dev-only; no global input events.

Session capabilities bind the owner to the bundle ID, PID, and launch time.
The native helper always validates the current AX tree and window fingerprint.
"""
from __future__ import annotations
import base64,fcntl,hashlib,hmac,json,os,re,secrets,subprocess,time
from pathlib import Path
from fastmcp.tools.base import ToolResult
from mcp.types import ImageContent
from .runtime_paths import DATA_ROOT
ROOT=DATA_ROOT/'background-native'
BINARY=Path(__file__).resolve().parents[2]/'build/dev_native_background'
FLAG=DATA_ROOT/'feature_flags.json'
SESSION=re.compile(r'[0-9a-f]{40}\.[0-9a-f]{64}\Z')

def enabled():
    if not FLAG.is_file() or FLAG.is_symlink():return False
    try:return json.loads(FLAG.read_text()).get('background_native') is True
    except (OSError,ValueError,TypeError):return False

def error(code,message):return {'ok':False,'error':{'code':code,'message':message}}

def secure(path):
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise PermissionError('Insecure native session directory')

def store(path,obj):
    data=json.dumps(obj,sort_keys=True)
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as file:file.write(data)

def helper(op,**parameters):
    if not BINARY.is_file() or BINARY.is_symlink():return error('DEPENDENCY_MISSING','Native Dev binary missing')
    try:
        request=json.dumps({'op':op,**parameters},ensure_ascii=False)
        if len(request)>30000:return error('INVALID_ARGUMENT','Native request exceeds limit')
        proc=subprocess.run([str(BINARY)],input=request+'\n',capture_output=True,text=True,
            timeout=12,env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin:/opt/homebrew/bin'})
        if proc.returncode or len(proc.stdout)>160000:return error('HELPER_FAILED','Native helper unavailable')
        response=json.loads(proc.stdout)
        if response.get('ok'):
            return {'ok':True,'result':response['result']}
        return error(response.get('code','NATIVE_ERROR'),response.get('message','Native API unavailable'))
    except (OSError,ValueError,subprocess.TimeoutExpired):return error('HELPER_FAILED','Native helper unavailable')

def begin(bundle_id):
    if not isinstance(bundle_id,str) or not re.fullmatch(r'[A-Za-z0-9.-]{3,180}',bundle_id):
        return error('INVALID_APP','Valid bundle ID required')
    found=helper('windows',bundle_id=bundle_id)
    if not found['ok']:return found
    details=found['result']
    if not details['windows']:return error('NO_WINDOWS','App has no accessible windows')
    pids={w['pid'] for w in details['windows']}
    if len(pids)!=1:return error('AMBIGUOUS_APP','Ambiguous application PID')
    secure(ROOT);secure(ROOT/'sessions')
    sid=secrets.token_hex(20);token=sid+'.'+secrets.token_hex(32)
    metadata={'bundle_id':bundle_id,'pid':pids.pop(),'launch_date':details['launch_date'],
              'created':time.time(),'expires':time.time()+7*86400,
              'token_hash':hashlib.sha256(token.encode()).hexdigest()}
    store(ROOT/'sessions'/(sid+'.json'),metadata)
    return {'ok':True,'result':{'session_token':token,'session_id':sid,'bundle_id':bundle_id,
               'pid':metadata['pid'],'window_count':len(details['windows']),'ttl_days':7}}

def authenticated(token):
    if not isinstance(token,str) or not SESSION.fullmatch(token):return None
    sid=token.split('.')[0]
    path=ROOT/'sessions'/(sid+'.json')
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:return None
    try:meta=json.loads(path.read_text())
    except (ValueError,OSError):return None
    if not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),meta.get('token_hash','')):
        return None
    if time.time()>meta.get('expires',0):return None
    return path,meta

def capture_verified(meta,ref):
    # Match a fresh AX window fingerprint under the session's exact app identity.
    inventory=helper('windows',bundle_id=meta['bundle_id'],expected_pid=meta['pid'],
                     expected_launch_date=meta['launch_date'])
    if not inventory.get('ok'):return inventory
    matches=[w for w in inventory['result']['windows'] if w['window_ref']==ref]
    if len(matches)!=1:return error('STALE_OR_AMBIGUOUS_WINDOW','Window fingerprint expired')
    window=matches[0]
    from .legacy_handlers import gui_ops
    image_dir=DATA_ROOT/'run/gui-captures'
    secure(image_dir)
    dest=image_dir/('native-'+secrets.token_hex(16)+'.jpg')
    bounds=window['bounds']
    try:
        result=gui_ops._call('capture_window',timeout=25,pid=meta['pid'],
            title=window['title'],**bounds,destination=str(dest))
        if dest.is_symlink() or not dest.is_file():
            return error('IMAGE_MISSING','Dev GUI produced no image')
        data=dest.read_bytes()
        if not (1000<len(data)<=850000 and data.startswith(b'\xff\xd8')):
            return error('IMAGE_INVALID','JPEG missing or exceeds limit')
        return {'ok':True,'result':{'image_data':base64.b64encode(data).decode('ascii'),
            'mime_type':'image/jpeg','image_bytes':len(data),
            'window_ref':ref,'capture_mode':result['capture_mode']}}
    except (OSError,RuntimeError,ValueError) as exc:
        message=str(exc)
        code='SCREEN_CAPTURE_DENIED' if 'SCREEN_CAPTURE_DENIED' in message else 'CAPTURE_UNAVAILABLE'
        return error(code,message[:250])
    finally:
        dest.unlink(missing_ok=True)

def execute(token,operation,**params):
    initial=authenticated(token)
    if not initial:return error('NOT_AUTHORIZED','Unknown, expired or invalid session capability')
    secure(ROOT/'locks')
    sid=token.split('.')[0]
    # A session lock serializes close/revoke with all concurrent in-flight actions.
    session_fd=os.open(ROOT/'locks'/(sid+'.session.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(session_fd,fcntl.LOCK_EX)
        current=authenticated(token)
        if not current:return error('NOT_AUTHORIZED','Session capability revoked')
        path,meta=current
        if operation=='end':
            path.unlink(missing_ok=True)
            return {'ok':True,'result':{'closed':True}}
        if operation not in ('windows','elements','action','capture'):
            return error('UNKNOWN_ACTION','Native operation not registered')
        key=hashlib.sha256(meta['bundle_id'].encode()).hexdigest()
        app_fd=os.open(ROOT/'locks'/(key+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(app_fd,fcntl.LOCK_EX)
            if operation=='capture':
                return capture_verified(meta,params.get('window_ref',''))
            return helper(operation,bundle_id=meta['bundle_id'],expected_pid=meta['pid'],
                  expected_launch_date=meta['launch_date'],**params)
        finally:
            fcntl.flock(app_fd,fcntl.LOCK_UN)
            os.close(app_fd)
    finally:
        fcntl.flock(session_fd,fcntl.LOCK_UN)
        os.close(session_fd)

def register(mcp):
    @mcp.tool(annotations={'readOnlyHint':True,'openWorldHint':False})
    def background_app_list()->dict:
        """List GUI-capable running macOS apps without activating them."""
        return helper('apps')
    @mcp.tool(annotations={'readOnlyHint':False,'openWorldHint':False})
    def background_app_create(bundle_id:str)->dict:
        """Bind a private capability to the running app PID and launch identity."""
        return begin(bundle_id)
    @mcp.tool(annotations={'readOnlyHint':True,'openWorldHint':False})
    def background_app_windows(session_token:str)->dict:
        """List AX windows with stale-detecting references for the owned app."""
        return execute(session_token,'windows')
    @mcp.tool(annotations={'readOnlyHint':True,'openWorldHint':False})
    def background_app_elements(session_token:str,window_ref:str,max_depth:int=4,max_nodes:int=120)->dict:
        """Read AX role/title/action tree, never passwords or AX field values."""
        return execute(session_token,'elements',window_ref=window_ref,max_depth=max_depth,max_nodes=max_nodes)
    @mcp.tool(annotations={'readOnlyHint':False,'openWorldHint':False})
    def background_app_action(session_token:str,window_ref:str,element_path:list[int],expected_role:str,
                              expected_title:str,action:str,text:str='',mode:str='background')->dict:
        """Set supported AX text values or perform direct AX actions; no global mouse/keyboard/focus."""
        if mode not in ('background','auto','foreground'):
            return error('INVALID_MODE','Mode must be foreground/background/auto')
        if mode == 'foreground':
            return error('REQUIRES_FOREGROUND','Use explicit existing GUI tools for foreground actions')
        return execute(session_token,'action',window_ref=window_ref,element_path=element_path,
                       expected_role=expected_role,expected_title=expected_title,action=action,text=text)
    @mcp.tool(annotations={'readOnlyHint':True,'openWorldHint':True})
    def background_app_capture(session_token:str,window_ref:str)->ToolResult:
        """Capture an owned AX window as a native MCP image content block."""
        response=execute(session_token,'capture',window_ref=window_ref)
        if not response.get('ok'):
            return ToolResult(structured_content=response)
        result=response['result']
        data=result['image_data']
        metadata={key:value for key,value in result.items() if key!='image_data'}
        return ToolResult(
            content=[ImageContent(data=data,mimeType='image/jpeg')],
            structured_content={'ok':True,'result':metadata})
    @mcp.tool(annotations={'readOnlyHint':False,'openWorldHint':False})
    def background_app_close(session_token:str)->dict:
        """Revoke native app session capability, never terminate the owner's application."""
        return execute(session_token,'end')
