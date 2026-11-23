"""Assigned-archive discovery/preparation tests with real synthetic NetCDFs.

The hand-built metadata follows the reducer's plan/manifest contract: a common
three-case inventory, corrected 20 primary fields, one mode, and three-hour
timestamps. Each student TAR contains only its own group's files.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import io
import itertools
import json
import shutil
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from netCDF4 import Dataset

KIT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(KIT))
import classroom_autodetect as auto
from make_demo import write_snapshot
from wrf_data import PRIMARY_FIELDS, scan_roots, read_surface


def sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retained_payload_hash(ds):
    """Match the reducer's tiny-grid block order for this unscaled fixture."""
    digest=hashlib.sha256()
    for name,var in sorted(ds.variables.items()):
        var.set_auto_maskandscale(False)
        var.set_auto_chartostring(False)
        chunks=[1 if dim=='Time' or dim.startswith('bottom_top') else min(n,256)
                if dim.startswith(('south_north','west_east')) else min(n,64)
                for dim,n in zip(var.dimensions,var.shape)]
        for starts in itertools.product(*(range(0,n,c) for n,c in zip(var.shape,chunks))):
            slices=tuple(slice(s,min(s+c,n)) for s,c,n in zip(starts,chunks,var.shape))
            digest.update(name.encode()+b'\0')
            digest.update(np.ascontiguousarray(var[slices]).tobytes())
    return digest.hexdigest()


