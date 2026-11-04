"""BF-20: owner-authorized, tokenless and idempotent initial browser dispatch.

The authenticated MCP owner is checked before calling enqueue. The transport
must never infer ownership from an executor URL or a claimed prompt string.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

from . import multi_project_watcher as legacy
from .watcher_browser_followups import MAX_PROMPT

KEY_RX = re.compile(r"^[A-Za-z0-9_-]{8,72}$")
STATES = ('prepared', 'sending', 'submitted', 'uncertain', 'blocked', 'completed')


def setup(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS chatbridge_browser_dispatches (
       project_id TEXT NOT NULL, task_id TEXT NOT NULL,
       executor_url TEXT NOT NULL, session_id TEXT NOT NULL,
       owner_subject TEXT NOT NULL, client_request_id TEXT NOT NULL UNIQUE,
       prompt TEXT NOT NULL, prompt_sha256 TEXT NOT NULL,
       state TEXT NOT NULL CHECK(state IN ('prepared','sending','submitted','uncertain','blocked','completed')),
       request_id TEXT, assistant_message_id TEXT, reported_status TEXT,
       last_error TEXT, created_at TEXT NOT NULL,
       PRIMARY KEY(project_id,task_id), UNIQUE(session_id)
    )""")
    columns={row[1] for row in db.execute('PRAGMA table_info(chatbridge_browser_dispatches)')}
    if 'reported_status' not in columns:
        db.execute('ALTER TABLE chatbridge_browser_dispatches ADD COLUMN reported_status TEXT')
    db.execute("""CREATE INDEX IF NOT EXISTS idx_cb_browser_dispatch_state
               ON chatbridge_browser_dispatches(state)""")
    db.execute("""CREATE TABLE IF NOT EXISTS chatbridge_browser_project_owners (
        project_id TEXT PRIMARY KEY, owner_subject TEXT NOT NULL
    )""")


def register_owned_project(db, project, orchestrator_url, owner_subject):
    """Atomically create or re-register only the verified owner's project."""
    legacy.require_name(project)
    legacy.canonical_url(orchestrator_url)
    if not isinstance(owner_subject,str) or not owner_subject.isascii() or not owner_subject.isdecimal():
        raise PermissionError('Verified GitHub account required')
    setup(db)
    db.execute('BEGIN IMMEDIATE')
    try:
        existing_project=db.execute('SELECT 1 FROM projects WHERE id=?',(project,)).fetchone()
        existing_grant=db.execute('SELECT owner_subject FROM chatbridge_browser_project_owners WHERE project_id=?',(project,)).fetchone()
        if existing_project and not existing_grant:
            raise PermissionError('Legacy unowned project cannot be claimed for new dispatch')
        result=legacy.register_project(db,project,orchestrator_url)
        db.execute("""INSERT OR IGNORE INTO chatbridge_browser_project_owners
                  (project_id,owner_subject) VALUES(?,?)""",(project,owner_subject))
        existing=db.execute("SELECT owner_subject FROM chatbridge_browser_project_owners WHERE project_id=?",(project,)).fetchone()
        if existing['owner_subject']!=owner_subject:
            raise PermissionError('Project belongs to another verified owner')
        db.execute('COMMIT')
        return result
    except BaseException:
        db.execute('ROLLBACK')
        raise


def validate_session(session: dict, session_id: str, executor_url: str) -> None:
    url = legacy.canonical_url(executor_url)
    conversation = url.rsplit('/c/', 1)[1]
    expected_project = url.split('/g/', 1)[1].split('/', 1)[0] if '/g/' in url else None
    if (not isinstance(session, dict) or not isinstance(session_id,str)
            or not session_id or session.get('session_id') != session_id
            or session.get('conversation_id') != conversation
            or session.get('project_id') != expected_project
            or session.get('mode') != 'persistent'):
        raise ValueError('Unverified persistent executor session route')


