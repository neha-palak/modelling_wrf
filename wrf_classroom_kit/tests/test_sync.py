import importlib.util,json,os,tempfile,unittest
from pathlib import Path
SPEC=importlib.util.spec_from_file_location('sync_hpc',Path(__file__).resolve().parents[1] / 'sync_hpc.py')
SYNC=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(SYNC)
class SFTP:
 def open(self,p,m): return open(p,m)
 def stat(self,p): return os.stat(p)
class TransferTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.base=Path(self.tmp.name); self.remote=self.base/'remote'; self.local=self.base/'local';self.remote.mkdir();self.local.mkdir()
  self.name='01_CTRL/wrflite_d01_2023-06-22_00-00-00.nc'; p=self.remote/self.name;p.parent.mkdir();p.write_bytes(b'first-record')
  self.manifest=dict(config_hash='known',planned_files=2,complete=False,files={self.name:dict(bytes=p.stat().st_size)})
  self.write_manifest()
 def tearDown(self): self.tmp.cleanup()
 def write_manifest(self): (self.remote/'manifest.json').write_text(json.dumps(self.manifest))
 def sync(self): return SYNC.sync_once(SFTP(),str(self.remote),self.local)
 def test_incremental_and_resume(self):
  self.assertEqual(self.sync(),(1,False,1));self.assertEqual(self.sync(),(0,False,1))
  n='01_CTRL/wrflite_d01_2023-06-22_03-00-00.nc';(self.remote/n).write_bytes(b'second-record')
  self.manifest['files'][n]={'bytes':len(b'second-record')};self.manifest['complete']=True;self.write_manifest()
  self.assertEqual(self.sync(),(1,True,2));self.assertTrue(json.loads((self.local/'manifest.json').read_text())['complete'])
 def test_changed_local_file_redownloads(self):
  self.sync();p=self.local/self.name;p.write_bytes(b'other-record');self.assertEqual(self.sync()[0],1);self.assertEqual(p.read_bytes(),b'first-record')
 def test_config_conflict_stops(self):
  self.sync();self.manifest['config_hash']='different';self.write_manifest()
  with self.assertRaises(ValueError): self.sync()
 def test_incomplete_source_is_not_published(self):
  self.manifest['files'][self.name]['bytes']=999;self.write_manifest()
  with self.assertRaises(ValueError): self.sync()
  self.assertFalse((self.local/self.name).exists());self.assertEqual(json.loads((self.local/'manifest.json').read_text())['files'],{})
 def test_unsafe_paths_rejected(self):
  for p in ['../evil.nc','/tmp/evil.nc','01_CTRL/../../evil.nc','01_CTRL\\evil.nc','01_CTRL/wrfout_d01_2023-06-22_00:00:00']:
   with self.assertRaises(ValueError): SYNC.safe_relative(p)
 def test_symlink_destination_rejected(self):
  outside=self.base/'outside';outside.mkdir()
  try: (self.local/'01_CTRL').symlink_to(outside,target_is_directory=True)
  except (OSError,NotImplementedError): self.skipTest('Symlink creation not available for this user/platform')
  with self.assertRaises(ValueError): self.sync()
  self.assertEqual(list(outside.iterdir()),[])
if __name__=='__main__': unittest.main(verbosity=2)
