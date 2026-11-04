"""Watcher revisioned file handoff v1. Reports are inert UTF-8, never executed."""
from __future__ import annotations
import hashlib,hmac,json,os,re,secrets,sqlite3,stat,time,uuid
from pathlib import Path

MAX_BYTES=81920
STATES={"checkpoint","needs_input","completed","blocked"}
TOKEN_RE=re.compile(r"^[A-Za-z0-9_-]{32,160}$")
def _watcher():
    from . import multi_project_watcher as w
    return w
def _name(value):
    return _watcher().require_name(value)
def _digest(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()
def _authenticate(stored,submitted):
    if not isinstance(submitted,str) or not TOKEN_RE.fullmatch(submitted):
        raise PermissionError("Missing task capability")
    if not stored or not hmac.compare_digest(stored,_digest(submitted)):
        raise PermissionError("Invalid task capability")

def setup(db):
    """Additive schema migration; preserve all existing browser task history."""
    cols={r["name"] for r in db.execute("PRAGMA table_info(tasks)")}
    for col,ddl in [
        ("mode","TEXT NOT NULL DEFAULT 'browser'"),
        ("last_revision","INTEGER NOT NULL DEFAULT 0"),
        ("submit_capability_hash","TEXT"),
        ("resume_capability_hash","TEXT"),
    ]:
        if col not in cols:db.execute(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")
    cols={r["name"] for r in db.execute("PRAGMA table_info(deliveries)")}
    if "revision" not in cols:
        db.execute("ALTER TABLE deliveries ADD COLUMN revision INTEGER")
    db.execute("DROP INDEX IF EXISTS deliveries_by_task")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS deliveries_browser_task_unique
       ON deliveries(project_id,task_id) WHERE revision IS NULL""")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS deliveries_file_revision_unique
       ON deliveries(project_id,task_id,revision) WHERE revision IS NOT NULL""")
    db.execute("""CREATE TABLE IF NOT EXISTS task_reports(
       project_id TEXT NOT NULL,task_id TEXT NOT NULL,revision INTEGER NOT NULL,
       status TEXT NOT NULL,path TEXT NOT NULL,sha256 TEXT NOT NULL,
       bytes INTEGER NOT NULL,created_at TEXT NOT NULL,
       PRIMARY KEY(project_id,task_id,revision))""")

    db.execute("""CREATE TABLE IF NOT EXISTS file_task_dispatch(
       project_id TEXT NOT NULL,task_id TEXT NOT NULL,
       request_key TEXT,prompt_sha256 TEXT,
       state TEXT NOT NULL DEFAULT 'registered',
       request_id TEXT,error_code TEXT,
       updated_ts REAL NOT NULL,
       PRIMARY KEY(project_id,task_id),
       FOREIGN KEY(project_id,task_id) REFERENCES tasks(project_id,id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS file_dispatch_events(
       event_id INTEGER PRIMARY KEY AUTOINCREMENT,
       project_id TEXT NOT NULL,task_id TEXT NOT NULL,
       request_key TEXT,event TEXT NOT NULL,request_id TEXT,error_code TEXT,
       recorded_ts REAL NOT NULL,
       FOREIGN KEY(project_id,task_id) REFERENCES tasks(project_id,id))""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS file_dispatch_state_audit
       AFTER UPDATE OF state ON file_task_dispatch
       WHEN OLD.state <> NEW.state
       BEGIN
         INSERT INTO file_dispatch_events(project_id,task_id,request_key,event,
                  request_id,error_code,recorded_ts)
         VALUES (NEW.project_id,NEW.task_id,COALESCE(NEW.request_key,OLD.request_key),
                 CASE WHEN OLD.state='failed' AND NEW.state='registered'
                      THEN 'recovered' ELSE NEW.state END,
                 COALESCE(NEW.request_id,OLD.request_id),
                 COALESCE(NEW.error_code,OLD.error_code),NEW.updated_ts);
       END""")
    db.execute("""INSERT OR IGNORE INTO file_task_dispatch(project_id,task_id,state,updated_ts)
       SELECT project_id,id,CASE WHEN last_revision>0 THEN 'reported'
            ELSE 'registered' END,CAST(strftime('%s','now') AS REAL) FROM tasks
       WHERE mode='file'""")

def register(db,project,task,chat_url):
    setup(db)
    w=_watcher();p=_name(project);t=_name(task)
    if db.execute("SELECT 1 FROM tasks WHERE project_id=? AND id=?",(p,t)).fetchone():
        raise ValueError("Existing task cannot switch mode")
    submit_token=secrets.token_urlsafe(36)
    resume_token=secrets.token_urlsafe(36)
    # Registration must not expose an intermediate browser-mode task.
    db.execute("BEGIN IMMEDIATE")
    try:
        w.register_task(db,p,t,chat_url)
        db.execute("""UPDATE tasks SET mode='file',last_revision=0,
          submit_capability_hash=?,resume_capability_hash=? WHERE project_id=? AND id=?""",
          (_digest(submit_token),_digest(resume_token),p,t))
        db.execute("""INSERT INTO file_task_dispatch(project_id,task_id,updated_ts)
                     VALUES(?,?,?)""",(p,t,time.time()))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return {"project_id":p,"task_id":t,"mode":"file","state":"watching",
            "executor_url":w.canonical_url(chat_url),
            "submission_token":submit_token,
            "orchestrator_token":resume_token,
            "next_revision":1,
            "warning":"Capabilities are secrets. Use only platform-permitted handoff; never bypass a blocked send. Keep orchestrator_token private."}

_DISPATCH_KEY_RX=re.compile(r'^[A-Za-z0-9_-]{8,128}$')
_DISPATCH_ID_RX=re.compile(r'^[A-Za-z0-9_-]{8,160}$')
_DISPATCH_ERROR_RX=re.compile(r'^[a-z][a-z0-9_]{2,47}$')

def record_dispatch(db,project,task,request_key,prompt_sha256,event,
                    *,request_id='',error_code=''):
    """Only records an explicit receipt; never sends any browser message."""
    p=_name(project);t=_name(task)
    if not isinstance(request_key,str) or not _DISPATCH_KEY_RX.fullmatch(request_key):
        raise ValueError('Invalid dispatch request key')
    if not isinstance(prompt_sha256,str) or not re.fullmatch(r'[a-f0-9]{64}',prompt_sha256):
        raise ValueError('Invalid dispatch prompt digest')
    if event not in ('prepare','queued','failed','uncertain'):
        raise ValueError('Invalid dispatch event')
    if event=='queued':
        if not isinstance(request_id,str) or not _DISPATCH_ID_RX.fullmatch(request_id):
            raise ValueError('Missing acknowledged request ID')
    elif request_id:
        raise ValueError('Request ID only permitted with queued receipt')
    if event=='failed':
        if not isinstance(error_code,str) or not _DISPATCH_ERROR_RX.fullmatch(error_code):
            raise ValueError('Invalid failure code; never store error details')
    elif error_code:
        raise ValueError('Error code only permitted for failed receipt')
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('''SELECT d.*,t.state AS task_state,t.last_revision,t.mode,
                          p.status AS project_status FROM file_task_dispatch d
                          JOIN tasks t ON t.project_id=d.project_id AND t.id=d.task_id
                          JOIN projects p ON p.id=t.project_id
                          WHERE d.project_id=? AND d.task_id=?''',(p,t)).fetchone()
        if (not row or row['mode']!='file' or row['project_status']!='enabled'
                or row['task_state']!='watching' or row['last_revision']!=0):
            raise ValueError('Not an active initial file-task dispatch')
        duplicate=(row['state']==('prepared' if event=='prepare' else event)
                   and row['request_key']==request_key
                   and row['prompt_sha256']==prompt_sha256
                   and (event!='queued' or row['request_id']==request_id)
                   and (event!='failed' or row['error_code']==error_code))
        if duplicate:
            db.execute('COMMIT')
            return {'project_id':p,'task_id':t,'state':row['state'],
                    'request_key':request_key,'duplicate':True}
        if ((event=='prepare' and row['state']!='registered')
                or (event!='prepare' and row['state']!='prepared')
                or (event!='prepare' and (row['request_key']!=request_key or
                     row['prompt_sha256']!=prompt_sha256))):
            raise ValueError('Dispatch state conflict; inspect before retry')
        state='prepared' if event=='prepare' else event
        count=db.execute('''UPDATE file_task_dispatch SET state=?,request_key=?,
            prompt_sha256=?,request_id=?,error_code=?,updated_ts=?
            WHERE project_id=? AND task_id=? AND state=?''',
            (state,request_key,prompt_sha256,request_id or None,error_code or None,
             time.time(),p,t,row['state'])).rowcount
        if count!=1:raise RuntimeError('Concurrent dispatch state update')
        db.execute('COMMIT')
        return {'project_id':p,'task_id':t,'state':state,
                'request_key':request_key,'duplicate':False}

    except BaseException:
        db.execute('ROLLBACK')
        raise

def recover_failed_dispatch(db,project,task,request_key,*,owner_confirmed=False):
    """Local owner-only rev0 recovery. Never reconstructs old credentials.

    Not exposed as an MCP tool. A denied message remains denied: no resend.
    """
    p=_name(project);t=_name(task)
    if owner_confirmed is not True:
        raise PermissionError('Explicit local owner confirmation required')
    if not isinstance(request_key,str) or not _DISPATCH_KEY_RX.fullmatch(request_key):
        raise ValueError('Invalid failed request key')
    submit_token=secrets.token_urlsafe(36)
    resume_token=secrets.token_urlsafe(36)
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('''SELECT d.state,d.request_key,t.last_revision,
            t.mode,t.state AS task_state,p.status AS project_status FROM
            file_task_dispatch d JOIN tasks t ON t.project_id=d.project_id
            AND t.id=d.task_id JOIN projects p ON p.id=d.project_id
            WHERE d.project_id=? AND d.task_id=?''',(p,t)).fetchone()
        if (not row or row['state']!='failed' or row['request_key']!=request_key
                or row['last_revision']!=0 or row['mode']!='file'
                or row['task_state']!='watching' or row['project_status']!='enabled'):
            raise ValueError('Task not eligible for lost-token recovery')
        for table in ('task_reports','deliveries'):
            if db.execute(f'SELECT 1 FROM {table} WHERE project_id=? AND task_id=? LIMIT 1',(p,t)).fetchone():
                raise ValueError('Report/delivery already exists; cannot rotate')
        for directory in (_reports_root()/p/t,_legacy_directory(p,t)):
            if directory.is_symlink() or any(
                (directory/name).exists() or (directory/name).is_symlink()
                for name in ('000001.md','000001.ready.json')):
                raise ValueError('Report material exists; cannot rotate')
        count=db.execute('''UPDATE tasks SET submit_capability_hash=?,
            resume_capability_hash=?,error=NULL WHERE project_id=? AND id=?
            AND last_revision=0 AND mode='file' AND state='watching' ''',
            (_digest(submit_token),_digest(resume_token),p,t)).rowcount
        if count!=1:raise RuntimeError('Task changed during recovery')
        count=db.execute('''UPDATE file_task_dispatch SET state='registered',
             request_key=NULL,prompt_sha256=NULL,request_id=NULL,error_code=NULL,
             updated_ts=? WHERE project_id=? AND task_id=? AND state='failed' ''',
             (time.time(),p,t)).rowcount
        if count!=1:raise RuntimeError('Dispatch changed during recovery')
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise
    return {'project_id':p,'task_id':t,'state':'registered',
            'next_revision':1,'submission_token':submit_token,
            'orchestrator_token':resume_token,
            'warning':'New credentials issued once; old credentials revoked. Do not transmit via blocked channel.'}


def dispatch_summary(db,project=None,*,at=None):
    """Read-only receipts; no capabilities, prompt digests or body contents."""
    sql='''SELECT project_id,task_id,request_key,state,request_id,
            error_code,updated_ts FROM file_task_dispatch'''
    rows=db.execute(sql+(' WHERE project_id=?' if project else ''),
                    (project,) if project else ()).fetchall()
    when=time.time() if at is None else float(at)
    result=[]
    for row in rows:
        r=dict(row)
        age=max(0,int(when-r['updated_ts']))
        r['display_state']='uncertain' if r['state']=='prepared' and age>=300 else r['state']
        r['age_seconds']=age
        # A queued request ID is not proof of actual executor execution.
        r['delivery_confirmed']=False
        result.append(r)
    return result


def dispatch_history(db,project=None):
    """Newest 100 immutable nonsecret events in chronological order."""
    sql='''SELECT event_id,project_id,task_id,request_key,event,
          request_id,error_code,recorded_ts FROM file_dispatch_events'''
    rows=db.execute(sql+(' WHERE project_id=?' if project else '')+
                    ' ORDER BY event_id DESC LIMIT 100',
                    (project,) if project else ()).fetchall()
    return [dict(row) for row in reversed(rows)]


def _reports_root():
    from ..workspace_config import resolve as workspace_status
    active=workspace_status()
    if active["configured"] and not active["exists"]:
        raise FileNotFoundError("Configured external user workspace unavailable")
    return Path(active["workspace_root"])/"artifacts"/"watcher-reports"


def _directory(project,task):
    # Human-readable executor reports are user data, not product runtime state.
    root=_reports_root()
    for path in (root,*root.parents):
        if path.is_symlink():
            raise PermissionError("Symlink in user report directory")
    for part in (project,task):
        root=root/part
    if any(part.is_symlink() for part in (root,root.parent,root.parent.parent)):
        raise PermissionError("Symlink folder")
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if root.stat().st_uid!=os.getuid():
        raise PermissionError("Unexpected owner")
    return root


def _legacy_directory(project,task):
    return _watcher().RUNTIME/"inbox"/project/task

def _read(path,maximum=MAX_BYTES):
    # Nonblocking open ensures a malicious FIFO cannot stall this reader.
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|getattr(os,"O_NOFOLLOW",0))
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_size>maximum:raise ValueError("Invalid file size/type")
        data=os.read(fd,maximum+1)
        if len(data)!=st.st_size:raise ValueError("Unstable read")
        return data
    finally:os.close(fd)