def _check_input(project, task, executor_url, prompt, request_key, owner_subject):
    legacy.require_name(project); legacy.require_name(task)
    url=legacy.canonical_url(executor_url)
    if not isinstance(owner_subject,str) or not owner_subject.isascii() or not owner_subject.isdecimal():
        raise PermissionError('Verified owner identity required')
    if not isinstance(request_key,str) or KEY_RX.fullmatch(request_key) is None:
        raise ValueError('Invalid request key')
    if not isinstance(prompt,str) or not 25 <= len(prompt) <= MAX_PROMPT or '\0' in prompt:
        raise ValueError('Invalid prompt length or content')
    if re.search(r'(?i)(authorization\\s*:\\s*bearer|submission_token|orchestrator_token|capability_token|session_cookie)',prompt):
        raise ValueError('Credential-bearing executor prompt is not allowed')
    return url,hashlib.sha256(prompt.encode('utf-8')).hexdigest()


def prior(db, project, task, executor_url, prompt, request_key, owner_subject):
    """Read duplicate before importing any session, so retries never create one."""
    url,digest=_check_input(project,task,executor_url,prompt,request_key,owner_subject)
    setup(db)
    row=db.execute("""SELECT * FROM chatbridge_browser_dispatches WHERE
        client_request_id=? OR (project_id=? AND task_id=?)""",(request_key,project,task)).fetchone()
    if row:
        if row['owner_subject'] != owner_subject:
            raise PermissionError('Project handoff owner mismatch')
        if (row['project_id'] != project or row['task_id'] != task or
                row['executor_url'] != url or row['prompt_sha256'] != digest or
                row['client_request_id'] != request_key):
            raise ValueError('Existing dispatch differs from immutable request')
        return {'project_id':project,'task_id':task,'state':row['state'],
                'client_request_id':request_key,'request_id':row['request_id'],
                'duplicate':True}
    return None


def enqueue(db, project, task, executor_url, prompt, request_key, owner_subject,
            session_id, *, session):
    duplicate=prior(db,project,task,executor_url,prompt,request_key,owner_subject)
    if duplicate:
        return duplicate
    url,digest=_check_input(project,task,executor_url,prompt,request_key,owner_subject)
    validate_session(session,session_id,url)
    db.execute('BEGIN IMMEDIATE')
    try:
        project_row=db.execute("SELECT * FROM projects WHERE id=? AND status='enabled'",(project,)).fetchone()
        if not project_row or project_row['orchestrator_url']==url:
            raise ValueError('Project missing, paused or executor is orchestrator')
        owner=db.execute('SELECT owner_subject FROM chatbridge_browser_project_owners WHERE project_id=?',(project,)).fetchone()
        if not owner or owner['owner_subject']!=owner_subject:
            raise PermissionError('No matching verified project-owner grant')
        if db.execute('SELECT 1 FROM projects WHERE orchestrator_url=?',(url,)).fetchone():
            raise ValueError('Executor belongs to another orchestrator')
        if db.execute('SELECT 1 FROM tasks WHERE chat_url=?',(url,)).fetchone():
            raise ValueError('Executor conversation already registered')
        if db.execute('SELECT 1 FROM tasks WHERE project_id=? AND id=?',(project,task)).fetchone():
            raise ValueError('Existing task cannot be superseded')
        db.execute("""INSERT INTO tasks(project_id,id,chat_url,state)
                  VALUES(?,?,?,'dispatch_prepared')""",(project,task,url))
        db.execute("""INSERT INTO chatbridge_task_sessions(project_id,task_id,session_id)
                  VALUES(?,?,?)""",(project,task,session_id))
        db.execute("""INSERT INTO chatbridge_browser_dispatches
          (project_id,task_id,executor_url,session_id,owner_subject,
           client_request_id,prompt,prompt_sha256,state,created_at)
          VALUES(?,?,?,?,?,?,?,?,'prepared',?)""",
          (project,task,url,session_id,owner_subject,request_key,prompt,digest,legacy.utc()))
        db.execute('COMMIT')
        return {'project_id':project,'task_id':task,'state':'prepared',
                'client_request_id':request_key,'request_id':None,'duplicate':False}
    except BaseException:
        db.execute('ROLLBACK')
        raise