def make_source(root,mode='full',steps=2):
    root.mkdir(parents=True,exist_ok=True)
    times=[(datetime(2023,6,22)+timedelta(hours=3*i)).strftime('%Y-%m-%d_%H:%M:%S')
           for i in range(steps)]
    config={'version':'1.0.0','root':'/synthetic/source','cases':list(auto.CASES),
            'domain':'d01','vertical':mode,'interval_hours':3,'anchor_hour':0,
            'primary_variables':list(PRIMARY_FIELDS),'selected_times':times,
            'compression':'zlib','complevel':2}
    signature=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    plan={'config_hash':signature,'config':config,'planned_files_per_case':steps,
          'planned_files_total':steps*len(auto.CASES)}
    manifest={'version':'1.0.0','config_hash':signature,'complete':True,
              'planned_files':plan['planned_files_total'],'files':{}}
    for case_number,case in enumerate(auto.CASES):
        for index,stamp in enumerate(times):
            relative=case+'/wrflite_d01_'+stamp.replace(':','-')+'.nc'
            path=root/relative
            write_snapshot(path,mode,case_number,index*3,4)
            with Dataset(path,'r+') as ds:
                payload=retained_payload_hash(ds)
                ds.wrflite_config_hash=signature
                ds.wrflite_payload_sha256=payload
            manifest['files'][relative]={'case':case,'time':stamp,'bytes':path.stat().st_size,
                                        'sha256_payload':payload,'reused':False,
                                        'source':{'path':'/synthetic/original/'+case+'/'+path.name,
                                                  'index':0,'time':stamp,'size':1,'mtime_ns':1}}
    manifest['output_data_bytes']=sum(x['bytes'] for x in manifest['files'].values())
    for name,value in [('plan.json',plan),('manifest.json',manifest)]:
        (root/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    return root


def make_archive(source,path,cases=('01_CTRL',),omit=(),extra=None,metadata=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((source/'manifest.json').read_text())
    with tarfile.open(path,'w') as archive:
        for name in ('plan.json','manifest.json'):
            if metadata and name in metadata:
                data=metadata[name]
                item=tarfile.TarInfo(name)
                item.size=len(data)
                archive.addfile(item,io.BytesIO(data))
            else:
                archive.add(source/name,arcname=name,recursive=False)
        for relative,info in manifest['files'].items():
            if info['case'] in cases and relative not in omit:
                archive.add(source/relative,arcname=relative,recursive=False)
        if extra:
            item,data=extra
            archive.addfile(item,io.BytesIO(data) if data is not None else None)
    return path


class AutodetectTests(unittest.TestCase):
    def setUp(self):
        # Intermediate files stay beside the kit, inside the shared workspace.
        self.temp=tempfile.TemporaryDirectory(prefix='autodetect_test_',dir=KIT.parent)
        self.root=Path(self.temp.name)
        self.source=make_source(self.root/'source full')
        self.inbox=self.root/'Student Drive with spaces'
        self.inbox.mkdir()
        self.work=self.root/'Student Work with spaces'

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self,candidate):
        with redirect_stdout(io.StringIO()):
            return auto.prepare_student_dataset(candidate,self.work)

    def test_single_group_archive_spaces_and_exact_provenance(self):
        archive=make_archive(self.source,self.inbox/'my assigned 01_CTRL_lite.tar')
        candidates=auto.discover_student_data([self.inbox])
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]['case'],'01_CTRL')
        self.assertEqual(candidates[0]['expected_records'],2)
        result=self.prepare(candidates[0])
        prepared=Path(result['data_root'])
        records,warnings,status=scan_roots([prepared])
        self.assertEqual(len(records),2)
        self.assertTrue(status['complete'])
        self.assertEqual(status['deferred_files'],0)
        self.assertEqual(status['scope_cases'],['01_CTRL'])
        self.assertEqual(warnings,[])
        self.assertEqual((prepared/'provenance/source_manifest.json').read_bytes(),(self.source/'manifest.json').read_bytes())
        self.assertEqual((prepared/'provenance/source_plan.json').read_bytes(),(self.source/'plan.json').read_bytes())
        self.assertFalse((prepared/'plan.json').exists())
        manifest=json.loads((prepared/'manifest.json').read_text())
        self.assertEqual(manifest['planned_files'],2)
        self.assertEqual(manifest['classroom_scope']['parent_planned_files'],6)
        self.assertEqual(manifest['classroom_scope']['parent_manifest_sha256'],sha_file(self.source/'manifest.json'))
        for record in records:
            relative=record.path.relative_to(prepared)
            self.assertEqual(sha_file(record.path),sha_file(self.source/relative))
            self.assertEqual(set(read_surface(record)['fields']),set(PRIMARY_FIELDS))
        self.assertFalse((prepared/'02_CTRL_NOISE').exists())
        self.assertFalse((prepared/'03_CLEAN').exists())
        self.assertTrue(archive.is_file())

    def test_group_and_mode_ambiguity_is_not_silently_resolved(self):
        make_archive(self.source,self.inbox/'control_full.tar')
        make_archive(self.source,self.inbox/'noise_full.tar',cases=('02_CTRL_NOISE',))
        surface=make_source(self.root/'source surface','surface')
        make_archive(surface,self.inbox/'control_surface.tar')
        all_candidates=auto.discover_student_data([self.inbox])
        self.assertEqual(len(all_candidates),3)
        one_group=auto.discover_student_data([self.inbox],group='1')
        self.assertEqual({c['case'] for c in one_group},{'01_CTRL'})
        self.assertEqual({c['mode'] for c in one_group},{'full','surface'})
        resolved=auto.discover_student_data([self.inbox],group='1',mode='full')
        self.assertEqual(len(resolved),1)
        self.assertEqual(resolved[0]['mode'],'full')

    def test_all_aggregates_only_matching_export_groups(self):
        for case in auto.CASES:
            make_archive(self.source,self.inbox/(case+'_lite.tar'),cases=(case,))
        candidates=auto.discover_student_data([self.inbox],group='all')
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]['cases'],list(auto.CASES))
        result=self.prepare(candidates[0])
        records,warnings,status=scan_roots([Path(result['data_root'])])
        self.assertEqual(len(records),6)
        self.assertEqual({record.case for record in records},set(auto.CASES))
        self.assertTrue(status['complete'])
        self.assertEqual(status['scope_cases'],list(auto.CASES))
        self.assertEqual(warnings,[])

    def test_extracted_single_group_preserves_shared_original_metadata(self):
        extracted=self.inbox/'already extracted group'
        extracted.mkdir()
        shutil.copytree(self.source/'02_CTRL_NOISE',extracted/'02_CTRL_NOISE')
        for name in ('plan.json','manifest.json'):
            shutil.copy2(self.source/name,extracted/name)
        metadata_before={name:(extracted/name).read_bytes() for name in ('plan.json','manifest.json')}
        inputs={p.relative_to(extracted):sha_file(p) for p in extracted.rglob('*.nc')}
        candidates=auto.discover_student_data([self.inbox])
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]['case'],'02_CTRL_NOISE')
        result=self.prepare(candidates[0])
        prepared=Path(result['data_root'])
        self.assertNotEqual(prepared,extracted)
        for name,original in metadata_before.items():
            self.assertEqual((extracted/name).read_bytes(),original)
        for relative,digest in inputs.items():
            self.assertEqual(sha_file(extracted/relative),digest)
            self.assertEqual(sha_file(prepared/relative),digest)
        records,warnings,status=scan_roots([prepared])
        self.assertEqual(len(records),2)
        self.assertTrue(status['complete'])
        self.assertEqual(status['deferred_files'],0)

    def test_resume_reuses_atomic_files_without_changing_arrays(self):
        archive=make_archive(self.source,self.inbox/'01_CTRL_lite.tar')
        candidate=auto.discover_student_data([self.inbox])[0]
        archive_before=sha_file(archive)
        result=self.prepare(candidate)
        prepared=Path(result['data_root'])
        files={p:(p.stat().st_mtime_ns,sha_file(p)) for p in prepared.rglob('*.nc')}
        with patch.object(auto,'_stream_to_file',side_effect=AssertionError('Ready file was unnecessarily recopied')):
            repeated=self.prepare(candidate)
        self.assertEqual(result['data_root'],repeated['data_root'])
        for path,(mtime,digest) in files.items():
            self.assertEqual(path.stat().st_mtime_ns,mtime)
            self.assertEqual(sha_file(path),digest)
        self.assertEqual(sha_file(archive),archive_before)
        self.assertEqual(list(prepared.rglob('*.part')),[])
        self.assertFalse((prepared/'.prepare.lock').exists())
        # A later notebook session can discover and reuse the prepared subset.
        candidates=auto.discover_student_data([prepared])
        self.assertEqual(len(candidates),1)
        self.assertTrue(candidates[0]['prepared'])

    def test_interrupted_preparation_resumes_only_unfinished_file(self):
        make_archive(self.source,self.inbox/'01_CTRL_lite.tar')
        candidate=auto.discover_student_data([self.inbox])[0]
        real_stream=auto._stream_to_file
        calls=[]
        def interrupted(stream,target,count):
            calls.append(target)
            if len(calls)==2:
                raise OSError('simulated interruption')
            return real_stream(stream,target,count)
        with patch.object(auto,'_stream_to_file',side_effect=interrupted):
            with self.assertRaises(OSError):
                self.prepare(candidate)
        prepared=next((self.work/'data').iterdir())
        self.assertFalse((prepared/'manifest.json').exists())
        self.assertFalse((prepared/'.prepare.lock').exists())
        self.assertEqual(len(list(prepared.rglob('*.nc'))),1)
        with patch.object(auto,'_stream_to_file',wraps=real_stream) as stream_copy:
            result=self.prepare(candidate)
            self.assertEqual(stream_copy.call_count,1)
        self.assertTrue(scan_roots([Path(result['data_root'])])[2]['complete'])

    def test_missing_selected_snapshot_fails_before_claiming_complete(self):
        manifest=json.loads((self.source/'manifest.json').read_text())
        missing=next(rel for rel,info in manifest['files'].items() if info['case']=='01_CTRL')
        make_archive(self.source,self.inbox/'01_CTRL_incomplete.tar',omit=(missing,))
        candidates=auto.discover_student_data([self.inbox])
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]['ready_records'],1)
        self.assertEqual(candidates[0]['expected_records'],2)
        with self.assertRaisesRegex(auto.PreparationError,'incomplete'):
            self.prepare(candidates[0])
        self.assertFalse(self.work.exists())

    def test_traversal_and_symlink_members_are_rejected(self):
        traversal=tarfile.TarInfo('../escape.txt')
        traversal.size=1
        bad_path=make_archive(self.source,self.inbox/'traversal.tar',extra=(traversal,b'x'))
        with self.assertRaisesRegex(auto.PreparationError,'Unsafe'):
            auto._archive_metadata(bad_path)
        link=tarfile.TarInfo('01_CTRL/symlink.nc')
        link.type=tarfile.SYMTYPE
        link.linkname='/outside/dataset.nc'
        bad_link=make_archive(self.source,self.inbox/'symlink.tar',extra=(link,None))
        with self.assertRaisesRegex(auto.PreparationError,'links/devices'):
            auto._archive_metadata(bad_link)
        self.assertEqual(auto.discover_student_data([self.inbox]),[])
        self.assertEqual(len(auto.DISCOVERY_WARNINGS),2)
        self.assertFalse((self.root/'escape.txt').exists())

    def test_malformed_metadata_and_demo_fallback_are_rejected(self):
        make_archive(self.source,self.inbox/'malformed.tar',metadata={'manifest.json':b'{bad json'})
        self.assertEqual(auto.discover_student_data([self.inbox]),[])
        self.assertTrue(auto.DISCOVERY_WARNINGS)
        demo_folder=self.root/'search here'/'demo_data'
        demo_folder.mkdir(parents=True)
        make_archive(self.source,demo_folder/'synthetic_full.tar')
        self.assertEqual(auto.discover_student_data([self.root/'search here']),[])
        empty=self.root/'empty student data'
        empty.mkdir()
        self.assertEqual(auto.discover_student_data([empty]),[])


if __name__=='__main__':
    unittest.main()