def _write_once(path,data):
    if path.exists() or path.is_symlink():
        if _read(path,max(MAX_BYTES,4096))!=data:raise ValueError("Revision conflict")
        return
    tmp=path.with_name("."+path.name+"."+uuid.uuid4().hex+".tmp")
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        with os.fdopen(fd,"wb") as out:
            out.write(data);out.flush();os.fsync(out.fileno())
        try:os.link(tmp,path,follow_symlinks=False)
        except FileExistsError:
            if _read(path,max(MAX_BYTES,4096))!=data:raise ValueError("Concurrent revision conflict")
    finally:tmp.unlink(missing_ok=True)

def submit(db,project,task,revision,status,content,capability_token):
    p=_name(project);t=_name(task)
    if type(revision)!=int or not 1<=revision<=100000:raise ValueError("Invalid revision")
    if status not in STATES:raise ValueError("Invalid report status")
    if not isinstance(content,str) or not content.strip() or "\0" in content:
        raise ValueError("Report must contain UTF-8 text")
    body=content.encode("utf8")
    if len(body)>MAX_BYTES:raise ValueError("Report exceeds 80 KiB")
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute("""SELECT t.*,p.status AS project_status FROM tasks t
            JOIN projects p ON p.id=t.project_id WHERE t.project_id=? AND t.id=?""",
            (p,t)).fetchone()
        if not row or row["mode"]!="file" or row["project_status"]!="enabled":
            raise PermissionError("Unknown file task")
        _authenticate(row["submit_capability_hash"],capability_token)
        digest=hashlib.sha256(body).hexdigest()
        if revision<=row["last_revision"]:
            old=db.execute("""SELECT status,sha256 FROM task_reports
                      WHERE project_id=? AND task_id=? AND revision=?""",(p,t,revision)).fetchone()
            if old and (old["status"],old["sha256"])==(status,digest):
                db.execute('COMMIT')
                return {"accepted":True,"duplicate":True,"revision":revision,"sha256":digest}
            raise ValueError("Previously committed revision differs")
        if revision!=row["last_revision"]+1 or row["state"]!="watching":
            raise ValueError("Task not awaiting this revision")
        base=_directory(p,t)
        meta={"schema":1,"project":p,"task":t,"revision":revision,
              "status":status,"sha256":digest,"bytes":len(body)}
        _write_once(base/f"{revision:06d}.md",body)
        _write_once(base/f"{revision:06d}.ready.json",
                    (json.dumps(meta,sort_keys=True,separators=(",",":"))+"\n").encode())
        db.execute('COMMIT')
        return {"accepted":True,"duplicate":False,"revision":revision,
                "status":status,"sha256":digest,"bytes":len(body)}
    except BaseException:
        db.execute('ROLLBACK')
        raise