def prepare_for_dispatch(db):
    setup(db)
    return db.execute("""SELECT d.* FROM chatbridge_browser_dispatches d
        JOIN projects p ON p.id=d.project_id
        JOIN tasks t ON t.project_id=d.project_id AND t.id=d.task_id
        WHERE d.state='prepared' AND p.status='enabled' AND
              t.state='dispatch_prepared' ORDER BY d.created_at,d.task_id LIMIT 2""").fetchall()


def quarantine_inflight(db):
    setup(db)
    db.execute('BEGIN IMMEDIATE')
    try:
        count=db.execute("""UPDATE chatbridge_browser_dispatches
            SET state='uncertain',last_error='watcher_restarted_during_initial_send'
            WHERE state='sending'""").rowcount
        db.execute("""UPDATE tasks SET state='blocked',error='watcher_restarted_during_initial_send'
            WHERE state='dispatch_prepared' AND EXISTS (
              SELECT 1 FROM chatbridge_browser_dispatches d
              WHERE d.project_id=tasks.project_id AND d.task_id=tasks.id
                AND d.state='uncertain' AND d.last_error='watcher_restarted_during_initial_send')""")
        db.execute('COMMIT')
        return count
    except BaseException:
        db.execute('ROLLBACK')
        raise


def verify_completed_result(db,project,task,request):
    setup(db)
    row=db.execute("""SELECT * FROM chatbridge_browser_dispatches
        WHERE project_id=? AND task_id=?""",(project,task)).fetchone()
    if not row or row['state']!='submitted' or not row['request_id']:
        raise ValueError('No submitted initial dispatch binding')
    url=row['executor_url']
    expected_project=url.split('/g/',1)[1].split('/',1)[0] if '/g/' in url else None
    if (not isinstance(request,dict) or request.get('request_id')!=row['request_id']
       or request.get('session_id')!=row['session_id']
       or request.get('client_request_id')!=row['client_request_id']
       or request.get('conversation_id')!=url.rsplit('/c/',1)[1]
       or request.get('project_id')!=expected_project
       or request.get('status')!='completed'
       or not isinstance(request.get('assistant_message_id'),str)
       or not request.get('assistant_message_id')
       or not isinstance(request.get('answer'),str) or not request.get('answer')):
        raise ValueError('Initial dispatch result provenance mismatch')
    return request['assistant_message_id']


def assert_scope(db,project,task,url,owner_subject):
    """Reject unauthorised projects before touching the ChatBridge session API."""
    legacy.require_name(project);legacy.require_name(task)
    url=legacy.canonical_url(url)
    setup(db)
    row=db.execute("""SELECT p.orchestrator_url,p.status,o.owner_subject
        FROM projects p LEFT JOIN chatbridge_browser_project_owners o
        ON p.id=o.project_id WHERE p.id=?""",(project,)).fetchone()
    if not row or row['status']!='enabled' or row['orchestrator_url']==url:
        raise ValueError('Unavailable owner project or invalid executor')
    if row['owner_subject']!=owner_subject:
        raise PermissionError('Project not authorized for authenticated owner')
    if db.execute('SELECT 1 FROM projects WHERE orchestrator_url=?',(url,)).fetchone():
        raise ValueError('Executor URL reserved by orchestrator')
    if db.execute('SELECT 1 FROM tasks WHERE chat_url=? OR (project_id=? AND id=?)',
                  (url,project,task)).fetchone():
        raise ValueError('Executor task or URL already exists')


def prepare_owner_dispatch(db,project,task,url,prompt,key,subject,api):
    """Authenticated MCP handler calls this after verifying OAuth subject."""
    old=prior(db,project,task,url,prompt,key,subject)
    if old:
        return old
    assert_scope(db,project,task,url,subject)
    from .watcher_http_adapter import session_import
    status=api('GET','/v1/system/status')
    if status.get('rate_limit',{}).get('provider_rate_limited'):
        raise ValueError('Provider rate limited; no session imported')
    session=api('POST','/v1/sessions',session_import(url,'watcher-executor:'+project+'/'+task))
    sid=session.get('session_id') if isinstance(session,dict) else None
    if not isinstance(sid,str) or not sid:
        raise ValueError('ChatBridge did not return a verified session')
    route=api('GET','/v1/sessions/'+sid)
    validate_session(route,sid,url)
    return enqueue(db,project,task,url,prompt,key,subject,sid,session=route)


