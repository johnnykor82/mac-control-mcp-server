"""Watcher revisioned file handoff v1. Reports are inert UTF-8, never executed."""
from __future__ import annotations
import hashlib,hmac,json,os,re,secrets,sqlite3,stat,uuid
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
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return {"project_id":p,"task_id":t,"mode":"file","state":"watching",
            "executor_url":w.canonical_url(chat_url),
            "submission_token":submit_token,
            "orchestrator_token":resume_token,
            "next_revision":1,
            "warning":"Copy submission_token only into this executor's task prompt. Keep orchestrator_token private."}

def _directory(project,task):
    root=_watcher().RUNTIME
    if root.is_symlink() or not root.is_dir():raise PermissionError("Unsafe runtime root")
    for part in ("inbox",project,task):
        root=root/part
        if root.is_symlink():raise PermissionError("Symlink folder")
        root.mkdir(mode=0o700,exist_ok=True)
        if root.stat().st_uid!=os.getuid():raise PermissionError("Unexpected owner")
        root.chmod(0o700)
    return root

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
    return {"accepted":True,"duplicate":False,"revision":revision,
            "status":status,"sha256":digest,"bytes":len(body)}

def _read_ready(project,task,revision):
    base=_directory(project,task)
    path=base/f"{revision:06d}.ready.json"
    if not path.exists():return None
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
            report=str(_directory(p,t)/f"{rev:06d}.md")
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
    # Read-only API must not create inbox directories as a side effect.
    base=_watcher().RUNTIME/"inbox"/p/t
    if any(x.is_symlink() for x in (base.parent.parent,base.parent,base)):
        raise PermissionError("Symlink in report path")
    expected=base/f"{r['revision']:06d}.md"
    if str(expected)!=r["path"]:raise PermissionError("Invalid indexed report path")
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