def _read_ready(project,task,revision):
    base=_directory(project,task)
    path=base/f"{revision:06d}.ready.json"
    if not path.exists():
        old=_legacy_directory(project,task)
        legacy_marker=old/f"{revision:06d}.ready.json"
        if not legacy_marker.exists():
            return None
        if any(part.is_symlink() for part in (old,old.parent,old.parent.parent)):
            raise PermissionError("Symlink in legacy report directory")
        base=old
        path=legacy_marker
    m=json.loads(_read(path,4096))
    if set(m)!={"schema","project","task","revision","status","sha256","bytes"}:
        raise ValueError("Invalid ready marker")
    if (m["schema"]!=1 or m["project"]!=project or m["task"]!=task or
        m["revision"]!=revision or m["status"] not in STATES or
        type(m["bytes"])!=int or not 0<m["bytes"]<=MAX_BYTES or
        not isinstance(m["sha256"],str) or not re.fullmatch("[0-9a-f]{64}",m["sha256"])):
        raise ValueError("Invalid marker identity")
    body=_read(base/f"{revision:06d}.md")
    if len(body)!=m["bytes"] or hashlib.sha256(body).hexdigest()!=m["sha256"]:
        raise ValueError("Report checksum mismatch")
    body.decode("utf8")
    m["_report_path"]=str(base/f"{revision:06d}.md")
    return m