def dispatch_prepared(db,api,*,dry_run=False):
    """At most one initial POST per cycle; write SENDING before network I/O."""
    rows=prepare_for_dispatch(db)
    if dry_run:
        return [{'task':r['project_id']+'/'+r['task_id'],'would_send':True} for r in rows]
    if not rows:
        return []
    status=api('GET','/v1/system/status')
    if status.get('rate_limit',{}).get('provider_rate_limited'):
        return [{'state':'deferred','reason':'provider_cooldown'}]
    if int(status.get('active') or 0)>=1:
        return [{'state':'deferred','reason':'gateway_busy'}]
    row=rows[0]
    project,task=row['project_id'],row['task_id']
    name=project+'/'+task
    try:
        route=api('GET','/v1/sessions/'+row['session_id'])
        validate_session(route,row['session_id'],row['executor_url'])
    except (ValueError,RuntimeError,KeyError) as exc:
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute("""UPDATE chatbridge_browser_dispatches SET
                 state='blocked',last_error='session_route_mismatch'
                 WHERE project_id=? AND task_id=? AND state='prepared'""",(project,task))
            db.execute("""UPDATE tasks SET state='blocked',error='session_route_mismatch'
                 WHERE project_id=? AND id=? AND state='dispatch_prepared'""",(project,task))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
        return [{'task':name,'state':'blocked','reason':'session_route_mismatch'}]
    db.execute('BEGIN IMMEDIATE')
    try:
        changed=db.execute("""UPDATE chatbridge_browser_dispatches SET
          state='sending' WHERE project_id=? AND task_id=? AND state='prepared'""",
          (project,task)).rowcount
        if changed!=1:
            raise ValueError('Dispatch changed before POST')
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise
    try:
        response=api('POST','/v1/sessions/'+row['session_id']+'/messages',
                 {'content':row['prompt'],'client_request_id':row['client_request_id']})
        request_id=response.get('request_id') if isinstance(response,dict) else None
        if not isinstance(request_id,str) or not request_id:
            raise ValueError('Missing gateway request identity')
    except PermissionError:
        # Explicit platform denial is terminal for this exact action.
        db.execute("UPDATE chatbridge_browser_dispatches SET state='blocked',last_error='platform_policy_denial' WHERE project_id=? AND task_id=? AND state='sending'",(project,task))
        db.execute("UPDATE tasks SET state='blocked',error='platform_policy_denial' WHERE project_id=? AND id=? AND state='dispatch_prepared'",(project,task))
        return [{'task':name,'state':'blocked','reason':'platform_policy_denial'}]
    except Exception as exc:
        from .watcher_http_adapter import TransportError
        # ChatBridge normalizes explicit HTTP authorization denials into
        # TransportError. These are terminal, not ambiguous delivery outcomes.
        if isinstance(exc, TransportError) and str(exc) in ('ChatBridge HTTP 401', 'ChatBridge HTTP 403'):
            reason=('gateway_auth_denied' if str(exc).endswith('401')
                    else 'platform_policy_denial')
            db.execute("UPDATE chatbridge_browser_dispatches SET state='blocked',last_error=? WHERE project_id=? AND task_id=? AND state='sending'",
                       (reason,project,task))
            db.execute("UPDATE tasks SET state='blocked',error=? WHERE project_id=? AND id=? AND state='dispatch_prepared'",
                       (reason,project,task))
            return [{'task':name,'state':'blocked','reason':reason}]
        # Never resend: gateway may have accepted the original POST.
        db.execute("""UPDATE chatbridge_browser_dispatches SET
             state='uncertain',last_error='initial_post_outcome_unknown'
             WHERE project_id=? AND task_id=? AND state='sending'""",(project,task))
        db.execute("""UPDATE tasks SET state='blocked',error='initial_post_outcome_unknown'
             WHERE project_id=? AND id=? AND state='dispatch_prepared'""",(project,task))
        return [{'task':name,'state':'uncertain','reason':'initial_post_outcome_unknown'}]
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute("""UPDATE chatbridge_browser_dispatches SET
          state='submitted',request_id=?,last_error=NULL
          WHERE project_id=? AND task_id=? AND state='sending'""",
          (request_id,project,task))
        db.execute("""INSERT INTO chatbridge_task_request_links
          (project_id,task_id,request_id,session_id) VALUES(?,?,?,?)""",
          (project,task,request_id,row['session_id']))
        db.execute("""UPDATE tasks SET state='watching'
          WHERE project_id=? AND id=? AND state='dispatch_prepared'""",(project,task))
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise
    return [{'task':name,'state':'submitted','request_id':request_id}]


