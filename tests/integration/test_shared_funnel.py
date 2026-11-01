"""Shared HTTPS Funnel simulation and prefixed OAuth behavior."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from fastmcp import FastMCP
from scripts import setup_network
from scripts.shared_funnel_routes import TARGET, backend_for, route_paths, analyze, choose
from mac_control.remote_http import remote_http_options
from mac_control.remote_mount import create_remote_app
from mac_control.remote_auth import build_auth
from tests.integration.test_remote_auth import sample_config

HOST = 'mac.tailnet.ts.net'
KEY = HOST + ':443'
OLD = {
 '/': {'Proxy':'http://127.0.0.1:3000'},
 '/aidom': {'Proxy':'http://127.0.0.1:9196'},
 '/outreach': {'Proxy':'http://127.0.0.1:8768'},
 '/meta/instagram/webhook': {'Proxy':'http://127.0.0.1:9188/meta/instagram/webhook'},
 **{('/v1/'+name): {'Proxy':'http://127.0.0.1:18764/v1/'+name}
    for name in ('ingest','location','presence','status','workouts/enrich',
                 'workouts/backfill-status')},
}
def config():
 return {'TCP':{'443':{'HTTPS':True}},
         'Web':{KEY:{'Handlers':deepcopy(OLD)}},
         'AllowFunnel':{KEY:True}}

class FakeFunnel:
 def __init__(self,fail=None):
  self.state=config()
  self.commands=[]
  self.fail=fail
 def run(self,args,timeout=12):
  self.commands.append(args)
  if 'status' in args:
   return subprocess.CompletedProcess(args,0,json.dumps(self.state),'')
  paths=[arg[11:] for arg in args if arg.startswith('--set-path=')]
  assert len(paths)==1,args
  path=paths[0]
  if 'off' in args:
   self.state['Web'][KEY]['Handlers'].pop(path,None)
   return subprocess.CompletedProcess(args,0,'','')
  if path==self.fail:
   return subprocess.CompletedProcess(args,1,'','failed')
  self.state['Web'][KEY]['Handlers'][path]={'Proxy':backend_for(path)}
  return subprocess.CompletedProcess(args,0,'','')

class SharedRouteTests(unittest.TestCase):
 def test_ten_existing_routes(self):
  state=config()
  self.assertEqual(len(state['Web'][KEY]['Handlers']),10)
  result=choose(state,HOST)
  self.assertEqual(result['status'],'shared_available')
  self.assertEqual(result['prefix'],'/maccontrol')
  self.assertEqual(len(result['missing']),3)
  self.assertEqual(len(state['Web'][KEY]['Handlers']),10)
 def test_legacy_root_endpoint_is_reused_unchanged(self):
  state=config()
  state['Web'][KEY]['Handlers']['/']={'Proxy':TARGET}
  outputs=[subprocess.CompletedProcess([],0,json.dumps(state),''),
           subprocess.CompletedProcess([],0,json.dumps(state),'')]
  with patch.object(setup_network,'run',side_effect=outputs):
   result=setup_network.publication_state('tailscale',HOST)
  self.assertEqual(result['status'],'existing_matching')
  self.assertEqual(result['public_url'],'https://'+HOST)

 def test_prefix_collision_chooses_next(self):
  state=config()
  state['Web'][KEY]['Handlers']['/maccontrol']={'Proxy':'http://127.0.0.1:9999'}
  self.assertEqual(choose(state,HOST)['prefix'],'/maccontrol-2')
 def test_shadow_path_and_unknown_config_rejected(self):
  for path in ('/maccontrol/mcp','/maccontrol/auth/callback',
               '/.well-known/oauth-authorization-server/maccontrol/extra'):
   state=config()
   state['Web'][KEY]['Handlers'][path]={'Proxy':'http://127.0.0.1:9999'}
   with self.subTest(path=path):
    self.assertEqual(analyze(state,HOST,'/maccontrol')['status'],'conflict')
  for kind in ('Services','numeric'):
   state=config()
   if kind=='Services': state['Services']={'x':{}}
   else: state['TCP']['443']['HTTPS']=1
   self.assertEqual(analyze(state,HOST,'/maccontrol')['status'],'conflict')

class SharedPublicationTests(unittest.TestCase):
 def publish(self,fake,confirmation='PUBLISH'):
  auth={'public_url':'https://'+HOST+'/maccontrol','allowed_github_ids':['123']}
  with patch.object(setup_network,'run',side_effect=fake.run), \
       patch.object(setup_network,'_oauth_guard',return_value=auth), \
       patch.object(setup_network.sys.stdin,'isatty',return_value=True):
   return setup_network._enable_shared_funnel(
    '/Applications/Tailscale.app/Contents/MacOS/Tailscale',HOST,
    '/maccontrol',Path('/example'),auth,input_fn=lambda _:confirmation)
 def test_additive_transaction_and_repeated_install(self):
  fake=FakeFunnel()
  original=deepcopy(fake.state)
  outcome=self.publish(fake)
  self.assertEqual(outcome['status'],'shared_funnel_published')
  self.assertEqual(len(outcome['added_routes']),3)
  routes=[args for args in fake.commands if '--bg' in args]
  self.assertEqual(len(routes),3)
  for command in routes:
   path=next(x[len('--set-path='):] for x in command if x.startswith('--set-path='))
   self.assertEqual(command[-1],backend_for(path))
  self.assertEqual({k:fake.state['Web'][KEY]['Handlers'][k] for k in OLD},OLD)
  self.assertEqual(len(fake.state['Web'][KEY]['Handlers']),len(OLD)+3)
  self.assertEqual(self.publish(fake)['status'],'existing_shared_funnel_reused')
  self.assertEqual(fake.state['TCP'],original['TCP'])
  self.assertEqual(fake.state['AllowFunnel'],original['AllowFunnel'])
  self.assertFalse(any('reset' in args for args in fake.commands))
 def test_owner_refusal_is_read_only(self):
  fake=FakeFunnel()
  with self.assertRaisesRegex(RuntimeError,'approve'):
   self.publish(fake,confirmation='NO')
  self.assertEqual(fake.state,config())
  self.assertFalse(any('--set-path=' in ' '.join(x) for x in fake.commands))
 def test_partial_failure_undoes_only_new_routes(self):
  fake=FakeFunnel(fail=route_paths('/maccontrol')[1])
  with self.assertRaisesRegex(RuntimeError,'rolled back'):
   self.publish(fake)
  self.assertEqual(fake.state,config())
  self.assertTrue(any('off' in args for args in fake.commands))
 def test_concurrent_foreign_route_change_fails_closed(self):
  fake=FakeFunnel()
  original_run=fake.run
  def concurrent(args,timeout=12):
   result=original_run(args,timeout=timeout)
   if '--bg' in args:
    fake.state['Web'][KEY]['Handlers']['/aidom']={'Proxy':'http://127.0.0.1:9999'}
   return result
  auth={'public_url':'https://'+HOST+'/maccontrol','allowed_github_ids':['123']}
  with patch.object(setup_network,'run',side_effect=concurrent), \
       patch.object(setup_network,'_oauth_guard',return_value=auth), \
       patch.object(setup_network.sys.stdin,'isatty',return_value=True):
   with self.assertRaisesRegex(RuntimeError,'rollback incomplete'):
    setup_network._enable_shared_funnel('tailscale',HOST,'/maccontrol',
                                       Path('/example'),auth,
                                       input_fn=lambda _:'PUBLISH')
  self.assertEqual(fake.state['Web'][KEY]['Handlers']['/aidom'],
                   {'Proxy':'http://127.0.0.1:9999'})
  self.assertFalse(any('reset' in args for args in fake.commands))

 def test_partial_preexisting_owned_route_is_not_deleted(self):
  fake=FakeFunnel(fail=route_paths('/maccontrol')[2])
  fake.state['Web'][KEY]['Handlers']['/maccontrol']={'Proxy':backend_for('/maccontrol')}
  with self.assertRaisesRegex(RuntimeError,'rolled back'):
   self.publish(fake)
  self.assertEqual(fake.state['Web'][KEY]['Handlers']['/maccontrol'],{'Proxy':backend_for('/maccontrol')})
  self.assertEqual({k:fake.state['Web'][KEY]['Handlers'][k] for k in OLD},OLD)

class MountedOAuthTests(unittest.TestCase):
 def test_actual_fastmcp_discovery_issuer_and_401(self):
  origin='https://'+HOST+'/maccontrol'
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'auth.json'
   data=sample_config()
   data['public_url']=origin
   path.write_text(json.dumps(data))
   path.chmod(0o600)
   app=create_remote_app(FastMCP('test',auth=build_auth(path)),
                         origin,**remote_http_options(origin))
   with TestClient(app,base_url='https://'+HOST) as client:
    auth=client.get('/.well-known/oauth-authorization-server/maccontrol')
    self.assertEqual(auth.status_code,200)
    self.assertEqual(auth.json()['issuer'],origin)
    self.assertEqual(auth.json()['token_endpoint'],origin+'/token')
    resource=client.get('/.well-known/oauth-protected-resource/maccontrol/mcp')
    self.assertEqual(resource.status_code,200)
    self.assertEqual(resource.json()['resource'],origin+'/mcp')
    challenge=client.post('/maccontrol/mcp',json={'jsonrpc':'2.0'})
    self.assertEqual(challenge.status_code,401)
    self.assertIn('WWW-Authenticate',challenge.headers)
    self.assertEqual(client.get('/.well-known/oauth-authorization-server').status_code,404)

if __name__=='__main__':
 unittest.main()