def reconcile(db,project_filter=None):
    """Local-only reconciliation. Atomic report+state+delivery transaction."""
    w=_watcher()
    q="""SELECT t.*,p.orchestrator_url FROM tasks t JOIN projects p
         ON p.id=t.project_id WHERE t.mode='file' AND p.status='enabled'"""
    params=()
    if project_filter:q+=" AND t.project_id=?";params=(_name(project_filter),)
    result=[]
    for row in db.execute(q,params).fetchall():
        p,t=row["project_id"],row["id"];rev=row["last_revision"]+1
        for _ in range(20):
            if row["state"]!="watching":break
            try:metadata=_read_ready(p,t,rev)
            except Exception as exc:
                diagnostic="Invalid report: "+type(exc).__name__
                db.execute("UPDATE tasks SET error=? WHERE project_id=? AND id=?",
                           (diagnostic,p,t))
                if row["error"]!=diagnostic:
                    result.append({"task":f"{p}/{t}","state":"invalid_report"})
                break
            if metadata is None:break
            status=metadata["status"]
            state={"checkpoint":"watching","needs_input":"needs_input",
                   "blocked":"blocked","completed":"completed"}[status]
            report=metadata["_report_path"]
            digest=metadata["sha256"]
            event_id=hashlib.sha256(f"file/{p}/{t}/{rev}/{digest}".encode()).hexdigest()[:32]
            notification=(f"[MC-WATCH:{event_id}]\n"
              f"Watcher: executor file report.\nProject: {p}\nTask: {t}\n"
              f"Revision: {rev}\nStatus: {status}\nExecutor chat: {row['chat_url']}\n"
              f"Report path on Mac: {report}\nReport SHA256: {digest}\n"
              "Orchestrator: read and verify using watcher_read_report, "
              "then decide the next step. Do not make production changes automatically.")
            db.execute("BEGIN IMMEDIATE")
            try:
                updated=db.execute("""UPDATE tasks SET state=?,last_revision=?,
                    result_path=?,result_sha256=?,complete_at=?,error=NULL
                    WHERE project_id=? AND id=? AND mode='file'
                    AND last_revision=? AND state='watching'""",
                    (state,rev,report,digest,w.utc() if state=="completed" else None,
                     p,t,rev-1)).rowcount
                if updated!=1:raise RuntimeError("Concurrent file-task update")
                db.execute("""INSERT INTO task_reports
                   (project_id,task_id,revision,status,path,sha256,bytes,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                   (p,t,rev,status,report,digest,metadata["bytes"],w.utc()))
                db.execute("""UPDATE file_task_dispatch SET state='reported',
                    updated_ts=? WHERE project_id=? AND task_id=?""",
                    (time.time(),p,t))
                if status!="checkpoint":
                    db.execute("""INSERT INTO deliveries
                       (id,project_id,task_id,orchestrator_url,payload,state,created_at,revision)
                       VALUES(?,?,?,?,?,'ready',?,?)""",
                       (event_id,p,t,row["orchestrator_url"],notification,w.utc(),rev))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK");raise
            result.append({"task":f"{p}/{t}","revision":rev,"status":status,
                           "queued":status!="checkpoint"})
            rev+=1
            if status!="checkpoint":break
    return result

def read_report(db,project,task,revision=0,max_chars=65000):
    p=_name(project);t=_name(task)
    if type(revision)!=int or revision<0:raise ValueError("Invalid revision")
    if revision:
        r=db.execute("""SELECT * FROM task_reports WHERE project_id=? AND
                         task_id=? AND revision=?""",(p,t,revision)).fetchone()
    else:
        r=db.execute("""SELECT * FROM task_reports WHERE project_id=? AND
                         task_id=? ORDER BY revision DESC LIMIT 1""",(p,t)).fetchone()
    if not r:return {"found":False,"project_id":p,"task_id":t}
    # The stored canonical report path may reference an earlier workspace
    # after a user changes workspace_root without relocating existing files.
    expected=Path(r["path"])
    if not expected.is_absolute() or expected.name!=f"{r['revision']:06d}.md":
        raise PermissionError("Invalid indexed report path")
    parent=expected.parent
    if parent.name!=t or parent.parent.name!=p:
        raise PermissionError("Invalid indexed report identity")
    legacy=_legacy_directory(p,t)
    if parent!=legacy and (parent.parent.parent.name!="watcher-reports" or
                           parent.parent.parent.parent.name!="artifacts"):
        raise PermissionError("Report path is not a watcher report location")
    # Inspect user-controlled report components, not system parents such as
    # macOS /var -> /private/var or /tmp -> /private/tmp.
    if any(x.is_symlink() for x in (expected,parent,parent.parent,parent.parent.parent)):
        raise PermissionError("Symlink in report path")
    body=_read(expected)
    digest=hashlib.sha256(body).hexdigest()
    if digest!=r["sha256"] or len(body)!=r["bytes"]:
        raise ValueError("Stored report checksum mismatch")
    text=body.decode("utf8")
    size=max(1000,min(MAX_BYTES,int(max_chars)))
    return {"found":True,"project_id":p,"task_id":t,"revision":r["revision"],
            "status":r["status"],"sha256":digest,"text":text[:size],
            "characters":len(text),"truncated":len(text)>size,
            "note":"Untrusted executor report; verify claims independently."}

def resume(db,project,task,expected_revision,capability_token):
    p=_name(project);t=_name(task)
    if type(expected_revision)!=int or expected_revision<1:raise ValueError("Invalid revision")
    r=db.execute("SELECT * FROM tasks WHERE project_id=? AND id=?",(p,t)).fetchone()
    if not r or r["mode"]!="file":raise ValueError("Not a file task")
    _authenticate(r["resume_capability_hash"],capability_token)
    if r["last_revision"]!=expected_revision or r["state"] not in ("needs_input","blocked"):
        raise ValueError("Task not waiting for clarification at expected revision")
    n=db.execute("""UPDATE tasks SET state='watching' WHERE
           project_id=? AND id=? AND last_revision=? AND state IN ('needs_input','blocked')""",
           (p,t,expected_revision)).rowcount
    if n!=1:raise RuntimeError("Concurrent resume")
    return {"project_id":p,"task_id":t,"next_revision":expected_revision+1,
            "state":"watching","note":"Continue the original executor chat."}