def poll_initial(db,task,api,*,dry_run=False):
    """Only the exact submitted request/turn can become an immutable report."""
    project,name=task['project_id'],task['id']
    row=db.execute("""SELECT * FROM chatbridge_browser_dispatches
           WHERE project_id=? AND task_id=?""",(project,name)).fetchone()
    if not row:
        return None
    if dry_run:
        return [{'task':project+'/'+name,'state':row['state'],'would_poll':True}]
    if row['state']!='submitted':
        return []
    req=api('GET','/v1/requests/'+row['request_id'])
    status=req.get('status') if isinstance(req,dict) else None
    expected_conversation=row['executor_url'].rsplit('/c/',1)[1]
    expected_project=(row['executor_url'].split('/g/',1)[1].split('/',1)[0]
                      if '/g/' in row['executor_url'] else None)
    # ChatBridge may resolve remote conversation/project IDs only on end_turn.
    # Never accept a *different* interim target; final turns require both exact.
    identity=(isinstance(req,dict)
         and req.get('request_id')==row['request_id']
         and req.get('session_id')==row['session_id']
         and req.get('client_request_id')==row['client_request_id']
         and (req.get('conversation_id')==expected_conversation
              if status=='completed'
              else req.get('conversation_id') in (None,expected_conversation))
         and (req.get('project_id')==expected_project
              if status=='completed'
              else req.get('project_id') in (None,expected_project)))
    if not identity or status in ('unknown','failed','interrupted'):
        db.execute("""UPDATE chatbridge_browser_dispatches SET state='uncertain',
            last_error='request_outcome_or_identity_unknown' WHERE project_id=? AND task_id=?""",
            (project,name))
        db.execute("""UPDATE tasks SET state='blocked',
            error='request_outcome_or_identity_unknown' WHERE project_id=? AND id=?""",
            (project,name))
        return [{'task':project+'/'+name,'state':'uncertain','reason':'request_outcome_or_identity_unknown'}]
    if status!='completed':
        return []
    # A stored request ID is not sufficient after the physical persistent
    # ChatBridge session has been rebound or rotated to another conversation.
    current_session=api('GET','/v1/sessions/'+row['session_id'])
    validate_session(current_session,row['session_id'],row['executor_url'])
    message_id=verify_completed_result(db,project,name,req)
    complete=legacy.completion_test(db,project,name,req['answer'],
                   generating=False,now_monotonic=__import__('time').monotonic())
    if not complete:
        return []
    reported='completed'
    try:
        structured=json.loads(req['answer'])
        if isinstance(structured,dict) and structured.get('status') in ('needs_input','blocked'):
            reported=structured['status']
    except (ValueError,TypeError):
        pass
    event=legacy.prepare_delivery(db,task,req['answer'])
    if reported!='completed':
        db.execute("UPDATE deliveries SET payload=payload||? WHERE id=? AND state='ready'",
                   ('\\nReported executor status (untrusted): '+reported,event['delivery_id']))
    db.execute("""UPDATE chatbridge_browser_dispatches SET state='completed',
           assistant_message_id=?,reported_status=? WHERE project_id=? AND task_id=? AND state='submitted'""",
           (message_id,reported,project,name))
    return [event]
